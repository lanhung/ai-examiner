# AI Examiner v0.8.0 Development Status

## Current state

- Version: `0.8.0.dev0`
- Branch: `develop/v0.8.0`
- Base candidate: `v0.7.0-rc.2`
- Release tag: not created
- Deployment status: local development only
- Alembic head: `20260723_0006`

v0.8 is being delivered as reviewable vertical slices. The first slice establishes
the safe, deterministic foundation of the Industry Template Platform without
changing stored sessions, database schemas, the current browser workflow or the
v0.7 text and realtime examination behavior.

## Increment A: contract and compiler foundation

Delivered:

- strict Pydantic source contract and generated JSON Schema Draft 2020-12;
- bounded YAML/JSON parser with alias, duplicate-key, depth, size and type guards;
- deterministic structural and semantic validation issue vocabulary;
- action, question, report, disclaimer, role, style and capability registries;
- deterministic compiler with canonical JSON and SHA-256 fingerprints;
- locked, bounded, selectable and one-way override validation;
- compiler output for planner, question selection, conversation, assessment,
  report, voice, safety, presentation and v0.7 compatibility;
- source-controlled `academic.thesis_defense` built-in template;
- read-only built-in catalog and health APIs;
- Wheel packaging of the built-in YAML resource;
- compatibility tests proving the template preserves v0.7 `SessionCreate` defaults.

Public endpoints added:

```text
GET /api/templates
GET /api/templates/health
```

The catalog deliberately exposes only reviewed metadata, capabilities, validation
versions and the compiled fingerprint. It does not expose the complete compiled
policy or any generated system instructions.

## Increment B: persistence and lifecycle

Delivered:

- additive SQLite/PostgreSQL-compatible migration `20260723_0006`;
- `ScenarioTemplate`, `ScenarioTemplateVersion`, `TemplateValidationRun` and
  `ProjectTemplateBinding` persistence models;
- unique semantic versions per template identity;
- idempotent startup seed for reviewed built-in versions;
- source and fingerprint drift detection for an existing built-in version;
- draft replacement, validation, compilation, clone and lifecycle APIs;
- explicit `draft -> candidate -> published -> deprecated` transition rules;
- passing validation, compiled artifact and behavioral evaluation gates before
  publication;
- local trust progression from `local_draft` through `local_published`;
- ORM update and delete guards for published and deprecated versions;
- SQLite `0005 -> 0006 -> 0005 -> 0006` migration regression preserving v0.7 data;
- PostgreSQL CI coverage for template persistence tests.

Authoring endpoints added:

```text
POST /api/templates
GET  /api/templates/{template_id}
GET  /api/template-versions/{version_id}
PUT  /api/template-versions/{version_id}
POST /api/template-versions/{version_id}/clone
POST /api/template-versions/{version_id}/validate
POST /api/template-versions/{version_id}/compile
POST /api/template-versions/{version_id}/status
```

## Verification

```text
Targeted template tests       25 passed
Targeted Ruff                 passed
Wheel built-in resource       packaged
Full pytest                   83 passed
Full Ruff                     passed
JavaScript syntax             passed
git diff --check              passed
Tracked-source secret scan    pending final staged-content gate
Alembic single head           20260723_0006
Alembic metadata drift check  no new upgrade operations
Docker Compose config         not run (Docker unavailable on this host)
```

Pytest exits successfully, but the Windows interpreter still prints the existing
async-generator cleanup `access violation` message after completing all tests.
There is no failed test, but this platform-specific shutdown noise remains a known
diagnostic issue.

## Held gates

The following work remains intentionally disabled or unimplemented:

- no public template import or export;
- no session binding or immutable runtime snapshot;
- no Planner, Policy Controller, Evaluator or Reporter behavior change;
- no database-backed catalog editor;
- local authoring is demoted to local trust states and cannot claim
  `built_in_reviewed`;
- no public marketplace, organization model or executable plugin;
- no merge to `main`, final `v0.8.0` tag or production deployment.

The current branch is suitable for contract review and local verification only.
It is not the completed v0.8 release.
