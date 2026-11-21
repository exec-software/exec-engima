# Development

Enigma's engine, checkpoint codec, and state validation are Matrix. Bash supplies
toolchain glue; Python 3 supplies the POSIX filesystem host and fault/restart
verification. No other database implements Enigma's persistence.

## Get the SDK

Use the public [NIL Framework setup instructions](https://github.com/exec-software/exec-nil-framework/blob/master/docs/getting-started/index.md).
The upstream Linux prerequisites include a C++17 compiler, CMake 3.21 or newer,
Python 3.12 or newer, LLVM development packages, and Pandoc. Follow upstream for
the current dependency details and other platforms.

Durable application sessions require NIL's runtime lock-ownership query from
[`dbb4379`](https://github.com/exec-software/exec-nil-framework/commit/dbb4379946f6800a79e485dcd890e8f5b0902b31).
That revision also includes discovery's optional-text field fix from
`ebc4eb5`. These changes are proposed in
[NIL PR #42](https://github.com/exec-software/exec-nil-framework/pull/42).
Earlier compilers can run the pattern on the VM but reject its optional text
fields during native compilation. The version string alone does not identify
this fix; select a matching complete development SDK.

For example, build the pinned public source beside this project:

```sh
git clone https://github.com/exec-software/exec-nil-framework.git ../exec-nil-framework
cd ../exec-nil-framework
git checkout dbb4379946f6800a79e485dcd890e8f5b0902b31
CMAKE_BUILD_PARALLEL_LEVEL=4 CTEST_PARALLEL_LEVEL=4 ./scripts/build-sdk.sh
```

The framework's build runs its tests and writes `sdk/`. It expects a clean
checkout. Enigma does not download dependencies or build the framework implicitly.

SDK discovery in `scripts/nil.sh` uses this order:

1. Explicit `NIL_SDK`, which must name a complete SDK directory.
2. The ignored project-local `.sdk` directory or symlink.
3. The sibling `../exec-nil-framework/sdk`.
4. The directory containing `nilbuild` found on `PATH`.

Tools reside directly in the SDK directory. If a PATH entry is a launcher or a
symlink outside that directory, set `NIL_SDK` explicitly.

The original seed used an SDK reporting `1.0.0-rc.1` from a dirty tree; that
version string was not a reproducible dependency pin. Current development uses
the clean source revision above. See [the validation record](validation.md) for
commands, results, and qualification limits. Release-SDK qualification and hosted
CI remain follow-up work; no prebuilt release is assumed.

## Daily commands

From the Enigma project directory:

```sh
./scripts/nil.sh describe
./scripts/nil.sh check
./scripts/nil.sh build --target all
./scripts/nil.sh run --target native -- --version
./scripts/nil.sh run -- --demo
./scripts/nil.sh run -- --surface
./scripts/build-storage.sh --target all
./scripts/test.sh
./scripts/test-durable-client.sh
./scripts/test-capacity.sh
```

The wrapper resolves the project independently of the invocation directory and
sets `NIL_STRICT_BOUNDS=1`, including for tests. This is required because unchecked
array access would undermine storage correctness as the engine develops. The
environment setting is a runtime check, not a database security boundary.

`scripts/test.sh` checks the engine, companion, and storage-worker projects,
runs Matrix tests, builds the requested execution targets, checks the CLI and
package examples, and exercises Python filesystem faults and process recovery.
Its default is both VM and native; `--target vm` or `--target native` selects one.

`scripts/test-durable-client.sh` checks the importable durable package and its
application example, then uses an external filesystem/process oracle to verify
close, stale-owner refusal, factory cleanup, poisoned-session behavior, path
pinning, and every typed operation on VM/native. It builds its own application
fixtures and requires the lock-ownership API in the pinned SDK.

`scripts/test-capacity.sh` exercises larger synthetic checkpoints, work versus
reply limits, maintenance capacity, and confirmed byte-capacity refusals through
the persistence hosts. It keeps the existing worker and process timeouts.

## Application record checks

Run `./scripts/test-records.sh` with the same complete development SDK. The
runner checks strict UTF-8 bodies, independent byte and count permissions,
version preconditions, complete enumeration, and the manifest codec. An
external process checks raw files and digests, restart retirement, and the
effects of failures before and during manifest publication. Select
`--target vm` or `--target native` to check one route.

## Durable host

The installed SDK's atomic file publication lacks a parent-directory sync
barrier and file locking; its ordinary stream flush is not an `fsync`. The
POSIX-only `scripts/store.py` supplies those operations without changing the NIL
framework. Python 3 is required for this path. It invokes the separately built
Matrix worker and does not build it implicitly.

```sh
./scripts/build-storage.sh --target vm
mkdir -p data
python3 scripts/store.py init data/example --scope work
python3 scripts/store.py serve data/example
```

Add `--target native` to use the native worker after building that target. Keep
the parent directory available and trusted; `init` exclusively creates the
private database directory and will not replace an existing one. `serve` opens
only an existing store and holds its nonblocking writer lock for the session.
It rotates the incarnation and durably retires every previous session grant
before `ready`; re-admission and new grants are explicit host operations.

See [the persistence guide](persistence.md) for line-delimited JSON requests,
receipt semantics, and recovery behavior. Do not infer a durable acknowledgement
from a direct Matrix worker response or an `enigma.client` call. Only the host's
receipt follows file and directory synchronization.

Focused host fault tests can run without a built Matrix worker:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_durable_host.py
```

Those tests inject a private worker/syscall fixture. They establish host
ordering and failure handling, not Matrix policy semantics or hardware power-cut
qualification. Full verification also uses real VM/native worker processes.

Build products stay in the ignored `build/` directory. Keep local databases,
backups, keys, and credentials out of Git; use synthetic fixtures in tests.

## Source conventions

General library gaps found while building Enigma should feed back into NIL.
The first contributions add POSIX durable byte publication, directory sync, and
context-owned advisory file locks (NIL-0028), then owner-only directory
creation, private-entry metadata verdicts, and `sha256_hex` (NIL-0029), each
with paired Ny/Matrix VM, AOT, and JIT checks. The
[consumer contract](../validation/nil-io/README.md) exercises those primitives
against a real Enigma revoked-grant payload using a matching development SDK:

```sh
NIL_SDK=/absolute/path/to/matching/development-sdk ./scripts/test-nil-io.sh
```

The existing host remains the qualified persistence path. A Matrix host now
exists under [`host/`](../host/README.md) and satisfies the same black-box
session contract on the VM and native routes, with either host able to serve a
database the other created:

```sh
NIL_SDK=/absolute/path/to/matching/development-sdk ./scripts/test-matrix-host.sh
```

That runner also injects storage faults from the filesystem and the process
environment, against both hosts: a commit that cannot be published is never
acknowledged, an unsafe or multiply-linked checkpoint is refused, a rewritten
payload fails its digest, and an oversized request ends a session rather than
being truncated into a different one.

`scripts/store.py` stays the default path while the Matrix host's NIL-0028
through NIL-0030 and native `random.hex` dependencies await release-SDK
qualification. Native discovery also needs the newer compiler pinned above;
current validation uses a matching complete development SDK. Host cutover stays
separate from this query change. Short
writes, a crash at a chosen commit phase, forged worker replies, and the
host's response to an uncertain publication still need a seam inside a host
and are not claimed. See [ENI-0003](design/ENI-0003-matrix-durable-host.md). Preserve
database policy in Enigma; only general mechanisms belong in the framework
standard library.

Use `book enigma.<area>` with files under `src/enigma/` and `.matrix` extensions.
Prefer explicit imports and named call arguments. Put `begin test` declarations
beside the code they exercise; `niltest` discovers tests through the entrypoint's
import graph. Run the test script with the SDK used to build the executable.
