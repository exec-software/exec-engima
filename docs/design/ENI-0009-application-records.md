# ENI-0009: Application records with immutable bodies

Status: **proposed, not implemented or qualified**. The coordination API below
names the intended first interface; it is not yet callable Matrix code. Changes
to these names must be coordinated with consumers. Storage limits and runtime
layouts still require implementation and matching SDK qualification.
It builds on [ENI-0002](ENI-0002-durable-state-and-recovery.md),
[ENI-0007](ENI-0007-application-sessions.md), and the current
[security policy](../../SECURITY.md).

## The application need

Goetic currently has seven aggregate documents totalling about 43 KiB and
expects 200–500 documents soon, with a path beyond 1,024. Each aggregate already
contains its application history. Its storage need is an exact latest body,
existence, and a monotonic version, plus durable compare-and-set replacement
and complete key enumeration. Historical body lookup is not required.

The evidence engine's 256-unit fields do not represent that contract. Splitting
a document into evidence fragments would make an application assemble its own
storage engine and atomicity rules. The proposed record layer belongs inside
Enigma: it owns keys, versions, body integrity, publication, enumeration,
capacity, and recovery. A companion package under `ext/` supplies the typed
application interface. Bodies do not become evidence or enter a query language.

Use a dedicated record-store profile initially. Its canonical manifest contains
record metadata and authority together. Existing evidence stores keep their
current format and semantics; this proposal does not silently convert them or
promise transactions spanning both profiles.

## Proposed first-profile bounds

| Resource | Proposed hard ceiling |
| --- | --- |
| Live keys per store | 2,048 |
| Key | 1–256 strict UTF-8 bytes, no NUL, exact spelling |
| One body | 4 MiB (4,194,304 bytes) |
| Aggregate referenced live bodies | 1 GiB (1,073,741,824 bytes) |
| Encoded record index | 384 KiB |
| Encoded authority table | 64 KiB, at most 256 retained grants |
| Manifest payload / integrity envelope | 512 KiB / 1 MiB |
| One complete enumeration reply | 2,048 entries and 512 KiB metadata |

The key ceiling permits the 1,024-plus workload; metadata or live-byte capacity
can bind first. These are proposed ceilings to qualify, not performance claims.
One body at its maximum must be supported; the aggregate ceiling does not
promise that every key can simultaneously contain 4 MiB. Counts, byte totals,
and version counters use explicitly checked integer widths and fail before
overflow. Limits never truncate a body, key, or result.

Bodies are opaque **strict UTF-8 byte arrays**, not NILData `Value` strings.
Enigma validates encoding but does not parse, normalize, reserialize, or inspect
application JSON. Byte equality includes line endings, whitespace, Unicode
spelling, and an empty body. A byte API can preserve U+0000; a text convenience
API must reject values it cannot represent losslessly. There is no implicit
repair or replacement-character decoding.

Key comparison is unsigned UTF-8 byte order without Unicode normalization or
case folding. Slashes, backslashes, dots, and wildcard characters are literal
key data. A key is never a filesystem pathname. All keys remain in one explicit
store scope; application actor policy can impose a narrower logical boundary.

The live-byte ceiling excludes obsolete and orphaned bodies. Those consume disk
until a future engine maintenance operation reclaims them. This first proposal
therefore makes no bounded-total-disk or indefinite-update claim. Deployment
needs explicit disk provisioning; storage exhaustion must follow the failure
contract below. A physical-byte admission/garbage-collection policy is an open
requirement before production qualification.

## Proposed typed calls

Every call takes a fresh host-established `access_context` through a client
bound to an owner, current incarnation, and explicit record grant. Bodies pass
directly as byte arrays, outside the current JSON worker/request envelopes.
The following names describe API intent; they are not executable Matrix syntax.

| Call | Request | Confirmed successful receipt |
| --- | --- | --- |
| `records.get` | `key`, `max_body_bytes` | `found`, exact `content`, `version`, `byte_length` |
| `records.put` | `key`, exact `content`, `expected_version` | new `version`, `byte_length` |
| `records.list_keys` | `max_keys`, `max_metadata_bytes`, `max_scan_keys` | complete ordered key/version/length entries, manifest generation |
| `records.close` | owner | closed owner; all aliases disabled |

Creation/opening use explicit record-profile factories. Opening does not create
a missing database, and a record factory rejects an evidence-profile store.
New-store creation also synchronizes the storage parent before its receipt,
as in the existing owner lifecycle. Trusted provisioning stays separate from
the application client.

