# Development

Enigma's implementation and unit tests are Matrix. Bash scripts provide
toolchain and validation glue. No other database is used to implement this seed.

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
./scripts/test.sh
```

The wrapper resolves the project independently of the invocation directory and
sets `NIL_STRICT_BOUNDS=1`, including for tests. This is required because unchecked
array access would undermine storage correctness as the engine develops. The
environment setting is a runtime check, not a database security boundary.

`scripts/test.sh` checks the project, runs colocated Matrix tests, builds the
requested execution targets, and checks the CLI contract against `VERSION`.
Its default is both VM and native; `--target vm` or `--target native` selects one.

Build products stay in the ignored `build/` directory. Keep local databases,
backups, keys, and credentials out of Git; use synthetic fixtures in tests.

## Source conventions

Use `book enigma.<area>` with files under `src/enigma/` and `.matrix` extensions.
Prefer explicit imports and named call arguments. Put `begin test` declarations
beside the code they exercise; `niltest` discovers tests through the entrypoint's
import graph. Run the test script with the SDK used to build the executable.
