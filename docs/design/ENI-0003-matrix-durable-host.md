# ENI-0003: The Matrix durable host

Status: design record for retiring the Python host. Nothing ported yet.

## What this decides

ENI-0002 split the persistence slice between a Matrix worker and a narrow
Python POSIX host because the installed NIL runtime lacked parent-directory
synchronization and file locking. The framework's NIL-0028 added
`write_bytes_durable`, `sync_directory`, `acquire_file_lock`, and
`release_file_lock`, so that specific justification no longer holds. This
record decides the shape of the Matrix host, what must exist before it is
written, and how the port is qualified in stages. It does not port anything.

## The split was a language boundary

`scripts/store.py` spawns a fresh one-shot Matrix worker per dispatch: the
worker reads one line, writes one candidate, and exits. The host owns the
private directory, the session lock, envelope integrity, commit ordering, and
receipts.

That boundary exists because the host was Python and the engine was Matrix. It
is not an isolation boundary. ENI-0002 calls it an embedded trusted-host
interface, and Enigma's model trusts its host: public Matrix fields are not an
isolation boundary, and caller text never creates authority. A single Matrix
program is therefore the target, not two Matrix processes exchanging JSON.

One property of the current topology is load-bearing and must not be lost
silently. A fresh process per dispatch makes it **structurally impossible** for
an authority object to survive a commit. ENI-0002 relies on this: "There are no
live clients retaining an earlier authority object across commits." Collapsing
to one process converts that structural guarantee into a code invariant, which
is a real weakening of enforcement even under a trusted host.

The collapse is accepted on condition that the invariant becomes explicit and
tested rather than assumed:

1. Each dispatch re-derives engine and permission state from the committed
   payload. No authority, grant, session, or clock value is carried across a
   commit boundary in memory.
2. Handles are discarded on replacement, as the engine already requires.
3. The checks `store.py` performs on a worker candidate remain, as
   pre-publication invariants: identity, incarnation, and generation match the
   expected successor; receipt shape matches its code; a denial neither mutates
   the payload nor reports an instance or generation.
4. A test asserts that a second dispatch cannot observe authority retired by
   the first, exercising the path that the fresh process used to guarantee.

Item 3 is not redundant internal assertion. It is the only remaining check that
a staged candidate is a legitimate successor to committed state, and it must run
before publication, not after.

## Required library surfaces

Three mechanisms remain outside Matrix. Each already exists and is exercised
inside the framework; none needs new algorithm work. Each needs a supported
surface in the NIL standard library, with VM and native providers and paired
Ny/Matrix route evidence, following NIL-0028's pattern:

| Need | Existing mechanism | Status |
| --- | --- | --- |
| Private directory creation | `nil::detail::create_private_directory` (0700, or a protected Windows owner DACL) | Internal helper; no language surface |
| Owner and mode inspection | the regular/owner/single-link/`0600` predicate in `secure_file_io.cpp` | Internal helper; no language surface |
| Standalone SHA-256 | `portable_sha256` in `common/content_digest.hpp` | Host-side only, used for module fingerprints |

`nilstd/experimental/security/hash.ny` appears to offer `sha256` already. It
does not: it is declared through `@interop` against `nilstd/native/`, which is
not referenced by the framework build at all, and it uses superseded `vec<u8>`
types. It is unbuilt legacy and must not be mistaken for a usable surface.

Exposing a digest requires care about what is claimed. A checkpoint digest
detects accidental corruption. It is not a signature, authentication, rollback
protection, or encryption, and the surface must say so where callers read it.

NILData needs no work here. Its JSON decoder already rejects duplicate members,
caps nesting at 32 levels, and has no `NaN` or `Infinity` grammar, so it is
strict in the three ways `store.py`'s `strict_json` is strict. Python's `json`
accepts nonfinite constants by default, which is why the placeholder needed an
explicit rejection hook and the Matrix decoder does not.

## Checkpoint compatibility is the migration lever

The Matrix host must produce byte-identical envelopes: exactly the members
`format`, `payload`, and `sha256`, with the digest taken over the payload's
UTF-8 bytes and rendered as lowercase hex. Identical bytes make the two hosts
interchangeable against the same database directory, so the existing durability
and recovery tests can run against either implementation and a half-ported tree
stays testable. Divergence here forces a cutover with no cross-check, which is
the outcome this record exists to avoid.

## Phases

Each phase is independently qualified and leaves a working tree.

- **A — surfaces.** Land the three library surfaces above with paired Ny/Matrix
  route evidence. Extend `validation/nil-io` to exercise each. No Enigma
  behavior changes.
- **B — envelope.** Implement envelope construction, digest verification, and
  strict decode in Matrix. Prove byte-identical output against `store.py` for
  the same payloads, including the corruption and malformed-envelope cases.
- **C — session.** Implement private-directory setup, the session lock,
  metadata preflight, and the five-step commit ordering in Matrix. Run the
  existing durability and recovery suites against the Matrix host.
- **D — cutover.** Move the CLI to the Matrix host. `scripts/store.py` stops
  being a host and remains only as a test oracle, then is removed once Matrix
  route evidence covers its cases.

Phase C is where acknowledgement ordering can regress silently, so it does not
begin until B is byte-identical.

## Verification keeps a host oracle

A Matrix program cannot be the only witness to its own filesystem effects.
Checking that bytes reached disk, that modes are `0600`, that a lock is released,
or that an interrupted commit left a complete file requires an observer outside
the program under test. `validation/nil-io` already works this way, with an
independent host oracle over a real Matrix payload.

So the Python *host* is a placeholder to retire, and the Python *tests* are an
oracle to keep. The 28 durability and recovery tests are the specification of
this slice's behavior; they are the instrument that makes the port checkable and
should outlive `store.py`. Replacing them with Matrix self-checks would reduce
evidence while appearing to complete the migration. Eventually some become
Matrix route tests, but an independent oracle for filesystem facts and real
process death stays.

## Limits

This record covers host language, not durability guarantees. Everything ENI-0002
excludes stays excluded: no hardware power-cut qualification, no general
anti-rollback, no detection of an externally restored coherent checkpoint, no
key management or encryption, no durable replay or idempotency ledger, no
backups or migrations. The 256-grant ceiling and absent compaction are unchanged
and still fail closed on exhaustion.

NIL-0028 is a Linux-tested POSIX source-runtime profile, not an installed or
release SDK. It is committed on the framework's `codex/enigma-durable-io`
branch, which is not yet pushed. Until it is released, a Matrix host builds only
against a matching development SDK, and the port cannot be the only supported
path. Non-Linux POSIX platforms need their own execution evidence; Windows
returns an explicit unsupported-platform error before filesystem mutation.

Single-writer behavior is unchanged. Concurrency, indexes, and transport
encoding remain open and must not be inferred from this consolidation.
