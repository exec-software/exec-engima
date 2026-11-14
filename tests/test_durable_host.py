"""Filesystem and acknowledgement tests; engine recovery is tested in Matrix."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("enigma_store_host", ROOT / "scripts" / "store.py")
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


class FakeWorker:
    """A deterministic transport fixture, without Enigma policy behavior."""

    def __init__(self):
        self.calls = []

    def __call__(self, envelope):
        self.calls.append(envelope)
        mode = envelope["mode"]
        if mode == "create":
            state = {"database_id": envelope["database_id"],
                     "incarnation": envelope["incarnation"], "generation": 0,
                     "marker": "initial"}
            code = "created"
        else:
            state = json.loads(envelope["payload"])
            if mode == "apply" and envelope["request"].get("instance") != state["incarnation"]:
                return {"code": "ok", "payload": envelope["payload"],
                        "receipt": {"code": "denied", "instance": "", "generation": 0}}
            state["generation"] += 1
            if mode == "recover":
                state["incarnation"] = envelope["incarnation"]
                code = "ready"
            else:
                state["marker"] = envelope["request"].get("marker", "applied")
                code = "ok"
        receipt = {"code": code, "instance": state["incarnation"],
                   "generation": state["generation"]}
        if mode == "apply" and envelope["request"].get("denied"):
            receipt = {"code": "denied", "instance": "", "generation": 0}
        if receipt["code"] in ("ok", "ready", "created"):
            receipt["database_id"] = state["database_id"]
        return {"code": "ok", "payload": json.dumps(state, separators=(",", ":")),
                "receipt": receipt}


class FaultIO(host.PosixIO):
    def __init__(self, phase=None, short_writes=False):
        self.phase = phase
        self.short_writes = short_writes
        self.events = []

    def write(self, descriptor, data):
        self.events.append("write")
        if self.phase == "write":
            return 0
        if self.short_writes:
            return os.write(descriptor, data[:7])
        return super().write(descriptor, data)

    def sync(self, descriptor):
        kind = "directory_sync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file_sync"
        self.events.append(kind)
        if self.phase == kind:
            raise OSError("synthetic sync failure")
        return super().sync(descriptor)

    def replace(self, source, destination, directory):
        self.events.append("replace")
        if self.phase == "replace":
            raise OSError("synthetic rename failure")
        return super().replace(source, destination, directory)


class DurableHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "database"
        self.worker = FakeWorker()

    def tearDown(self):
        self.temporary.cleanup()

    def initialize(self, io_boundary=None):
        with host.Store(str(self.path), self.worker, create=True, io=io_boundary) as store:
            return store.initialize("synthetic")

    def read_envelope(self):
        return json.loads((self.path / host.CHECKPOINT).read_bytes())

    def test_initialization_uses_private_files_and_syncs_before_acknowledgement(self):
        boundary = FaultIO(short_writes=True)
        created = self.initialize(boundary)
        self.assertEqual(created["code"], "created")
        self.assertEqual(created["generation"], 0)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.path / host.CHECKPOINT).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.path / host.LOCK).stat().st_mode), 0o600)
        self.assertGreater(boundary.events.count("write"), 1)
        self.assertEqual(boundary.events[-4:], ["file_sync", "replace", "directory_sync", "directory_sync"])
        envelope = self.read_envelope()
        self.assertEqual(envelope["sha256"], hashlib.sha256(envelope["payload"].encode()).hexdigest())

    def test_recovery_rotates_incarnation_and_commits_before_ready(self):
        created = self.initialize()
        boundary = FaultIO()
        with host.Store(str(self.path), self.worker, io=boundary) as store:
            ready = store.recover()
            self.assertEqual(ready["code"], "ready")
            self.assertEqual(ready["generation"], 1)
            self.assertNotEqual(ready["instance"], created["instance"])
            self.assertEqual(json.loads(self.read_envelope()["payload"])["incarnation"], ready["instance"])
            self.assertEqual(boundary.events[-3:], ["file_sync", "replace", "directory_sync"])

    def test_missing_primary_never_initializes_or_uses_a_backup(self):
        self.initialize()
        (self.path / host.CHECKPOINT).rename(self.path / "checkpoint.backup")
        calls = len(self.worker.calls)
        with host.Store(str(self.path), self.worker) as store:
            with self.assertRaisesRegex(host.StoreError, "corrupt"):
                store.recover()
        self.assertEqual(len(self.worker.calls), calls)
        self.assertFalse((self.path / host.CHECKPOINT).exists())

    def test_corruption_never_falls_back_to_an_older_checkpoint(self):
        self.initialize()
        backup = (self.path / host.CHECKPOINT).read_bytes()
        (self.path / "checkpoint.backup").write_bytes(backup)
        envelope = self.read_envelope()
        envelope["payload"] += " "
        (self.path / host.CHECKPOINT).write_text(json.dumps(envelope))
        with host.Store(str(self.path), self.worker) as store:
            with self.assertRaisesRegex(host.StoreError, "corrupt"):
                store.recover()
        self.assertEqual((self.path / "checkpoint.backup").read_bytes(), backup)

    def test_duplicate_keys_nonfinite_numbers_and_bad_unicode_are_rejected(self):
        for value in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                      b'{"a":1e999}', b'{"a":"\\ud800"}', b'{"a":"\xff"}'):
            with self.subTest(value=value), self.assertRaises(host.StoreError):
                host.strict_json(value)
        with self.assertRaises(host.StoreError):
            host.strict_json("[" * 40 + "0" + "]" * 40)

    def test_envelope_requires_exact_keys_and_digest(self):
        self.initialize()
        original = self.read_envelope()
        for change in ({**original, "extra": 1}, {**original, "format": "other"},
                       {**original, "sha256": "0" * 64}):
            with self.subTest(change=change):
                (self.path / host.CHECKPOINT).write_text(json.dumps(change))
                with host.Store(str(self.path), self.worker) as store:
                    with self.assertRaises(host.StoreError):
                        store.recover()

    def test_second_writer_is_rejected_without_running_worker(self):
        self.initialize()
        with host.Store(str(self.path), self.worker):
            calls = len(self.worker.calls)
            with self.assertRaisesRegex(host.StoreError, "busy"):
                host.Store(str(self.path), self.worker)
            self.assertEqual(len(self.worker.calls), calls)

    def test_existing_directory_is_never_reinitialized(self):
        self.initialize()
        previous = (self.path / host.CHECKPOINT).read_bytes()
        with self.assertRaisesRegex(host.StoreError, "exists"):
            host.Store(str(self.path), self.worker, create=True)
        self.assertEqual((self.path / host.CHECKPOINT).read_bytes(), previous)

    def test_symlink_and_hardlinked_primary_are_rejected(self):
        self.initialize()
        primary = self.path / host.CHECKPOINT
        real = self.path / "real"
        primary.rename(real)
        primary.symlink_to(real.name)
        with host.Store(str(self.path), self.worker) as store:
            with self.assertRaises(host.StoreError):
                store.recover()
        primary.unlink()
        os.link(real, primary)
        with host.Store(str(self.path), self.worker) as store:
            with self.assertRaises(host.StoreError):
                store.recover()

    def test_unsafe_directory_lock_and_checkpoint_permissions_are_rejected(self):
        self.initialize()
        os.chmod(self.path, 0o755)
        with self.assertRaisesRegex(host.StoreError, "unsafe_directory"):
            host.Store(str(self.path), self.worker)
        os.chmod(self.path, 0o700)
        os.chmod(self.path / host.LOCK, 0o644)
        with self.assertRaisesRegex(host.StoreError, "unsafe_file"):
            host.Store(str(self.path), self.worker)
        os.chmod(self.path / host.LOCK, 0o600)
        os.chmod(self.path / host.CHECKPOINT, 0o644)
        with host.Store(str(self.path), self.worker) as store:
            with self.assertRaises(host.StoreError):
                store.recover()

    def test_storage_failures_poison_service_and_never_return_a_receipt(self):
        self.initialize()
        for phase in ("write", "file_sync", "replace", "directory_sync"):
            with self.subTest(phase=phase):
                boundary = FaultIO()
                with host.Store(str(self.path), self.worker, io=boundary) as store:
                    ready = store.recover()
                    before = (self.path / host.CHECKPOINT).read_bytes()
                    boundary.phase = phase
                    with self.assertRaisesRegex(host.StoreError, "storage_error"):
                        store.apply({"instance": ready["instance"], "marker": phase})
                    self.assertTrue(store.poisoned)
                    with self.assertRaisesRegex(host.StoreError, "poisoned"):
                        store.apply({"instance": ready["instance"]})
                    if phase != "directory_sync":
                        self.assertEqual((self.path / host.CHECKPOINT).read_bytes(), before)
                self.assertFalse(any(p.name.startswith(".checkpoint-") for p in self.path.iterdir()))

    def test_abrupt_commit_crashes_preserve_a_complete_canonical_checkpoint(self):
        phases = ("partial_write", "after_file_sync", "after_replace", "after_directory_sync")
        for phase in phases:
            with self.subTest(phase=phase):
                path = Path(self.temporary.name) / phase
                with host.Store(str(path), self.worker, create=True) as store:
                    store.initialize("synthetic")
                    previous = store.payload
                candidate_state = json.loads(previous)
                candidate_state["generation"] += 1
                candidate_state["marker"] = "candidate:" + phase
                candidate = json.dumps(candidate_state, separators=(",", ":"))

                class CrashIO(host.PosixIO):
                    def write(self, descriptor, data):
                        if phase == "partial_write":
                            os.write(descriptor, data[:max(1, len(data) // 2)])
                            os._exit(73)
                        return super().write(descriptor, data)

                    def sync(self, descriptor):
                        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
                        super().sync(descriptor)
                        if ((phase == "after_file_sync" and not is_directory)
                                or (phase == "after_directory_sync" and is_directory)):
                            os._exit(73)

                    def replace(self, source, destination, directory):
                        super().replace(source, destination, directory)
                        if phase == "after_replace":
                            os._exit(73)

                receipt_reader, receipt_writer = os.pipe()
                child = os.fork()
                if child == 0:
                    os.close(receipt_reader)
                    try:
                        with host.Store(str(path), self.worker, io=CrashIO()) as store:
                            # This test isolates commit publication, not engine
                            # admission. A receipt would follow a returned commit.
                            store.payload = previous
                            store.commit(candidate)
                            os.write(receipt_writer, b"ACK\n")
                    except BaseException:
                        os._exit(91)
                    os._exit(92)
                os.close(receipt_writer)
                status = None
                try:
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        completed, observed_status = os.waitpid(child, os.WNOHANG)
                        if completed == child:
                            status = observed_status
                            break
                        time.sleep(0.01)
                    if status is None:
                        os.kill(child, signal.SIGKILL)
                        os.waitpid(child, 0)
                        self.fail("crash fixture failed to terminate")
                    self.assertTrue(os.WIFEXITED(status))
                    self.assertEqual(os.WEXITSTATUS(status), 73)
                    self.assertEqual(os.read(receipt_reader, 1024), b"",
                                     "receipt escaped before interrupted commit completed")
                finally:
                    os.close(receipt_reader)

                # Opening the lock after abrupt exit also proves that kernel
                # cleanup released it despite bypassing Python finally blocks.
                with host.Store(str(path), self.worker) as recovered:
                    payload = recovered.load()
                self.assertIn(payload, (previous, candidate))
                if phase in ("partial_write", "after_file_sync"):
                    self.assertEqual(payload, previous)
                    self.assertTrue(any(item.name.startswith(".checkpoint-")
                                        for item in path.iterdir()))
                if phase == "after_directory_sync":
                    self.assertEqual(payload, candidate)

    def test_stale_instance_denial_does_not_rewrite_checkpoint(self):
        self.initialize()
        boundary = FaultIO()
        with host.Store(str(self.path), self.worker, io=boundary) as store:
            store.recover()
            before = (self.path / host.CHECKPOINT).read_bytes()
            boundary.events.clear()
            denied = store.apply({"instance": "0" * 32})
            self.assertEqual(denied, {"code": "denied", "instance": "", "generation": 0})
            self.assertEqual(boundary.events, [])
            self.assertEqual((self.path / host.CHECKPOINT).read_bytes(), before)

    def test_bad_worker_binding_is_not_published(self):
        self.initialize()
        before = (self.path / host.CHECKPOINT).read_bytes()
        def bad_worker(envelope):
            reply = self.worker(envelope)
            reply["receipt"]["instance"] = "0" * 32
            return reply
        with host.Store(str(self.path), bad_worker) as store:
            with self.assertRaisesRegex(host.StoreError, "worker_protocol"):
                store.recover()
            self.assertTrue(store.poisoned)
        self.assertEqual((self.path / host.CHECKPOINT).read_bytes(), before)

    def test_changed_denial_still_commits_before_metadata_free_receipt(self):
        self.initialize()
        boundary = FaultIO()
        with host.Store(str(self.path), self.worker, io=boundary) as store:
            ready = store.recover()
            boundary.events.clear()
            denied = store.apply({"instance": ready["instance"], "denied": True})
            self.assertEqual(denied, {"code": "denied", "instance": "", "generation": 0})
            self.assertEqual(json.loads(self.read_envelope()["payload"])["generation"], 2)
            self.assertEqual(boundary.events[-3:], ["file_sync", "replace", "directory_sync"])

    def test_fifo_primary_is_rejected_without_blocking(self):
        self.initialize()
        (self.path / host.CHECKPOINT).unlink()
        os.mkfifo(self.path / host.CHECKPOINT, 0o600)
        with host.Store(str(self.path), self.worker) as store:
            with self.assertRaises(host.StoreError):
                store.recover()

    def test_worker_output_is_bounded_and_exactly_one_json_line(self):
        for program in ("print('{}'); print('{}')", "print('x' * 2200000)",
                        "import sys; sys.stderr.write('failure')", "print('{bad')"):
            with self.subTest(program=program):
                transport = host._worker_transport([sys.executable, "-c", program])
                with self.assertRaises(host.StoreError):
                    transport({"input": "fixture"})

    def test_exited_worker_parent_does_not_leave_a_pipe_holding_descendant(self):
        pid_file = Path(self.temporary.name) / "descendant.pid"
        program = (
            "import os,time\n"
            "child=os.fork()\n"
            "if child == 0:\n"
            "    time.sleep(60)\n"
            "    os._exit(0)\n"
            f"with open({str(pid_file)!r}, 'w') as output: output.write(str(child))\n"
            "os._exit(0)\n"
        )
        transport = host._worker_transport([sys.executable, "-c", program], _timeout=0.25)
        child = None
        try:
            with self.assertRaises(host.StoreError):
                transport({"input": "fixture"})
            self.assertTrue(pid_file.exists())
            child = int(pid_file.read_text())
            stopped = False
            for _attempt in range(50):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    stopped = True
                    break
                status = Path(f"/proc/{child}/stat")
                if status.exists() and status.read_text().split(") ", 1)[1].startswith("Z "):
                    stopped = True
                    break
                time.sleep(0.01)
            self.assertTrue(stopped, "worker descendant survived owned-group cleanup")
        finally:
            if child is not None:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_commit_failure_stops_main_before_next_request(self):
        self.initialize()
        boundary = FaultIO()
        output, errors = io.StringIO(), io.StringIO()
        worker = self.worker
        def failing_worker(envelope):
            reply = worker(envelope)
            if envelope["mode"] == "apply":
                boundary.phase = "file_sync"
            return reply
        class LiveInput:
            calls = 0
            def readline(self, size):
                self.calls += 1
                ready = json.loads(output.getvalue().splitlines()[0])
                return json.dumps({"instance": ready["instance"]}).encode() + b"\n"
        incoming = LiveInput()
        status = host.main(["serve", str(self.path)], input_stream=incoming, output_stream=output,
                           error_stream=errors, _worker=failing_worker, _io=boundary)
        self.assertEqual(status, 1)
        self.assertEqual(incoming.calls, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertIn("storage_error", errors.getvalue())

    def test_request_framing_is_bounded_and_remainder_never_becomes_a_request(self):
        self.initialize()
        class BoundedInput(io.BytesIO):
            def readline(self, size=-1):
                if size != host.MAX_REQUEST + 1:
                    raise AssertionError("unbounded input read")
                return super().readline(size)
        for content in (b"x" * (host.MAX_REQUEST + 10) + b'\n{}\n', b'{}'):
            with self.subTest(content_length=len(content)):
                output, errors = io.StringIO(), io.StringIO()
                before = len([item for item in self.worker.calls if item["mode"] == "apply"])
                status = host.main(["serve", str(self.path)], input_stream=BoundedInput(content),
                                   output_stream=output, error_stream=errors, _worker=self.worker)
                self.assertEqual(status, 1)
                self.assertEqual(len(output.getvalue().splitlines()), 1)
                self.assertIn("invalid_request", errors.getvalue())
                self.assertEqual(len([item for item in self.worker.calls if item["mode"] == "apply"]), before)

    def test_malformed_request_has_no_worker_effect_and_complete_next_line_can_continue(self):
        self.initialize()
        output, errors = io.StringIO(), io.StringIO()
        content = b'{"x":1,"x":2}\n{"instance":"stale"}\n'
        status = host.main(["serve", str(self.path)], input_stream=io.BytesIO(content),
                           output_stream=output, error_stream=errors, _worker=self.worker)
        self.assertEqual(status, 0)
        receipts = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([receipt["code"] for receipt in receipts], ["ready", "invalid", "denied"])
        self.assertEqual(errors.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
