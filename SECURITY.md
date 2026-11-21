# Security

## Current implementation

Enigma has a bounded evidence engine, a volatile Matrix client, an importable
durable Matrix session/client, and POSIX persistence hosts.
The engine checks scoped grants before examining evidence requests, binds them
to an exact entity/session and the audience `enigma`, and checks operation
rights, logical expiry, limits, and live delegation ancestry. Delegation cannot
expand scope, rights, expiry, or per-request limits. Revocation invalidates a
grant and its descendants on later API calls. There is no administrator bypass.

These are API checks over **trusted host assertions**. The registry's `install`
method is a host-only fixture for provisioning authority, not enrollment or
authentication. An entity label, grant ID, or claimed source does not prove
identity. Matrix class fields are currently public: code in the same process
can access or change store and registry memory. The host must own these handles
and keep hostile code outside the process. This slice does not establish an
unforgeable capability or a hostile-process isolation boundary.

There is no authentication service, network listener, encryption, or native
Anomalous integration. The direct embedded client remains volatile. The durable
host retains evidence and permission state under the commit and recovery
contract below. No version is qualified to hold sensitive or production data.
See [ENI-0001](docs/design/ENI-0001-evidence-and-authority.md) for evidence policy
and [ENI-0002](docs/design/ENI-0002-durable-state-and-recovery.md) for persistence.

## Durable acknowledgements and recovery

The default durable receipts come through `scripts/store.py`; the optional
Matrix host follows the same commit contract under
[ENI-0003](docs/design/ENI-0003-matrix-durable-host.md). A staging reply alone
is not a durable acknowledgement. The POSIX host
holds an exclusive nonblocking advisory writer lock, writes a private candidate,
syncs the file, atomically replaces the canonical checkpoint, and syncs the
database directory before returning the receipt. Initial creation also syncs
the parent directory. An I/O or worker-protocol failure stops the session without
a success receipt; no later request uses its uncertain in-memory state.

The importable durable session uses that same commit implementation as the
Matrix CLI. Every dispatch proves current runtime lock ownership; a cached
active flag cannot survive loss of the lock. Close disables aliases before
release, and storage/protocol failure poisons the owner and clears its payload.
The typed application reply separates confirmed domain outcomes from failures
whose effect may be unknown. There is no automatic retry or re-admission.
See [ENI-0007](docs/design/ENI-0007-application-sessions.md).

The single checkpoint retains evidence, permission definitions, delegation
ancestry, revocation flags, nonreused ID counters, and the logical clock floor.
Reads and denied operations are also committed when their staged state changes,
so authorization cannot advance the floor only in memory. Matrix validates the
whole checkpoint before exposing evidence or authority.

Opening a store retires **all** loaded session grants and reclaims their rows,
installs a fresh random incarnation, and commits that recovery transition before
`ready`. The trusted host must re-admit callers and explicitly install new
grants. Old-incarnation requests are denied before their bodies are interpreted.

A grant identifier is issued rather than positional and is never reissued, so a
reclaimed identifier is never handed to a different holder. A retirement
high-water mark is retained, so a reclaimed grant is still refused as revoked
rather than as one that never existed, though the engine no longer reports when
or by whom it was revoked. Recovery reclaims retired rows so ordinary restarts
do not spend a lifetime grant budget. The ceiling counts retained rows,
including grants revoked during the current session. Identifiers are
not protected against an operator restoring a checkpoint written before one was
issued, which is a consequence of the rollback limit below. Persistent
permission definitions do not authenticate a session after restart.

Missing, malformed, truncated, checksum-invalid, or semantically invalid primary
state fails closed. Opening never auto-initializes a database, and recovery never
uses a backup or orphaned staging file to bypass corrupt canonical state. An
older valid checkpoint may predate an acknowledged revocation. See [the
persistence guide](docs/persistence.md) for the request and failure contract.

Guarantees assume a trusted owner and storage ancestry plus a local POSIX
filesystem honoring `fsync`, atomic rename, and advisory locks. Directory and
file handles reject unsafe final components; this does not contain a hostile
owner replacing trusted ancestry. SHA-256 detects accidental corruption, not
forgery or restoration of an older coherent snapshot. Retirement plus a fresh
incarnation prevents saved session authority from returning through this recovery
path; general rollback detection needs separately trusted monotonic state.
Physical power-cut behavior and arbitrary filesystem/device behavior have not
been qualified. An unacknowledged effect can be present after restart, so callers
must inspect state rather than blindly retrying.

## Identity and time

