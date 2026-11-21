# Enigma client for Matrix

An in-process companion library above the Enigma engine. It lives in `ext/`,
outside `nil.std`, so it can become a separately distributed package later.
The current namespace is `enigma.client`; there is no package-manager integration
or stable release compatibility promise yet.

## Why this surface

Agents should not have to synthesize query strings to record and investigate
evidence. The client accepts typed propositions and returns typed receipts,
resolution state, completeness, and evidence IDs. Supporting and opposing
evidence coexist; neither silently overwrites the other.

Use `describe_surface with nothing` to discover protocol `enigma.evidence.v1`,
the operation list, current hard limits, and this embedded client's lack of
persistence. This describes the protocol, not the permissions held by a particular grant. Text
limits use the engine's Matrix text-length operation. Each call returns a fresh
description, including a fresh operation array.

| Operation | Meaning |
| --- | --- |
| `support` | Record attributable support for a proposition. |
| `oppose` | Record attributable opposition to the same proposition. |
| `resolve` | Inspect visible evidence at an explicit revision and work/output budgets. |
| `inspect` | Retrieve one evidence item at an explicit revision. |
| `withdraw` | Withdraw evidence through the engine's ownership and revision checks. |
| `compact` | Explicitly reclaim retracted evidence across the scope under separate maintenance authority. |
| `discover` | Find active evidence and provenance using exact-or-any proposition selectors. |

The client forwards exact revision and budget arguments. It does not retry
writes, silently increase limits, choose a truth winner, or turn a partial
answer into a complete one. `minus 1` requests the latest revision or disables
a write revision precondition; `0` remains the real empty historical snapshot.

`compact with nothing` returns a typed `compaction_receipt` with `code`,
`revision`, the number of events `reclaimed`, and the `retained_from` history
horizon. It preserves unwithdrawn assertions and issued identifiers. A resolve
at a nonzero revision below that horizon reports `incomplete`; revision `0`
stays exact. A reclaimed assertion is `not_found` through `inspect`.

Compaction permanently gives up historical explanations. It requires the
separate scope-wide maintenance right `16`; withdraw-own right `4` grants no
compaction authority. Existing masks such as `7` (read, assert, withdraw-own)
keep their previous authority. A host can explicitly install `23` to include
compaction in that mask, subject to the same context, revocation, scope, and
work-limit checks. Delegation can only retain rights already held by the parent.

## Discover evidence without knowing the whole proposition

`discover` uses the existing read right `1`. The typed `evidence_pattern` has
three `Option of text` selectors: `Option.None` accepts any value, while
`Option.Some` matches exact nonempty text of at most 256 units. Characters such
as `*` and `?` are literal data. This is not a wildcard or query-string language.

```matrix
read everything from nil.std.core.option
read evidence_pattern from enigma.discovery

value related is build evidence_pattern with subject being Option.None,
    relation being (Option.Some holding "depends-on"), object_value being Option.None
value found is adapter.discover with pattern being related, as_of being minus 1,
    max_work being 128, max_evidence being 16
```

The result carries active evidence `items` in descending evidence-ID order,
including their proposition, polarity, source, and acting entity/session. Two
items can concern the same proposition or disagree; discovery does not choose a
truth winner or return a resolved proposition verdict. Use `resolve` for the
evidence state of a selected proposition.

`items` is a bounded `evidence_batch`. Its `count with nothing` gives the number
of returned reports; `get with index being index` returns `Option of evidence_item`,
with `None` for an index outside the batch. Each retrieved record is a copy.
The durable JSON receipt represents the same reports as an `items` array.

```matrix
repeat for index from 0 to (found.items.count with nothing)
    consider found.items.get with index being index
        when Option.Some holding report then say report.subject
        when Option.None then say "No report at this index."
    end consider
end repeat
```

`revision` pins the requested snapshot. `inspected` meters scanned events,
including withdrawals and nonmatches. `matched` counts observed matching active
reports; it is only a lower bound if `complete` is false. `evidence_complete`
also becomes false when `max_evidence` truncates the returned items, even when
the scan itself completed. Both budgets remain subject to the grant's limits.

Revision `0` stays exactly empty. History below the reported `retained_from`
horizon remains incomplete after compaction, and every call rechecks current
authority even for a historical revision. Denied or invalid results expose no
evidence or snapshot metadata. This first bounded operation has no continuation
cursor; callers must not treat a truncated list as exhaustive.

## Host setup and trust

The embedding host opens an engine and authority registry, installs fixture or
application grants, establishes an access context, and calls `connect`. The
client copies context fields at connection time and keeps the live authority
registry shared so later revocation remains effective. The client defines no
grant-installation method; the underlying registry remains host-only.

Contexts are snapshots. For each synchronous dispatch, the trusted host must
establish the current identity/session and current monotonic tick, then call
`connect` again with that fresh context. Reconnecting does not mint or extend a
grant. Do not treat a client holding a fixed old tick as a live clock. Copying
the context prevents accidental alias mutation; it does not authenticate its
contents or establish clock freshness. The example deliberately uses one fixed
tick in a short synthetic fixture.

This is an API for trusted embedding code, not isolation against hostile code
in the process. Matrix class fields are currently public. The host is responsible
for authenticated identity, a trustworthy clock, grant provisioning, and protecting
handles. This direct client supplies no network authentication, encryption, or
persistent commits.
See the root [security policy](../../SECURITY.md).

## Relationship to durable storage

This direct client remains volatile: `supports_persistence` is deliberately
`false`, and its method returns are not durable acknowledgements. The separate
[POSIX storage host](../../docs/persistence.md) invokes the Matrix operation
worker and publishes receipts only after checkpoint synchronization. It retains
permission and revocation state along with evidence.

On opening a durable store, recovery retires all prior session grants and commits
a fresh incarnation before `ready`. Old contexts and numeric grant IDs do not
re-admit a caller; the trusted host must establish a current session and install
new authority explicitly. The embedded client does not automatically attach to,
recover, or commit a durable store. A transport-aware durable client can be added
as a separate package surface later.

## Run the example and tests

From the repository root, select a complete NIL SDK:

```sh
export NIL_SDK=/absolute/path/to/exec-nil-framework/sdk
export NIL_STRICT_BOUNDS=1
"$NIL_SDK/nilbuild" run --project ext/enigma-client/nil.project.nildata --sdk "$NIL_SDK"
"$NIL_SDK/nilbuild" test --project ext/enigma-client/nil.project.nildata --sdk "$NIL_SDK" --target all
```

The example uses synthetic data and explicitly installed host fixture grants.
It demonstrates contradiction, a historical snapshot after withdrawal, and a
bounded incomplete query, and checks discovery of active evidence without an
exact proposition. Process exit discards all data.

For direct imports, add `ext/enigma-client/src` and the engine's `src` directory
to your project's `includePaths`. The client depends on the engine's public
Matrix books; it is not copied into the framework's core standard library.
