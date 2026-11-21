# Persistent stores

The POSIX host makes the bounded Matrix engine persistent. Use this path for
durable receipts over the host protocol; the direct `enigma.client` API remains
an in-memory API. Matrix applications can also use the importable
[durable application package](applications.md).
The host and request stream are trusted embedding interfaces. Supplying an
entity/session in JSON does not authenticate it.

## Build, initialize, and open

From the repository root with a complete NIL SDK selected:

```sh
./scripts/build-storage.sh --target all
mkdir -p data
python3 scripts/store.py init data/example --scope work --target vm
python3 scripts/store.py serve data/example --target vm
```

`init` requires a new directory and an existing parent. It never overwrites an
existing directory. `serve` requires an existing valid checkpoint and lock file;
missing state is an error. Select `--target native` to run the native Matrix
worker. The host does not build tools implicitly. Python 3 and POSIX directory,
locking, synchronization, and rename primitives are required.

Initialization returns a `created` JSON receipt. Each `serve` holds the writer
lock and first commits recovery, then emits a `ready` receipt with database ID,
current `instance`, and generation. Every subsequent request is one JSON line
on standard input; each response is one JSON line on standard output. EOF closes
the session. Errors go to standard error with a nonzero exit status. Keep the
database directory and its ancestry under trusted control.

## A trusted-host session

This short fixture opens the initialized store, provisions an agent, records
evidence, then revokes its grant. Real embedding code must establish the caller
from authenticated host admission and supply fresh logical time per dispatch.

```python
import json
import subprocess
import sys

host = subprocess.Popen(
    [sys.executable, "scripts/store.py", "serve", "data/example"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
)
ready = json.loads(host.stdout.readline())
assert ready["code"] == "ready"

def request(**body):
    body["instance"] = ready["instance"]
    host.stdin.write(json.dumps(body) + "\n")
    host.stdin.flush()
    return json.loads(host.stdout.readline())

grant = request(op="install", entity="demo:agent", session=1, operations=7,
                expires=1000, work_limit=128, result_limit=128, tick=1)
assert grant["code"] == "ok"
caller = dict(entity="demo:agent", session=1, audience="enigma", tick=1)
claim = dict(subject="release:sample", relation="ready", object_value="yes")
print(request(op="support", caller=caller, grant_id=grant["grant_id"],
              claim=claim, source="synthetic:passing-check", expected_revision=-1))
print(request(op="discover", caller=caller, grant_id=grant["grant_id"],
              pattern=dict(subject="release:sample", relation=None, object_value=None),
              as_of=-1, max_work=128, max_evidence=16))
print(request(op="revoke", caller=caller, grant_id=grant["grant_id"]))
host.stdin.close()
assert host.wait() == 0
```

The fixed tick in the fixture represents one synthetic logical instant. An old
client snapshot is not a live clock or authority after recovery. On every open,
all loaded grants are retired before `ready`. Retained permission definitions,
ancestry, and revocation flags remain together during a session. Recovery
reclaims the retired rows, preserving a retirement high-water mark, the
nonreused grant-ID counter, and the clock floor; new authenticated sessions need
explicit new grants. A retired ID stays refused, and is never reissued within
the checkpoint lineage. Recovery never automatically compacts evidence.

## Request fields

Every request has `op` and the current `instance`. Unknown or missing fields are
rejected. All operations except trusted-host `install` include `caller`, with
exact fields `entity`, `session`, `audience` (`enigma`), and `tick`.

| Operation | Additional fields |
| --- | --- |
| `install` | `entity`, `session`, `operations`, `expires`, `work_limit`, `result_limit`, `tick`; trusted host provisioning only. |
| `delegate` | `parent_id`, new holder `entity` and `session`, `operations`, `expires`, `work_limit`, `result_limit`. |
| `revoke` | `grant_id`; the exact holder retires that grant and its descendants. |
| `support`, `oppose` | `grant_id`, `claim`, `source`, `expected_revision`. |
| `withdraw` | `grant_id`, `evidence_id`, `expected_revision`. |
| `compact` | `grant_id`; explicit scope-wide history reclamation. |
| `resolve` | `grant_id`, `claim`, `as_of`, `max_work`, `max_evidence`. |
| `inspect` | `grant_id`, `evidence_id`, `as_of`. |
| `discover` | `grant_id`, `pattern`, `as_of`, `max_work`, `max_evidence`. |

`claim` has exact text fields `subject`, `relation`, `object_value`. Rights are
resolve/inspect/discover `1`, assert `2`, withdraw-own `4`, delegate `8`, and compact `16`,
combined as a bitmask. Existing masks `1` through `15` gain no maintenance
authority. The single store's scope is supplied by the host, not by request data.
Revision `-1` requests latest or disables a write precondition; `0` remains a
real empty snapshot. Successful domain receipts carry their revision/evidence
metadata. Failure receipts keep incarnation/generation empty or zero. Treat
`denied`, `invalid`, `conflict`, `limit`, `capacity`, and `not_found` as distinct
outcomes. Only a stale-incarnation denial leaves the checkpoint unchanged;
accepted stages, including domain denials, commit security state before reply.

