"""Filesystem oracle for the typed Enigma record API."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

from test_durable_client import RunningApp


ROOT = Path(__file__).resolve().parent.parent
SDK = Path(os.environ.get("NIL_SDK", ROOT / ".sdk"))
ROUTES = tuple(os.environ.get("ENIGMA_TEST_TARGETS", "vm,native").split(","))
ENABLED = os.environ.get("ENIGMA_RECORD_TESTS") == "1"
BODY_LIMIT = 4 * 1024 * 1024


def command(route: str, *arguments: Path | str) -> list[str]:
    artifact = ROOT / "build/record-probe/enigma-record-probe"
    executable = ([str(SDK / "nilinterpreter"), str(artifact.with_suffix(".nil"))]
                  if route == "vm" else [str(artifact)])
    return [*executable, *map(str, arguments)]


def manifest(directory: Path) -> tuple[bytes, dict, dict]:
    path = directory / "manifest.json"
    raw = path.read_bytes()
    envelope = json.loads(raw)
    assert set(envelope) == {"format", "payload", "sha256"}
    assert envelope["format"] == "enigma.checkpoint.v1"
    assert hashlib.sha256(envelope["payload"].encode("utf-8")).hexdigest() == envelope["sha256"]
    state = json.loads(envelope["payload"])
    assert state["schema"] == "enigma.records.v1"
    for entry in (directory, directory / "objects"):
        info = entry.lstat()
        assert stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
    for entry in (path, directory / ".lock"):
        info = entry.lstat()
        assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    rows: dict = {}
    for page in state["index"]:
        for key, version, length, body_id, digest in page:
            assert re.fullmatch(r"[0-9a-f]{32}", body_id)
            body_path = directory / "objects" / body_id
            info = body_path.lstat()
            assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
            assert info.st_size == length
            assert hashlib.sha256(body_path.read_bytes()).hexdigest() == digest
            assert key not in rows
            rows[key] = (version, length, body_path)
    assert list(rows) == sorted(rows, key=lambda key: key.encode("utf-8"))
    assert state["live_bytes"] == sum(row[1] for row in rows.values())
    return raw, state, rows


@unittest.skipUnless(ENABLED, "run scripts/test-records.sh to build the record probe")
class RecordTests(unittest.TestCase):
    def create(self, route: str, directory: Path, content: bytes) -> tuple[bytes, dict, dict]:
        source = directory.parent / "input.bin"
        source.write_bytes(content)
        with RunningApp(command(route, "create", directory, source)) as process:
            self.assertEqual(process.line(), "records-written")
            self.assertEqual(process.line(), "records-closed")
            process.finish()
        raw, state, rows = manifest(directory)
        self.assertEqual(state["sequence"], 3)
        self.assertEqual(state["authority"]["clock_floor"], 3)
        self.assertEqual(state["authority"]["next_grant_id"], 2)
        self.assertEqual(list(rows), ["../empty", "z:primary"])
        self.assertEqual(rows["../empty"][:2], (2, 0))
        self.assertEqual(rows["z:primary"][:2], (3, len(content)))
        self.assertEqual(rows["z:primary"][2].read_bytes(), content)
        self.assertEqual(len(list((directory / "objects").iterdir())), 3)
        self.assertFalse((directory / "empty").exists())
        self.assertFalse((directory.parent / "empty").exists())
        return raw, state, rows

    def inspect_open(self, route: str, directory: Path, expected: str, *, limited: bool = False) -> None:
        completed = subprocess.run(command(route, "limited-open" if limited else "observe", directory),
                                   input=b"", capture_output=True, check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        self.assertEqual(completed.stderr, b"")
        self.assertEqual(completed.stdout, (expected + "\n").encode("utf-8"))

    def test_exact_four_mebibytes_round_trip_and_restart_retires_authority(self) -> None:
        unit = b"row\x00\r\n" + "éΩ🌎".encode("utf-8") + b"\x7f"
        repeats, remainder = divmod(BODY_LIMIT, len(unit))
        content = unit * repeats + b"z" * remainder
        for route in ROUTES:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-record-exact-") as temporary:
                path = Path(temporary) / "db"
                raw, before, saved_rows = self.create(route, path, content)
                self.inspect_open(route, path, "limit", limited=True)
                self.assertEqual((path / "manifest.json").read_bytes(), raw)
                exported = path.parent / "output.bin"
                with RunningApp(command(route, "reopen", path, exported)) as process:
                    self.assertEqual(process.line(), "records-recovered")
                    self.assertEqual(process.line(), "records-exported")
                    process.finish()
                self.assertEqual(exported.read_bytes(), content)
                _, after, observed_rows = manifest(path)
                self.assertEqual(after["database_id"], before["database_id"])
                self.assertNotEqual(after["incarnation"], before["incarnation"])
                self.assertGreater(after["generation"], before["generation"])
                self.assertEqual(after["authority"]["retired_through"], 1)
                self.assertEqual(after["authority"]["next_grant_id"], 3)
                self.assertEqual(after["authority"]["clock_floor"], 4)
                self.assertEqual([row["id"] for row in after["authority"]["grants"]], [2])
                self.assertEqual(observed_rows, saved_rows)

    def test_missing_unsafe_and_corrupt_canonical_bodies_fail_closed(self) -> None:
        for route in ROUTES:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-record-corrupt-") as temporary:
                path = Path(temporary) / "db"
                content = b"current body\x00\n"
                raw, _, rows = self.create(route, path, content)
                primary = rows["z:primary"][2]
                aside = path.parent / "current-aside"
                older = [candidate for candidate in (path / "objects").iterdir()
                         if candidate not in {row[2] for row in rows.values()}]
                self.assertEqual(len(older), 1)

                primary.rename(aside)
                self.inspect_open(route, path, "corrupt")
                self.assertEqual((path / "manifest.json").read_bytes(), raw)

                primary.symlink_to(older[0])
                self.inspect_open(route, path, "corrupt")
                self.assertEqual((path / "manifest.json").read_bytes(), raw)
                primary.unlink()
                aside.rename(primary)

                primary.write_bytes(content[:-1] + b"?")
                self.inspect_open(route, path, "corrupt")
                self.assertEqual((path / "manifest.json").read_bytes(), raw)
                primary.write_bytes(content)

                invalid_manifest = raw + b"\x00trailing bytes"
                (path / "manifest.json").write_bytes(invalid_manifest)
                self.inspect_open(route, path, "corrupt")
                self.assertEqual((path / "manifest.json").read_bytes(), invalid_manifest)
                (path / "manifest.json").write_bytes(raw)
                self.inspect_open(route, path, "ready")

    def test_more_than_1024_keys_recover_enumerate_and_extend(self) -> None:
        for route in ROUTES:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-record-index-") as temporary:
                path = Path(temporary) / "db"
                _, state, _ = self.create(route, path, b"seed")
                objects = path / "objects"
                for prior in objects.iterdir():
                    prior.unlink()
                digest = hashlib.sha256(b"").hexdigest()
                entries = []
                for identifier in range(1, 1026):
                    body_id = f"{identifier:032x}"
                    (objects / body_id).touch(mode=0o600, exist_ok=False)
                    entries.append([f"item:{identifier:06d}", identifier, 0, body_id, digest])
                state["index"] = [entries[start:start + 32] for start in range(0, len(entries), 32)]
                state["sequence"] = 1025
                state["live_bytes"] = 0
                payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
                envelope = {"format": "enigma.checkpoint.v1", "payload": payload,
                            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}
                (path / "manifest.json").write_text(json.dumps(envelope), encoding="utf-8")

                with RunningApp(command(route, "enumerate", path)) as process:
                    self.assertEqual(process.line(), "large-index-open")
                    self.assertEqual(process.line(), "large-index-listed")
                    self.assertEqual(process.line(), "large-index-extended")
                    process.finish()
                _, observed, rows = manifest(path)
                self.assertEqual(observed["sequence"], 1026)
                self.assertEqual(observed["authority"]["retired_through"], 1)
                self.assertEqual(len(rows), 1026)
                self.assertEqual(rows["item:001026"][:2], (1026, 0))

    def test_corruption_discovered_by_get_poisoned_active_owner(self) -> None:
        for route in ROUTES:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-record-get-corrupt-") as temporary:
                path = Path(temporary) / "db"
                content = b"body verified at open"
                self.create(route, path, content)
                with RunningApp(command(route, "corrupt-read", path)) as process:
                    self.assertEqual(process.line(), "read-ready")
                    raw, _, rows = manifest(path)
                    primary = rows["z:primary"][2]
                    primary.write_bytes(content[:-1] + b"?")
                    process.send("read")
                    self.assertEqual(process.line(), "corrupt-read-refused")
                    primary.write_bytes(content)
                    process.send("again")
                    self.assertEqual(process.line(), "poison-closed")
                    process.finish()
                self.assertEqual((path / "manifest.json").read_bytes(), raw)
                self.inspect_open(route, path, "ready")

    def test_body_and_manifest_publication_failures_poison_owner(self) -> None:
        for route in ROUTES:
            for phase in ("body", "manifest"):
                with self.subTest(route=route, phase=phase), tempfile.TemporaryDirectory(prefix="enigma-record-fault-") as temporary:
                    path = Path(temporary) / "db"
                    self.create(route, path, b"existing record")
                    canonical = path / "manifest.json"
                    objects = path / "objects"
                    interrupted_path = objects if phase == "body" else canonical
                    backup = path.parent / "interrupted"
                    with RunningApp(command(route, "fault-" + phase, path)) as process:
                        self.assertEqual(process.line(), "fault-ready")
                        self.inspect_open(route, path, "lock_error")
                        raw, before, rows = manifest(path)
                        previous_bodies = set(objects.iterdir())

                        interrupted_path.rename(backup)
                        if phase == "body":
                            interrupted_path.touch(mode=0o600)
                        else:
                            interrupted_path.mkdir(mode=0o700)
                        process.send("write")
                        self.assertEqual(process.line(), "publication-refused")
                        if phase == "body":
                            self.assertEqual(canonical.read_bytes(), raw)
                            interrupted_path.unlink()
                        else:
                            self.assertEqual(len(set(objects.iterdir()) - previous_bodies), 1)
                            self.assertTrue(interrupted_path.is_dir())
                            interrupted_path.rmdir()
                        backup.rename(interrupted_path)

                        process.send("again")
                        self.assertEqual(process.line(), "poison-closed")
                        process.finish()
                    self.assertEqual(canonical.read_bytes(), raw)
                    self.inspect_open(route, path, "ready")
                    _, recovered, contents = manifest(path)
                    self.assertEqual(recovered["sequence"], before["sequence"])
                    self.assertEqual(recovered["authority"]["retired_through"], 2)
                    self.assertEqual(contents, rows)


if __name__ == "__main__":
    unittest.main()
