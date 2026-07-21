# v0.7 Long-term Learner Intelligence Architecture

## 1. Objective

v0.7 turns session-level cognitive evidence into controlled longitudinal
intelligence. It must help answer:

- what has been directly observed about this learner;
- what may have decayed since the last observation;
- which concept should be retested and why;
- how performance changes across sessions and projects;
- which interaction preferences the learner has approved;
- what persistent memory exists and how to remove it.

The release is successful only if it improves retest and growth decisions without
creating opaque or permanent labels.

## 2. Current baseline and gaps

The current cognitive path is:

```text
Answer turn
  -> Analyzer
  -> Evaluator
  -> KnowledgeEvidenceEvent
  -> KnowledgeState aggregate
  -> AdaptiveQuestionSelector
```

Existing strengths:

- assessment evidence is append-only and tied to exact turns;
- state is rebuildable;
- pseudonymous `LearnerSubject` supports repeated sessions in one project;
- misconception and assistance evidence are retained;
- fixed and adaptive policies can be compared.

Remaining gaps:

- `LearnerSubject` is project-scoped and cannot represent an optional global learner;
- `KnowledgeUnit.code` is not a canonical cross-project concept identifier;
- historical aggregation does not model elapsed time or retention uncertainty;
- no due-date or priority model exists for reassessment;
- preferences have no evidence, confirmation or expiry lifecycle;
- no unified inspect, export, correction, disable and deletion workflow exists;
- current aggregate confidence can grow without a recency penalty.

## 3. Scope boundary

### Included

- optional opaque cross-project learner identity;
- canonical concept registry and reviewed mappings;
- time-aware learner-concept state;
- growth series and regression signals;
- shadow-mode retest planning;
- explicit and confirmed interaction preferences;
- memory center, export, correction and deletion;
- deterministic replay and algorithm version comparison;
- SQLite implementation that remains PostgreSQL-compatible.

### Excluded

- login, SSO, organizations and role-based access control;
- clinical, personality, emotion or employability profiles;
- unrestricted episodic chat memory;
- training a proprietary memory model;
- automatic high-stakes decisions;
- replacing v0.5 evidence events or v0.6 assessment authority;
- mandatory PostgreSQL deployment.

## 4. System architecture

```text
Session Analyzer / Evaluator
        |
        v
KnowledgeEvidenceEvent (existing source evidence)
        |
        +---------------------> Session KnowledgeState (existing)
        |
        v
Concept Mapping Gate <---- Canonical Concept Registry
        |
        v
Learner Memory Event Ledger
        |
        +--> Longitudinal State Builder
        |       -> observed mastery
        |       -> predicted retention
        |       -> confidence and stability
        |       -> growth series
        |
        +--> Retest Planner (shadow first)
        |       -> due concepts
        |       -> priority and reason
        |       -> candidate questions
        |
        +--> Preference Policy Gate
        |       -> explicit/confirmed preferences
        |       -> expiry and contradiction handling
        |
        v
Memory Center / Export / Correction / Deletion
```

LLMs may propose concept mappings and preference candidates. They do not calculate
retention, authorize persistence or select an active retest without deterministic
validation.

## 5. Identity model

### 5.1 LearnerIdentity

An optional opaque identity links project-scoped subjects:

```text
LearnerIdentity
  id: UUID
  opaque_key_hash: string, unique
  display_name: optional
  memory_enabled: boolean
  memory_scope: project_only | linked_projects
  retention_policy_version: string
  created_at
  disabled_at: optional
```

`opaque_key_hash` is derived from an external opaque reference with an application
secret. Email, phone and provider tokens are not required.

### 5.2 LearnerIdentityLink

```text
LearnerIdentityLink
  learner_identity_id
  learner_subject_id: optional for identity-level control events
  status: proposed | confirmed | revoked
  provenance: explicit | imported | admin_test
  created_at
  revoked_at: optional
```

Links must be explicit in v0.7. Automatic identity matching is forbidden.

### 5.3 Compatibility

Sessions without a global identity continue to work exactly as v0.6. Cross-project
memory is disabled unless a confirmed link and enabled policy both exist.

## 6. Canonical concept model

### 6.1 Concept

```text
Concept
  id: UUID
  namespace: string
  canonical_key: string
  title: string
  description: optional
  language: string
  status: active | merged | deprecated
  version: integer
```

The unique key is `(namespace, canonical_key)`. Namespaces prevent accidental
merging across unrelated domains.

