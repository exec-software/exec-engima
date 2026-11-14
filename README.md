# Enigma

Enigma is an experimental database engine for humans and AI agents, written
in **Matrix** on the [NIL Framework](https://github.com/exec-software/exec-nil-framework).
Its intended query language takes Matrix's readable, explicit syntax as its
starting point. Data security is a core design requirement.

The repository is named `exec-engima`; the engine and executable are **Enigma**
and `enigma`.

## Current state

**0.1.0-dev has a working, bounded in-memory evidence engine.** A proposition is
`(subject, relation, object_value)`. Supporting and opposing reports coexist,
with source attribution and the acting entity/session. Withdrawing evidence
appends an event; earlier snapshots keep their original meaning.

- Resolve a proposition as `unknown`, `supported`, `contradicted`, or `contested`.
  These describe evidence, not objective truth or probability.
- Receive evidence IDs, counts, revision, and separate scan/output completeness.
  A budget-exhausted scan reports `incomplete`.
- Use scoped, session-bound grants with operation, expiry, and work/output
  limits; delegation can only narrow authority and ancestor revocation stays live.
- Interact through a typed Matrix companion library in
  [`ext/enigma-client`](ext/enigma-client/README.md), outside `nil.std`.

This first slice tests a useful direction rather than committing to SQL or
document-store architecture. [ENI-0001](docs/design/ENI-0001-evidence-and-authority.md)
defines the semantics and limits.

Authority follows Anomalous's model, currently implemented as a trusted-host
policy fixture. Matrix fields are public: this is **not isolation against hostile
code in the same process**. Context identity and fresh logical ticks come from
the embedding host. There is no authentication, network listener, query parser,
encryption, persistence, durable revocation, or crash-recovery guarantee.

## Build and run

Install or build a complete NIL SDK using the
[development guide](docs/development.md). From this checkout:

```sh
export NIL_SDK=/absolute/path/to/exec-nil-framework/sdk
./scripts/nil.sh check
./scripts/nil.sh build --target all
./scripts/nil.sh run -- --help
./scripts/nil.sh run -- --version
./scripts/nil.sh run -- --surface
./scripts/nil.sh run -- --demo
./scripts/test.sh
```

`build --target all` builds VM and native outputs. Native compilation needs an
LLVM-enabled SDK and a host C++ linker. Use `--target vm` for VM-only development,
including `./scripts/test.sh --target vm`.

If this project sits beside `exec-nil-framework`, its `sdk/` is discovered
automatically. The wrapper always enables runtime bounds checks. Directly
running generated binaries requires `NIL_STRICT_BOUNDS=1` as well.

The synthetic demo exercises competing evidence, history, bounded work, and live
revocation:

```text
Enigma evidence demo (synthetic, in memory)
initial: supported
after opposition: contested
after withdrawal: supported
historical revision 2: contested
budget 1: incomplete
after revocation: denied
```

`--surface` emits a NILData description of the companion operations and hard
limits. The client accepts typed requests; it does not need to generate query
strings. Stores currently hold at most 128 events, and all data disappears at
process exit.

## Project map

| Path | Purpose |
| --- | --- |
| `nil.project.nildata` | NIL project settings; analyzer warnings fail checking. |
| `src/main.matrix` | Executable entrypoint. |
| `src/enigma/ledger.matrix` | Append-only evidence, temporal reads, bounded resolution. |
| `src/enigma/authority.matrix` | Host grant lifecycle and authorization. |
| `ext/enigma-client/` | Companion Matrix library, tests, and standalone example. |
| `scripts/` | SDK selection, strict-bounds execution, and validation. |
| [Design](docs/design/README.md) | Architecture, query direction, and first milestones. |
| [Security](SECURITY.md) | Current limits, reporting, and intended threat boundaries. |
| [Contributing](CONTRIBUTING.md) | Development expectations. |

## License

MIT. See [LICENSE](LICENSE).
