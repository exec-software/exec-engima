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

This is a separate project rather than part of `src/` because it needs NIL-0028
through NIL-0030, which no installed SDK has. Keeping it out of `src/enigma/`
lets `./scripts/test.sh` keep running on the previously selected SDK. Build and
exercise it with a matching development SDK:

```sh
NIL_SDK=/absolute/path/to/matching/development-sdk ./scripts/test-matrix-host.sh
```

That script runs the black-box session contract against this host on both
routes, runs it again against `scripts/store.py`, and checks that either host
can serve a database the other created.

## What the collapse changed

The host/worker split was a language boundary, not an isolation boundary, and
it is gone: staging calls `stage_request` in process instead of spawning a
worker. The request envelope is still serialized and re-parsed on the way in,
deliberately, so the worker's strict validation stays exactly as qualified
rather than gaining a second, looser entry point.

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

What keeps `store.py` in place is not missing evidence but the SDK. This host
needs NIL-0028 through NIL-0030 and a native `random.hex`, so making it the
default would leave `./scripts/test.sh` unrunnable without a development build.

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
