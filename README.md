# Enigma

Enigma is the seed of a new database engine for humans and AI agents, written
in **Matrix** on the [NIL Framework](https://github.com/exec-software/exec-nil-framework).
Its intended query language takes Matrix's readable, explicit syntax as its
starting point. Data security is a core design requirement.

The repository is named `exec-engima`; the engine and executable are **Enigma**
and `enigma`.

## Current state

**0.1.0-dev is a project bootstrap.** It builds a Matrix executable, reports its
version, displays help, rejects unsupported arguments, and includes Matrix
tests. There is no query parser, storage engine, network listener, authentication,
authorization, encryption, transaction system, or durability guarantee yet.

The design direction is:

- One explicit, inspectable query model for people and software agents.
- Typed parameters and structured results rather than generated query strings.
- Scoped identities, least privilege, and attributable access to data.
- Documented isolation, recovery, and resource limits backed by tests.

These are goals. The design notes identify work that remains open.

## Build and run

Install or build a complete NIL SDK using the
[development guide](docs/development.md). From this checkout:

```sh
export NIL_SDK=/absolute/path/to/exec-nil-framework/sdk
./scripts/nil.sh check
./scripts/nil.sh build --target all
./scripts/nil.sh run -- --help
./scripts/nil.sh run -- --version
./scripts/test.sh
```

`build --target all` builds VM and native outputs. Native compilation needs an
LLVM-enabled SDK and a host C++ linker. Use `--target vm` for VM-only development,
including `./scripts/test.sh --target vm`.

If this project sits beside `exec-nil-framework`, its `sdk/` is discovered
automatically. The wrapper always enables runtime bounds checks. Directly
running generated binaries requires `NIL_STRICT_BOUNDS=1` as well.

## Project map

| Path | Purpose |
| --- | --- |
| `nil.project.nildata` | NIL project settings; analyzer warnings fail checking. |
| `src/main.matrix` | Executable entrypoint. |
| `src/enigma/core.matrix` | Bootstrap identity, argument contract, and tests. |
| `scripts/` | SDK selection, strict-bounds execution, and validation. |
| [Design](docs/design/README.md) | Architecture, query direction, and first milestones. |
| [Security](SECURITY.md) | Current limits, reporting, and intended threat boundaries. |
| [Contributing](CONTRIBUTING.md) | Development expectations. |

## License

MIT. See [LICENSE](LICENSE).
