# Enigma design seed

Status: proposed direction except for the bootstrap described below.

## Purpose

Build a database engine in Matrix whose operations are readable to people and
precise enough for agents to construct, inspect, and constrain. Enigma should
make data access authority explicit and keep sensitive data out of incidental
outputs. Novelty must come from useful behavior that can be demonstrated.

## What exists

The only executable behavior is help, version reporting, and argument rejection.
There is no database and no data-access security boundary yet. The module layout
leaves room for a parser, planner, policy layer, executor, and storage components;
those components have not been implemented or selected.

## Decisions for the seed

- Matrix is the implementation language; NILData configures the NIL project.
- Query syntax will draw from Matrix. Enigma queries remain a separate language
  with a separately specified grammar and semantics.
- Human tools and agent tools should share the same checked execution path.
- Database operations must eventually carry explicit identity and access scope.
- Security and correctness claims require evidence before they become guarantees.

## Candidate differentiators

These are ideas to evaluate, not a promised feature set:

- An inspectable operation plan showing requested access before execution.
- Agent delegation restricted by data scope, operation, purpose, and lifetime.
- Structured provenance and redacted audit events for human and agent activity.
- Bounded execution with explicit limits on work, output, and time.

An explanation or an agent's stated purpose is never itself authorization.
Enforcement must come from authenticated authority and checked policy.

## First milestones

1. **Language contract:** define an initial data model, a narrow query grammar,
   typed bindings, structured results, and error behavior. Add acceptance fixtures
   and parser limits before implementing the parser.
2. **In-memory vertical slice:** create a collection, insert a typed record, and
   read a projection through one checked execution path. Use synthetic data.
3. **Access boundary:** model identities and delegated authority; deny missing
   authority and test cross-scope access, invalid delegation, and redaction.
   Introduce no external access before this boundary is enforceable.
4. **Persistence and recovery:** specify file format, transactions, crash behavior,
   corruption handling, backup/restore, and migration. Prove the chosen guarantees
   through restart, fault, and recovery tests.
5. **Interfaces and evaluation:** add human and agent transports through the same
   access boundary. Measure workloads and compare results with reproducible baselines.

## Open decisions

Record model, query semantics, storage layout, concurrency model, transaction
isolation, index design, cryptographic dependencies, key lifecycle, deployment
model, and compatibility policy are all open. Do not infer those choices from
the Enigma name or from illustrative syntax.

See [query direction](query-language.md) and the [security model](../../SECURITY.md).
