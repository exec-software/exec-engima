# ENI-0004: Authority capacity across restarts

Status: implemented. Identifiers are issued rather than positional and recovery
reclaims the rows it retires. This introduced `enigma.state.v2`; evidence
retention subsequently advances the schema to v3 in [ENI-0005](ENI-0005-evidence-retention.md).

## The problem is restarts, not data

A grant identifier is its position in the registry: `authorize` computes
`index is grant_id minus 1`, and `append_grant` returns the new
`grant_count`. Identifiers therefore only ever count upward, and the registry
only ever grows.

Recovery retires every loaded grant by marking it revoked, keeping its row so
that revocation history survives, and new callers are then admitted with fresh
grants. Nothing removes the retired rows, and the ceiling is 256. So each
restart consumes part of a lifetime budget: after enough ordinary restarts an
Enigma database refuses to admit anyone, permanently, with no growth in stored
evidence at all.

ENI-0002 records that "repeated recovery and re-admission can exhaust it" and
that exhaustion fails closed. Failing closed is right. Reaching that state
through nothing but normal operation is not: a database that bricks itself on
its two-hundred-and-fifty-seventh restart is broken, however safely it says so.

## Why pruning is not simply allowed

Two documented guarantees stand in the way, and both are load-bearing.

Identifiers are never recycled, so a revoked grant's identifier can never be
handed to a different holder. Because an identifier *is* an array position,
removing any row renumbers every row after it, which is exactly recycling.

Revocation history is preserved alongside evidence. Dropping a retired row
drops the record that it was revoked, which an evidence-oriented engine should
not do quietly.

A third invariant is easy to miss. `live` walks a grant's ancestry and refuses
any step where `parent_id is at least cursor`. That is the acyclicity guard,
and it works only because identifiers increase with position.

## Decision

**Separate the identifier from the position.** The registry gains an explicit
identifier per row and a `next_grant_id` counter that only increases.
Resolution becomes a search rather than an index, which at 256 rows is a scan
of a short array. The acyclicity guard survives unchanged: a parent is always
issued before its child, so a parent's identifier is still strictly smaller.

**Prune a row only when it is revoked and no live grant's ancestry reaches
it.** Stating the general rule, rather than "recovery may drop everything",
keeps it correct for any later compaction. Recovery happens to satisfy it
completely: it revokes every grant, `bound_holder` requires a live grant, and
`delegate` requires `bound_holder` on the parent, so no grant admitted after a
recovery can descend from one retired by it. Everything retired is therefore
unreachable, and recovery can reclaim all of it.

**Keep the explanation with a high-water mark, not with tombstones.** Because
recovery retires every grant at once, retirement is a prefix property: there is
an identifier below which everything issued has been retired. Recording that
one number, `retired_through`, preserves the distinction a pruned row would
otherwise lose:

| Identifier | Answer | Meaning |
| --- | --- | --- |
| Present in the registry | the usual checks | a live or revoked grant |
| Absent and `<= retired_through` | `revoked` | issued, then retired |
| Absent and `> retired_through` | `unknown` | never issued |

Every pruned identifier was revoked before it was pruned, so the middle row is
truthful rather than a convenient default. That depends on *where* pruning
runs: the implementation prunes only during recovery, which revokes everything
first and leaves the registry empty, so retirement stays a prefix and
`retired_through` cannot be claimed for an identifier that was never revoked.
Pruning mid-session would satisfy the rule above but would break the prefix,
and it is not needed for this defect. This costs two numbers of state and
keeps the engine able to say *why* a grant is refused, which matters more here
than in a database that only has to produce the right denial.

After this change the 256 ceiling bounds retained grant rows rather than every
grant a database will ever issue. Rows revoked during the current session still
occupy capacity until recovery retires and reclaims the whole registry.

## What this does not do

It does not bound the evidence log, which is a separate ceiling of 128 events
with its own retention question, and not this record's subject.

It does not raise the in-session ceiling. A registry with 256 retained rows
still refuses another grant. Recovery reclaims those rows, requiring fresh
admission for all callers; no operation silently evicts a grant to admit another.

It does not survive an operator rollback. `next_grant_id` lives in the
checkpoint, so restoring a file written before an identifier was issued
restores a counter that will issue it again. ENI-0002 already records that
restoring an older coherent checkpoint is undetectable without separately
trusted monotonic state, and identifier reuse is one more consequence of that
blind spot rather than a new one. The guarantee here is that an identifier is
never reissued within a checkpoint lineage.

It does not add an authority audit log. `retired_through` answers "was this
identifier retired", not "when, by whom, or why". Per-grant revocation
provenance remains future work.

## Schema

Grant rows gain an `id` member, and the state gains `next_grant_id` and
`retired_through`. The decoder requires an exact member set, so this is
`enigma.state.v2`.

A v1 checkpoint is refused with a distinct code rather than upgraded in place.
Migrations remain future work, as ENI-0002 records, and a database holding only
synthetic data is the right time to make a schema break explicit instead of
building an upgrade path that cannot be exercised against anything real.

## Validation

The check that would have caught the original defect is a restart loop: open,
admit, recover, repeatedly, far past 256, and require the database to keep
admitting callers and to keep refusing retired identifiers as `revoked`. A
run of a few thousand recoveries is cheap and is the direct expression of the
bug.

Beside that: an identifier is never reissued after pruning, a pruned
identifier is refused as `revoked` while an unissued one is refused as
`unknown`, a delegated chain whose ancestor is revoked stays denied across a
recovery, pruning never removes a row an ancestry still reaches, and a live
registry at 256 grants still fails closed on the next admission.
