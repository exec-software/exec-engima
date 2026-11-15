# Enigma design

Enigma tests an evidence-oriented database model for people and agents. The
working first slice preserves competing reports, their provenance, and the
historical view before a withdrawal. It does not commit the engine to relational
tables, document collections, or an existing SQL/NoSQL category.

The benefit to evaluate is concrete: an agent can retain disagreement, inspect
what supports an answer, and distinguish an incomplete investigation from an
absence of evidence. This is a design hypothesis, not a claim that evidence or
temporal database concepts are new.

## Implemented slice

[ENI-0001: Evidence views under explicit authority](ENI-0001-evidence-and-authority.md)
defines evidence behavior. [ENI-0002: Durable state and fail-closed recovery](ENI-0002-durable-state-and-recovery.md)
defines the persistence host and restart contract.
[ENI-0003: The Matrix durable host](ENI-0003-matrix-durable-host.md) decides how
the Python placeholder host is retired; nothing is ported yet.

| Area | Current behavior |
| --- | --- |
| Evidence | Exact text propositions with independently attributable support and opposition. |
| History | Assertions and withdrawals append events; as-of reads preserve prior views. |
| Resolution | `unknown`, `supported`, `contradicted`, or `contested` after a complete scan; `incomplete` when work runs out. |
| Bounds | 128 events per store, explicit work/output limits, and separate evidence-list completeness. |
| Authority | Trusted-host entity/session grants with exact audience, scope, rights, logical expiry, attenuation, and live ancestor revocation. |
| Client | Typed operations and a discoverable surface under [`ext/enigma-client`](../../ext/enigma-client/README.md), outside `nil.std`. |
| Persistence | Matrix checkpoint codec and validated recovery, with POSIX host locking, private files, atomic replacement, and sync-before-receipt ordering. |
| Restart authority | Retain permission definitions, counters, ancestry, revocations, and clock floor; retire all old session grants and commit a fresh incarnation before `ready`. |

Each store has independent IDs, revisions, capacity, and work budgets. A failed
write does not advance its revision. Current authority is required even for an
old snapshot. Withdrawal and inspection honor grant work limits and return a
structured `limit` response when the required scan is too large.

The implementation is Matrix, configured through NILData. The canonical surface
is the typed evidence operation model. No text query parser, inference system,
causal dependency model, network transport, or cryptography exists. Direct
embedded use remains volatile; durable receipts are supplied only by the
separate POSIX storage host.

## Authority direction

Follow Anomalous's separation of entity identity, admitted session, and scoped
sigil authority, as described in its [identity and authority design](https://github.com/exec-software/exec-anomalous/blob/87e365dadac72a481b03cfe175b06e0129dc6c1d/docs/architecture/identity-and-authority.md)
and [ADR 0040](https://github.com/exec-software/exec-anomalous/blob/87e365dadac72a481b03cfe175b06e0129dc6c1d/docs/adr/0040-separate-entity-identity-authentication-and-authority.md).
Human and agent requests share the same operation and policy path. An entity
name, an asserted purpose, or an administrator label cannot grant authority.

The working registry uses trusted-host fixture grants and supplied logical
ticks. It does not authenticate entities or obtain native task/channel/session
provenance. The host must establish fresh context for each dispatch; a copied
client context is not a live clock. Matrix class fields are public, so direct
same-process memory access is outside the API policy boundary. There is no
hostile-process isolation, realtime-expiry guarantee, or native Anomalous adapter.
See the [security policy](../../SECURITY.md).

The durable path retains evidence and security state together. Opening a store
retains old grant rows and revocations, marks every old session grant retired,
and commits a fresh random incarnation before admitting requests. New authority
requires explicit re-admission; old-incarnation requests receive a fixed denial.
Corruption or missing canonical state fails closed instead of restoring an older
permission snapshot. There is no grant-ID recycling or compaction: the retained
registry can exhaust its 256-grant ceiling and then fails closed.

Durability assumes a trusted owner and storage ancestry plus a local POSIX
filesystem honoring sync, atomic rename, and advisory locks. A coherent older
checkpoint restored outside the protocol cannot be detected without separately
trusted monotonic state. The current recovery path prevents saved session
authority from being restored; it does not prove general anti-rollback, durable
replay/idempotency accounting, or hardware power-cut behavior. See [the
persistence guide](../persistence.md).

## Next questions and milestones

1. **Native authority integration:** consume verified Anomalous admission and
   installed sigils through an explicit adapter. Define request/effect binding,
   replay handling, fresh session incarnations, and the trusted clock boundary.
2. **Richer evidence semantics:** evaluate typed values, causal dependencies,
   derived conclusions, and changes that invalidate them. Define how authority
   and provenance propagate before exposing cross-scope reasoning.
3. **Persistence beyond the bounded checkpoint:** define compaction without
   authority-ID reuse, migrations, backup/restore, durable replay/idempotency,
   externally anchored rollback detection, and broader filesystem qualification.
4. **Human language surface:** design bounded Matrix-inspired syntax that compiles
   into the same typed operations and authority checks. A parser must not execute
   arbitrary Matrix or grant authority from text.
5. **Evaluation:** measure workloads involving competing evidence, corrections,
   historical explanations, and constrained agent activity. Compare usefulness,
   correctness, and cost with reproducible baselines.

Package-manager distribution of the client is deferred. Storage layout,
concurrency, indexes, transport encoding, cryptographic dependencies, and
compatibility policy remain open. Choose those mechanisms to support useful,
testable behavior; do not infer them from an architectural label.

See [query surface direction](query-language.md) for the shared operation model.