`get` returns `code = ok, found = false, content = [], version = 0,
byte_length = 0` only for an absent key under current read authority. A stored
empty body returns `found = true`, empty content, and a positive version. An
existing body larger than the caller's or grant's byte ceiling returns `limit`
with no partial content. Corruption returns a storage failure, never absence.

`put` requires an explicit version precondition. `expected_version = 0` means
create only if absent. A positive value means replace only that exact current
version. There is no unconditional overwrite sentinel in the first API. A
conflict leaves the body and version unchanged and exposes no body through a
write-only grant. An authorized caller can issue `get` separately.

A successful put issues a new positive store-wide record sequence and assigns
it to that key. The sequence never decreases or reuses an identifier within a
checkpoint lineage, including replacement with byte-identical content. An
ordinary refusal issues no version. Zero remains exclusively absence. There is
no deletion API initially, avoiding an undefined delete/recreate version rule.
Restoring an older coherent store remains subject to Enigma's rollback limit.

`list_keys` pins one current manifest generation and returns every key once in
byte order, with versions and lengths but no bodies. It succeeds only when all
entries fit the requested and granted count, metadata-byte, and scan ceilings.
Otherwise it returns `limit` and no entries. It never returns an apparently
complete prefix. The store's index admission must ensure its full enumeration
fits the profile's maximum metadata reply. No cursor or historical list API is
needed for this bounded profile. A list followed by gets is not a multi-call
snapshot; returned versions let the application detect intervening changes.

Replies retain the current distinction between a confirmed domain outcome and
a lifecycle/storage failure with `outcome_unknown`. Confirmed `conflict`,
`capacity`, `limit`, `invalid`, or `denied` is not a successful put. Refusals
return empty content and zero record metadata. Denial happens before key lookup
or body access. No client automatically retries a put or re-admits a session.

## Coordination API names

The planned books are `enigma.records.session` and `enigma.records.client`,
with a typed companion under `ext/enigma-records`. The initial names are fixed
for adapter preparation; consumers must not substitute a fake implementation
or treat this document as evidence that their adapters compile yet.

| Book | Planned public name | Contract |
| --- | --- | --- |
| session | `create_record_database(directory, scope)` | Exclusive new store; `record_open_result`. |
| session | `open_record_database(directory, max_verify_bytes)` | Existing store only; full bounded verification and recovery before `record_open_result`. |
| session | `record_owner.close()` | `closed` or `lock_error`; all aliases disabled before release. |
| session | `record_owner.describe_limits()` | `record_limits` with key, body, live-byte, index, grant, and manifest ceilings. |
| client | `provision_record_host(owner, entity, session_id, actions, expires, limits, tick)` | Trusted-host admission; `record_reply<record_grant_receipt>`. |
| client | `connect_records(owner, grant_id)` | `record_client` pinned to the owner and incarnation. |
| client | `record_client.get(caller, key, max_body_bytes)` | `record_reply<record_get_receipt>`. |
| client | `record_client.put(caller, key, content, expected_version)` | `record_reply<record_put_receipt>`. |
| client | `record_client.list_keys(caller, max_keys, max_metadata_bytes, max_scan_keys)` | `record_reply<record_list_receipt>`. |
| client | `record_client.revoke(caller)` | Revoke the connected grant; `record_reply<record_grant_receipt>`. |
| client | `record_client.delegate(caller, entity, session_id, actions, expires, limits)` | Narrowed child; `record_reply<record_grant_receipt>`. |

`record_open_result` contains `code`, `outcome_unknown`, and `owner`. Only
`created` or `ready` returns an active owner. Other outcomes return an inactive
owner and release acquired locks. `record_reply<T>` contains `confirmed`,
`receipt`, and `failure`; `record_failure` contains `code` and `outcome_unknown`,
following the existing durable reply distinction. Confirmed replies have empty
failure metadata. Failed replies carry empty receipt data and the failure code.

The planned receipt fields are:

- `record_get_receipt`: `code`, `found`, `content`, `version`, `byte_length`.
  `content` is an exact byte array.
- `record_put_receipt`: `code`, `version`, `byte_length`.
- `record_list_receipt`: `code`, `complete`, `entries`, `generation`.
  `entries` is a `record_key_batch` exposing `count()` and checked `get(index)`;
  each `record_key_entry` contains `key`, `version`, and `byte_length`. Its
  backing columns follow supported primitive-array layouts.
- `record_grant_receipt`: `code`, `grant_id`.

