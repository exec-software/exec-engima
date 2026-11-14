# Working on Enigma

Enigma is a new database-engine seed written in Matrix. The repository spelling
is `exec-engima`; the product is Enigma. Read `README.md`, `docs/development.md`,
`docs/design/README.md`, and `SECURITY.md` before extending the engine.

- Implement engine behavior in Matrix under `src/enigma/` with `.matrix` files.
- Use `nil.project.nildata`; do not add a legacy JSON manifest by default.
- Consult the public NIL Matrix guide for supported syntax. Do not invent
  Matrix APIs or treat proposed Enigma syntax as executable Matrix.
- Run `./scripts/test.sh`; it enables `NIL_STRICT_BOUNDS=1` on VM and native
  routes. `./scripts/test.sh --target vm` is available when native is unavailable.
- Keep Matrix tests beside their implementation and reachable through imports.
- Document semantic and security decisions with the relevant change. Distinguish
  implemented guarantees from planned capabilities.
- Do not add a network listener, load production data, or introduce crypto or
  persistence claims without implementing and testing the necessary contracts.
- Keep generated output, SDKs, secrets, and local databases untracked. Use
  synthetic data in tests and examples.
- Do not modify sibling projects or the parent workspace to make this project
  build. Select a complete SDK through `NIL_SDK` when needed.
