# NIL storage primitive consumer contract

This Matrix program exercises the reusable library mechanisms Enigma needs:
`write_bytes_durable`, `sync_directory`, and context-owned advisory file locks.
It serializes a real Enigma permission registry containing a revoked grant,
publishes it with NIL's durable primitive, reads and validates it, and confirms
that the grant remains denied. An independent host oracle verifies bytes,
private modes, namespace contents, and released lock ownership.

Run with a matching development compiler, runtime, and standard library:

```sh
NIL_SDK=/absolute/path/to/matching/development-sdk ./scripts/test-nil-io.sh
```

`--target vm` or `--target native` selects one route. The normal Enigma suite
continues to support the previously selected SDK; this separate contract fails
clearly if the new declarations/provider are absent. The NIL change lives in
the framework's `codex/enigma-durable-io` branch and is not an installed SDK
release. Do not combine its declarations with an older runtime.

This is a consumer conformance check, not a second production storage host.
It writes a raw Matrix state payload named `snapshot.json` in a fresh private
test directory. That file is not the `checkpoint.json` integrity envelope used
by the durable host. The current host still supplies private-directory setup,
metadata checks, integrity hashing, and orchestration. Port those responsibilities
only after the corresponding library surfaces and full recovery path are
qualified; a successful filesystem primitive alone does not port the protocol.
