# AI Examiner v0.8.0 Development Status

## Current state

- Version: `0.8.0.dev0`
- Branch: `develop/v0.8.0`
- Base candidate: `v0.7.0-rc.2`
- Release tag: not created
- Deployment status: local development only
- Alembic head: `20260723_0007`

v0.8 is being delivered as reviewable vertical slices. The current implementation
now carries one immutable template snapshot through planning, selection,
conversation authorization, assessment and report generation.

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

## Increment C: session binding and immutable replay snapshots

Delivered:

- immutable `academic.thesis_defense@1.1.0` compatibility version with declared
  bounded follow-up overrides while preserving published v1.0;
- deterministic template resolution precedence:
  explicit session version, project default binding, then legacy mode mapping;
- project binding read, replace and clear endpoints with compiled default-override
  validation;
- optional template version and override fields on text and realtime voice session
  creation;
- effective runtime settings derived from one compiler path for text and voice;
- immutable compiled snapshot, compiler version, accepted overrides and fingerprint
  on every newly mapped defense session;
- session inspection endpoint with stored-artifact fingerprint verification;
- Qwen voice safety clamps applied before compilation so the recorded snapshot
  matches runtime behavior;
- additive migration `20260723_0007` and downgrade refusal when bound sessions
  would lose historical policy;
- backward compatibility for old request bodies and unmapped teaching/interview
  modes.

Runtime endpoints added:

```text
GET    /api/projects/{project_id}/template-binding
PUT    /api/projects/{project_id}/template-binding
DELETE /api/projects/{project_id}/template-binding
GET    /api/sessions/{session_id}/template
```

## Increment D: template-guided planning and adaptive selection

Delivered:

- immutable `academic.thesis_defense@1.2.0` with the expanded assumption and
  critical-reflection taxonomy while retaining v1.0 and v1.1;
- optional template version, overrides and mode on blueprint generation;
- Planner input containing the compiled objectives, allowed question types,
  coverage requirements, difficulty bounds and question limit;
- objective IDs on every template-guided question;
- deterministic rejection of provider output outside the allowed type or
  difficulty bounds;
- deterministic question-limit enforcement;
- explicit `met` or `impossible` objective-coverage result in blueprint data;
- adaptive candidate filtering by the immutable session snapshot;
- required-objective coverage priority before ordinary gap/importance scoring;
- template fingerprint and effective selector constraints in adaptive decision
  audit records;
- compatibility for old blueprints without template objective metadata.

## Increment E: conversation and assistance policy

Delivered:

- one provider-neutral effective conversation policy for text, OpenAI Realtime and
  Qwen Realtime sessions;
- template action allowlist enforcement after deterministic policy selection;
- safe authorized fallbacks when a requested action is forbidden;
- per-decision audit of requested/effective action, allowed actions, fallback
  reason, assistance boundaries, answer disclosure and active interruption;
- template-controlled follow-up limit, hint availability and correction timing;
- explicit answer-disclosure prohibition in both realtime voice providers;
- proactive examiner interruption enabled only when the template declares it and
  the user opts in;
- learner barge-in remains independent and always available;
- `template-validator-v2` terminal-action validation and idempotent revalidation of
  existing built-in versions;
- `adaptive-v2`, `adaptive-template-v2`, `fixed-template-v1` and
  `conversation-policy-v1` audit identifiers.

## Increment F: template assessment and report integration

Delivered:

- a registered deterministic rubric for correctness, completeness,
  evidence/reasoning and boundary-awareness dimensions;
- exact weighted score recomputation from the immutable session snapshot;
- localized rubric anchors plus answer, point and document evidence on every
  dimension assessment;
- objective scores with weights and evidence linked to the blueprint's objective
  mappings;
- independent, report-separately and deterministic 70/30 blended assisted
  performance policies;
- weighted-total and `no_total` aggregate policies;
- registered report section builders and template-controlled section order;
- reviewed localized disclaimer registry and template identity/fingerprint in
  reports;
- browser rendering for template objective scores and score-free coaching reports;
- explicit tests proving voice timing, interruptions, emotion and interaction
  signals cannot affect correctness scores;
- `template-assessment-v1`, `assessment-report-v3` and
  `template-validator-v3` audit identifiers.

## Verification

```text
Targeted assessment tests     41 passed
Targeted Ruff                 passed
Wheel built-in resource       packaged
Full pytest                   104 passed
Full Ruff                     passed
JavaScript syntax             passed
git diff --check              passed
Tracked-source secret scan    no key patterns found
Alembic single head           20260723_0007
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
- no database-backed catalog editor;
- local authoring is demoted to local trust states and cannot claim
  `built_in_reviewed`;
- no public marketplace, organization model or executable plugin;
- no merge to `main`, final `v0.8.0` tag or production deployment.

The current branch is suitable for contract review and local verification only.
It is not the completed v0.8 release.
