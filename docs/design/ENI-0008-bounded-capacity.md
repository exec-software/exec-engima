# ENI-0008: Bounded checkpoint capacity

Status: implementation contract for the larger bounded checkpoint.

## Separate storage, investigation, and reply limits

The first application integration retained at most 128 events and used the same
number for read work and returned evidence. That made a small reply a small
database. An application needs to investigate more evidence without receiving
an unbounded response or silently acquiring a larger permission budget.

Raise retained storage to 1,024 events and maximum read work to 1,024. Keep
returned evidence lists and discovery batches at 128 items. These are separate
limits in the typed surface: `max_events`, `max_assertion_events`, `max_work`,
and `max_evidence`. Grants still bound both requested budgets independently;
a previously installed work limit of 128 does not become 1,024.

A full scan can report complete counts and a complete resolution while its
returned evidence list is truncated. `evidence_complete` remains false in that
case. A scan limited to 128 events in a larger store remains explicitly
incomplete. This change has no continuation cursor, so a truncated discovery
list cannot be used to enumerate every matching report. Narrower exact patterns
can reduce matches; they do not bypass the scan budget.

## Leave room to correct evidence

Assertion admission stops at 1,023 retained events. The last slot is available
for withdrawal, under the same ownership, current authority, expected revision,
and work checks as before. A caller with explicit scope-wide compaction right
can then reclaim the withdrawn pair. Neither withdrawal authority nor reaching
capacity authorizes compaction by itself. Compaction remains explicit because
it gives up historical explanations.

The reserve permits one withdrawal when assertions have filled the store; it
is not an unlimited maintenance queue. A store already holding 1,024 events
must compact eligible pairs before appending another event. Unwithdrawn
assertions remain retained and identifiers are never renumbered.

## Byte admission is also capacity

The whole-state codec remains bounded at 512 KiB. Checkpoint envelopes remain
1 MiB, serialized staging requests 1 MiB, external requests 64 KiB, and worker
frames 2 MiB including the newline. NILData's depth, node, and value limits are
unchanged. Raising all these limits would hide resource costs and would not
solve eventual capacity exhaustion.

Durable admission instead budgets the independently encoded table arrays:

| Table | Admission limit |
| --- | --- |
| Retained events | 384 KiB |
| Events after an assertion | 382 KiB |
| Retained grants | 64 KiB |

The 2 KiB event reserve accommodates one maximum-width withdrawal row. The
separate grant budget leaves room for fresh admission after recovery retires
loaded grants. The remaining payload headroom covers bounded root fields,
security-counter growth, and incarnation replacement.

Every successful growth operation also preflights the actual payload: at most
510 KiB (522,240 bytes), reserving 2 KiB below the codec limit for security
metadata growth. Its JSON-encoded payload string must fit 952 KiB (974,848
bytes), leaving 64 KiB for the request and 8 KiB for staging metadata. Checking
the actual nested representation permits compatible legacy data without
assuming a fixed escape ratio. Large or escape-heavy records can reach byte
capacity before the event or grant row ceiling.

If a proposed mutation exceeds byte admission, staging rebuilds from the last
committed state and discards the proposed evidence/grant change. It retains
the security clock floor observed during authorization and the next generation.
The host commits that state before publishing a confirmed `capacity` receipt.
No evidence revision, event identifier, grant identifier, or revocation effect
from the refused mutation is retained. The session remains usable for reads,
revocation, explicit compaction, and close. A permission-clock rollback remains
denied even when the preceding operation received `capacity`.

Malformed state, an invalid candidate, or actual publication failure retains
its existing fail-closed behavior. A capacity receipt is not proof that a
previous uncertain write was absent and does not create an automatic retry or
idempotency guarantee.

## Compatibility and authority

The payload remains `enigma.state.v3`; its member set and evidence semantics do
not change. The decoder continues to accept valid v3 tables above the new
admission budgets; they are not silently rewritten. Recovery still requires
its successor checkpoint to fit the existing hard bounds. New allocations must
fit the current admission budgets and actual payload preflights. A new
mutation checks the table it grows, so fresh host admission can succeed when
its grant table and actual payload fit even if retained legacy evidence exceeds
the newer event budget. Reading a legacy state does not promise room for every
allocation or security transition near the hard codec limit. An older engine with
the 128-event validator rejects a checkpoint containing more than 128 events;
this is not backward compatibility with old binaries or a migration facility.

Every read still checks current scoped authority before evidence access.
Recovery still retires every prior-session grant, preserves issued counters,
retirement marks and the clock floor, and durably installs a new incarnation
before ready. Larger storage does not re-admit saved sessions, enlarge a grant,
or weaken ancestry revocation. The trusted-host, POSIX, and plaintext boundaries
in the security policy are unchanged.

## Verification and next work

Exercise large checkpoints through both persistence hosts and the typed
application client on VM and native routes. Check complete scans with truncated
output, small grants refusing expensive inspection/withdrawal/compaction,
withdrawal plus compaction at the event ceiling, and malformed histories beyond
the former 128-event boundary. Byte-capacity checks must independently inspect
the checkpoint, prove no partial mutation or identifier advance, prove the
clock floor was committed, and reopen with fresh admission.

Every durable call still decodes and re-encodes one bounded checkpoint. Event
and withdrawal membership scans can perform quadratic work. This expansion is
for larger bounded application prototypes; indexes, incremental storage,
snapshot-bound continuation, backup/restore, native admission, encryption, and
production qualification remain separate work.
