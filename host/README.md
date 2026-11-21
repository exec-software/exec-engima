# The Matrix durable host

`enigma-durable-host` is the Matrix implementation of the persistence host
ENI-0002 described and [ENI-0003](../docs/design/ENI-0003-matrix-durable-host.md)
decided to port. It presents the same command surface as `scripts/store.py`:

```sh
enigma-durable-host init <directory> --scope <scope>
enigma-durable-host serve <directory>
```

`--target` is accepted and ignored. It selected a worker route for the Python
host; staging is in process now.

This is a separate project because its filesystem and stream dependencies
include NIL-0028 through NIL-0030. Those surfaces still need release-SDK
qualification. The engine's native discovery API also needs the optional-text
field compiler fix pinned in the [development guide](../docs/development.md).
Build and exercise this host with a matching development SDK:

```sh
NIL_SDK=/absolute/path/to/matching/development-sdk ./scripts/test-matrix-host.sh
```

That script runs this host's own Matrix checks, the black-box session contract
against it on both routes, the storage-fault contract, the same two contracts
against `scripts/store.py`, and a check that either host can serve a database
the other created.

Candidate validation and payload identity are tested in Matrix, in the
`enigma.host.candidate` suite beside the code they exercise, because that logic
moved here when the worker process went away. What stays in Python is the
external-oracle layer: real restarts and `SIGKILL`, lock contention, injected
storage faults, and byte-identity against the other encoder. A program cannot
witness its own death, and it cannot be the only witness to whether its bytes
reached the disk. [ENI-0003](../docs/design/ENI-0003-matrix-durable-host.md)
records the full division.

## What the collapse changed

The host/worker split was a language boundary, not an isolation boundary, and
it is gone: staging calls `stage_request_typed` in process instead of spawning a
worker. The request envelope is still serialized and re-parsed on the way in,
deliberately, so the worker's strict validation stays exactly as qualified
rather than gaining a second, looser entry point.

The reply stays typed so a checkpoint and full discovery result do not need to
fit together inside one NILData value. Candidate validation is unchanged; the
external worker encodes the same bounded JSON packet from checked component
fragments. [ENI-0006](../docs/design/ENI-0006-bounded-evidence-discovery.md)
defines this framing boundary.

A fresh worker process per dispatch used to make retained authority
structurally impossible. In one process that becomes a code invariant, so every
dispatch re-derives its identity from the committed payload, and
`check_candidate` keeps every check the Python host performed on a worker
reply. Those checks are the only remaining verification that a staged candidate
is a legitimate successor to committed state, and they run before publication.

## Status

`scripts/store.py` remains the qualified persistence path. This host satisfies
the same session contract — recovery, incarnation rotation, fail-closed
corruption handling, single-writer refusal, clock-floor persistence, and
survival of `SIGKILL` mid-session — and the same storage-fault contract, where
a commit that cannot be published is never acknowledged, an unsafe or
multiply-linked checkpoint is refused, a rewritten payload fails its digest,
and an oversized request ends the session rather than being truncated into a
different one. Both contracts run against both hosts, because a scenario only
one host satisfies describes that host rather than the contract.

`store.py` remains the default while the filesystem/runtime additions await
release-SDK qualification and the host cutover remains separate. Native
discovery now also requires a newer compiler, so the current SDK dependency is
explicit rather than inferred from the unchanged version string.

Four scenarios still need a seam inside a host and are not claimed here: a
partial write followed by success, a crash at a chosen commit phase, a worker
reply that violates its protocol, and this host's response to NIL-0028's
uncertain publication. A seam was deliberately not added — a production host
with a fault switch is no longer the thing under test.

## One difference worth knowing

The Python host opens the database directory once and performs every later
operation relative to that descriptor, so a swapped directory cannot redirect
it mid-session. NIL's file operations are path-based with no-follow on the
final component only, and place parent-directory containment outside their
contract. ENI-0002 already assumes a trusted owner of the storage directory and
its ancestry, so this is not a regression against the stated guarantee, but it
is weaker than what `store.py` actually does. A directory-relative surface
would close it.
