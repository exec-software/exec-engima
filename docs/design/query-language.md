# Query and operation surface

Status: typed evidence operations are implemented; a textual query parser is
not implemented.

Enigma's canonical surface is an operation model that preserves evidence,
provenance, authority, historical revision, and completeness. It is not
predetermined to be relational, document-oriented, SQL, or NoSQL. Storage
structure and human syntax should serve that model instead of selecting the
semantics by convention.

## Working typed surface

The companion [Matrix client](../../ext/enigma-client/README.md) lives under
`ext/enigma-client`, outside the framework's core standard library. It exposes
`support`, `oppose`, `resolve`, `inspect`, and `withdraw`, plus a discoverable
surface descriptor. Requests pass typed propositions and explicit parameters;
agents do not need to synthesize query strings.

A proposition is the exact triple `(subject, relation, object_value)`. Support
and opposition are separate attributable evidence, not overwriting assignments.
Different values are not automatically contradictory. The current value type
is bounded text; richer values and relation semantics remain future work.

Resolution supplies an explicit snapshot, work budget, and evidence-list budget.
Revision `0` is a real empty view; `-1` requests latest. Complete scans distinguish
`unknown`, `supported`, `contradicted`, and `contested`. Work exhaustion yields
`incomplete` rather than a final answer. A fully scanned answer can have an
incomplete evidence list; `evidence_complete` reports that separately.

Writes accept an expected revision so an agent can detect stale assumptions.
Withdrawals append a correction event and preserve prior snapshots. Withdrawal
and inspection also check grant work limits and can return `limit` without
returning evidence. See [ENI-0001](ENI-0001-evidence-and-authority.md) for the
complete operation and authority contract.

## Future Matrix-inspired text

A human-readable language should borrow Matrix's named inputs, explicit types,
word operators, and visible block boundaries. It must compile into the same
typed operations used by the client, with the same authority and resource
checks. The language should expose evidence and completeness directly rather
than conceal disagreement behind a single selected value.

No concrete text grammar is standardized in this slice. Before implementing
one, define acceptance fixtures for a bounded expression of a proposition,
support or opposition with source attribution, a historical evidence view, and
an explicit work/output budget. Do not accept arbitrary Matrix programs as
queries.

The future parser must keep data bindings separate from language structure,
reject ambiguous or unknown constructs, bound input and nesting, and return
structured source errors. A bound value must not introduce identifiers or
operations. Natural-language plausibility must not select permissions or
silently repair a request into a different effect.

## One authority path

Identity and authority come from the host, outside operation text and data
bindings. Enigma follows the separation in Anomalous's [identity and authority
design](https://github.com/exec-software/exec-anomalous/blob/87e365dadac72a481b03cfe175b06e0129dc6c1d/docs/architecture/identity-and-authority.md).
A future native adapter must establish the live session and applicable sigils;
the current embedded engine uses explicit trusted-host fixtures.

Neither textual requests nor the client can authorize themselves. Current
grants apply to historical views too. The host supplies fresh logical-tick
context per dispatch; client snapshots do not establish realtime freshness.
Current public Matrix class fields are not isolation from hostile same-process
code. Authentication, native admission, durable revocation, persistent storage,
network transport, inference, and causal dependencies remain separate work.