Enigma follows the identity, session, and scoped-authority separation described
in Anomalous's [identity and authority design](https://github.com/exec-software/exec-anomalous/blob/87e365dadac72a481b03cfe175b06e0129dc6c1d/docs/architecture/identity-and-authority.md)
and [ADR 0040](https://github.com/exec-software/exec-anomalous/blob/87e365dadac72a481b03cfe175b06e0129dc6c1d/docs/adr/0040-separate-entity-identity-authentication-and-authority.md).
Those documents define the integration direction; this engine does not implement
Anomalous admission, authenticators, native sigils, or trusted task/channel
provenance.

The host must establish the current verified entity/session and a fresh,
monotonic logical tick for **each dispatch**. Grant expiry means the supplied
tick must be strictly less than the grant's expiry; the registry rejects
rollback below its observed clock floor. This is a logical-tick model, not a
wall-clock or realtime-expiry guarantee. A client copies its context at
connection time, so the host must reconnect with fresh context for subsequent
dispatches. Holding a client with an old tick does not establish freshness.

A future native adapter must derive context from actual live admission and
installed authority rather than request fields. Body/effect binding, durable
replay/idempotency accounting, externally verified session incarnations, and
trusted clock integration remain required before external access.

The durable host preserves grant IDs and counters and binds requests to the
current incarnation. Direct embedded replacement remains a different path:
opening a new in-memory registry or store can reuse numbers. Discard old clients
and establish new bindings; standalone numeric IDs or saved contexts are never
portable authority. Do not bypass durable recovery with fresh in-memory objects
and then claim that old authority has been recovered safely.

## Evidence and resource boundaries

- A store has one access scope and its own event IDs, revisions, capacity, and
  scan budgets. Denied operations return fixed empty receipts before evidence
  validation; current authority is required for historical reads too.
- Successful assertions and withdrawals append events. Withdrawal requires the
  asserting entity and separate withdrawal authority. Source text is unverified
  data; acting entity/session come from the host context.
- Resolution distinguishes support, opposition, disagreement, and absence of
  evidence. A work-limited scan reports `incomplete`; an evidence-list cap is
  reported separately. Neither evidence state nor a source label proves truth.
- Discovery requires the same current read authority and returns active reports
  in that scope. Selectors are exact text or explicit any values; text never
  creates an operator. Partial counts are lower bounds, and an empty partial
  list does not establish absence. Current authority applies to every snapshot.
- Each store holds at most 1,024 retained events, with assertions limited to
  1,023 to reserve one withdrawal slot; a caller with explicit scoped
  compaction authority (`16`) may compact retracted evidence. Withdrawal of
  one's own assertions (`4`) does not authorize deletion of scope-wide history.
  After compaction a historical read
  below the resulting horizon reports `incomplete` rather than an answer the
  store can no longer substantiate. Proposition components and source text
  are bounded at 256 units under NIL's text-length operation; scope and entity
  labels are bounded at 128. The authority registry retains at most 256 grant
  rows, including grants revoked in the current session; recovery retires and
  reclaims every row while preserving issued counters and the retirement mark.
  Identifiers are never recycled within a checkpoint lineage.
- Resolve and discovery accept work budgets through 1,024 events; returned
  evidence lists remain capped at 128 items. Durable admission bounds the
  encoded event array at 384 KiB, reserving 2 KiB from assertions for
  withdrawal, and the encoded grant array at 64 KiB. Byte exhaustion returns
  confirmed `capacity`, discarding the refused mutation while preserving the
  observed clock floor and commit generation. Recovery and revocation retain
  their existing authority rules. See
  [ENI-0008](docs/design/ENI-0008-bounded-capacity.md).
- Resolve meters inspected log events. Withdrawal, compaction, and inspection return
  `limit` when their required scan exceeds the grant's work limit. Event budgets
  are not CPU-time quotas: bounded withdrawal checks add work within a scan.
- These checks do not establish resistance to timing side channels, denial of
  service, host compromise, or allocation failure. Process recovery is bounded
  by the checkpoint contract above. Direct host memory access can bypass the
  API contract.

## Remaining security work

Native admission integration, durable replay/idempotency state, protected
transport, maintained cryptographic dependencies, key rotation and recovery,
externally anchored rollback protection, redacted audit integrity and retention,
and backup/restore verification remain planned. Historical evidence is not a
tamper-proof audit log. Revocation cannot undo completed effects or recover data
already returned.

Do not invent cryptographic algorithms or infer safety from a model's stated
purpose. Human and agent requests must follow the same authority path.

## Reporting an issue

Do not include credentials, private records, or an exploitable security report
in a public issue. Use the repository's **Security → Report a vulnerability**
option. If private reporting is unavailable, open a public issue requesting a
private contact, without vulnerability details or sensitive data.

Only synthetic data belongs in public examples and reproductions. Supported
versions and response commitments will be documented when a release process
exists.
