"""Independent application oracle for the importable Matrix durable package."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
SDK = Path(os.environ.get("NIL_SDK", ROOT / ".sdk"))
TARGETS = tuple(filter(None, os.environ.get("ENIGMA_TEST_TARGETS", "vm,native").split(",")))
ENABLED = os.environ.get("ENIGMA_DURABLE_TESTS") == "1"


def command(route: str, *, example: bool = False) -> list[str]:
    artifact = (ROOT / "ext/enigma-durable/build/enigma-durable-example" if example
                else ROOT / "build/durable-app-probe/enigma-durable-app-probe")
    return [str(SDK / "nilinterpreter"), str(artifact.with_suffix(".nil"))] if route == "vm" else [str(artifact)]


def checkpoint(path: Path) -> tuple[bytes, dict]:
    raw = (path / "checkpoint.json").read_bytes()
    envelope = json.loads(raw)
    assert set(envelope) == {"format", "payload", "sha256"}
    assert envelope["format"] == "enigma.checkpoint.v1"
    assert hashlib.sha256(envelope["payload"].encode("utf-8")).hexdigest() == envelope["sha256"]
    state = json.loads(envelope["payload"])
    assert state["schema"] == "enigma.state.v3"
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    for name in ("checkpoint.json", ".lock"):
        info = (path / name).lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert stat.S_IMODE(info.st_mode) == 0o600
    return raw, state


class RunningApp:
    def __init__(self, args: list[str], *, cwd: Path | None = None):
        self.process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.pending = b""

    def line(self) -> str:
        deadline = time.monotonic() + 30
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise AssertionError("application receipt timed out")
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                raise AssertionError("application exited: " + self.process.stderr.read(4096).decode("utf-8", "replace"))
            self.pending += chunk
            if len(self.pending) > 65536:
                raise AssertionError("oversized application diagnostic")
        line, self.pending = self.pending.split(b"\n", 1)
        return line.decode("utf-8")

    def send(self, text: str) -> None:
        self.process.stdin.write(text.encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def finish(self) -> None:
        self.process.stdin.close()
        assert self.process.wait(timeout=10) == 0
        assert self.process.stdout.read() == b""
        assert self.process.stderr.read() == b""

    def __enter__(self) -> "RunningApp":
        return self

    def __exit__(self, *_args: object) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed:
                stream.close()


@unittest.skipUnless(ENABLED, "run scripts/test-durable-client.sh to build the application fixtures")
class DurableClientTests(unittest.TestCase):
    def run_program(self, route: str, mode: str, directory: Path | str, *,
                    example: bool = False, cwd: Path | None = None) -> str:
        result = subprocess.run([*command(route, example=example), mode, str(directory)],
                                cwd=cwd, input=b"", stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stderr, b"")
        return result.stdout.decode("utf-8")

    def assert_lock_available(self, directory: Path, expected: bool) -> None:
        descriptor = os.open(directory / ".lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                available = False
            else:
                available = True
            self.assertEqual(available, expected)
        finally:
            os.close(descriptor)

    def test_application_example_reopens_data_and_requires_fresh_admission(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                self.assertEqual(self.run_program(route, "create", path, example=True), "application-created\n")
                _raw, before = checkpoint(path)
                self.assertEqual(before["revision"], 1)
                self.assertEqual(len(before["events"]), 1)
                self.assertEqual(before["events"][0]["source"], "synthetic:app")
                self.assert_lock_available(path, True)
                self.assertEqual(self.run_program(route, "reopen", path, example=True), "application-reopened\n")
                _raw, after = checkpoint(path)
                self.assertNotEqual(before["incarnation"], after["incarnation"])
                self.assertEqual(after["database_id"], before["database_id"])
                self.assertEqual(after["events"], before["events"])
                self.assertGreaterEqual(after["retired_through"], 1)
                self.assertGreater(after["next_grant_id"], before["next_grant_id"])
                self.assertTrue(after["grants"][-1]["revoked"])
                self.assertGreaterEqual(after["clock_floor"], before["clock_floor"])
                self.assert_lock_available(path, True)

    def test_close_releases_lock_and_every_alias_stops_dispatching(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                self.assertEqual(self.run_program(route, "lifecycle", path), "lifecycle-ok\n")
                _raw, state = checkpoint(path)
                self.assertEqual(state["generation"], 1)
                self.assertEqual(state["events"], [])
                self.assert_lock_available(path, True)

    def test_all_typed_operations_share_one_durable_session(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                self.assertEqual(self.run_program(route, "typed-operations", path), "typed-operations-ok\n")
                _raw, state = checkpoint(path)
                self.assertEqual(state["revision"], 3)
                self.assertEqual(state["retained_from"], 3)
                self.assertEqual(len(state["events"]), 1)
                self.assertEqual(state["events"][0]["source"], "synthetic:typed")
                self.assertEqual(state["next_grant_id"], 3)
                self.assertTrue(all(row["revoked"] for row in state["grants"]))
                self.assertEqual(state["clock_floor"], 13)
                self.assert_lock_available(path, True)

    def test_stale_owner_cannot_overwrite_a_successor_after_losing_its_lock(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                self.assertEqual(self.run_program(route, "stale-owner", path), "stale-owner-ok\n")
                _raw, state = checkpoint(path)
                self.assertEqual(state["generation"], 2)
                self.assertEqual(state["next_grant_id"], 2)
                self.assertEqual(len(state["grants"]), 1)
                self.assert_lock_available(path, True)

    def test_failed_open_releases_its_lock_before_invocation_teardown(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                self.run_program(route, "create", path, example=True)
                (path / "checkpoint.json").write_bytes(b"{broken")
                with RunningApp([*command(route), "failed-open", str(path)]) as app:
                    self.assertEqual(app.line(), "failed-open")
                    self.assertIsNone(app.process.poll())
                    self.assert_lock_available(path, True)
                    self.assertEqual((path / "checkpoint.json").read_bytes(), b"{broken")
                    app.send("exit")
                    app.finish()

    def test_failed_commit_poisoning_prevents_reuse_and_close_releases_lock(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                with RunningApp([*command(route), "hold", str(path)]) as app:
                    self.assertEqual(app.line(), "ready")
                    original, before = checkpoint(path)
                    self.assertEqual(before["revision"], 1)
                    self.assert_lock_available(path, False)
                    canonical = path / "checkpoint.json"
                    canonical.unlink()
                    canonical.mkdir(mode=0o700)
                    app.send("write")
                    self.assertEqual(app.line(), "outcome-unknown")
                    self.assert_lock_available(path, False)
                    canonical.rmdir()
                    canonical.write_bytes(original)
                    canonical.chmod(0o600)
                    app.send("again")
                    self.assertEqual(app.line(), "poisoned")
                    self.assertEqual(canonical.read_bytes(), original)
                    app.send("close")
                    self.assertEqual(app.line(), "closed")
                    self.assertIsNone(app.process.poll())
                    self.assert_lock_available(path, True)
                    app.send("exit")
                    app.finish()
                self.assertEqual(checkpoint(path)[1]["revision"], 1)

    def test_working_directory_changes_do_not_redirect_a_live_database(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                root = Path(temporary)
                (root / "other").mkdir(mode=0o700)
                canary = root / "other/db"
                self.run_program(route, "create", canary, example=True)
                original = checkpoint(canary)[0]
                self.assertEqual(self.run_program(route, "cwd-pin", "db", cwd=root), "cwd-pin-ok\n")
                self.assertEqual(checkpoint(canary)[0], original)
                _raw, state = checkpoint(root / "db")
                self.assertEqual(len(state["grants"]), 1)
                self.assertEqual(state["revision"], 0)
                self.assert_lock_available(root / "db", True)

    def test_posix_literal_backslashes_and_utf8_keep_their_filename(self) -> None:
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                root = Path(temporary)
                parent = root / "parent\\Ω"
                parent.mkdir(mode=0o700)
                path = parent / "database\\β"
                self.assertEqual(self.run_program(route, "lifecycle", path), "lifecycle-ok\n")
                self.assertEqual(checkpoint(path)[1]["events"], [])
                self.assertFalse((root / "parent").exists())
                self.assert_lock_available(path, True)

    def test_typed_discovery_reads_a_full_width_persisted_batch(self) -> None:
        content = '"\\\n' * 85 + '"'
        actor = '"\\\n' * 42 + '"\\'
        for route in TARGETS:
            with self.subTest(route=route), tempfile.TemporaryDirectory(prefix="enigma-app-") as temporary:
                path = Path(temporary) / "db"
                self.run_program(route, "create", path, example=True)
                canonical = path / "checkpoint.json"
                envelope = json.loads(canonical.read_bytes())
                state = json.loads(envelope["payload"])
                state["revision"] = 128
                state["events"] = [{"id": i, "kind": 1, "subject": content, "relation": content,
                                    "object_value": content, "polarity": i % 2, "source": content,
                                    "entity": actor, "session": 77, "target": 0} for i in range(1, 129)]
                envelope["payload"] = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
                envelope["sha256"] = hashlib.sha256(envelope["payload"].encode("utf-8")).hexdigest()
                canonical.write_text(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                self.assertEqual(self.run_program(route, "full-read", path), "full-read-ok\n")
                _raw, after = checkpoint(path)
                self.assertEqual(after["events"], state["events"])
                self.assertEqual(after["clock_floor"], 11)
                self.assert_lock_available(path, True)
