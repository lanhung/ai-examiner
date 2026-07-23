# v0.8 Scenario Template API

## 1. Conventions

- Base path: `/api`
- IDs are UUID strings.
- Template semantic versions are immutable after publication.
- All dynamic responses use `Cache-Control: no-store`.
- Validation failures return stable issue codes and JSON Pointer paths.
- Existing v0.7 session requests remain accepted without a template identifier.

## 2. Template catalog

### `GET /api/templates`

Query parameters:

```text
category        optional
status          active | deprecated
trust_level     optional
language        optional
include_drafts  false by default
```

Returns template identities and their latest eligible version. It does not return
full compiled policy by default.

### `GET /api/templates/{template_id}`

Returns identity metadata and version summaries.

### `GET /api/template-versions/{version_id}`

Returns source, lifecycle, validation summary and fingerprint. Secrets, session data
and internal rendered system prompts are never included.

## 3. Authoring lifecycle

### `POST /api/templates`

Creates a local template and initial draft.

```json
{
  "slug": "local.research_update_review",
  "category": "academic",
  "semantic_version": "0.1.0",
  "source": {
    "schema_version": "1.0",
    "template": {},
    "capabilities": {},
    "objectives": [],
    "question_policy": {},
    "assistance_policy": {},
    "conversation_policy": {},
    "assessment_policy": {},
    "report_policy": {},
    "safety_policy": {},
    "overrides": {}
  }
}
```

Response: `201 Created` with template and draft version IDs.

### `POST /api/template-versions/{version_id}/clone`

Creates a mutable draft from any readable version.

```json
{
  "semantic_version": "0.2.0"
}
```

### `PUT /api/template-versions/{version_id}`

Replaces source content for a `draft` only. Candidate, published and deprecated
versions reject mutation with `409 TEMPLATE_VERSION_IMMUTABLE`.

### `POST /api/template-versions/{version_id}/validate`

Runs structural, semantic and capability validation.

```json
{
  "status": "failed",
  "validator_version": "template-validator-v1",
  "issues": [
    {
      "code": "DIMENSION_WEIGHTS_INVALID",
      "severity": "error",
      "path": "/assessment_policy/dimensions",
      "message": "Dimension weights must sum to 1.0"
    }
  ]
}
```

### `POST /api/template-versions/{version_id}/compile`

Compiles a valid draft or candidate and returns the normalized contract,
`compiler_version` and fingerprint. Compilation has no publication side effect.

### `POST /api/template-versions/{version_id}/status`

```json
{
  "status": "candidate"
}
```

Allowed transitions:

```text
draft -> candidate
candidate -> draft
candidate -> published
published -> deprecated
```

Publishing requires a passing validation run and required behavioral-evaluation
metadata. Published source and compiled content are immutable.

## 4. Preview, comparison and portability

### `POST /api/template-versions/{version_id}/preview`

```json
{
  "language": "zh-CN",
  "overrides": {
    "question_limit": 8,
    "voice": "disabled"
  },
  "fixture": "partial_answer"
}
```

Returns effective settings, rejected overrides, sample question plan, expected
policy action, score behavior and report outline. Preview never creates a real exam
session or learner-memory event.

### `GET /api/template-versions/{left_id}/diff/{right_id}`

Returns semantic differences grouped by objectives, policies, rubric, report, safety
and overrides. Secret or rendered prompt content is not returned.

### `GET /api/template-versions/{version_id}/export?format=yaml`

Exports canonical template source and metadata. Export excludes compiled internal
prompt text and application state.

### `POST /api/templates/import`

Accepts bounded YAML or JSON and always creates a `local_draft`. Import never
publishes or activates a template.

## 5. Project binding

### `PUT /api/projects/{project_id}/template-binding`

```json
{
  "template_version_id": "uuid",
  "default_overrides": {
    "question_limit": 8
  }
}
```

Only a published, non-deprecated version can become the default for new sessions.
Changing the binding does not alter existing sessions.

### `GET /api/projects/{project_id}/template-binding`

Returns the active project default, effective override preview and compatibility
warnings.

## 6. Session creation

The existing `POST /api/sessions` request gains optional fields:

```json
{
  "project_id": "uuid",
  "blueprint_id": "uuid",
  "template_version_id": "uuid",
  "template_overrides": {
    "question_limit": 8,
    "difficulty_initial": 3
  },
  "profile": "qwen:qwen-plus",
  "learner_subject_key": "optional"
}
```

If `template_version_id` is absent, the server uses the project binding or legacy
mode mapping. A supplied template and a contradictory legacy mode return
`422 TEMPLATE_MODE_CONFLICT`.

The response includes:

```json
{
  "id": "session-uuid",
  "template": {
    "template_id": "uuid",
    "version_id": "uuid",
    "slug": "academic.thesis_defense",
    "semantic_version": "1.0.0",
    "fingerprint": "sha256:...",
    "compiler_version": "template-compiler-v1"
  },
  "effective_settings": {},
  "override_audit": []
}
```

Voice-session creation accepts the same template fields. The text and voice paths
must compile to the same effective policy fingerprint for equivalent inputs.

## 7. Session and report inspection

### `GET /api/sessions/{session_id}/template`

Returns the immutable effective snapshot metadata and a safe structured view of the
compiled policy. It does not reload current template content.

### Existing report endpoint

`GET /api/sessions/{session_id}/report` adds:

```json
{
  "template": {
    "slug": "academic.thesis_defense",
    "semantic_version": "1.0.0",
    "fingerprint": "sha256:..."
  },
  "objective_scores": [],
  "required_disclaimer_ids": ["practice_not_formal_decision"]
}
```

## 8. Evaluation endpoints

### `POST /api/template-versions/{version_id}/evaluations`

Runs deterministic fixtures by default. Paid model evaluation requires an explicit
profile and remains asynchronous.

```json
{
  "suite": "template-contract-v1",
  "profiles": [],
  "asynchronous": true
}
```

### `GET /api/template-evaluations/{evaluation_id}`

Returns schema, compiler, behavior, safety, compatibility and quality metrics with
dataset, model, prompt, policy and compiler versions.

## 9. Stable error codes

```text
TEMPLATE_NOT_FOUND
TEMPLATE_VERSION_NOT_FOUND
TEMPLATE_VERSION_IMMUTABLE
TEMPLATE_VERSION_CONFLICT
TEMPLATE_SCHEMA_UNSUPPORTED
TEMPLATE_STRUCTURAL_INVALID
TEMPLATE_SEMANTIC_INVALID
TEMPLATE_CAPABILITY_UNAVAILABLE
TEMPLATE_PUBLISH_GATE_FAILED
TEMPLATE_OVERRIDE_LOCKED
TEMPLATE_OVERRIDE_OUT_OF_RANGE
TEMPLATE_MODE_CONFLICT
TEMPLATE_IMPORT_TOO_LARGE
TEMPLATE_IMPORT_UNSAFE
```

Errors use the existing API envelope and never include raw provider responses,
compiled system prompts, keys or user documents.

## 10. Compatibility contract

- Existing v0.7 clients can continue creating text and voice sessions with `mode`.
- Existing session rows remain readable with `template_version_id = null`.
- Legacy behavior is represented by deterministic built-in compatibility snapshots.
- No endpoint automatically rewrites old sessions or reports.
- Removal of legacy mode input is deferred beyond v0.8 and requires usage telemetry.
