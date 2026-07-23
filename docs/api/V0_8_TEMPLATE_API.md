# v0.8 Scenario Template API

## 1. Conventions

Implementation status on `develop/v0.8.0`:

- catalog, identity/version reads, create, replace, clone, validate, compile and
  lifecycle status endpoints are implemented;
- project binding and session snapshots are implemented;
- semantic template diff, bounded import and source-only export are implemented;
- preview remains planned;
- this API is development-only until the v0.8 release gates pass.

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
  "validator_version": "template-validator-v3",
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

Returns a deterministic recursive semantic diff. Changes carry JSON Pointer paths
and are grouped under template metadata, capabilities, objectives, questioning,
assistance, conversation, assessment, reporting, safety, presentation, voice,
compatibility and override policy. Secret or rendered prompt content is not
returned.

### `GET /api/template-versions/{version_id}/export?format=yaml`

Exports canonical template source only as UTF-8 YAML or JSON. Response headers
identify the immutable source fingerprint and `template-export-v1` contract.
Export excludes compiled internal prompt text, documents, learner memory,
credentials and application state.

### `POST /api/templates/import`

Accepts bounded YAML or JSON and always creates a new local identity and initial
version. The server ignores any ownership, lifecycle or trust claim in the
document and assigns:

```text
owner_scope = local
status = draft
trust_level = local_draft
```

Import never publishes or activates a template. Optional `target_slug` and
`semantic_version` fields allow the caller to choose a non-conflicting local
identity without changing the imported behavior.

## 4.1 Authoring authorization seam

Template mutation endpoints use a shared authoring-context dependency. In v0.8 it
identifies a local operator and reports:

```json
{
  "scope": "local_template_authoring",
  "authorization_enforced": false
}
```

This is an explicit integration seam, not production authentication. v0.9 must
replace it with authenticated actor, organization and role checks before enabling
multi-user authoring.

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

Returns the active project default and its validated default overrides. A `DELETE`
request clears the active default without deleting its history.

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

The response includes the immutable version and fingerprint:

```json
{
  "id": "session-uuid",
  "template_version_id": "uuid",
  "template_fingerprint": "sha256:...",
  "config": {
    "template_resolution_source": "explicit | project_default | legacy"
  }
}
```

Voice-session creation accepts the same template fields. The text and voice paths
must compile to the same effective policy fingerprint for equivalent inputs.

## 6.1 Blueprint planning

`POST /api/projects/{project_id}/blueprints` accepts optional `mode`,
`template_version_id` and `template_overrides` fields in addition to
`document_id` and `profile`.

When a template resolves, the Planner receives the compiled objectives, allowed
question types, objective coverage, difficulty bounds and question limit. The
blueprint response includes:

```json
{
  "template_plan": {
    "template_version_id": "uuid",
    "semantic_version": "1.2.0",
    "fingerprint": "sha256:...",
    "resolution_source": "explicit | project_default | legacy",
    "objectives": ["contribution", "methodology"],
    "allowed_question_types": ["evidence", "method"],
    "difficulty": {"minimum": 1, "maximum": 5},
    "question_limit": 6,
    "coverage": {
      "status": "met | impossible",
      "counts": {},
      "unmet": []
    }
  }
}
```

Every template-guided question contains `objective_ids`. Output with an undeclared
question type or out-of-bounds difficulty is rejected rather than silently
entering a session.

## 6.2 Effective conversation policy

Text and voice session responses include a safe `conversation_policy` in their
runtime configuration:

```json
{
  "policy_version": "conversation-policy-v1",
  "allowed_actions": ["ASK_FOLLOWUP", "GIVE_HINT", "MOVE_ON", "END"],
  "max_followups_per_question": 2,
  "hints": {"allowed": true, "maximum_per_question": 1},
  "corrections": {
    "allowed": true,
    "timing": "after_independent_attempt"
  },
  "answer_disclosure": {"allowed": false},
  "active_interruption": {
    "declared_enabled": false,
    "enabled": false,
    "level": "off",
    "user_can_disable": true
  }
}
```

The effective policy may tighten but never weaken the compiled template. Proactive
examiner interruption requires both template permission and user opt-in. Learner
barge-in, which stops examiner audio, is a separate safety and usability behavior.

Every text policy decision returns `policy_audit` containing requested and
effective actions, the allowlist and any deterministic fallback reason. Realtime
providers receive the same assistance, disclosure and interruption boundaries in
trusted server-side instructions.

## 7. Session and report inspection

### `GET /api/sessions/{session_id}/template`

Returns immutable effective snapshot metadata, accepted overrides and a structured
view of the compiled policy. It verifies the snapshot fingerprint against the
stored compiler and template schema metadata; it does not recompile current source.

### Existing report endpoint

For template-bound sessions, `GET /api/sessions/{session_id}/report` returns
`assessment-report-v3` and adds:

```json
{
  "template": {
    "slug": "academic.thesis_defense",
    "version": "1.2.0",
    "title": "论文答辩训练",
    "fingerprint": "sha256:..."
  },
  "score_policy": {
    "assisted_performance": "report_separately",
    "aggregate": "weighted_dimensions",
    "overall_basis": "objective_weighted",
    "blend_weights": null
  },
  "overall_score": 3.84,
  "computed_overall_score": 3.84,
  "show_total_score": true,
  "objective_scores": [
    {
      "id": "methodology",
      "title": "方法理解",
      "weight": 0.25,
      "score": 3.7,
      "evidence_count": 2,
      "evidence": []
    }
  ],
  "dimension_scores": [
    {
      "id": "correctness",
      "title": "正确性",
      "weight": 0.35,
      "score": 4.1,
      "evidence_count": 3,
      "evidence": []
    }
  ],
  "section_order": ["summary", "objective_scores", "dimension_scores", "evidence"],
  "sections": [
    {"id": "summary", "data": {}},
    {"id": "objective_scores", "data": []}
  ],
  "disclaimer_id": "practice_not_formal_decision",
  "disclaimer": "本报告仅用于训练和辅助判断..."
}
```

Every dimension assessment stored on an answer includes the effective weight,
normalized score, display-scale score, localized rubric anchors, answer quote,
point-level evidence identifiers and material evidence references. The report
recomputes totals deterministically from those stored values.

`assessment.aggregate = no_total` or `report.show_total_score = false` produces
`overall_score = null`, `show_total_score = false` and `risk_level = not_scored`.
The report remains valid and still includes objective, dimension and evidence
sections selected by the template.

The assessment runtime only consumes answer-analysis fields registered for the
dimension. Speech duration, pauses, interruption count, response latency,
interaction preferences, inferred emotion and other voice signals cannot alter
correctness scores.

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
