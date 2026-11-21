# ENI-0007: Durable sessions for applications

Status: implementation contract for the first application integration.

## One implementation of durable ownership

The volatile `enigma.client` is useful inside a computation but cannot commit
application data. The persistence CLI previously owned the filesystem and lock
lifecycle, so applications would have to spawn it or copy its implementation.

Extract that implementation into `enigma.durable.session` under
`ext/enigma-durable`. The Matrix CLI becomes an adapter over the same session.
Staging, semantic validation, checkpoint envelopes, private-file checks,
candidate binding, and synchronization ordering remain shared. The Python host
remains available through its existing protocol; no network listener is added.

`create_database(directory, scope)` exclusively creates a new store and returns
an active owner only after checkpoint publication and parent-directory sync.
`open_database(directory)` opens an existing store, retires loaded grants, and
commits a fresh incarnation before returning an active owner. Neither silently
replaces a store or restores a backup. Failures return an inactive session and
release any lock acquired by that factory.

Directory paths are pinned to an absolute POSIX path at creation/open time.
Later working-directory changes cannot redirect a commit while the owner holds
the original lock. Path spelling preserves literal backslashes and UTF-8;
trailing directory separators are stripped before final-component inspection.
Storage ancestry remains trusted, as in ENI-0002; this is not containment against
an owner replacing its directory tree.

## Lock lifetime is part of the API

The owner stores its runtime lock token and exposes `dispatch` and explicit
`close`. Closing disables every alias before releasing the lock. A second close
is harmless. A release/proof failure reports `lock_error` and never makes the
owner usable again.

NIL releases descriptors when an execution ends or its runtime context resets.
A Matrix object can survive that boundary in an embedding, so an `active` field
is insufficient proof of continued ownership. Before dispatch, the session
requires `file_lock_is_held(token)` to confirm current-context ownership without
releasing the lock. A lost token poisons the old owner before it interprets the
request. It cannot overwrite a successor that opened the database after release.
Tokens are not transferable authority across contexts.

Sessions are synchronous and belong to one execution context. Applications must
close them explicitly. Runtime cleanup is a final safeguard, not a substitute
for application lifecycle management. Concurrent dispatch on one owner is not a
supported application contract.

## Confirmed receipts and uncertain effects

Dispatch derives state and authority afresh from the last committed payload,
through the same strictly serialized staging request used by the CLI. It
validates identity, incarnation, generation, and receipt binding, and prepares
the receipt before publication. Only a successful commit permits adoption of a
new payload and a confirmed return. Reads and domain denials still commit when
their security state changes.

An I/O or protocol failure poisons the owner, clears its cached payload, and
refuses all further dispatch. If publication was attempted, the error reports
`outcome_unknown: true`: an unacknowledged effect may exist. A typed client that
cannot interpret a reply after dispatch also invalidates the owner and reports
an unknown outcome. No client retries a write or reconnects automatically.

Recovery requires explicit close, open, and fresh host admission. Applications
must inspect recovered state before deciding how to handle an uncertain write.
There is no durable idempotency ledger or exactly-once claim in this slice.

## Typed application facade

`enigma.durable.client` forwards typed support, opposition, withdrawal,
resolution, inspection, discovery, compaction, delegation, and revocation.
Connecting pins the current incarnation and grant ID. Every method takes a
fresh host-established `access_context`; it does not retain a copied clock or
rebind an old grant after reopening.

Calls return a uniform `durable_reply<receipt>` record with `confirmed`,
`receipt`, and `failure`. When `confirmed` is true, the receipt's own `code`
can still be `denied`, `conflict`, `capacity`, or another domain outcome. When
false, the receipt is empty and carries the failure code; `failure` contains
the lifecycle/transport code and `outcome_unknown` flag. It must not be
interpreted as a confirmed rejection.

This direct typed record preserves the known field provenance of discovery's
evidence batch. NIL's current closed enum-storage profile does not permit
hiding a record containing a class inside a general `Result` payload. The
application API keeps one reply shape for every operation without relaxing
that runtime check.

Trusted provisioning is a separate `provision_for_host` function over the owner,
not an application-client method. Identity/session labels remain trusted host
assertions. Matrix fields are public: these interfaces provide API guardrails,
not isolation against hostile code sharing the process. Native Anomalous
admission remains future work.

Other runtimes can use the existing bounded JSON host protocol through a
trusted adapter. They must preserve the same identity, permission, failure,
and recovery distinctions. An untrusted network request must not receive the
host's provisioning channel merely because it supplied a role or entity name.

## Validation

Keep the existing host session/fault contracts against the refactored Matrix
CLI and Python host. Add an independent application oracle on VM/native for:

- Separate create/reopen application processes with persisted reports, retired
  grant refusal, fresh admission, and subsequent revocation.
- Explicit close while the process remains alive, alias invalidation, writer
  contention, and cleanup after a corrupt-store open.
- A stale owner refusing dispatch while a successor owns the writer lock.
- External storage failure causing an unknown outcome and poisoned-session
  refusal, with no receipt or automatic retry.
- Working-directory changes leaving the original database pinned and an
  unrelated canary database unchanged.

The runtime query has paired Ny/Matrix route, native-context, and embedded-VM
lifecycle checks. These are application development guarantees within the
bounded POSIX profile; they do not add authentication, encryption, multiwriter
storage, release-SDK qualification, or production-data qualification.
