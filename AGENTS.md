# Working on Enigma

Enigma is a new database-engine seed written in Matrix. Read `README.md`,
`docs/development.md`, `docs/design/README.md`,
`docs/design/ENI-0001-evidence-and-authority.md`,
`docs/design/ENI-0002-durable-state-and-recovery.md`,
`docs/design/ENI-0003-matrix-durable-host.md`,
`docs/design/ENI-0004-authority-capacity.md`, and `SECURITY.md` before
extending the engine.

- Implement engine behavior in Matrix under `src/enigma/` with `.matrix` files.
- Use `nil.project.nildata`; do not add a legacy JSON manifest by default.
- Consult the public NIL Matrix guide for supported syntax. Do not invent
  Matrix APIs or treat proposed Enigma syntax as executable Matrix.
- Run `./scripts/test.sh`; it enables `NIL_STRICT_BOUNDS=1` on VM and native
  routes. `./scripts/test.sh --target vm` is available when native is unavailable.
- Keep Matrix tests beside their implementation and reachable through imports.
- The companion library belongs under `ext/enigma-client/`, outside `nil.std`.
- Preserve Anomalous's separation of identity, admitted session, and scoped
  authority. Caller text never creates authority. This model trusts its host;
  public Matrix fields are not an isolation boundary. Hosts must supply fresh
  context and logical time per dispatch, and discard handles on replacement.
- Treat evidence states as evidence, not truth. Budget exhaustion is incomplete;
  historical reads require current authority and revision zero stays empty.
- Document semantic and security decisions with the relevant change. Distinguish
  implemented guarantees from planned capabilities.
- Do not add a network listener, load production data, or introduce crypto or
  persistence claims without implementing and testing the necessary contracts.
- Keep generated output, SDKs, secrets, and local databases untracked. Use
  synthetic data in tests and examples.
- General library gaps should feed back into NIL. Make framework changes in an
  isolated NIL branch with paired Ny/Matrix runtime checks; keep database policy
  in Enigma and preserve unrelated sibling/parent work. Select matching tools
  and library sources through `NIL_SDK` when qualifying a new runtime.
- Durable calls go through `scripts/store.py` and the separate Matrix storage
  worker. The existing embedded client remains volatile. Never acknowledge a
  durable operation before file fsync, atomic publication, and directory fsync.
- Recovery must retire loaded session grants and commit the fresh incarnation
  before ready. Missing or invalid primary state never bootstraps or falls back.
- Preserve authority counters, revocation history, and clock floors together
  with evidence. Reads and denials can change security state and need commits.
