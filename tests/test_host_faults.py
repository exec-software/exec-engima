"""Storage-fault behavior of a durable host, injected from outside it.

ENI-0003 phase D. The Python host's fault checks in test_durable_host.py
replace its own PosixIO to force short writes, synchronization failures and
replace failures. That seam cannot be reused here, and adding one to the Matrix
host would be worse than having no test: a production host with a fault switch
is no longer the thing under test. NIL-0028's own helpers carry that rule
explicitly.

So these faults come from the filesystem and the process environment instead,
which is where real ones come from. What is deliberately *not* claimed: a
partial write followed by success, and a crash at a chosen commit phase, both
of which need a seam inside the host. `RLIMIT_FSIZE` makes a write fail rather
than truncate, and the SIGKILL check in test_storage_recovery.py kills at an
arbitrary point rather than a chosen one.

Every check here holds for either host, and the runner exercises both. That
is the point: a scenario only one host satisfies is a description of that
host, not of the contract.

Skipped unless ENIGMA_HOST_COMMAND names a host, so ./scripts/test.sh keeps
running against the previously selected SDK.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import shlex
import signal
import stat
import subprocess
import tempfile
import unittest


HOST_COMMAND = shlex.split(os.environ.get("ENIGMA_HOST_COMMAND", ""))
REASON = "set ENIGMA_HOST_COMMAND to a durable host to exercise"


def small_file_limit() -> None:
    # A checkpoint is larger than this, so publishing one fails outright.
    resource.setrlimit(resource.RLIMIT_FSIZE, (64, 64))


@unittest.skipUnless(HOST_COMMAND, REASON)
class HostFaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="enigma-matrix-fault."))
        self.database = self.workspace / "db"

    def tearDown(self) -> None:
        # A failed test can leave the directory unwritable.
        for path in (self.database, self.workspace):
            try:
                path.chmod(0o700)
            except OSError:
                pass
        subprocess.run(["rm", "-rf", str(self.workspace)], check=False)

    def initialize(self) -> dict:
        result = subprocess.run([*HOST_COMMAND, "init", str(self.database), "--scope", "work"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)

    def serve(self, requests: bytes = b"", *, preexec=None, timeout: int = 60):
        return subprocess.run([*HOST_COMMAND, "serve", str(self.database)],
                              input=requests, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout,
                              preexec_fn=preexec)

    def read_line(self, process, timeout: float = 30) -> bytes:
        import select
        import time
        pending = b""
        deadline = time.monotonic() + timeout
        while b"\n" not in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("timed out waiting for a host receipt")
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                continue
            chunk = process.stdout.read(1)
            if not chunk:
                raise AssertionError("host closed its output before a receipt")
            pending += chunk
        return pending

    def checkpoint(self) -> bytes:
        return (self.database / "checkpoint.json").read_bytes()

    def test_a_failed_commit_never_acknowledges_recovery(self) -> None:
        self.initialize()
        before = self.checkpoint()
        # Recovery has to commit a fresh incarnation before it is ready, so a
        # host that cannot write must not report readiness.
        result = self.serve(preexec=small_file_limit)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'"ready"', result.stdout)
        self.assertEqual(self.checkpoint(), before,
                         "a failed commit must leave the committed checkpoint intact")

    def test_an_unwritable_directory_stops_the_session_without_a_receipt(self) -> None:
        self.initialize()
        # Readiness is acknowledged first, and only then does publication
        # become impossible. Denying it before startup would test the opposite
        # thing: the directory preflight, which refuses to serve at all.
        process = subprocess.Popen([*HOST_COMMAND, "serve", str(self.database)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0)
        try:
            ready = self.read_line(process)
            self.assertIn(b'"ready"', ready, ready)
            # Recovery committed a fresh incarnation to become ready, so the
            # baseline is the checkpoint as of readiness, not as of creation.
            before = self.checkpoint()
            self.database.chmod(0o500)
            # The request has to bind the live incarnation, or the engine
            # denies it before its body and the denial changes nothing, so
            # there would be no publication to fail.
            install = json.dumps({"op": "install", "entity": "agent:a", "session": 11,
                                  "operations": 15, "expires": 1000, "work_limit": 128,
                                  "result_limit": 128, "tick": 10,
                                  "instance": json.loads(ready)["instance"]}).encode() + b"\n"
            process.stdin.write(install)
            process.stdin.flush()
            remainder, _ = process.communicate(timeout=30)
        finally:
            self.database.chmod(0o700)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        # Whatever the engine would have answered, an effect that cannot be
        # published is never acknowledged.
        self.assertEqual(remainder.strip(), b"", remainder)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(self.checkpoint(), before)

    def test_unsafe_modes_are_refused_before_serving(self) -> None:
        self.initialize()
        for name, mode in (("", 0o755), ("checkpoint.json", 0o644), (".lock", 0o644)):
            target = self.database / name if name else self.database
            original = stat.S_IMODE(target.stat().st_mode)
            target.chmod(mode)
            try:
                result = self.serve()
                self.assertNotEqual(result.returncode, 0,
                                    f"serving should refuse mode {mode:o} on {name or 'the directory'}")
                self.assertNotIn(b'"ready"', result.stdout)
            finally:
                target.chmod(original)

    def test_a_checkpoint_that_is_not_a_private_regular_file_fails_closed(self) -> None:
        self.initialize()
        canonical = self.database / "checkpoint.json"
        saved = canonical.read_bytes()
        elsewhere = self.workspace / "elsewhere.json"
        elsewhere.write_bytes(saved)
        elsewhere.chmod(0o600)

        # A symlink to a perfectly good checkpoint is still not the checkpoint.
        canonical.unlink()
        canonical.symlink_to(elsewhere)
        result = self.serve()
        self.assertNotEqual(result.returncode, 0, "a symlinked checkpoint must be refused")
        self.assertNotIn(b'"ready"', result.stdout)
        canonical.unlink()

        # Nor is a FIFO, which would also block a reader that followed it.
        os.mkfifo(canonical, 0o600)
        result = self.serve(timeout=30)
        self.assertNotEqual(result.returncode, 0, "a FIFO checkpoint must be refused")
        self.assertNotIn(b'"ready"', result.stdout)
        canonical.unlink()

        # A second hard link means another name reaches the same inode.
        os.link(elsewhere, canonical)
        result = self.serve()
        self.assertNotEqual(result.returncode, 0, "a multiply-linked checkpoint must be refused")
        self.assertNotIn(b'"ready"', result.stdout)
        canonical.unlink()

        canonical.write_bytes(saved)
        canonical.chmod(0o600)
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn(b'"ready"', result.stdout)

    def test_request_framing_is_bounded_and_malformed_input_does_not_commit(self) -> None:
        self.initialize()
        process = subprocess.Popen([*HOST_COMMAND, "serve", str(self.database)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0)
        try:
            ready = self.read_line(process)
            self.assertIn(b'"ready"', ready, ready)
            after_recovery = self.checkpoint()
            # Text that is not an object is refused, and the session carries on.
            process.stdin.write(b"not json at all\n")
            process.stdin.flush()
            self.assertIn(b'"invalid"', self.read_line(process))
            process.stdin.write(b"[1,2,3]\n")
            process.stdin.flush()
            self.assertIn(b'"invalid"', self.read_line(process))
            self.assertEqual(self.checkpoint(), after_recovery,
                             "a refused request must not publish anything")
            # A request beyond the framing bound ends the session instead of
            # being truncated into a different, valid request.
            process.stdin.write(b'{"op":"' + b"x" * 70000 + b'"}\n')
            process.stdin.flush()
            remainder, _ = process.communicate(timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        self.assertEqual(remainder.strip(), b"", remainder)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(self.checkpoint(), after_recovery)

    def test_a_truncated_or_rewritten_envelope_fails_closed(self) -> None:
        self.initialize()
        canonical = self.database / "checkpoint.json"
        saved = canonical.read_bytes()
        envelope = json.loads(saved)

        def rewrite(content: bytes) -> None:
            canonical.unlink()
            canonical.write_bytes(content)
            canonical.chmod(0o600)

        # Truncation, a digest that describes nothing here, and a payload
        # changed without its digest. None may be adopted.
        cases = {
            "truncated": saved[: len(saved) // 2],
            "wrong digest": json.dumps({**envelope, "sha256": "0" * 64},
                                       separators=(",", ":")).encode(),
            # Any different payload text invalidates the digest. A trailing
            # space keeps it valid JSON, so this tests digest verification
            # rather than the decoder rejecting malformed state.
            "edited payload": json.dumps({**envelope, "payload": envelope["payload"] + " "},
                                         separators=(",", ":")).encode(),
        }
        for label, content in cases.items():
            rewrite(content)
            result = self.serve()
            self.assertNotEqual(result.returncode, 0, f"{label} must fail closed")
            self.assertNotIn(b'"ready"', result.stdout, label)

        rewrite(saved)
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