### 6.2 KnowledgeUnitConceptMap

```text
KnowledgeUnitConceptMap
  knowledge_unit_id
  concept_id
  relation: exact | narrower | broader | related
  confidence: 0..1
  status: proposed | accepted | rejected
  source: rule | model | human
  evidence_json
  model_profile: optional
  prompt_version: optional
  created_at
  reviewed_at: optional
```

Only accepted `exact` and `narrower` mappings may update long-term mastery. A broad
or ambiguous mapping may inform search but not aggregate scores.

### 6.3 Mapping gate

The gate requires:

- namespace agreement;
- semantic and prerequisite compatibility;
- supporting source text or rubric points;
- confidence at or above a configurable threshold;
- abstention when the top candidates are too close;
- review for merges that affect an existing learner history.

## 7. Memory event ledger

`LearnerMemoryEvent` supplements rather than replaces `KnowledgeEvidenceEvent`:

```text
LearnerMemoryEvent
  id: UUID
  learner_identity_id: optional
  learner_subject_id
  concept_id: optional
  source_evidence_event_id: optional
  event_type
  payload_json
  occurred_at
  recorded_at
  policy_version
  algorithm_version
  supersedes_event_id: optional
  deleted_at: optional
```

Event types are the categories accepted by ADR-004. An idempotency key prevents a
source evidence event from being imported twice.

Corrections append a superseding event. User-requested deletion is different: it
hard-deletes affected source and derived rows after creating a minimal job-level
audit record that contains no deleted content.

## 8. Longitudinal learner-concept state

`LearnerConceptState` is a rebuildable cache:

```text
learner_identity_id or learner_subject_id
concept_id
observed_mastery
observed_confidence
last_observed_at
predicted_retention
prediction_confidence
stability_days
difficulty_estimate
evidence_count
independent_evidence_count
assisted_evidence_count
active_misconceptions_json
next_retest_at
algorithm_version
rebuilt_at
```

### 8.1 Separate observations from predictions

- `observed_mastery` is the weighted result at the last valid observation.
- `predicted_retention` estimates recall now, given elapsed time.
- `prediction_confidence` decreases when evidence is sparse, old or contradictory.
- the UI must label predictions as estimates and show the last observation date.

### 8.2 Initial research baselines

v0.7 evaluates at least three deterministic strategies:

```text
no_decay              carry the last observation forward
fixed_half_life       conservative configurable decay
evidence_half_life    half-life updated from repeated independent outcomes
```

FSRS and trainable half-life regression are research references, not hard-coded
production truth. The schema keeps stability, difficulty and algorithm version so a
validated implementation can be substituted later.

### 8.3 Evidence weighting

Long-term state must distinguish:

- main-question independent evidence;
- follow-up evidence;
- hinted or corrected evidence;
- synthetic, imported or human-reviewed evidence;
- contradictions and self-corrections.

Assisted performance may show learning gain but cannot be presented as independent
retention.

## 9. Retest planning

`RetestPlan` and `RetestItem` persist auditable recommendations:

```text
RetestPlan
  learner identity or subject
  horizon_start / horizon_end
  status: shadow | proposed | accepted | completed | cancelled
  policy_version

RetestItem
  concept_id
  due_at
  priority
  reason_code
  predicted_retention
  uncertainty
  source_state_version
  selected_question_id: optional
  outcome_event_id: optional
```

Initial priority is deterministic:

```text
priority
  = retention_gap
  + uncertainty_weight
  + misconception_weight
  + importance_weight
  + overdue_weight
  - recent_repetition_penalty
  - assistance_only_penalty
```

Hard constraints:

- do not retest an accepted mastered concept too frequently;
- prioritize unresolved misconceptions over cosmetic score improvement;
- do not schedule from an unaccepted concept mapping;
- respect session time and prerequisite order;
- avoid exact question repeats when alternatives exist;
- expose the reason to the user.

All v0.7 retest decisions begin in `shadow` status. Active scheduling requires the
evaluation gates to pass.

## 10. Preference memory

Allowed preference keys are registry-defined, for example:

```text
response_language
explanation_style: concise | example_first | step_by_step
interruption_level
thinking_pause_tolerance
hint_policy
preferred_session_length_minutes
```

Each `LearnerPreference` contains:

```text
value
source: explicit | confirmed | inferred
confidence
supporting_event_ids
status: proposed | active | rejected | expired
confirmed_at
expires_at
policy_version
```

