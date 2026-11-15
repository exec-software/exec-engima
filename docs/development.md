# Development

Enigma's engine, checkpoint codec, and state validation are Matrix. Bash supplies
toolchain glue; Python 3 supplies the POSIX filesystem host and fault/restart
verification. No other database implements Enigma's persistence.

## Get the SDK

Use the public [NIL Framework setup instructions](https://github.com/exec-software/exec-nil-framework/blob/master/docs/getting-started/index.md).
The upstream Linux prerequisites include a C++17 compiler, CMake 3.21 or newer,
Python 3.12 or newer, LLVM development packages, and Pandoc. Follow upstream for
the current dependency details and other platforms.

For example, build a clean public checkout beside this project:

```sh
git clone https://github.com/exec-software/exec-nil-framework.git ../exec-nil-framework
cd ../exec-nil-framework
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

The seed is validated with a local development SDK reporting `1.0.0-rc.1`.
That SDK reports a dirty source tree, so its version string is not a reproducible
upstream dependency pin. Clean upstream SDK qualification, a pinned toolchain,
and hosted CI are follow-up work; no prebuilt release is assumed.

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
```

The wrapper resolves the project independently of the invocation directory and
sets `NIL_STRICT_BOUNDS=1`, including for tests. This is required because unchecked
array access would undermine storage correctness as the engine develops. The
environment setting is a runtime check, not a database security boundary.

`scripts/test.sh` checks the engine, companion, and storage-worker projects,
runs Matrix tests, builds the requested execution targets, checks the CLI and
package examples, and exercises Python filesystem faults and process recovery.
Its default is both VM and native; `--target vm` or `--target native` selects one.

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

The existing host remains the qualified persistence path. The library surfaces
the port depends on are now qualified; the checkpoint envelope, commit
orchestration, and recovery path are not ported, and a complete host port still
needs separate qualification. See
[ENI-0003](design/ENI-0003-matrix-durable-host.md) for the staging. Preserve
database policy in Enigma; only general mechanisms belong in the framework
standard library.

Use `book enigma.<area>` with files under `src/enigma/` and `.matrix` extensions.
Prefer explicit imports and named call arguments. Put `begin test` declarations
beside the code they exercise; `niltest` discovers tests through the entrypoint's
import graph. Run the test script with the SDK used to build the executable.
