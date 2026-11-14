# Security

## Current implementation

Enigma has a bounded, in-memory evidence engine and an embedded Matrix client.
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

There is no authentication service, network listener, encryption, persistence,
durable revocation, or recovery guarantee. Process exit discards evidence and
authority state. No version is qualified to hold sensitive or production data.
See [ENI-0001](docs/design/ENI-0001-evidence-and-authority.md) for the exact contract.

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
installed authority rather than request fields. Body/effect binding, replay
control, session and issuer incarnations, durable security accounting, and a
restart epoch or recovery contract remain required work before external access.

Numeric grant IDs belong to one live registry, and evidence IDs and revisions
belong to one live store. A replacement or restarted instance can reuse those
numbers. There is no issuer/store epoch or retained replay state to detect stale
ID reuse. The host must discard old clients and establish new instance bindings;
standalone numeric IDs or saved contexts cannot safely carry authority across
replacement or restart.

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
- Each store holds at most 128 events. Proposition components and source text
  are bounded at 256 units under NIL's text-length operation; scope and entity
  labels are bounded at 128. The authority registry admits at most 256 grants.
- Resolve meters inspected log events. Withdrawal and inspection return
  `limit` when their required scan exceeds the grant's work limit. Event budgets
  are not CPU-time quotas: bounded withdrawal checks add work within a scan.
- These checks do not establish resistance to timing side channels, denial of
  service, host compromise, allocation failure, or process crashes. Direct host
  memory access can bypass the API contract.

## Remaining security work

Durable revocation and replay state, native admission integration, protected
transport, maintained cryptographic dependencies, key rotation and recovery,
redacted audit integrity and retention, and backup/restore verification remain
planned. Historical evidence is not a tamper-proof audit log. Revocation cannot
undo completed effects or recover data already returned.

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
