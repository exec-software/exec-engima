# Contributing

Enigma is in early engine development. Read [the design](docs/design/README.md),
[development guide](docs/development.md), and [security policy](SECURITY.md) first.

Write engine code and its unit tests in Matrix. Keep toolchain glue small and
portable. Use public, synthetic fixtures and avoid adding generated programs,
SDKs, credentials, or local data to the repository.

For a change that establishes query semantics, storage behavior, or an access
boundary, describe the contract and relevant failure cases in `docs/design/`
with the implementation. Label unimplemented behavior as proposed. Prefer a
small working vertical slice over broad APIs with placeholder behavior.

Run:

```sh
./scripts/test.sh
```

This checks analyzer warnings, Matrix tests, builds, and the CLI contract on VM
and native routes with strict runtime bounds checking. If a target cannot run
on your host, identify the SDK and exact target you checked; do not claim both.
Add behavior tests for meaningful changes to parsing, policy, storage, recovery,
and interfaces. No performance or security guarantee should be asserted without
the evidence that supports it.

Keep changes scoped and explain the resulting behavior and validation in the
pull request. Follow [SECURITY.md](SECURITY.md) when reporting vulnerabilities.
