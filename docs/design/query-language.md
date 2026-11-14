# Query language direction

Status: illustrative design sketch. No parser or query executor exists.

Enigma should borrow Matrix's explicit types, word operators, named inputs,
and visible block boundaries. It should define a small database grammar instead
of accepting arbitrary Matrix programs as queries.

For discussion, a read could look like:

```text
read from documents
    where owner-id equals parameter owner-id
    select id, title
    limit 20
end read
```

This is proposed Enigma syntax, not executable Matrix. Collection names, field
names, keywords, parameter notation, and result types are not yet standardized.
The first parser milestone must replace this sketch with a grammar and fixtures.

## Intended contract

- Bind typed values separately from query text. A bound value cannot introduce
  keywords, identifiers, or extra operations.
- Resolve names against a schema. Dynamic identifiers need their own explicit,
  checked mechanism if introduced.
- Authenticate the request context outside query text. A query cannot grant
  itself privileges or change its identity.
- Validate the complete operation before effects; reject unknown or ambiguous
  constructs with structured errors and source locations.
- Define null/missing values, equality, ordering, limits, and mutation atomicity
  before they appear in an implementation.
- Specify parser and execution resource limits and whether each result is
  complete, limited, or interrupted. Do not silently truncate results.

Human-readable syntax and machine-readable requests should resolve to the same
checked operation representation. A future transport can carry typed bindings,
request IDs, and result metadata without relying on natural-language inference.

## First acceptance cases

Start with one collection, scalar fields, an equality filter, explicit projection,
and a row limit. Cover malformed and oversized input, unknown fields, binding
type mismatches, query text inside a parameter, and unauthorized data scope.
Mutation, joins, vector retrieval, and user-defined execution remain separate
decisions.
