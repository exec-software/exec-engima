# ENI-0001: Evidence views under explicit authority

Status: implementation contract for the first in-memory slice.

## Why this model

An agent often needs to retain competing reports, explain an answer, and revisit
what was known before a correction. Overwriting a value loses those distinctions.
Enigma will first test an evidence-oriented model, without committing the engine
to relational tables or document collections. This is a useful hypothesis to
evaluate, not a claim that evidence graphs or temporal databases are new.

A proposition is the exact text triple `(subject, relation, object_value)`.
An assertion explicitly supports or opposes that proposition and records source
attribution plus the acting entity/session from trusted host context. Source text
is unverified data, not identity or an instruction. Different object values do
not automatically contradict each other; no relation cardinality or inference
system is assumed.

An evidence store represents one access scope. Assertions and withdrawals append
events; successful events advance that store's revision by one. Assertion IDs are
their assertion-event revisions. A withdrawal names an existing, active assertion
by the same entity and requires separate withdrawal authority. Failed operations
leave evidence and revision unchanged. Independent stores have independent IDs,
revisions, capacity, and scan budgets.

## Read semantics

The revision `0` is a real empty snapshot; `-1` explicitly requests latest.
Historical reads retain the source, actor, polarity, and withdrawal state that
existed at the selected revision. Current authority is always required, including
for historical data: a historical snapshot never restores an expired grant.

For a proposition, active evidence produces four states:

| Support | Opposition | State |
| --- | --- | --- |
| absent | absent | `unknown` |
| present | absent | `supported` |
| absent | present | `contradicted` |
| present | present | `contested` |

These are descriptions of evidence in a scope, not statements of truth,
probability, or consensus. Resolution returns the snapshot, counts, evidence IDs,
and completeness separately. A budget-exhausted scan reports `incomplete` even if
the evidence observed so far supports a more specific state. An output cap can
truncate the evidence ID list while a fully scanned verdict remains complete;
`evidence_complete` makes that distinction explicit. No partial result silently
looks like a complete answer.

## Authority and Anomalous

Follow Anomalous's separation of entity identity, admitted session, and scoped
sigil authority. The host establishes context independently of request contents.
There is no administrator bypass and an entity label alone grants nothing.

The in-memory policy registry binds a grant to an exact entity/session, audience
`enigma`, scope, operation mask, expiry, and per-request work/output limits.
Operations are resolve/inspect (`1`), assert (`2`), withdraw-own (`4`), and delegate
(`8`). Delegation inherits scope and cannot enlarge rights, expiry, or limits.
Authorization checks live ancestry; revoking a grant invalidates descendants.
Expired, copied, mismatched, unknown, and clock-rollback contexts fail closed.
Denial returns a fixed empty response before examining query or evidence data.

`install` is a trusted-host fixture, not a caller-accessible enrollment endpoint.
Context ticks must come from trusted monotonic host state. The client package
never installs authority. A future Anomalous adapter must derive context from
live native task/channel/session admission and map installed sigils to these
operations; request payloads cannot supply authority. Native integration needs
body/effect binding, replay control, incarnation checks, durable epochs, and an
explicit restart contract before it can become an external service.

## Exact implementation boundary

This slice is a synchronous embedded engine for trusted same-process Matrix
code. Matrix class fields currently remain publicly accessible; the host owns
the store and registry and must not expose their memory to hostile code. These
classes are not unforgeable kernel capabilities. There is no authentication,
transport, crypto, persistence, durable revocation, or hostile-process isolation.
Revocation is checked on each synchronous call, with no prepare/commit window.
Direct host memory access is outside this API policy boundary.

Hard bounds are 128 events per store and 256 text units per proposition component
or source (using the NIL text length operation). Scope labels are at most 128.
Resolve budgets meter inspected log events; each event may also require bounded
withdrawal membership checks, so this is not a CPU-time quota. Every store is
small and bounded; performance is not yet an optimization target. Allocation
failure and process crashes have no transactional or recovery guarantee.

Inspection and withdrawal require the current snapshot/history length to fit
the grant's work ceiling; they return an empty `limit` receipt otherwise. Store
capacity counts assertions and withdrawals together. A full store rejects all
further events, including withdrawals; this prototype has no compaction or
reserved maintenance capacity yet.

## Package boundary

The companion Matrix library lives at `ext/enigma-client`, namespace
`enigma.client`, above the engine and outside `nil.std`. It exposes typed
support, opposition, resolution, inspection, and withdrawal, and a discoverable
surface descriptor. A future text language must compile into the same operation
model and authority path. Package-manager publication is deferred.