`record_access_limits` contains `max_read_bytes`, `max_write_bytes`,
`max_scan_keys`, `max_list_keys`, and `max_list_metadata_bytes`. Record action
bits are read `1`, write `2`, list `4`, and delegate `8`, in the distinct record
authority profile. These do not reinterpret evidence grants. Every client call
requires a fresh `access_context`, including delegation and revocation.

A successful put's returned version is authoritative. Versions increase
store-wide, so applications must not assume a key's next version equals its
previous version plus one. Goetic's application revisions remain inside the
unchanged body and are separate from storage CAS versions.

## Authority has explicit byte ceilings

The existing evidence `work_limit` and `result_limit` count events and returned
items. They must not be reinterpreted as body bytes or silently enlarged to
permit 4 MiB reads. Record authority needs a versioned resource profile, proposed
as `enigma.records.v1`, with explicit named actions and ceilings:

- Actions: record read, write, list, and delegation; import/maintenance remains
  a separate trusted-host boundary.
- Byte ceilings: `max_read_bytes`, `max_write_bytes`, and
  `max_list_metadata_bytes` per call.
- Count ceilings: `max_scan_keys` and `max_list_keys` per call.

Use a new durable grant schema containing these fields and the existing exact
holder entity/session, audience, scope, expiry, parent, and revocation state.
Evidence grants cannot authorize record calls merely because a numeric bit or
identifier matches. Delegation must narrow every action and byte/count ceiling,
with live ancestor revocation and the same clock-floor checks. Recovery retires
record grants and their byte authority together; no saved byte allowance can
outlive its session grant. Provisioning remains a host-only operation.

Goetic's server would hold service authority and supply fresh verified service
context on each call in one synchronous NIL invocation. Goetic continues to
check its current actor policy before reaching this service boundary. Enigma
must not accept a user-supplied actor label as service admission. The first
record profile does not replace Goetic's actor policy or invent native
Anomalous admission. Same-process public fields remain outside an isolation
boundary, as in the current engine.

## Bodies precede one atomic manifest publication

A proposed layout has a private store directory, its existing kind of writer
lock, a canonical versioned manifest, and a private `objects/` directory.
Every body uses a fresh engine-generated opaque identifier, never a key-derived
path. The index records the key, current version, body identifier, exact byte
length, and SHA-256 digest. The digest detects corruption; it is not encryption,
authentication, or an anti-rollback mechanism. Bodies and manifests remain
plaintext. This retains the trusted storage-owner/ancestry and local POSIX
filesystem assumptions; it does not contain a hostile privileged host or
qualify hardware power-cut behavior.

For an authorized put, the engine would:

1. Prove current lock ownership and derive authority from the committed
   manifest. Check the version precondition and all row, byte, grant, metadata,
   integer, and encoded-envelope bounds before publishing anything.
2. Write the new body to a fresh immutable private file with no-clobber
   publication. Synchronize its contents and the objects directory. A successful
   body write alone does not make the record visible.
3. Build a complete successor manifest referencing that body and retaining
   evidence-independent authority, revocations, counters, and the clock floor.
   Prepare and validate the bound receipt before canonical publication.
4. Durably publish that manifest by private candidate write, file sync, atomic
   replacement, and database-directory sync. Only then adopt it and acknowledge
   the put. The old manifest remains the logical state until this publication.

Body publication must happen before manifest publication. A crash between them
can leave an unreferenced file, but no acknowledged manifest can name a body
that was merely buffered. A crash during manifest publication may leave the
previous or successor manifest; an unacknowledged put can therefore be present.
If manifest publication may have occurred, report `outcome_unknown = true`.
Any I/O/protocol failure poisons the owner and stops subsequent dispatch; a
known pre-publication domain refusal keeps the owner usable. Advancing the
permission clock during a refused call still requires a manifest commit before
a confirmed response, including reads and denials that change security state.

All public operations are synchronous within one owning NIL invocation. The
owner checks `file_lock_is_held` per dispatch, closes explicitly, refuses stale
aliases, and never continues from an uncertain cached manifest. No network
listener, concurrent writer, or cross-invocation handle is introduced.

## Fail-closed recovery and latest-only bodies

Opening reads only the canonical manifest and validates its complete shape,
identity, profile, index ordering/uniqueness, counters, byte totals, and grant
ancestry. It must validate every referenced body's private regular-file status,
length, strict UTF-8, and digest before returning an active owner. Verification
can process one bounded body at a time; it need not retain all content in RAM.
A caller-provided opening verification budget can refuse an oversized workload
before reading it, but cannot turn partial verification into `ready`. Startup
cost at the aggregate ceiling needs measurement before those limits qualify.

