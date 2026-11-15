# ENI-0005: Evidence retention without a wrong historical answer

Status: implemented. Events carry their issued revision, `compact` reclaims
matched pairs under withdrawal authority, a view below the horizon answers
`incomplete`, and the checkpoint schema is `enigma.state.v3`.

## The ceiling counts writes, not evidence

An evidence store holds 128 events. Assertions and withdrawals both append, and
`revision_value` only increases, so the ceiling counts everything ever written
rather than everything currently held. A store that asserts a claim and then
withdraws it has no evidence to show for two of its 128 events, and a store
used for corrections spends its capacity on churn.

This is the shape ENI-0004 fixed for authority, where ordinary restarts spent a
lifetime budget. Here the budget is spent by ordinary corrections, which is the
workload the engine exists to serve: an agent that revises a claim is doing the
thing evidence-orientation is for, and the engine charges it twice and then
refuses.

## Why the log cannot simply be truncated

Three things stand in the way, and all three are the point of the engine rather
than incidental.

An assertion identifier *is* its assertion event's revision, so removing
earlier events and renumbering would change the identity of evidence that
callers hold. ENI-0004 met the same problem with grants.

As-of reads reconstruct a prior view by scanning back to the beginning.
Truncating the log does not make those reads fail; it makes them *wrong*, which
is worse. A proposition supported at revision 5 and withdrawn at revision 9
must read as supported at 7, and a truncated log would answer `unknown` with
every appearance of confidence.

An unwithdrawn assertion below any horizon still contributes to the current
answer. Dropping it changes a present-tense result, not just a historical one.

## Decision

**Reclaim matched pairs, not prefixes.** An assertion and the withdrawal that
retires it contribute nothing to any view at or after the withdrawal. When both
events sit below a retention horizon, the pair can be removed without changing
any answer the store still claims to give. An assertion with no withdrawal is
never reclaimed, whatever its age, because it is still evidence.

**Identifiers stay put.** Events carry their issued revision explicitly, as
grants now carry their issued identifier, and `revision_value` remains the
logical clock and the as-of coordinate. Nothing is renumbered, so an identifier
a caller holds keeps meaning what it meant. The ceiling then counts *retained*
events, so it bounds evidence rather than history.

**A read before the horizon is `incomplete`, never a guess.** The resolution
record already carries this answer for a scan that ran out of work budget, and
the engine already distinguishes an incomplete investigation from an absence of
evidence. A view the store can no longer reconstruct is the same kind of fact,
and gets the same answer. Revision `0` stays exact: no events existed, so an
empty snapshot is not a reconstruction.

| As-of revision | Answer |
| --- | --- |
| `0` | exact, `unknown`: nothing had been written |
| below the horizon | `incomplete` |
| at or above the horizon | exact, as today |

**Compaction is explicit, not automatic.** This is the decision that most
distinguishes this record from ENI-0004. Retiring session grants at recovery is
*required*: restoring session authority would be a security failure. Reclaiming
evidence is not required by anything — it trades history for capacity. Doing it
silently on every restart would mean an agent loses the ability to explain what
was known before the last restart, in a database whose reason for existing is
explaining what was known. So compaction is an operation a caller invokes under
authority, and a store that is never compacted fills up and fails closed, which
is the honest outcome.

## What this does not do

It does not raise the 128 ceiling. After this change the ceiling bounds
retained events, and a store holding 128 unwithdrawn assertions is genuinely
full. Raising the number is a separate question about bounded work and
checkpoint size.

It does not compact evidence that is merely old. Age is not a reason to forget
an assertion nobody retracted.

It does not let a compacted view be recovered. The horizon only moves forward,
and a reclaimed pair is gone. Backup and restore remain future work, and they
are the answer for keeping history that is wanted after compaction.

It does not change what `inspect` reports for a reclaimed assertion, which
stays `not_found`. Distinguishing "reclaimed" from "never existed" would want
the same high-water-mark treatment grants received, and is deferred rather than
decided here.

## Schema

Events gain their issued revision, and the store gains the retention horizon.
That is `enigma.state.v3`, refused rather than upgraded from v2, for the
reasons ENI-0004 records.

## Validation

The check that expresses the defect is a churn loop: assert and withdraw the
same claim far more times than the ceiling, compacting as it goes, and require
the store to keep accepting writes while a current read still resolves
correctly from the assertions that were never withdrawn.

Beside that: an identifier is never reused or renumbered across compaction, an
unwithdrawn assertion below the horizon still counts toward the current answer,
an as-of read below the horizon reports `incomplete` while revision `0` stays
exact, an as-of read at or above the horizon is unchanged, a store of
unwithdrawn assertions still fills and fails closed, and compaction requires
authority like any other operation.
