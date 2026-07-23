# v0.8 Increment H Verification

## Scope

Increment H completes WP-10 template portability and comparison without expanding
the current single-user deployment into a public marketplace.

## Security properties

- YAML/JSON documents use the existing bounded parser.
- YAML aliases, custom tags, unsupported objects and oversized input fail before
  persistence.
- Imported metadata cannot claim built-in ownership, publication or reviewed
  trust.
- Export serializes template source only.
- Export cannot include user documents, learner memory, rendered system prompts,
  provider payloads, credentials or runtime state.
- Dynamic API responses remain `Cache-Control: no-store`.

## Determinism properties

- Exported JSON uses stable key ordering.
- Semantic diff recursively compares typed source documents.
- Every difference has a JSON Pointer path and old/new values.
- Differences are grouped by behavioral policy section.
- Repeating the same diff produces byte-equivalent JSON data.

## Authorization boundary

Mutation routes now consume a common authoring context. v0.8 deliberately reports
that authorization is not enforced because the supported deployment remains a
single-user local evaluation environment. This dependency is the replacement point
for v0.9 identity, organization membership and RBAC checks.

## Automated coverage

`tests/test_template_transfer_v08.py` verifies:

1. source-only JSON export and safe re-import;
2. YAML export contract;
3. unsafe and oversized import rejection;
4. deterministic policy-grouped semantic diff;
5. stable not-found and invalid-format responses;
6. forced local draft ownership and trust;
7. dynamic `no-store` response headers.

The final full-suite, packaging, migration and secret-scan results are recorded in
`PROJECT_STATUS.md` after the Increment H release gate runs.

## Final gate

```text
Targeted template tests       30 passed
Full pytest                   114 passed
Ruff                          passed
JavaScript syntax             passed
git diff --check              passed
Alembic head                  20260723_0007
Alembic metadata drift        none
Wheel build                   passed
Tracked-source secret scan    no key patterns found
```

Pytest returns exit code zero after all assertions. The Windows host still prints
the previously documented AnyIO/Proactor shutdown access-violation diagnostic.