After verification, retire all loaded session grants, preserve issued counters,
retirement marks and clock floors, and durably publish a fresh incarnation
before ready. Missing, corrupt, unsafe, or mismatched canonical bodies block
opening. A current get that detects corruption also fails and poisons its owner.
There is no search for an older body, older manifest, backup, or orphan to make
a corrupt current record appear readable.

Only the current body is addressable. Old immutable bodies, including
unreferenced replacements and interrupted candidates, are maintenance material,
not application history or recovery candidates. Goetic keeps its aggregate
history inside the payload. A later garbage collector needs its own explicit
lock, durable reachability, deletion, sync, and failure contract; this proposal
does not claim safe reclamation from ordinary filesystem deletion.

## Initial import is private until the application switches

No immediate public multi-document transaction is required. Import can create a
wholly private record-store generation, load it through normal puts, validate
and read back every entry, verify the exact full inventory and totals, and
close its owner. None of those partial steps is application-visible.

Goetic then publishes its private generation selector atomically under its own
switch contract. Requests must see either the complete previous source or the
complete validated record store. It must quiesce writes or take a validated
stable source snapshot first. The selector must not point to an incomplete
store; canonical corruption must not silently select the previous generation.
An uncertain selector publication requires inspecting the canonical selector,
not blindly repeating import or falling back.

The import inventory distinguishes absent source records from present empty
bodies. Absent records stay absent/version zero; present empty bytes become a
stored record with a positive Enigma version. Preserve every present body's
exact bytes, including application history. Source application revisions inside
the body remain unchanged; new storage CAS versions belong to the new store,
so old storage-version handles must be discarded on cutover. Source snapshots
and backups remain outside Enigma and are not automatic recovery candidates.

The inventory ledger and universe aggregate could later benefit from a bounded
batch or resumable mutation plan. That requires a separate visibility and
precondition contract; independent puts must not be advertised as atomic across
those keys. The private-generation import does not require such an API now.

## Mechanisms and staged implementation

The development SDK used by current Enigma exposes bounded
`read_regular_bytes`, `write_bytes_durable`, private-directory creation and
inspection, `sync_directory`, byte-array SHA-256, and context-owned lock APIs.
These are useful mechanisms, not proof of a qualified 4 MiB record engine.
NILData remains for the small manifest and metadata; its 1 MiB value limit is
unchanged. The existing 64 KiB JSON request protocol cannot carry this body API.

Before implementation, qualify or add these missing consumer mechanisms:

- Strict UTF-8 validation and exact bounded byte/text conversion, including
  malformed encodings, embedded NUL, and native/VM behavior. Byte-at-a-time text
  assembly is not an assumed adequate 4 MiB path.
- Direct Matrix byte-array request/reply layouts and acceptable bounded memory
  and latency at 4 MiB; no hidden NILData conversion of a body.
- Manifest/index codec capacity, exact enumeration layout, checked integer
  widths, and the new durable grant resource schema on both routes.
- Body-file metadata inspection, bounded no-follow reads and digest checks,
  durable no-clobber body publication, and body-before-manifest fault ordering
  through an independent filesystem/process oracle.
- A complete matching SDK for the actual Goetic consumer. Its current source
  [`332b6f5`](https://github.com/exec-software/exec-nil-framework/commit/332b6f5fb3e5567e4c0d7b21b5778c5b245be3de)
  SDK lacks `file_lock_is_held`; current Enigma's older development SDK must not
  be assumed to contain Goetic's newer compiler fixes.
  Pin and test one source generation rather than selecting by version label.

General byte/runtime/filesystem gaps belong in isolated NIL contributions with
paired Ny/Matrix tests. Index policy, authority, versions, and record semantics
stay in Enigma. Do not add unsupported std names and proceed as if they exist.

Implementation should follow four reviewable stages: qualify the shared SDK and
byte path; implement the engine-owned manifest/body lifecycle and record grants;
expose and independently test typed get/put/enumeration on VM/native; then run
Goetic's exact validated import and generation switch against synthetic copies.
Acceptance includes empty versus absent, create-only and stale CAS, repeated
identical writes, 4 MiB boundaries, more than 1,024 keys, byte/count capacity,
complete enumeration, restart retirement and revocation, corrupt canonical
bodies, publication failures, and interrupted imports. Until that evidence
exists, this remains a proposal and the existing application-record store has
not been implemented.
