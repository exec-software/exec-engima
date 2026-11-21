"""Fresh-process recovery checks for the real Matrix worker and POSIX host."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / "scripts" / "store.py"
# ENI-0003 phase C: the same black-box session contract has to hold for either
# host, so the command that launches one is configurable. These tests drive a
# real process over its CLI and never reach inside it, which is what makes
# them portable; the checks in test_durable_host.py inject Python I/O hooks
# and remain specific to that host.
HOST_COMMAND = (shlex.split(os.environ["ENIGMA_HOST_COMMAND"])
                if os.environ.get("ENIGMA_HOST_COMMAND")
                else [sys.executable, str(HOST)])
TARGETS = tuple(filter(None, os.environ.get("ENIGMA_TEST_TARGETS", "vm").split(",")))
CLAIM = {"subject": "sample:release", "relation": "ready", "object_value": "yes"}


def caller(entity: str = "agent:a", session: int = 11, tick: int = 10) -> dict:
    return {"entity": entity, "session": session, "audience": "enigma", "tick": tick}


def checkpoint(path: Path) -> tuple[bytes, dict]:
    content = (path / "checkpoint.json").read_bytes()
    envelope = json.loads(content)
    return content, json.loads(envelope["payload"])


class HostSession:
    """Bounded line reads keep a broken worker from hanging the test suite."""

    def __init__(self, path: Path, target: str):
        self.process = subprocess.Popen(
            [*HOST_COMMAND, "serve", str(path), "--target", target],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.pending = b""
        try:
            self.ready = self.receive()
            if self.ready.get("code") != "ready":
                raise AssertionError(f"host did not become ready: {self.ready!r}")
            self.instance = self.ready["instance"]
        except BaseException:
            self.close(kill=True)
            raise

    def receive(self, timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("timed out waiting for a durable host receipt")
            readable, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not readable:
                raise AssertionError("timed out waiting for a durable host receipt")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                self.process.wait(timeout=5)
                diagnostic = self.process.stderr.read(4096).decode("utf-8", "replace")
                raise AssertionError(f"host exited before a receipt: {diagnostic}")
            self.pending += chunk
            if len(self.pending) > 2 * 1024 * 1024:
                raise AssertionError("oversized host receipt")
        line, self.pending = self.pending.split(b"\n", 1)
        result = json.loads(line)
        if not isinstance(result, dict):
            raise AssertionError("host receipt was not an object")
        return result

    def request(self, request: dict) -> dict:
        request = dict(request)
        request.setdefault("instance", self.instance)
        data = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        self.process.stdin.write(data)
        self.process.stdin.flush()
        return self.receive()

    def close(self, *, kill: bool = False) -> None:
        if self.process.poll() is None:
            if kill:
                self.process.kill()
            else:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def __enter__(self) -> "HostSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class StorageRecoveryTests(unittest.TestCase):
    def initialize(self, path: Path, target: str) -> dict:
        result = subprocess.run(
            [*HOST_COMMAND, "init", str(path), "--scope", "work", "--target", target],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stderr, b"")
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["code"], "created")
        return receipt

    def install(self, host: HostSession, *, entity: str = "agent:a", session: int = 11,
                operations: int = 15, tick: int = 10, expires: int = 1000) -> dict:
        return host.request({"op": "install", "entity": entity, "session": session,
                             "operations": operations, "expires": expires,
                             "work_limit": 128, "result_limit": 128, "tick": tick})

    def resolve(self, host: HostSession, grant_id: int, *, who: dict | None = None,
                as_of: int = -1) -> dict:
        return host.request({"op": "resolve", "caller": who or caller(), "grant_id": grant_id,
                             "claim": CLAIM, "as_of": as_of, "max_work": 128, "max_evidence": 128})

    def test_evidence_history_and_provenance_survive_fresh_process(self) -> None:
        source = 'synthetic:pass "checked"\nnext line Ω'
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                with HostSession(path, target) as host:
                    first_instance = host.instance
                    issued = self.install(host)
                    self.assertEqual(issued["code"], "ok")
                    grant = issued["grant_id"]
                    support = host.request({"op": "support", "caller": caller(), "grant_id": grant,
                                            "claim": CLAIM, "source": source, "expected_revision": 0})
                    self.assertEqual(support["code"], "ok")
                    opposition = host.request({"op": "oppose", "caller": caller(), "grant_id": grant,
                                               "claim": CLAIM, "source": "synthetic:missing-review",
                                               "expected_revision": 1})
                    self.assertEqual(opposition["code"], "ok")
                    withdrawal = host.request({"op": "withdraw", "caller": caller(), "grant_id": grant,
                                               "evidence_id": opposition["evidence_id"], "expected_revision": 2})
                    self.assertEqual(withdrawal["revision"], 3)
                    self.assertEqual(self.resolve(host, grant)["state"], "supported")
                    self.assertEqual(self.resolve(host, grant, as_of=2)["state"], "contested")
                with HostSession(path, target) as host:
                    self.assertNotEqual(host.instance, first_instance)
                    self.assertEqual(self.resolve(host, grant)["code"], "denied")
                    restored = checkpoint(path)[1]
                    self.assertTrue(all(row["revoked"] for row in restored["grants"]))
                    issued = self.install(host, session=22, operations=1)
                    self.assertEqual(issued["code"], "ok")
                    self.assertGreater(issued["grant_id"], grant)
                    fresh_caller = caller(session=22)
                    current = self.resolve(host, issued["grant_id"], who=fresh_caller)
                    historical = self.resolve(host, issued["grant_id"], who=fresh_caller, as_of=2)
                    self.assertEqual((current["state"], current["revision"]), ("supported", 3))
                    self.assertEqual((historical["state"], historical["supporting"], historical["opposing"]),
                                     ("contested", 1, 1))
                    evidence = host.request({"op": "inspect", "caller": fresh_caller,
                                             "grant_id": issued["grant_id"], "evidence_id": 1, "as_of": -1})
                    self.assertEqual(evidence["evidence"]["source"], source)
                    self.assertEqual(evidence["evidence"]["entity"], "agent:a")
                    self.assertEqual(evidence["evidence"]["session"], 11)
                    old_view = host.request({"op": "inspect", "caller": fresh_caller,
                                             "grant_id": issued["grant_id"], "evidence_id": 2, "as_of": 2})
                    now_view = host.request({"op": "inspect", "caller": fresh_caller,
                                             "grant_id": issued["grant_id"], "evidence_id": 2, "as_of": -1})
                    self.assertEqual(old_view["evidence"]["withdrawn_at"], 0)
                    self.assertEqual(now_view["evidence"]["withdrawn_at"], 3)

    def test_acknowledged_revocation_and_descendants_survive_sigkill(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                host = HostSession(path, target)
                try:
                    root = self.install(host)
                    self.assertEqual(root["code"], "ok")
                    child = host.request({"op": "delegate", "caller": caller(), "parent_id": root["grant_id"],
                                          "entity": "agent:child", "session": 22, "operations": 9,
                                          "expires": 900, "work_limit": 64, "result_limit": 64})
                    self.assertEqual(child["code"], "ok")
                    grandchild = host.request({"op": "delegate", "caller": caller("agent:child", 22),
                                               "parent_id": child["grant_id"], "entity": "agent:grandchild",
                                               "session": 33, "operations": 1, "expires": 800,
                                               "work_limit": 32, "result_limit": 32})
                    self.assertEqual(grandchild["code"], "ok")
                    revoked = host.request({"op": "revoke", "caller": caller(), "grant_id": root["grant_id"]})
                    self.assertEqual(revoked["code"], "ok")
                    # Inspect before recovery retires every grant: this proves the
                    # acknowledged revocation itself reached the checkpoint.
                    state = checkpoint(path)[1]
                    self.assertEqual([row["revoked"] for row in state["grants"]], [True, False, False])
                    host.close(kill=True)
                    self.assertEqual(host.process.returncode, -signal.SIGKILL)
                    self.assertTrue(checkpoint(path)[1]["grants"][0]["revoked"])
                finally:
                    host.close(kill=True)
                with HostSession(path, target) as reopened:
                    state = checkpoint(path)[1]
                    # ENI-0004: recovery reclaims the rows it retires, so an
                    # ordinary restart no longer spends a lifetime budget. The
                    # guarantee the old row inspection stood for is asserted
                    # by the counters and the denials below: the identifiers
                    # were issued and retired, none is reissued, and every one
                    # is still refused.
                    self.assertEqual(state["grants"], [])
                    self.assertEqual(state["retired_through"], grandchild["grant_id"])
                    self.assertEqual(state["next_grant_id"], grandchild["grant_id"] + 1)
                    for entity, session, grant in (("agent:a", 11, root["grant_id"]),
                                                   ("agent:child", 22, child["grant_id"]),
                                                   ("agent:grandchild", 33, grandchild["grant_id"])):
                        denied = self.resolve(reopened, grant, who=caller(entity, session))
                        self.assertEqual(denied["code"], "denied")
                        self.assertEqual((denied["instance"], denied["generation"]), ("", 0))
                    fresh = self.install(reopened, session=44, operations=1)
                    self.assertEqual(fresh["code"], "ok")
                    self.assertGreater(fresh["grant_id"], grandchild["grant_id"])

    def test_denied_expiry_observation_persists_clock_floor(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                host = HostSession(path, target)
                try:
                    issued = self.install(host, operations=1, tick=1, expires=50)
                    self.assertEqual(issued["code"], "ok")
                    expired = self.resolve(host, issued["grant_id"], who=caller(tick=50))
                    self.assertEqual(expired["code"], "denied")
                    self.assertEqual(checkpoint(path)[1]["clock_floor"], 50)
                    host.close(kill=True)
                    self.assertEqual(checkpoint(path)[1]["clock_floor"], 50)
                finally:
                    host.close(kill=True)
                with HostSession(path, target) as reopened:
                    self.assertEqual(checkpoint(path)[1]["clock_floor"], 50)
                    stale = self.install(reopened, session=22, operations=1, tick=49)
                    self.assertEqual(stale["code"], "invalid")
                    fresh = self.install(reopened, session=22, operations=1, tick=50)
                    self.assertEqual(fresh["code"], "ok")
                    self.assertGreater(fresh["grant_id"], issued["grant_id"])
                    backwards = self.resolve(reopened, fresh["grant_id"], who=caller(session=22, tick=49))
                    self.assertEqual(backwards["code"], "denied")
                    self.assertEqual(checkpoint(path)[1]["clock_floor"], 50)

    def test_old_incarnation_denial_precedes_body_and_does_not_commit(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                with HostSession(path, target) as first:
                    old_instance = first.instance
                with HostSession(path, target) as reopened:
                    before, _state = checkpoint(path)
                    denied = reopened.request({"instance": old_instance, "op": {"bad": "shape"},
                                               "caller": None, "unexpected": "synthetic"})
                    self.assertEqual(denied, {"code": "denied", "instance": "", "generation": 0})
                    self.assertEqual(checkpoint(path)[0], before)

    def test_corrupt_or_missing_primary_never_uses_older_backup(self) -> None:
        for target in TARGETS:
            for variant in ("missing", "truncated", "checksum", "semantic"):
                with self.subTest(target=target, variant=variant), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                    path = Path(temporary) / "db"
                    self.initialize(path, target)
                    with HostSession(path, target) as host:
                        issued = self.install(host)
                        self.assertEqual(issued["code"], "ok")
                        older, _state = checkpoint(path)
                        backup = path / "older-valid-backup.json"
                        backup.write_bytes(older)
                        backup.chmod(0o600)
                        revoked = host.request({"op": "revoke", "caller": caller(), "grant_id": issued["grant_id"]})
                        self.assertEqual(revoked["code"], "ok")
                    canonical = path / "checkpoint.json"
                    content = canonical.read_bytes()
                    if variant == "missing":
                        canonical.unlink()
                    elif variant == "truncated":
                        canonical.write_bytes(content[:len(content) // 2])
                    else:
                        envelope = json.loads(content)
                        state = json.loads(envelope["payload"])
                        if variant == "checksum":
                            state["clock_floor"] += 1
                        else:
                            state["grants"][0]["parent"] = 1
                        envelope["payload"] = json.dumps(state, separators=(",", ":"))
                        if variant == "semantic":
                            envelope["sha256"] = hashlib.sha256(envelope["payload"].encode("utf-8")).hexdigest()
                        canonical.write_text(json.dumps(envelope), encoding="utf-8")
                    broken = canonical.read_bytes() if canonical.exists() else None
                    result = subprocess.run(
                        [*HOST_COMMAND, "serve", str(path), "--target", target],
                        input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=30, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assertIn(b"enigma store: corrupt", result.stderr)
                    self.assertEqual(backup.read_bytes(), older)
                    if broken is None:
                        self.assertFalse(canonical.exists())
                    else:
                        self.assertEqual(canonical.read_bytes(), broken)

    def test_second_process_cannot_recover_while_writer_is_live(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                with HostSession(path, target) as first:
                    before = checkpoint(path)[0]
                    second = subprocess.run(
                        [*HOST_COMMAND, "serve", str(path), "--target", target],
                        input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, check=False,
                    )
                    self.assertNotEqual(second.returncode, 0)
                    self.assertEqual(second.stdout, b"")
                    self.assertIn(b"enigma store: busy", second.stderr)
                    self.assertEqual(checkpoint(path)[0], before)
                    self.assertEqual(self.install(first)["code"], "ok")

    def test_missing_recent_events_fail_closed_even_with_a_matching_digest(self) -> None:
        # Compaction can leave holes only below its declared horizon. A valid
        # checksum over an impossible tail must not become a confident answer.
        for target in TARGETS:
            for variant in ("first", "middle", "last", "all"):
                with self.subTest(target=target, variant=variant), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                    path = Path(temporary) / "db"
                    self.initialize(path, target)
                    with HostSession(path, target) as host:
                        grant = self.install(host)["grant_id"]
                        for revision in range(3):
                            added = host.request({"op": "support", "caller": caller(), "grant_id": grant,
                                                  "claim": CLAIM, "source": "synthetic:tail",
                                                  "expected_revision": revision})
                            self.assertEqual(added["code"], "ok")
                    canonical = path / "checkpoint.json"
                    envelope = json.loads(canonical.read_bytes())
                    state = json.loads(envelope["payload"])
                    self.assertEqual((state["revision"], state["retained_from"]), (3, 0))
                    if variant == "all":
                        state["events"] = []
                    else:
                        del state["events"][{"first": 0, "middle": 1, "last": 2}[variant]]
                    envelope["payload"] = json.dumps(state, separators=(",", ":"))
                    envelope["sha256"] = hashlib.sha256(envelope["payload"].encode("utf-8")).hexdigest()
                    canonical.write_text(json.dumps(envelope), encoding="utf-8")
                    broken = canonical.read_bytes()
                    result = subprocess.run(
                        [*HOST_COMMAND, "serve", str(path), "--target", target],
                        input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=30, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assertIn(b"enigma store: corrupt", result.stderr)
                    self.assertEqual(canonical.read_bytes(), broken)

    def test_restarts_reclaim_grant_rows_and_never_reissue_an_identifier(self) -> None:
        # ENI-0004 end to end. The exhaustion proof is a thousand cycles in
        # the enigma.authority suite, where it costs milliseconds. What needs
        # a real process here is narrower: that the counters survive the
        # codec, the host and an actual restart, and that rows do not pile up
        # across them.
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                issued = []
                for restart in range(5):
                    with HostSession(path, target) as host:
                        # Reclamation happens when a session opens and
                        # recovers, not when one closes, so this is where the
                        # previous session's grant has to have gone.
                        opened = checkpoint(path)[1]
                        self.assertEqual(opened["grants"], [])
                        if issued:
                            self.assertGreaterEqual(opened["retired_through"], issued[-1])
                            self.assertEqual(opened["next_grant_id"], issued[-1] + 1)
                        grant = self.install(host, session=11 + restart)
                        self.assertEqual(grant["code"], "ok")
                        issued.append(grant["grant_id"])
                        live = checkpoint(path)[1]
                        self.assertEqual(len(live["grants"]), 1, "only the admitted grant is live")
                        self.assertEqual(live["grants"][0]["id"], grant["grant_id"])
                # Every identifier was distinct and increasing, so none was
                # handed out twice even though every row was reclaimed.
                self.assertEqual(issued, sorted(set(issued)))
                with HostSession(path, target) as reopened:
                    for grant_id in issued:
                        self.assertEqual(self.resolve(reopened, grant_id)["code"], "denied")

    def test_compaction_reclaims_churn_and_refuses_a_view_it_cannot_rebuild(self) -> None:
        # ENI-0005 end to end. The 300-cycle proof lives in the
        # enigma.evidence suite; what needs a real host here is that an
        # invoked compaction survives the codec and a restart, and that the
        # horizon it set still refuses an older view afterwards.
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                with HostSession(path, target) as host:
                    grant = self.install(host)["grant_id"]
                    kept = host.request({"op": "support", "caller": caller(), "grant_id": grant,
                                         "claim": CLAIM, "source": "synthetic:kept",
                                         "expected_revision": -1})
                    self.assertEqual(kept["code"], "ok")
                    churn = host.request({"op": "oppose", "caller": caller(), "grant_id": grant,
                                          "claim": CLAIM, "source": "synthetic:churn",
                                          "expected_revision": -1})
                    self.assertEqual(churn["code"], "ok")
                    gone = host.request({"op": "withdraw", "caller": caller(), "grant_id": grant,
                                         "evidence_id": churn["evidence_id"], "expected_revision": -1})
                    self.assertEqual(gone["code"], "ok")
                    before = len(checkpoint(path)[1]["events"])
                    denied = host.request({"op": "compact", "caller": caller(), "grant_id": grant})
                    self.assertEqual(denied, {"code": "denied", "instance": "", "generation": 0})
                    self.assertEqual(len(checkpoint(path)[1]["events"]), before)
                    maintenance = self.install(host, entity="agent:maintenance", session=31, operations=16)
                    self.assertEqual(maintenance["code"], "ok")
                    compacted = host.request({"op": "compact", "caller": caller("agent:maintenance", 31),
                                              "grant_id": maintenance["grant_id"]})
                    self.assertEqual(compacted["code"], "ok")
                    # The withdrawn pair goes; the assertion nobody retracted stays.
                    self.assertEqual(compacted["reclaimed"], 2)
                    self.assertEqual(compacted["retained_from"], gone["revision"])
                    after = checkpoint(path)[1]
                    self.assertEqual(len(after["events"]), before - 2)
                    self.assertEqual(after["retained_from"], gone["revision"])
                    # The clock did not rewind, so an identifier still means
                    # what it meant.
                    self.assertEqual(after["revision"], gone["revision"])
                    self.assertEqual([row["id"] for row in after["events"]], [kept["evidence_id"]])
                # The horizon survives a restart, and so does the refusal.
                with HostSession(path, target) as reopened:
                    live = self.resolve(reopened, grant)
                    self.assertEqual(live["code"], "denied", "the old grant was retired by recovery")
                    fresh = self.install(reopened, session=12)["grant_id"]
                    holder = caller(session=12)
                    current = self.resolve(reopened, fresh, who=holder)
                    self.assertEqual(current["state"], "supported")
                    self.assertTrue(current["complete"])
                    # A view inside the reclaimed window cannot be rebuilt, so
                    # it is refused rather than answered with confidence.
                    stale = reopened.request({"op": "resolve", "caller": holder, "grant_id": fresh,
                                              "claim": CLAIM, "as_of": 1, "max_work": 128,
                                              "max_evidence": 128})
                    self.assertEqual(stale["state"], "incomplete")
                    self.assertFalse(stale["complete"])

    def test_restoring_older_coherent_checkpoint_does_not_reactivate_session(self) -> None:
        for target in TARGETS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="enigma-recovery-") as temporary:
                path = Path(temporary) / "db"
                self.initialize(path, target)
                with HostSession(path, target) as host:
                    old_instance = host.instance
                    issued = self.install(host, operations=1)
                    self.assertEqual(issued["code"], "ok")
                    old_checkpoint, old_state = checkpoint(path)
                    self.assertFalse(old_state["grants"][0]["revoked"])
                    revoked = host.request({"op": "revoke", "caller": caller(), "grant_id": issued["grant_id"]})
                    self.assertEqual(revoked["code"], "ok")
                    self.assertTrue(checkpoint(path)[1]["grants"][0]["revoked"])
                # Simulate operator restoration of a complete, checksummed older
                # file. Latest evidence history cannot be proved in this threat
                # model, but restored session authority must still be retired.
                (path / "checkpoint.json").write_bytes(old_checkpoint)
                with HostSession(path, target) as reopened:
                    self.assertNotEqual(reopened.instance, old_instance)
                    # ENI-0004: the restored grant is not merely marked
                    # revoked, it is reclaimed and its identifier sits below
                    # the retirement mark, which is a stronger statement of
                    # the same guarantee.
                    restored = checkpoint(path)[1]
                    self.assertEqual(restored["grants"], [])
                    self.assertGreaterEqual(restored["retired_through"], issued["grant_id"])
                    old_envelope = reopened.request({"op": "resolve", "instance": old_instance,
                                                     "caller": caller(), "grant_id": issued["grant_id"],
                                                     "claim": CLAIM, "as_of": -1,
                                                     "max_work": 128, "max_evidence": 128})
                    self.assertEqual(old_envelope, {"code": "denied", "instance": "", "generation": 0})
                    self.assertEqual(self.resolve(reopened, issued["grant_id"])["code"], "denied")


if __name__ == "__main__":
    if not TARGETS or any(target not in ("vm", "native") for target in TARGETS):
        raise SystemExit("ENIGMA_TEST_TARGETS must be a comma-separated list of vm/native targets")
    unittest.main()
