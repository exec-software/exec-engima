#!/usr/bin/env python3
"""POSIX durability and process glue for the Matrix storage worker.

The worker owns engine and permission semantics. This host owns one private
directory, one writer lock, checkpoint integrity, and durable acknowledgement.
Only trusted local embedding code may provide a worker or I/O implementation.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import BinaryIO, Callable, TextIO


MAX_CHECKPOINT = 1024 * 1024
MAX_REQUEST = 65536
MAX_WORKER_OUTPUT = 2 * MAX_CHECKPOINT
MAX_GENERATION = (1 << 63) - 1
CHECKPOINT = "checkpoint.json"
LOCK = ".lock"
FORMAT = "enigma.checkpoint.v1"
ROOT = Path(__file__).resolve().parent.parent
HEX_ID = re.compile(r"[0-9a-f]{32}\Z")


class StoreError(Exception):
    """A fixed public error code, never a path or underlying host diagnostic."""


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("nonfinite constant")


def strict_json(data: str | bytes) -> object:
    """Reject ambiguous keys, nonfinite numbers, bad Unicode, and deep input."""
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                raise ValueError("nesting")
            if isinstance(item, str):
                item.encode("utf-8", "strict")
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("nonfinite number")
            elif isinstance(item, dict):
                pending.extend((key, depth + 1) for key in item)
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise StoreError("invalid_json") from error


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8", "strict")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise StoreError("worker_protocol") from error


def _metadata(payload: str) -> tuple[str, str, int]:
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_CHECKPOINT:
        raise StoreError("worker_protocol")
    data = strict_json(payload)
    if not isinstance(data, dict):
        raise StoreError("worker_protocol")
    database_id = data.get("database_id")
    incarnation = data.get("incarnation")
    generation = data.get("generation")
    if (not isinstance(database_id, str) or not HEX_ID.fullmatch(database_id)
            or not isinstance(incarnation, str) or not HEX_ID.fullmatch(incarnation)
            or type(generation) is not int or not 0 <= generation <= MAX_GENERATION):
        raise StoreError("worker_protocol")
    return database_id, incarnation, generation


def _private_regular(descriptor: int) -> os.stat_result:
    current = os.fstat(descriptor)
    if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.geteuid()
            or current.st_nlink != 1 or stat.S_IMODE(current.st_mode) != 0o600):
        raise StoreError("unsafe_file")
    return current


class PosixIO:
    """Small injectable syscall boundary for deterministic fault tests."""

    def write(self, descriptor: int, data: bytes) -> int:
        return os.write(descriptor, data)

    def sync(self, descriptor: int) -> None:
        os.fsync(descriptor)

    def replace(self, source: str, destination: str, directory: int) -> None:
        os.replace(source, destination, src_dir_fd=directory, dst_dir_fd=directory)


class Store:
    def __init__(self, path: str, worker: Callable[[dict], dict], *,
                 create: bool = False, io: PosixIO | None = None):
        self.path = os.path.abspath(path)
        self.worker = worker
        self.io = io or PosixIO()
        self.directory = -1
        self.lock = -1
        self.payload = ""
        self.poisoned = False
        self.new = create
        try:
            if create:
                os.mkdir(self.path, 0o700)
                os.chmod(self.path, 0o700, follow_symlinks=False)
            self.directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY |
                                     os.O_NOFOLLOW | os.O_CLOEXEC)
            current = os.fstat(self.directory)
            if current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o700:
                raise StoreError("unsafe_directory")
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            self.lock = os.open(LOCK, flags, 0o600, dir_fd=self.directory)
            if create:
                os.fchmod(self.lock, 0o600)
            _private_regular(self.lock)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StoreError("busy") from error
            visible = os.stat(LOCK, dir_fd=self.directory, follow_symlinks=False)
            held = os.fstat(self.lock)
            if (visible.st_dev, visible.st_ino) != (held.st_dev, held.st_ino):
                raise StoreError("unsafe_file")
        except StoreError:
            self.close()
            raise
        except FileExistsError as error:
            self.close()
            raise StoreError("exists") from error
        except OSError as error:
            self.close()
            raise StoreError("storage_error") from error

    def close(self) -> None:
        for name in ("lock", "directory"):
            descriptor = getattr(self, name, -1)
            if descriptor >= 0:
                setattr(self, name, -1)
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def load(self) -> str:
        descriptor = -1
        try:
            descriptor = os.open(CHECKPOINT, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                 dir_fd=self.directory)
            before = _private_regular(descriptor)
            if before.st_size > MAX_CHECKPOINT:
                raise StoreError("corrupt")
            chunks = []
            remaining = MAX_CHECKPOINT + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = _private_regular(descriptor)
            if (len(content) > MAX_CHECKPOINT or len(content) != before.st_size
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise StoreError("corrupt")
            envelope = strict_json(content)
            if (not isinstance(envelope, dict)
                    or set(envelope) != {"format", "payload", "sha256"}
                    or envelope["format"] != FORMAT
                    or not isinstance(envelope["payload"], str)
                    or not isinstance(envelope["sha256"], str)):
                raise StoreError("corrupt")
            payload = envelope["payload"]
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if not secrets.compare_digest(envelope["sha256"], digest):
                raise StoreError("corrupt")
            _metadata(payload)
            return payload
        except (OSError, ValueError, UnicodeError, StoreError) as error:
            raise StoreError("corrupt") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def commit(self, payload: str) -> None:
        if self.poisoned:
            raise StoreError("poisoned")
        temporary = ".checkpoint-" + secrets.token_hex(16)
        descriptor = -1
        try:
            content = _json_bytes({"format": FORMAT, "payload": payload,
                                   "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()})
            if len(content) > MAX_CHECKPOINT:
                raise StoreError("checkpoint_too_large")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                                 dir_fd=self.directory)
            os.fchmod(descriptor, 0o600)
            offset = 0
            while offset < len(content):
                written = self.io.write(descriptor, content[offset:])
                if written <= 0 or written > len(content) - offset:
                    raise OSError("short write")
                offset += written
            self.io.sync(descriptor)
            os.close(descriptor)
            descriptor = -1
            self.io.replace(temporary, CHECKPOINT, self.directory)
            self.io.sync(self.directory)
            self.payload = payload
        except (OSError, StoreError, UnicodeError) as error:
            self.poisoned = True
            raise StoreError("storage_error") from error
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                os.unlink(temporary, dir_fd=self.directory)
            except OSError:
                pass

    def _stage(self, mode: str, database_id: str, incarnation: str,
               scope: str = "", request: dict | None = None) -> tuple[str, dict]:
        if self.poisoned:
            raise StoreError("poisoned")
        envelope = {"mode": mode, "payload": self.payload, "database_id": database_id,
                    "incarnation": incarnation, "scope": scope, "request": request or {}}
        try:
            reply = self.worker(envelope)
            if not isinstance(reply, dict) or reply.get("code") != "ok":
                raise StoreError("corrupt" if isinstance(reply, dict) and reply.get("code") == "corrupt"
                                 else "worker_protocol")
            if set(reply) != {"code", "payload", "receipt"} or not isinstance(reply["receipt"], dict):
                raise StoreError("worker_protocol")
            candidate, receipt = reply["payload"], reply["receipt"]
            if mode == "apply" and candidate == self.payload:
                if receipt != {"code": "denied", "instance": "", "generation": 0}:
                    raise StoreError("worker_protocol")
                return candidate, receipt
            observed_id, observed_incarnation, generation = _metadata(candidate)
            expected_generation = 0 if mode == "create" else _metadata(self.payload)[2] + 1
            if (observed_id != database_id or observed_incarnation != incarnation
                    or generation != expected_generation or not isinstance(receipt.get("code"), str)):
                raise StoreError("worker_protocol")
            if receipt["code"] in ("ok", "ready", "created"):
                if (receipt.get("instance") != incarnation or type(receipt.get("generation")) is not int
                        or receipt["generation"] != generation or receipt.get("database_id") != database_id):
                    raise StoreError("worker_protocol")
            elif (receipt["code"] not in ("denied", "invalid", "conflict", "limit", "capacity", "not_found")
                  or receipt.get("instance") != "" or type(receipt.get("generation")) is not int
                  or receipt["generation"] != 0 or "database_id" in receipt):
                raise StoreError("worker_protocol")
            if mode in ("create", "recover"):
                expected_code = "created" if mode == "create" else "ready"
                if receipt.get("code") != expected_code or receipt.get("database_id") != database_id:
                    raise StoreError("worker_protocol")
            return candidate, receipt
        except (StoreError, ValueError, TypeError, KeyError, UnicodeError) as error:
            self.poisoned = True
            if isinstance(error, StoreError):
                raise
            raise StoreError("worker_protocol") from error

    def initialize(self, scope: str) -> dict:
        if not self.new or self.payload:
            raise StoreError("invalid_state")
        database_id, incarnation = secrets.token_hex(16), secrets.token_hex(16)
        candidate, receipt = self._stage("create", database_id, incarnation, scope)
        self.commit(candidate)
        parent = -1
        try:
            parent = os.open(os.path.dirname(self.path), os.O_RDONLY | os.O_DIRECTORY |
                             os.O_NOFOLLOW | os.O_CLOEXEC)
            self.io.sync(parent)
        except OSError as error:
            self.poisoned = True
            raise StoreError("storage_error") from error
        finally:
            if parent >= 0:
                os.close(parent)
        self.new = False
        return receipt

    def recover(self) -> dict:
        if self.new or self.payload:
            raise StoreError("invalid_state")
        self.payload = self.load()
        database_id, old_incarnation, _generation = _metadata(self.payload)
        incarnation = secrets.token_hex(16)
        while incarnation == old_incarnation:
            incarnation = secrets.token_hex(16)
        candidate, receipt = self._stage("recover", database_id, incarnation)
        self.commit(candidate)
        return receipt

    def apply(self, request: dict) -> dict:
        if not self.payload:
            raise StoreError("invalid_state")
        database_id, incarnation, _generation = _metadata(self.payload)
        candidate, receipt = self._stage("apply", database_id, incarnation, request=request)
        if candidate != self.payload:
            self.commit(candidate)
        return receipt


def _worker_command(target: str) -> list[str]:
    binary = ROOT / "build" / "storage" / "enigma-storage-worker"
    if target == "native":
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise StoreError("worker_missing")
        return [str(binary)]
    configured = os.environ.get("NIL_SDK")
    if configured:
        sdk = Path(configured)
    else:
        candidates = [ROOT / ".sdk", ROOT.parent / "exec-nil-framework" / "sdk"]
        sdk = next((item for item in candidates if (item / "nilinterpreter").is_file()), None)
        if sdk is None:
            executable = shutil.which("nilinterpreter")
            if executable is None:
                raise StoreError("sdk_missing")
            sdk = Path(executable).resolve().parent
    interpreter = sdk / "nilinterpreter"
    artifact = binary.with_suffix(".nil")
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise StoreError("sdk_missing")
    if not artifact.is_file():
        raise StoreError("worker_missing")
    return [str(interpreter), str(artifact)]


def _worker_transport(command: list[str], *, _timeout: float = 30) -> Callable[[dict], dict]:
    def invoke(envelope: dict) -> dict:
        environment = os.environ.copy()
        environment["NIL_STRICT_BOUNDS"] = "1"
        process = None
        selector = selectors.DefaultSelector()
        try:
            incoming = _json_bytes(envelope) + b"\n"
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=environment, start_new_session=True)
            for stream, event, name in ((process.stdin, selectors.EVENT_WRITE, "input"),
                                        (process.stdout, selectors.EVENT_READ, "output"),
                                        (process.stderr, selectors.EVENT_READ, "error")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event, name)
            output = bytearray()
            written = 0
            deadline = time.monotonic() + _timeout
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StoreError("worker_failed")
                for key, _events in selector.select(min(remaining, 1)):
                    stream = key.fileobj
                    if key.data == "input":
                        count = os.write(stream.fileno(), incoming[written:written + 65536])
                        if count <= 0:
                            raise StoreError("worker_failed")
                        written += count
                        if written == len(incoming):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                        elif key.data == "error":
                            raise StoreError("worker_failed")
                        else:
                            if len(output) + len(chunk) > MAX_WORKER_OUTPUT:
                                raise StoreError("worker_failed")
                            output.extend(chunk)
            if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                raise StoreError("worker_failed")
        except (OSError, subprocess.TimeoutExpired) as error:
            raise StoreError("worker_failed") from error
        finally:
            selector.close()
            if process is not None:
                # A parent can exit while its descendants retain our pipes.
                # The entire fresh session belongs to this one invocation;
                # clean it up even when the direct child has already exited.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
        if not output.endswith(b"\n") or output.count(b"\n") != 1:
            raise StoreError("worker_failed")
        reply = strict_json(bytes(output))
        if not isinstance(reply, dict):
            raise StoreError("worker_protocol")
        return reply
    return invoke


def _emit(stream: TextIO, receipt: dict) -> None:
    stream.write(_json_bytes(receipt).decode("utf-8") + "\n")
    stream.flush()


def main(argv: list[str] | None = None, *, input_stream: BinaryIO | None = None,
         output_stream: TextIO | None = None, error_stream: TextIO | None = None,
         _worker: Callable[[dict], dict] | None = None, _io: PosixIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="POSIX host for Enigma durable checkpoints")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("path")
    initialize.add_argument("--scope", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("path")
    for subparser in (initialize, serve):
        subparser.add_argument("--target", choices=("vm", "native"), default="vm")
    arguments = parser.parse_args(argv)
    incoming = input_stream or sys.stdin.buffer
    outgoing = output_stream or sys.stdout
    errors = error_stream or sys.stderr
    try:
        worker = _worker or _worker_transport(_worker_command(arguments.target))
        with Store(arguments.path, worker, create=arguments.mode == "init", io=_io) as store:
            if arguments.mode == "init":
                _emit(outgoing, store.initialize(arguments.scope))
                return 0
            _emit(outgoing, store.recover())
            while True:
                line = incoming.readline(MAX_REQUEST + 1)
                if not line:
                    return 0
                if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                    raise StoreError("invalid_request")
                try:
                    request = strict_json(line)
                    if not isinstance(request, dict):
                        raise StoreError("invalid_json")
                except StoreError:
                    _emit(outgoing, {"code": "invalid"})
                    continue
                _emit(outgoing, store.apply(request))
    except (StoreError, OSError, BrokenPipeError) as error:
        code = str(error) if isinstance(error, StoreError) else "storage_error"
        errors.write("enigma store: " + code + "\n")
        errors.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
