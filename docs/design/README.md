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
defines the executable contract.

| Area | Current behavior |
| --- | --- |
| Evidence | Exact text propositions with independently attributable support and opposition. |
| History | Assertions and withdrawals append events; as-of reads preserve prior views. |
| Resolution | `unknown`, `supported`, `contradicted`, or `contested` after a complete scan; `incomplete` when work runs out. |
| Bounds | 128 events per store, explicit work/output limits, and separate evidence-list completeness. |
| Authority | Trusted-host entity/session grants with exact audience, scope, rights, logical expiry, attenuation, and live ancestor revocation. |
| Client | Typed operations and a discoverable surface under [`ext/enigma-client`](../../ext/enigma-client/README.md), outside `nil.std`. |

Each store has independent IDs, revisions, capacity, and work budgets. A failed
write does not advance its revision. Current authority is required even for an
old snapshot. Withdrawal and inspection honor grant work limits and return a
structured `limit` response when the required scan is too large.

The implementation is Matrix, configured through NILData. The canonical surface
is the typed evidence operation model. No text query parser, inference system,
causal dependency model, persistence, network transport, or cryptography exists.

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
hostile-process isolation, realtime-expiry guarantee, persistent security state,
or durable revocation. See the [security policy](../../SECURITY.md).

Grant IDs, evidence IDs, and revisions identify state only within their live
registry/store instances. Replacement or restart can reuse numbers; issuer/store
epochs and retained replay state do not exist yet. Old numeric IDs and client
contexts must not be reused as authority under replacement instances.

## Next questions and milestones

1. **Native authority integration:** consume verified Anomalous admission and
   installed sigils through an explicit adapter. Define request/effect binding,
   replay handling, fresh session incarnations, and the trusted clock boundary.
2. **Richer evidence semantics:** evaluate typed values, causal dependencies,
   derived conclusions, and changes that invalidate them. Define how authority
   and provenance propagate before exposing cross-scope reasoning.
3. **Durable state:** specify the event format, transactions, corruption and crash
   behavior, restart epochs, revocation recovery, migrations, and backup/restore.
   Prove guarantees through fault and recovery tests before claiming them.
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
