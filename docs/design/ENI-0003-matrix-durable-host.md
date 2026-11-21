# ENI-0003: The Matrix durable host

Status: design record for retiring the Python host. Phases A, B and C are
implemented, and phase D's evidence gap is closed: a Matrix host satisfies the
session contract and the storage-fault contract on both routes, and so does
`scripts/store.py`. The cutover itself waits on a released SDK, not on
evidence.

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

Discovery adds one internal framing refinement in
[ENI-0006](ENI-0006-bounded-evidence-discovery.md). A full checkpoint and result
can exceed NILData's 1 MiB limit when combined in one value. Staging therefore
returns typed reply parts to the Matrix host, which keeps the same candidate
checks. The request envelope remains serialized and strictly decoded. The
Python worker receives the same bounded JSON packet, assembled from separately
NILData-encoded parts; its existing 2 MiB transport limit is unchanged.

## Required library surfaces

Three mechanisms were outside Matrix. Each already existed and was exercised
inside the framework, so none needed new algorithm work, only a supported
surface with VM and native providers and paired Ny/Matrix route evidence. The
framework's NIL-0029 adds them as four functions in `nil.std.io`, since
inspection splits by entry kind:

| Need | Surface | Status |
| --- | --- | --- |
| Private directory creation | `create_private_directory` | Qualified in NIL-0029 |
| Owner and mode inspection | `is_private_regular_file`, `is_private_directory` | Qualified in NIL-0029 |
| Standalone SHA-256 | `sha256_hex` | Qualified in NIL-0029 |

The predicates return `Result<bool, text>` so recovery can tell an uninspectable
entry from one inspected and judged unsafe. That distinction matters here: ENI-0002
requires missing or invalid primary state to fail closed rather than bootstrap, and
a surface that reported absence as "not private" would erase the difference.

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

Byte-identity holds, and it holds for two specific reasons rather than by
luck. Both are now checked instead of assumed, because each is a trap for
anyone extending the envelope:

1. **Member order.** NILData sorts object members; Python preserves insertion
   order. `format`, `payload` and `sha256` are already alphabetical, so the two
   coincide. A member added out of alphabetical order would diverge silently,
   so `test_members_are_alphabetical_so_both_orderings_agree` asserts the
   property, not the current spelling.
2. **Control-character escaping.** NILData spells a control character
   `\u000a` where Python writes `\n`. These never describe the same checkpoint
   because a payload is itself JSON output, and JSON escapes every control
   character on the way in. The Python suite asserts this for every control
   byte; the Matrix suite checks the newline case through its own encoder.

Note what the codec does **not** do: it takes the digest as a parameter rather
than hashing. That keeps `enigma.persistence` buildable against the previously
selected SDK, which has no `sha256_hex` and no native `text.byte_at` provider,
so the existing suite keeps running on both routes. A Matrix host that verifies
a checkpoint end to end therefore still needs NIL-0029, which is development-SDK
only. "Digest verification" here means comparison, not computation.

## Phases

Each phase is independently qualified and leaves a working tree.

- **A — surfaces.** *Done.* The surfaces above landed with paired Ny/Matrix
  evidence across textual and binary VM, AOT, and JIT. `validation/nil-io`
  exercises each one and now also computes the digest a checkpoint envelope
  would carry, with the host oracle recomputing it through Python's `hashlib`.
  So the digest half of byte-identical envelopes is already checked rather than
  assumed; phase B still has to match the envelope's JSON members and bytes.
  No Enigma behavior changed.
- **B — envelope.** *Done.* `enigma.persistence` gained `build_envelope`,
  `read_envelope` and `confirm_envelope`, with the `enigma.storage.envelope`
  suite covering round-trip, a changed payload, non-hex and uppercase digests,
  a missing, extra, duplicated or mistyped member, a wrong format identifier,
  and a decode failure never becoming a confirmation. Byte-identity is pinned
  from both sides on golden vectors, and `validation/nil-io` compares a Matrix
  envelope built over real revoked-grant state against the bytes `store.py`
  would write for the same payload.
- **C — session.** *Done.* `host/` builds `enigma-durable-host` with the same
  command surface as `scripts/store.py`. The seven checks in
  `test_storage_recovery.py` drive a host over its CLI, so they were
  parameterized and now run against the Matrix host on the interpreter and
  native routes, against the Python host, and in both interoperability
  directions, through `scripts/test-matrix-host.sh`.

  Three surfaces turned out to be needed beyond phase A's three, each found by
  trying to write the host rather than by reading `store.py`:
  `read_line_option` (NIL-0030), because `read_line` faulted at end of input so
  a served session could not shut down cleanly; a native provider for
  `random.hex`, because incarnation identifiers are drawn per recovery and the
  host could not be built natively without it; and nothing at all for the
  metadata preflight, because `read_regular_bytes` already opens once without
  following its final component and rejects input observed changing under it,
  which is what `store.py` assembled from `fstat` comparisons.

  The five-step commit ordering is one call: `write_bytes_durable` performs the
  private staging file, its synchronization, atomic replacement, and
  synchronization of the same publication directory. Initial creation still
  synchronizes the parent separately, because publishing a file inside a new
  directory does not make that directory's own name durable.