Rules:

- explicit settings activate immediately;
- one behavioral observation can only create a proposal;
- inferred proposals require repeated consistent evidence and user confirmation;
- contradictions lower confidence or expire the proposal;
- sensitive traits and personality descriptors are outside the registry;
- preferences affect interaction, never assessment score.

## 11. Agent responsibilities

### Memory Candidate Extractor

Proposes schema-bound misconception, concept-mapping or preference candidates. It
cannot write durable state.

### Concept Mapping Agent

Ranks canonical concepts and supplies evidence. It must support abstention.

### Memory Policy Gate

Deterministically checks category, consent, source evidence, confidence, scope,
expiry and idempotency.

### Retention Engine

Pure, versioned calculations from approved evidence. No LLM call.

### Retest Planner

Pure candidate ranking and constraints. An LLM may phrase a new question only after
the concept and action are selected.

### Memory Narrator

Explains growth, uncertainty and recommendations. It reads state but cannot change
it or invent evidence.

## 12. API surface

Detailed contracts belong in `docs/api/V0_7_LONG_TERM_MEMORY_API.md`. The planned
surface is:

```text
POST   /api/learner-identities
POST   /api/learner-identities/{id}/links
GET    /api/learner-identities/{id}/memory
PATCH  /api/learner-identities/{id}/memory-settings
GET    /api/learner-identities/{id}/growth
GET    /api/learner-identities/{id}/retest-plans
POST   /api/learner-identities/{id}/retest-plans
GET    /api/learner-identities/{id}/preferences
PATCH  /api/learner-identities/{id}/preferences/{preference_id}
POST   /api/learner-identities/{id}/memory/rebuild
POST   /api/learner-identities/{id}/memory/export
DELETE /api/learner-identities/{id}/memory
```

Until authentication exists, these endpoints are evaluation-only and must not be
exposed on a public server without an operator access boundary.

## 13. Memory center UI

The user-facing memory center must show:

- memory enabled state and scope;
- observed versus predicted concept state;
- evidence count, dates and source sessions;
- growth chart without false precision;
- due retests with reasons;
- explicit, proposed and expired preferences;
- inspect, correct, export, disable and delete actions.

No large personality score, global intelligence score or permanent red weakness
badge is allowed.

## 14. Deletion and export

### Export

Export includes machine-readable JSON and a readable summary with:

- identity metadata excluding secrets;
- linked project subjects;
- source evidence references and session dates;
- concept mappings;
- observed and predicted states with algorithm versions;
- preferences and confirmation provenance;
- retest plans and outcomes.

### Deletion

Supported scopes:

```text
preference
concept
project_link
all_long_term_memory
identity_and_memory
```

The deletion job invalidates caches, removes related exports and rebuilds unaffected
state. Backups follow the documented retention window and are not silently restored
into active state.

## 15. Migration and deployment

- use additive Alembic migrations first;
- preserve v0.5/v0.6 tables and endpoints;
- support SQLite in the single-server evaluation deployment;
- avoid SQLite-specific JSON query logic in the domain layer;
- add indexes for identity, concept, time and source event;
- rehearse upgrade and downgrade on a copied production-like database;
- include new memory tables in project/identity deletion and backup tests;
- keep Docker Compose startup unchanged until an accepted implementation requires a
  worker job for rebuild/export.

## 16. Observability

Record without retaining answer content in operational logs:

- memory candidates proposed/accepted/rejected by category;
- mapping acceptance and abstention;
- rebuild duration and event count;
- prediction algorithm/version;
- retest plan generation and user acceptance;
- export/deletion job completion;
- cross-identity access denial;
- stale or contradictory preference expiry.

## 17. Failure behavior

- if identity linking fails, continue with project-scoped session state;
- if concept mapping is uncertain, abstain and retain local knowledge-unit state;
- if retention calculation fails, show the last observation without a prediction;
- if rebuild versions disagree, preserve old aggregate and flag review;
- if deletion fails, keep the request pending and block new long-term writes for the
  affected scope;
- never silently switch learner identities or merge concepts.

## 18. Implementation sequence

```text
memory policy and opaque identity
-> concept registry and shadow mappings
-> longitudinal event import and deterministic replay
-> retention baselines and growth API
-> shadow retest planner
-> confirmed preference memory
-> memory center, export and deletion
-> longitudinal evaluation and release hardening
```

No active retest scheduling or inferred preference activation is enabled before its
separate gate passes.
