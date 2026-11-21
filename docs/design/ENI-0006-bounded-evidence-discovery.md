# ENI-0006: Bounded evidence discovery

Status: implementation contract for the discovery slice.

The initial numerical bounds recorded here are superseded by
[ENI-0008](ENI-0008-bounded-capacity.md): 1,024 retained events, 1,023 assertion
admission, work through 1,024 events, and 128-item replies.

## The missing operation

`resolve` answers a question about a complete proposition. A caller must already
know its subject, relation, and value. An agent exploring an unfamiliar scope
cannot ask which relations a subject has, or which subjects report a value,
without guessing triples. Returning only identifiers would then require an
inspection call and another history scan for every report.

Add discovery of active evidence under an explicit pattern. This exposes the
evidence needed to form the next question without inventing a parser, inference
rule, or truth verdict.

## Selectors and results

An `evidence_pattern` has `subject`, `relation`, and `object_value`, each an
`Option of text`: `None` matches any value, while `Some` matches exact text.
An exact value must contain 1–256 NIL text units. `*`, `?`, punctuation, and
source-like text remain literal data. The durable protocol uses JSON `null`
for any and a string for exact, with all three members required.

`discover(pattern, as_of, max_work, max_evidence)` returns full active evidence
items in a bounded typed batch, newest evidence ID first. `items.count()` reports
the number returned and `items.get(index)` returns an `Option of evidence_item`,
with `None` for an invalid index. Each item retains its proposition, polarity,
source, acting entity/session, and assertion revision. Its `withdrawn_at` is
zero because it was active at the requested snapshot. Withdrawn reports can
still be inspected explicitly, subject to retention.

The Matrix batch owns independent primitive columns, following the supported
native aggregate layout. The durable protocol serializes it as a JSON array of
report objects. Its 128-item ceiling is independent of the retained-event
bound expanded in ENI-0008.
General arrays of records remain a separate NIL native-runtime capability.

Several reports can match the same proposition, and opposing reports are
returned independently. `matched` counts reports observed, not distinct
propositions. Discovery does not resolve disagreement; use `resolve` for that.

The result also includes `revision`, `retained_from`, `inspected`, `complete`,
and `evidence_complete`:

| Field | Meaning |
| --- | --- |
| `revision` | The selected snapshot; latest (`-1`) is pinned once per call. |
| `retained_from` | The current history horizon. |
| `inspected` | Eligible retained events examined, including withdrawals and nonmatches. |
| `matched` | Active matching reports seen; a lower bound when the scan is incomplete. |
| `complete` | All eligible history was examined and the snapshot remains reconstructable. |
| `evidence_complete` | The investigation is complete and every matching report fits the output. |

Work ranges from 1 through 1,024 and output from 1 through 128; both must fit
the grant's corresponding work/output limit. Reaching the output cap does not stop the scan: a complete
investigation can have a truncated list. A bounded scan that returns no reports
does not prove absence unless `complete` is true.

## Snapshot and authority rules

Discovery requires current scoped read authority (`1`), before validating the
pattern or accessing evidence. It uses the same entity/session, audience,
expiry, ancestry revocation, and clock-floor rules as `resolve` and `inspect`.
Read authority already permits inspecting every report in its scope; discovery
adds no grant or cross-scope access. A denied typed result is empty with zero
metadata. Durable failures use the fixed base receipt without an instance.

Revision `0` remains an exact empty snapshot. A future revision is invalid.
Events newer than the selected snapshot are outside the investigation and do
not consume its work budget. A nonzero snapshot below the compaction horizon
is incomplete, including when a scan of surviving rows finishes.

Scan backwards so every possible withdrawal at or before the selected snapshot
is visited before its assertion. This matters for partial results: an emitted
report must never later turn out to have been withdrawn at that snapshot.
Membership checks add bounded work within the event scan, as in `resolve`;
event budgets are not CPU-time quotas.

Durable dispatch stages and commits discovery like other reads. A read or denial
can advance the logical clock floor, so the host synchronizes its checkpoint
before publishing the receipt. Restart retires previous session grants; a saved
pattern or historical revision cannot re-admit a caller. No checkpoint schema
change is required because discovery stores no new state.

## Bounded staging frames

A checkpoint and a full escape-heavy result each fit NILData's 1 MiB value
limit, but their combined worker packet can exceed it. The worker transport
already allows 2 MiB. Keep the library's default limit intact: staging returns
typed `code`, `payload`, and `receipt` parts internally. The Matrix host consumes
those parts and retains its existing candidate, identity, generation, and
receipt checks. Requests still enter through the same strictly decoded
serialized envelope, re-deriving authority from committed state each time.

The external worker encodes each part independently through NILData, then joins
only those checked JSON fragments with fixed keys and punctuation. It bounds
the complete frame, including the output newline, at 2 MiB. No raw payload or
caller text becomes JSON structure. Python still receives the same three-key
packet and validates it before publication. This changes internal framing,
not commit ordering or authority.

Host byte conversion processes bounded chunks and joins text chunks pairwise.
It preserves exact bytes, including UTF-8 sequences split across chunks,
without passing or copying the full checkpoint for each byte. The secure file
operations and receipt timeouts remain unchanged.

## Boundary and validation

This slice has no continuation cursor. A correct cursor would need snapshot and
retention binding, withdrawal scan state, and a fresh authority check per call.
A partial result remains explicit rather than pretending to be a complete page
sequence. ENI-0008 expands storage and work while retaining the 128-item reply
ceiling, so a complete investigation can still have a truncated list.
There is no wildcard language, sorting expression, join, aggregation, inference,
or text-query execution.

Validation covers exact/any selectors, literal wildcard characters, provenance
and opposing reports, newest-first order, withdrawals at historical snapshots,
revision zero, future revisions, work versus output truncation, compaction,
fresh results, invalid inputs, and current authority. The durable contract also
checks restarts, ancestor revocation, clock-floor commits, and escape-heavy
full-capacity receipts through the actual hosts on VM and native routes.