## Bounded evidence discovery

`pattern` requires exactly `subject`, `relation`, and `object_value`. Each is
either `null` for any value or a nonempty string of at most 256 NIL text units
for an exact match. A string such as `"*"` matches that literal value; it is
not an operator. All-null selects all active reports in the authorized scope.

A successful receipt returns `items` (full evidence records), `revision`,
`retained_from`, `inspected`, `matched`, `complete`, and `evidence_complete`.
Items are active at the selected revision, newest evidence ID first, and
retain source, actor/session, and polarity. Multiple reports for one proposition
remain separate. Discovery does not decide which report is true.

Work counts eligible retained events, including withdrawals and nonmatches.
The output cap can truncate items while a scan finishes: `complete` may be
true with `evidence_complete` false. When the scan is incomplete, `matched`
is only a lower bound, and an empty list does not prove absence. Both budgets
must fit the grant: work ranges from 1 through 1,024 and output from 1 through
128. Revision `0` stays exactly
empty; a nonzero revision below the retention horizon is incomplete. There is
no continuation cursor in this slice.

Current read authority (`1`) is checked before pattern validation and evidence
access. Expired, revoked, wrong-session, and retired grants cannot discover
history. Like other accepted read stages, discovery commits the logical clock
floor before its receipt. See [ENI-0006](design/ENI-0006-bounded-evidence-discovery.md).

## Explicit evidence retention

`compact` reclaims each withdrawn assertion together with its withdrawal event,
including pairs belonging to other holders in the same scope. It requires the
separate compact right `16`; the ability to withdraw one's own evidence does
not grant permission to discard the scope's historical explanations. The
operation checks the grant's work ceiling and never reclaims an unwithdrawn
assertion. It runs only when requested, never on restart.

The receipt contains `revision`, `reclaimed` (an event count), and
`retained_from` (the history horizon). Compaction leaves the revision unchanged
and never renumbers an event or reuses an evidence ID. A historical `resolve`
with `0 < as_of < retained_from` reports `incomplete` rather than a confident
answer from a history it cannot reconstruct. Revision `0` remains exactly
empty, and a fully scanned view at or above the horizon remains exact.
`inspect` returns `not_found` for a reclaimed assertion. Reclaimed history
cannot be recovered from this store.

The payload schema is `enigma.state.v3`. Earlier schemas are rejected rather
than silently migrated; no migration or backup/restore facility exists yet.

## Recovery and failures

The authoritative file is `checkpoint.json`. Its versioned SHA-256 envelope
protects the exact Matrix payload against accidental corruption. Semantic
validation also checks event history and grant ancestry. Data is plaintext;
owner-only modes are not encryption or protection against a privileged host.

Each commit writes a new private file, synchronizes it, atomically replaces the
checkpoint, and synchronizes the directory before returning the receipt. Initial
creation also synchronizes the parent. Reads and denials commit too, because
they can advance permission time. A failed or uncertain commit terminates the
session; do not continue using stale in-memory authority.

A torn, corrupt, or missing primary blocks opening. Older backups and orphaned
staging files are never selected automatically. Interrupted operations may have
committed without a receipt; inspect the recovered state before retrying.
Requests are limited to 64 KiB per line, Matrix payloads to 512 KiB under NIL's
text-length operation, and checkpoint envelopes to 1 MiB. The prototype holds
1,024 retained events and 256 retained grant rows. Assertions stop at 1,023
retained events to reserve one withdrawal slot. Durable admission separately
bounds the encoded event array at 384 KiB (382 KiB for assertion admission)
and the encoded grant array at 64 KiB. Large or escape-heavy records can reach
byte capacity before the row ceiling. A confirmed `capacity` reply discards
the attempted evidence/grant mutation while committing its observed security
clock floor and the next generation; it does not poison the session.

Explicit evidence compaction can reclaim withdrawn pairs; recovery reclaims
retired grant rows. Compaction is still required to free event slots and does
not happen automatically. Read work can cover 1,024 events, but every evidence
list is capped at 128. Identifiers are never recycled within the checkpoint
lineage. See [ENI-0008](design/ENI-0008-bounded-capacity.md).

See [ENI-0002](design/ENI-0002-durable-state-and-recovery.md) and
[SECURITY.md](../SECURITY.md) for exact filesystem assumptions, recovery retirement,
and the limits of rollback protection. Native Anomalous admission, encryption,
backup/restore, migrations, and hardware power-cut qualification remain future
work.
