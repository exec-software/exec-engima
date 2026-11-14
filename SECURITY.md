# Security

## Current state

Enigma is a bootstrap executable. It has no database, network service,
authentication, authorization, encryption, or persistence. No version is
qualified to hold sensitive or production data. Security capabilities below
are requirements for future work, not implemented protections.

## Intended boundaries

- **Identity and authority:** give human and agent requests attributable
  identities. Require explicit scoped authority, deny absent authority, and
  bound delegation by scope and lifetime. Treat a requested purpose as input,
  never proof of permission.
- **Input and execution:** treat queries, bindings, schema names, stored content,
  and agent-generated requests as untrusted. Use typed bindings and checked
  plans; bound parsing, execution, output, and concurrency.
- **Data separation:** enforce access at the execution boundary, including
  metadata, errors, exports, backups, and future search/index paths. Test access
  across identities and data scopes.
- **Cryptography and keys:** choose maintained cryptographic components and an
  explicit key-management model before claiming protection at rest or in transit.
  Design rotation, revocation, recovery, and backup behavior together. Do not
  invent cryptographic algorithms.
- **Audit and diagnostics:** make operations attributable while excluding raw
  secrets and unnecessary record content from logs, errors, and telemetry.
  Audit integrity, retention, and access controls need their own design.
- **Recovery:** specify integrity checks, transaction and crash semantics,
  corruption behavior, and restore verification before claiming durability.

An administrator or compromised host can cross application-level boundaries.
The future threat model must document host trust, key access, side channels,
availability, and the limits of revocation after data has been returned.

## Reporting an issue

Do not include credentials, private records, or an exploitable security report
in a public issue. Use the repository's **Security → Report a vulnerability**
option when available. If private reporting is unavailable, open a public issue
requesting a private contact, without vulnerability details or sensitive data.

Only synthetic data belongs in public examples and reproductions. Supported
versions and response commitments will be documented when a release process
exists.
