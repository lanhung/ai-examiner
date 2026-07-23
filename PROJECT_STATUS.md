# AI Examiner v0.8.0 Development Status

## Current state

- Version: `0.8.0.dev0`
- Branch: `develop/v0.8.0`
- Base candidate: `v0.7.0-rc.2`
- Release tag: not created
- Deployment status: local development only
- Alembic head: `20260721_0005` (unchanged)

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

## Verification

```text
Targeted template tests       18 passed
Targeted Ruff                 passed
Wheel built-in resource       packaged
Full pytest                   76 passed
Full Ruff                     passed
JavaScript syntax             passed
git diff --check              passed
Tracked-source secret scan    passed
Docker Compose config         not run (Docker unavailable on this host)
```

Pytest exits successfully, but the Windows interpreter still prints the existing
async-generator cleanup `access violation` message after completing all tests.
There is no failed test, but this platform-specific shutdown noise remains a known
diagnostic issue.

## Held gates

The following work remains intentionally disabled or unimplemented:

- no template persistence, lifecycle migration or public import;
- no session binding or immutable runtime snapshot;
- no Planner, Policy Controller, Evaluator or Reporter behavior change;
- no database-backed catalog editor;
- no external template may claim `built_in_reviewed` trust;
- no public marketplace, organization model or executable plugin;
- no merge to `main`, final `v0.8.0` tag or production deployment.

The current branch is suitable for contract review and local verification only.
It is not the completed v0.8 release.
