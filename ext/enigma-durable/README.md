# Durable Matrix client

`enigma.durable.client` connects a Matrix application to an embedded durable
session. It lives above the engine under `ext/`, outside `nil.std`. The existing
`enigma.client` package remains an in-memory API.

The package uses the same session implementation as the Matrix command-line
host. It does not implement another checkpoint format or commit protocol.
Use the matching development SDK described in the root
[development guide](../../docs/development.md); its lock-ownership query is
required before an application dispatch.

## Open, admit, and call

`create_database(directory, scope)` exclusively creates a new store and returns
`code = "created"`; `open_database(directory)` opens an existing valid store
and returns `code = "ready"`. Both results contain `session` and
`outcome_unknown`. Check the code before using the session. Failed creation
never overwrites an existing directory, and failed opening never initializes
or restores another checkpoint.

The application host retains the owner session, establishes admission, then
calls `provision_for_host`. Provisioning is separate from the application
client; there is no `install` method on `durable_client`.

```matrix
read create_database from enigma.durable.session
read connect, provision_for_host from enigma.durable.client
read access_context from enigma.authority
read proposition from enigma.ledger

value opened is create_database with directory being directory, scope being "work"
!!! Check opened.code equals "created" before continuing.
value owner is opened.session
value granted is provision_for_host with owner being owner, entity being "app:worker",
    session_id being 1, operations being 7, expires being 1000,
    work_limit being 128, result_limit being 128, tick being 1
!!! Check granted.confirmed, then granted.receipt.code.
value client is connect with owner being owner, grant_id being granted.receipt.grant_id
value caller is build access_context with entity being "app:worker", session being 1,
    audience being "enigma", tick being 2
value claim is build proposition with subject being "application:sample",
    relation being "status", object_value being "ready"
value outcome is client.support with caller being caller, claim being claim,
    source being "synthetic:app", expected_revision being 0
```

The [standalone example](examples/main.matrix) checks every result and closes on every handled failure.
Its fixed identities are synthetic fixtures, not authentication.

Each client call requires a fresh host-established `access_context`. The client
pins the session incarnation at connection and stores no copied caller context.
A pattern, grant number, or identity label cannot re-admit a caller after a
restart. Reopening retires old grants before returning `ready`; the host must
establish a current session and provision fresh authority explicitly.

## Confirmed outcomes and uncertainty

Every operation returns a direct typed `durable_reply<T>` with three fields:

- `confirmed = true` means `receipt` is a confirmed domain response. Check
  `receipt.code` for `ok`, `denied`, `invalid`, `conflict`, `limit`, `capacity`,
  or `not_found` as applicable. `failure.code` is empty and
  `failure.outcome_unknown` is false. State-changing reads and denials have
  been committed before this reply is returned.
- `confirmed = false` means `failure` reports a lifecycle, construction,
  storage, or protocol problem. `failure.code` is a fixed code and
  `failure.outcome_unknown` says whether the attempted effect may have reached
  storage. `receipt` is blank, with its code set to that failure code and all
  evidence/snapshot metadata cleared. Never infer that an uncertain write was
  absent and never retry it blindly.

`invalid_request` is a checked construction failure before dispatch and has
`outcome_unknown = false`. Storage/protocol failures disable the owner session;
all later calls refuse until it is closed and a new session is opened. A typed
receipt that fails validation also poisons the owner, since a commit may already
have occurred. The client never retries, grants authority, or repairs a request.

Use expected revisions and inspect recovered state after an uncertain result.
There is no durable idempotency ledger in this version.

## Typed operations

| Method | Inputs after `caller` | Typed receipt |
| --- | --- | --- |
| `support`, `oppose` | `claim`, `source`, `expected_revision` | `write_receipt` |
| `withdraw` | `evidence_id`, `expected_revision` | `write_receipt` |
| `resolve` | `claim`, `as_of`, `max_work`, `max_evidence` | `resolution` |
| `inspect` | `evidence_id`, `as_of` | `inspect_receipt` |
| `discover` | `pattern`, `as_of`, `max_work`, `max_evidence` | `discovery_result` |
| `compact` | none | `compaction_receipt` |
| `delegate` | `entity`, `session_id`, `operations`, `expires`, `work_limit`, `result_limit` | `grant_receipt` |
| `revoke` | none; retires the client's own grant | `grant_receipt` |

Selectors, revision zero/latest, evidence states, provenance, retention, and
budget completeness have the same semantics as the engine. Scope-wide
compaction requires explicit right `16`; withdrawal alone does not authorize it.
Discovery returns the bounded report batch with `count` and checked `get`.

## Lifetime and integration boundary

Call `owner.close with nothing` on every handled exit. `closed` is idempotent;
`lock_error` means the lock could not be verified/released. The owner always
refuses later calls. Copies of a client share that same owner lifetime. Runtime
teardown releases owned locks, but applications should close explicitly.

Use a session within its owning NIL invocation and context. A retained handle
cannot rely on a lock after that context ends: the session verifies the runtime
still owns its lock token before another dispatch and refuses if ownership was
lost. This is a synchronous, single-writer API, not concurrent session sharing.

The embedding host remains trusted. Matrix fields are public and same-process
code is not isolated by these facades. Storage ancestry must remain trusted;
there is no network listener, authentication service, encryption, general
rollback defense, or production qualification. See [SECURITY.md](../../SECURITY.md).

## Build and run the application fixture

From the repository root with a matching SDK selected:

```sh
export NIL_SDK=/absolute/path/to/matching/development-sdk
"$NIL_SDK/nilbuild" build --project ext/enigma-durable/nil.project.nildata --sdk "$NIL_SDK" --target all
mkdir -p data
NIL_STRICT_BOUNDS=1 ext/enigma-durable/build/enigma-durable-example create data/application
NIL_STRICT_BOUNDS=1 ext/enigma-durable/build/enigma-durable-example reopen data/application
```

Use `nilinterpreter ext/enigma-durable/build/enigma-durable-example.nil` for the
VM route. The fixture emits `application-created` and `application-reopened`.
It writes synthetic evidence, closes, reopens in another process, proves a
retired grant is denied, explicitly admits a fresh read session, discovers the
persisted report, revokes that read grant, and verifies denial again.

For an application project, add `ext/enigma-durable/src` and the engine's `src`
directory to its `includePaths`. Package-manager publication and a stable release
compatibility promise remain future work.
