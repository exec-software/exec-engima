# ENI-0002: Durable state and fail-closed recovery

Status: implementation contract for the persistence slice.

## Boundary

The evidence and permission engines, checkpoint codec, semantic validation, and
recovery transitions remain Matrix. The installed NIL runtime has atomic file
publication but lacks parent-directory synchronization and file locking. Its
ordinary stream flush is not a durability barrier. A narrow Python POSIX host
therefore supplies filesystem durability and serialization of callers. This is
an embedded trusted-host interface, not an authentication service or a network
protocol. The existing direct `enigma.client` remains explicitly volatile.

The host invokes a separate Matrix worker to stage each operation against the
last committed state. A worker reply is a candidate, never a durable receipt.
There are no live clients retaining an earlier authority object across commits.
Only the host publishes receipts after committing the candidate checkpoint.

## Checkpoint and commit

One canonical `checkpoint.json` contains a versioned envelope, a UTF-8 JSON
payload produced by Matrix, and a SHA-256 digest of that exact payload. The digest
detects accidental corruption; it is not a signature, encryption, or rollback
protection. JSON interchange uses the checked NILData implementation; arbitrary
data is never concatenated into JSON syntax.

The payload contains schema, database identity, current incarnation, generation,
scope, event history, complete permission registry including parent ancestry and
revocation flags, nonreused ID counters implicit in retained rows, and clock floor.
The Matrix decoder validates exact shapes, types, limits, withdrawal semantics,
and grant attenuation before exposing any state. There is no partial recovery of
evidence without matching authority state.

The host holds one exclusive nonblocking advisory lock for the full session. It
uses a private owner-controlled directory, regular private files, and no-follow
opens. For every candidate, in the same directory:

1. Create a fresh private staging file and write all envelope bytes.
2. Synchronize the staging file.
3. Atomically replace the canonical checkpoint.
4. Synchronize the database directory.
5. Adopt the candidate and publish its receipt.

Initial creation additionally synchronizes the parent directory. Creation is
explicit and exclusive; opening an existing store never silently initializes it.
Every accepted staged dispatch is committed, including reads and denied calls,
because authorization can advance the clock floor. An I/O or worker failure
terminates the session without a success receipt. No later request may continue
using uncertain authority in that process.

## Recovery and authority

Recovery reads only the canonical checkpoint. A missing, malformed, truncated,
checksum-invalid, or semantically invalid checkpoint fails closed. There is no
automatic fallback to an earlier snapshot: an older valid file may predate an
acknowledged revocation. Orphaned staging files are never recovery candidates.

Before `ready`, the Matrix recovery transition retires **all** loaded grants,
preserving their definitions, IDs, ancestry, and existing revocation history.
It retains the clock floor and evidence history, installs a fresh host-generated
incarnation, and advances the checkpoint generation. The host durably commits
that transition before serving another operation.

An admitted session is transient authority; its disk representation does not
authenticate a caller after restart. The trusted host must re-admit callers and
explicitly provision new grants. Old grant rows are never recycled. Requests
also bind the current incarnation; a saved old-incarnation request gets a fixed
denial before its body is interpreted. Grant issuance and re-admission remain
trusted host responsibilities, following the Anomalous separation in ENI-0001.

The retained registry still has a 256-grant ceiling. Repeated recovery and
re-admission can exhaust it. Exhaustion fails closed; compaction must not reuse
old authority identifiers and is not implemented in this slice.

## Failures and limits of the guarantee

After process termination during a commit, storage may contain the complete
previous checkpoint or the complete candidate. An unacknowledged effect can
therefore be present after recovery; callers must inspect state rather than
blindly retrying. No success receipt precedes synchronization. Corruption of the
canonical file blocks recovery instead of restoring possibly obsolete grants.

These guarantees assume a local POSIX filesystem and storage stack honoring
`fsync`, atomic rename, and advisory locks, plus a trusted owner of the storage
directory and its ancestry. Filesystem or device lies, privileged replacement,
host compromise, and uncooperative writers are outside this boundary. Tests
exercise real process restarts, faults, and interrupted commit phases; they do
not establish hardware power-cut qualification or universal filesystem support.

Restoring an older coherent checkpoint is not detectable without separately
trusted monotonic state. Retiring recovered grants and installing a new random
incarnation prevents replay of saved session authority under this recovery path;
it does not prove the evidence history is the latest one or implement general
anti-rollback protection. Key management, encryption, native Anomalous admission,
durable replay/idempotency ledgers, backups, and migrations remain future work.
