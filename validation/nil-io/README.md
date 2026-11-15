# NIL storage primitive consumer contract

This Matrix program exercises the reusable library mechanisms Enigma needs:
`write_bytes_durable`, `sync_directory`, context-owned advisory file locks,
`create_private_directory`, the private-entry metadata verdicts, and
`sha256_hex`. It serializes a real Enigma permission registry containing a
revoked grant, publishes it with NIL's durable primitive, reads and validates
it, and confirms that the grant remains denied. It then creates its own
owner-only database directory, republishes the payload inside it, and computes
the digest a checkpoint envelope would carry.

It then builds the whole checkpoint envelope in Matrix over that state,
confirms the payload round-trips, and confirms that a digest describing some
other payload is rejected and a truncated envelope fails to decode.

An independent host oracle verifies bytes, private file modes, the owner-only
directory mode, namespace contents, and released lock ownership. It recomputes
the digest with Python's `hashlib`, and compares the Matrix envelope against
the bytes `scripts/store.py` would write for the same payload, by importing
that host rather than restating its encoder. ENI-0003 makes byte-identical
envelopes the precondition for porting the host, so this is the check that
keeps a half-ported tree readable by either one.

Run with a matching development compiler, runtime, and standard library:

```sh
NIL_SDK=/absolute/path/to/matching/development-sdk ./scripts/test-nil-io.sh
```

`--target vm` or `--target native` selects one route. The normal Enigma suite
continues to support the previously selected SDK; this separate contract fails
clearly if the new declarations/provider are absent. The NIL changes live in
the framework's `codex/enigma-durable-io` branch (NIL-0028 and NIL-0029) and are
not an installed SDK release. Do not combine their declarations with an older
runtime.

This is a consumer conformance check, not a second production storage host.
It writes a raw Matrix state payload named `snapshot.json` in a fresh private
test directory. That file is not the `checkpoint.json` integrity envelope used
by the durable host. The current host still supplies the checkpoint
envelope format, commit orchestration, and the recovery path. Private-directory
setup, metadata checks, and integrity hashing now have qualified library
surfaces, but a qualified primitive is not a ported protocol: ordering,
acknowledgement, and fail-closed recovery are what ENI-0003 phases B through D
still have to move.