- **D — cutover.** *Evidence landed; the move is blocked.* The fault-injection
  gap is closed by `tests/test_host_faults.py`, which injects from the
  filesystem and the process environment rather than through a seam inside the
  host. Adding a seam was rejected: a production host with a fault switch is no
  longer the thing under test, which is the rule NIL-0028's own helpers state.
  Every check runs against both hosts, because a scenario only one of them
  satisfies describes that host rather than the contract. Writing them found a
  real gap — the Matrix host accepted a checkpoint with a loose mode or a
  second hard link, which `store.py` rejects — and the host now performs that
  preflight explicitly.

  The Matrix host's NIL-0028 through NIL-0030 and native `random.hex` dependencies
  still need release-SDK qualification. `scripts/store.py` stays the default
  while that cutover remains separate. Discovery subsequently requires a newer
  compiler for optional-text fields too; its minimum source revision is explicit
  in the development guide. An unchanged SDK version string proves neither
  compiler nor filesystem support.

  Four scenarios remain out of reach without a seam, and are not claimed: a
  partial write followed by success, a crash at a chosen commit phase, a
  worker reply that violates its protocol, and the host's handling of
  NIL-0028's uncertain publication. `RLIMIT_FSIZE` makes a write fail outright
  rather than truncate; the `SIGKILL` check kills at an arbitrary point rather
  than a chosen one; `stage_request` is the real engine, so no reply can be
  forged past it; and the framework tests the uncertain outcome of the
  primitive, not this host's response to it.

Phase C is where acknowledgement ordering can regress silently, so it did not
begin until B was byte-identical. It now can.

## Verification keeps a host oracle

A Matrix program cannot be the only witness to its own filesystem effects.
Checking that bytes reached disk, that modes are `0600`, that a lock is released,
or that an interrupted commit left a complete file requires an observer outside
the program under test. `validation/nil-io` already works this way, with an
independent host oracle over a real Matrix payload.

So the Python *host* is a placeholder to retire, and the Python *tests* are an
oracle to keep. Replacing them with Matrix self-checks would reduce evidence
while appearing to complete the migration.

That distinction is now a concrete division rather than an intention. Of the
1,675 lines of Python in the repository:

| Concern | Where it lives | Why |
| --- | --- | --- |
| Envelope build, digest confirmation, strict decode | `enigma.storage.envelope`, 7 Matrix checks | Pure codec logic with no host to witness |
| Candidate validation, payload identity | `enigma.host.candidate`, 10 Matrix checks | Moved into the host, so tested beside it |
| Real restarts, `SIGKILL`, lock contention | `tests/test_storage_recovery.py`, 7 checks | A process cannot witness its own death |
| Storage faults | `tests/test_host_faults.py`, 6 checks | Injected from outside, so no host needs a seam |
| Byte-identical envelopes | `tests/test_envelope_parity.py`, 6 checks | The second witness has to be the other encoder |
| `store.py`'s own internals | `tests/test_durable_host.py`, 21 checks | Retires with `store.py` |

The two Matrix suites are not a translation of Python checks; they cover logic
that moved. `a_receipt_naming_another_instance_is_refused` is the case
`test_bad_worker_binding_is_not_published` made by corrupting a worker reply
from outside, and it now sits beside the check it exercises.

Two of `store.py`'s checks have no successor and need none.
`test_worker_output_is_bounded_and_exactly_one_json_line` and
`test_exited_worker_parent_does_not_leave_a_pipe_holding_descendant` are about
a subprocess transport. The Matrix host has no subprocess, so those concerns
disappear rather than moving.

What retires is the Python *engine* path, not the Python *checks*. Removing
`store.py` removes 954 lines, itself and the white-box checks that reach into
it. `test_envelope_parity.py` loses its second encoder and wants retargeting
rather than deleting: the format properties it asserts, members in
alphabetical order and no raw control byte in a payload, still want a witness
that is not the encoder under test.

The roughly 720 lines that remain are the external-oracle layer, and both
hosts are measured against all of it. That is the floor, not a staging post: a
Matrix program cannot witness its own death, and it cannot be the only witness
to whether its bytes reached the disk.

## Limits

This record covers host language, not durability guarantees. Everything ENI-0002
excludes stays excluded: no hardware power-cut qualification, no general
anti-rollback, no detection of an externally restored coherent checkpoint, no
key management or encryption, no durable replay or idempotency ledger, no
backups or migrations. The grant ceiling bounds retained rows rather than
every grant ever issued, per [ENI-0004](ENI-0004-authority-capacity.md). Grants
revoked during a session still occupy rows until recovery; exhaustion fails closed.

NIL-0028 is a Linux-tested POSIX source-runtime profile, not an installed or
release SDK. The framework additions are published on `codex/enigma-durable-io`
in [draft PR #42](https://github.com/exec-software/exec-nil-framework/pull/42),
with [focused consumer validation](../validation.md). Until released, a Matrix host builds only
against a matching development SDK, and the port cannot be the only supported
path. Non-Linux POSIX platforms need their own execution evidence; Windows
returns an explicit unsupported-platform error before filesystem mutation.

Single-writer behavior is unchanged. Concurrency, indexes, and transport
encoding remain open and must not be inferred from this consolidation.

One difference between the hosts is worth recording rather than discovering
later. `store.py` opens the database directory once and performs every later
operation relative to that descriptor, so a swapped directory cannot redirect
it mid-session. NIL's file operations are path-based, with no-follow on the
final component only, and explicitly place parent-directory containment outside
their contract. ENI-0002 already assumes a trusted owner of the storage
directory and its ancestry, so the Matrix host does not break a stated
guarantee, but it is weaker than what the Python host actually does. Closing it
needs a directory-relative surface, which is not in any phase above.
