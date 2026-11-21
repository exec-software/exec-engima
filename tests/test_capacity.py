"""Independent capacity, maintenance, and durable byte-refusal checks.

The fixtures are synthetic checkpoints encoded outside Matrix. Every open,
request, and recovery still passes through the real host and engine.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_durable_client import RunningApp, checkpoint
from test_storage_recovery import HOST_COMMAND, HostSession, caller


ROOT = Path(__file__).resolve().parent.parent
SDK = Path(os.environ.get("NIL_SDK", ROOT / ".sdk"))
TARGETS = tuple(filter(None, os.environ.get("ENIGMA_TEST_TARGETS", "vm").split(",")))
ENABLED = os.environ.get("ENIGMA_CAPACITY_TESTS") == "1"
TYPED = os.environ.get("ENIGMA_CAPACITY_TYPED") == "1"
CLAIM = {"subject": "synthetic:capacity", "relation": "status", "object_value": "ready"}
ANY = {"subject": None, "relation": None, "object_value": None}
BASE_CAPACITY = {"code": "capacity", "instance": "", "generation": 0}
BASE_DENIED = {"code": "denied", "instance": "", "generation": 0}
RESOLUTION_DENIED = {"code": "denied", "instance": "", "generation": 0,
                     "state": "unavailable", "revision": 0, "complete": False,
                     "evidence_complete": False, "inspected": 0, "supporting": 0,
                     "opposing": 0, "evidence_ids": []}
ASSERTION_BYTES = 382 * 1024


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def event(identifier: int, *, wide: bool = False) -> dict:
    return {"id": identifier, "kind": 1,
            "subject": "\x01" * 256 if wide else CLAIM["subject"],
            "relation": '\\"' * 128 if wide else CLAIM["relation"],
            "object_value": "Ω" * 128 if wide else CLAIM["object_value"],
            "polarity": 1, "source": "\x01" * 256 if wide else "synthetic:capacity",
            "entity": "agent:a", "session": 11, "target": 0}


def seed(path: Path, rows: list[dict], *, revision: int | None = None) -> dict:
    _raw, state = checkpoint(path)
    state["events"] = rows
    state["revision"] = len(rows) if revision is None else revision
    state["retained_from"] = 0
    payload = compact_json(state)
    envelope = {"format": "enigma.checkpoint.v1", "payload": payload,
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}
    (path / "checkpoint.json").write_text(compact_json(envelope), encoding="utf-8")
    return state


def near_byte_capacity() -> list[dict]:
    rows: list[dict] = []
    while len(compact_json([*rows, event(len(rows) + 1, wide=True)]).encode("utf-8")) <= ASSERTION_BYTES:
        rows.append(event(len(rows) + 1, wide=True))
    return rows


@unittest.skipUnless(ENABLED, "run scripts/test-capacity.sh to build the capacity fixtures")
class CapacityTests(unittest.TestCase):
    def initialize(self, path: Path, target: str) -> None:
        result = subprocess.run([*HOST_COMMAND, "init", str(path), "--scope", "work", "--target", target],
                                input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout)["code"], "created")

    def install(self, host: HostSession, *, work: int = 1024, tick: int = 10,
                session: int = 11) -> dict:
        return host.request({"op": "install", "entity": "agent:a", "session": session,
                             "operations": 31, "expires": 1000, "work_limit": work,
                             "result_limit": 128, "tick": tick})

    def resolve(self, host: HostSession, grant: int, *, work: int = 1024,
                tick: int = 10, session: int = 11) -> dict:
        return host.request({"op": "resolve", "caller": caller(session=session, tick=tick),
                             "grant_id": grant, "claim": CLAIM, "as_of": -1,
                             "max_work": work, "max_evidence": 128})

    def test_large_store_preserves_work_bounds_output_bounds_and_maintenance(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-capacity-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                seed(path, [event(i) for i in range(1, 1024)])
                with HostSession(path, target) as host:
                    grant = self.install(host)["grant_id"]
                    partial = self.resolve(host, grant, work=128)
                    self.assertEqual((partial["code"], partial["state"], partial["inspected"]),
                                     ("ok", "incomplete", 128))
                    self.assertFalse(partial["complete"])
                    found = self.resolve(host, grant)
                    self.assertEqual((found["code"], found["revision"], found["supporting"], found["inspected"]),
                                     ("ok", 1023, 1023, 1023))
                    self.assertTrue(found["complete"])
                    self.assertFalse(found["evidence_complete"])
                    self.assertEqual(found["evidence_ids"], list(range(1023, 895, -1)))
                    discovered = host.request({"op": "discover", "caller": caller(), "grant_id": grant,
                                               "pattern": ANY, "as_of": -1,
                                               "max_work": 1024, "max_evidence": 128})
                    self.assertEqual((discovered["matched"], discovered["inspected"]), (1023, 1023))
                    self.assertTrue(discovered["complete"])
                    self.assertFalse(discovered["evidence_complete"])
                    self.assertEqual([item["id"] for item in discovered["items"]], list(range(1023, 895, -1)))
                    limited = self.install(host, work=128)["grant_id"]
                    self.assertEqual(self.resolve(host, limited), RESOLUTION_DENIED)
                    for operation, extra in (("inspect", {"evidence_id": 1, "as_of": -1}),
                                             ("withdraw", {"evidence_id": 1, "expected_revision": 1023}),
                                             ("compact", {})):
                        refusal = host.request({"op": operation, "caller": caller(),
                                                "grant_id": limited, **extra})
                        self.assertEqual(refusal["code"], "limit")
                    full = host.request({"op": "support", "caller": caller(), "grant_id": grant,
                                         "claim": CLAIM, "source": "synthetic:overflow", "expected_revision": 1023})
                    self.assertEqual(full["code"], "capacity")
                    _raw, before = checkpoint(path)
                    self.assertEqual((before["revision"], len(before["events"])), (1023, 1023))
                    withdrawn = host.request({"op": "withdraw", "caller": caller(), "grant_id": grant,
                                              "evidence_id": 1, "expected_revision": 1023})
                    self.assertEqual((withdrawn["code"], withdrawn["revision"]), ("ok", 1024))
                    self.assertEqual(len(checkpoint(path)[1]["events"]), 1024)
                    compacted = host.request({"op": "compact", "caller": caller(), "grant_id": grant})
                    self.assertEqual((compacted["code"], compacted["revision"], compacted["reclaimed"],
                                      compacted["retained_from"]), ("ok", 1024, 2, 1024))
                    after = self.resolve(host, grant)
                    self.assertTrue(after["complete"])
                    self.assertEqual((after["revision"], after["supporting"]), (1024, 1022))
                _raw, durable = checkpoint(path)
                self.assertEqual([row["id"] for row in durable["events"]], list(range(2, 1024)))

    def test_byte_capacity_keeps_security_state_and_owner_usable(self) -> None:
        rows = near_byte_capacity()
        self.assertGreater(len(compact_json(rows).encode("utf-8")), 375 * 1024)
        self.assertLess(len(rows), 1023, "this fixture must exhaust bytes before event count")
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-byte-capacity-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                seed(path, rows)
                with HostSession(path, target) as host:
                    grant = self.install(host)["grant_id"]
                    _raw, before = checkpoint(path)
                    refused = host.request({"op": "support", "caller": caller(tick=50), "grant_id": grant,
                                            "claim": {key: "\x01" * 256 for key in CLAIM},
                                            "source": "\x01" * 256, "expected_revision": len(rows)})
                    self.assertEqual(refused, BASE_CAPACITY)
                    _raw, after = checkpoint(path)
                    self.assertEqual(after["events"], before["events"])
                    self.assertEqual(after["revision"], before["revision"])
                    self.assertEqual(after["grants"], before["grants"])
                    self.assertEqual(after["clock_floor"], 50)
                    self.assertEqual(after["generation"], before["generation"] + 1)
                    self.assertEqual(self.resolve(host, grant, tick=49), BASE_DENIED)
                    healthy = self.resolve(host, grant, tick=50)
                    self.assertEqual(healthy["code"], "ok")
                    self.assertTrue(healthy["complete"])
                    revoked = host.request({"op": "revoke", "caller": caller(tick=51), "grant_id": grant})
                    self.assertEqual(revoked["code"], "ok")
                    self.assertTrue(checkpoint(path)[1]["grants"][0]["revoked"])
                with HostSession(path, target) as reopened:
                    self.assertEqual(self.resolve(reopened, grant, tick=51), BASE_DENIED)
                    self.assertEqual(self.install(reopened, tick=50, session=22)["code"], "invalid")
                    fresh = self.install(reopened, tick=51, session=22)
                    self.assertEqual(fresh["code"], "ok")
                    self.assertGreater(fresh["grant_id"], grant)
                    self.assertEqual(self.resolve(reopened, fresh["grant_id"], tick=51, session=22)["code"], "ok")
                _raw, final = checkpoint(path)
                self.assertEqual(final["events"], rows)
                self.assertEqual(final["clock_floor"], 51)
                self.assertGreaterEqual(final["retired_through"], grant)

    def test_recovery_validates_the_expanded_tail_and_withdrawals(self) -> None:
        duplicate = [event(i) for i in range(1, 257)]
        for identifier in (257, 258):
            duplicate.append({"id": identifier, "kind": 2, "subject": "", "relation": "",
                              "object_value": "", "polarity": 0, "source": "", "entity": "agent:a",
                              "session": 11, "target": 129})
        missing = [event(i) for i in range(1, 257) if i != 129]
        cases = (("oversized", [event(i) for i in range(1, 1026)], 1025),
                 ("missing-tail", missing, 256), ("duplicate-withdrawal", duplicate, 258))
        for target in TARGETS:
            for name, rows, revision in cases:
                with self.subTest(target=target, variant=name), tempfile.TemporaryDirectory(prefix="enigma-invalid-capacity-") as temporary:
                    path = Path(temporary) / "db"
                    self.initialize(path, target)
                    seed(path, rows, revision=revision)
                    canonical = path / "checkpoint.json"
                    broken = canonical.read_bytes()
                    result = subprocess.run([*HOST_COMMAND, "serve", str(path), "--target", target],
                                            input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            timeout=30, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assertIn(b"enigma store: corrupt", result.stderr)
                    self.assertEqual(canonical.read_bytes(), broken)

    @unittest.skipUnless(TYPED, "typed fixture runs once for each selected execution route")
    def test_typed_client_reads_large_counts_without_expanding_output(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-typed-capacity-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                seed(path, [event(i) for i in range(1, 1024)])
                artifact = ROOT / "build/capacity-probe/enigma-capacity-probe"
                command = ([str(SDK / "nilinterpreter"), str(artifact.with_suffix(".nil"))]
                           if target == "vm" else [str(artifact)])
                with RunningApp([*command, "large", str(path)]) as application:
                    for expected in ("capacity-opened", "capacity-resolved", "capacity-discovered", "capacity-closed"):
                        self.assertEqual(application.line(), expected)
                    application.finish()
                _raw, final = checkpoint(path)
                self.assertEqual(len(final["events"]), 1023)
                self.assertEqual(final["clock_floor"], 12)

    @unittest.skipUnless(TYPED, "typed fixture runs once for each selected execution route")
    def test_typed_byte_capacity_is_a_confirmed_usable_domain_refusal(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-typed-byte-capacity-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                rows = near_byte_capacity()
                seed(path, rows)
                artifact = ROOT / "build/capacity-probe/enigma-capacity-probe"
                command = ([str(SDK / "nilinterpreter"), str(artifact.with_suffix(".nil"))]
                           if target == "vm" else [str(artifact)])
                with RunningApp([*command, "bytes", str(path)]) as application:
                    for expected in ("capacity-opened", "capacity-confirmed", "capacity-usable", "capacity-closed"):
                        self.assertEqual(application.line(), expected)
                    application.finish()
                _raw, final = checkpoint(path)
                self.assertEqual(final["events"], rows)
                self.assertEqual(final["revision"], len(rows))
                self.assertEqual(final["clock_floor"], 50)


if __name__ == "__main__":
    unittest.main()
