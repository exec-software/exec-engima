# Development validation

## Bounded discovery — 2026-11-20

Engine source is
[`0d2d150`](https://github.com/exec-software/exec-enigma/commit/0d2d15097feda7370aaef6bd18526b1086d8a6f4).
The complete development SDK was packaged from clean NIL source
[`ebc4eb5`](https://github.com/exec-software/exec-nil-framework/commit/ebc4eb518156248cee9dbc6585d16ba09eb464f3),
including the optional-text field fix in
[NIL PR #42](https://github.com/exec-software/exec-nil-framework/pull/42).
The SDK manifest reports `worktree_dirty: false`. The workspace selects that
immutable SDK generation through the ignored project-local `.sdk` link.

With that SDK selected, these commands pass on Linux x86_64:

```sh
./scripts/test.sh
./scripts/test-matrix-host.sh
./scripts/test-nil-io.sh
```

- The full suite passes 170 Matrix executions across VM/native, 24 CLI checks,
  and both package examples. Of 46 Python methods, 40 pass and six host-fault
  methods are deliberately deferred to the host-specific runner.
- The host runner passes 26 Matrix host test executions. The same 13 recovery
  and six storage-fault tests pass against the Matrix VM host, Matrix native
  host, and Python host. Both checkpoint interoperability directions pass.
- The independent NIL I/O consumer passes VM/native, including private modes,
  lock release, checkpoint/envelope bytes, and digest checks.

Discovery tests cover exact/any selectors, literal wildcard characters, current
authority and ancestor revocation, historical withdrawals, retention horizons,
and independent scan/output completeness. The real hosts also return all 128
full-width, escape-heavy reports from a validated synthetic checkpoint.

Staging tests check typed/wire parity, escaped-data injection resistance,
unchanged small-frame bytes, frames above NILData's individual 1 MiB document
limit, and the inclusive 2 MiB worker limit including its newline. One extra
byte returns a fixed failure. Host byte-conversion tests preserve empty input,
chunk boundaries, non-NUL bytes, and UTF-8 split across a chunk. The maximum-size
case passes with the original receipt timeouts after chunked conversion.

Ten focused NIL field/enum/ABI route groups pass, including paired Ny/Matrix
record and class fields with `Option<text>` and `Result<text,text>`. The source
SDK build used `NIL_RUN_TESTS=OFF` in development mode; those route checks ran
separately. This is focused consumer evidence, not full NIL-suite, release-SDK,
cross-platform, or hardware power-cut qualification. Earlier compilers can run
the pattern on the VM but lack the field metadata fix needed by native code.
The [development guide](development.md) pins the required source revision.

## Retention and durable host — 2026-11-20

Validated on Linux x86_64 on 2026-11-20. Engine source is
[`3cea3cb`](https://github.com/exec-software/exec-enigma/commit/3cea3cb48c4ee124bfadb8843e6168c25dc3d77d).
The matching NIL development SDK was packaged from clean source
[`451a4ff`](https://github.com/exec-software/exec-nil-framework/commit/451a4ff2328f2ff7552588e7fc74e23bcf81ce42),
proposed in [NIL PR #42](https://github.com/exec-software/exec-nil-framework/pull/42).
Compiler, native runtime, and standard-library sources came from that same
SDK generation; its manifest reports `worktree_dirty: false`.

### Commands and results

With `NIL_SDK` selecting that development SDK:

```sh
./scripts/test.sh
./scripts/test-nil-io.sh
./scripts/test-matrix-host.sh
```

- The full suite passes 138 Matrix test executions across VM/native, 24 CLI
  checks, and both package examples. Python discovers 43 methods, with 37
  passing and six host-fault methods deliberately skipped until a host command
  is selected by the separate runner below.
- The NIL I/O consumer passes on VM/native. An independent Python oracle checks
  checkpoint bytes and envelopes, SHA-256, private modes, and released locks.
- The Matrix host's own logic passes on VM/native. The same ten recovery tests
  and six external storage-fault tests pass against the Matrix VM host, Matrix
  native host, and Python host. Both checkpoint interoperability directions pass.
- The full suite also passes against the previously installed sibling SDK, so
  the Python persistence path does not require the new NIL additions.

The new regressions require explicit compaction right `16`, preserve the
meaning of existing masks, deny delegated authority after ancestor revocation,
and refuse missing recent checkpoint events even when their envelope digest
has been recomputed. Historical reads below a compaction horizon stay
`incomplete` across restart; old session grants stay denied.

In the NIL source checkout, all 14 selected CTest groups pass: durable helper
faults and lock lifecycle, embedded console state, private directories,
static/shared native ABI, durable routes, existing byte/ordinary-I/O routes,
console routes, and paired secure-hex routes. Directory symlinks ending in `/`
and failed embedded streams with zero `errno` have focused regressions.

### Qualification boundary

SDK packaging used `NIL_RUN_TESTS=OFF` in development mode; the selected CTests
above ran separately. This is focused source-runtime and consumer evidence,
not full NIL-suite, release-SDK, cross-platform, or hardware power-cut
qualification. The installed SDK remains unchanged. `scripts/store.py` remains
the default persistence host while the Matrix host needs the unreleased NIL
surfaces. The limits in [ENI-0002](design/ENI-0002-durable-state-and-recovery.md)
and [ENI-0003](design/ENI-0003-matrix-durable-host.md) still apply.
