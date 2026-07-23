# v0.8 Increment B Persistence and Lifecycle Results

## Scope

Increment B persists the deterministic template artifacts from Increment A and
implements an explicit local authoring lifecycle. It does not bind templates to
exam sessions.

## Storage contract

Alembic head `20260723_0006` adds:

```text
ScenarioTemplate
ScenarioTemplateVersion
TemplateValidationRun
ProjectTemplateBinding
```

All tables are additive. Existing v0.7 tables and columns are unchanged.

## Lifecycle contract

```text
draft
  -> candidate
  -> published
  -> deprecated
```

`candidate -> draft` is the only reverse authoring transition. Publication
requires:

1. the latest validation run passed;
2. a deterministic compiled artifact and fingerprint exist;
3. an explicit behavioral-evaluation summary reports `status=passed`;
4. the evaluation includes at least one fixture.

Local source trust progresses through `local_draft`, `local_candidate` and
`local_published`. Public input cannot claim `built_in_reviewed`.

Published and deprecated versions reject content updates, invalid status changes
and deletion through ORM guards. API mutation endpoints reject them before flush.

## Built-in seed behavior

Startup seeds `academic.thesis_defense@1.0.0` exactly once. Repeated seeding does
not create another identity, version or validation row.

If source-controlled content or the compiler fingerprint changes without a semantic
version bump, startup raises an error instead of rewriting the published artifact.

## Verification

```text
targeted v0.8 tests                  25 passed
full pytest                          83 passed
ruff                                 passed
JavaScript syntax                    passed
git diff --check                     passed
SQLite 0005 -> 0006                  passed
SQLite 0006 -> 0005                  passed
SQLite 0005 -> 0006 re-upgrade       passed
v0.7 project row preservation        passed
Alembic single head                   20260723_0006
Alembic metadata drift check          no new upgrade operations
PostgreSQL template persistence      configured in CI
Docker Compose config                not run; Docker unavailable on this host
```

The Windows interpreter still emits the existing asynchronous cleanup
`access violation` text after pytest reports success and returns exit code zero.

## Held gates

- project binding is stored but not yet exposed as runtime behavior;
- exam and voice sessions do not yet store immutable template snapshots;
- Planner, Policy Controller, Evaluator and Reporter still use v0.7 inputs;
- only the thesis-defense compatibility template is seeded;
- no import, export, editor or public marketplace is enabled;
- no final v0.8 tag or stable deployment is authorized.

Increment C should implement WP-05 session binding and snapshot replay while
preserving every legacy request body.
