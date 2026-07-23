# v0.8 Industry Template Platform Architecture

## 1. Objective

v0.8 turns AI Examiner from a research-defense application into a controlled
multi-scenario platform. A selected template must change:

- what capabilities and evidence the session seeks;
- which question types and difficulty paths are available;
- when the examiner follows up, hints, corrects or moves on;
- how independent and assisted performance are evaluated;
- which report sections and disclaimers are produced;
- which voice and interruption behaviors are permitted;
- which safety and human-review constraints are mandatory.

Changing only the visible role name or system prompt does not satisfy v0.8.

## 2. Baseline and integration gaps

The v0.7 runtime already provides reusable foundations:

```text
documents and multimodal evidence
  -> blueprint and knowledge units
  -> fixed/adaptive question selection
  -> analyzer and evidence-bound evaluator
  -> policy controller
  -> text/realtime interviewer
  -> report and longitudinal learner state
```

The remaining scenario logic is fragmented across:

- `Project.domain`;
- `ExamSession.mode`;
- session booleans and numeric limits;
- reporter branches for defense versus teaching;
- voice role text;
- planner question types fixed to research defense;
- implicit assumptions in the browser UI.

v0.8 replaces those implicit choices with one compiled runtime contract.

## 3. Scope

### Included

- versioned template schema and deterministic compiler;
- lifecycle: draft, candidate, published and deprecated;
- built-in template catalog and local custom templates;
- session binding and immutable effective snapshots;
- structured objectives, policies, rubrics, reports and safety rules;
- template validation, preview, diff, clone, import and export;
- compatibility mappings for existing modes;
- behavioral template evaluation and regression reports;
- responsive template library/editor and session selector;
- additive SQLite/PostgreSQL-compatible migration.

### Excluded

- public marketplace and third-party executable plugins;
- organizations, tenant sharing, SSO and RBAC;
- automatic hiring, admission, grading, medical or employment decisions;
- arbitrary code, HTML, Jinja or system-prompt execution from templates;
- QTI conformance certification;
- payment, licensing and template monetization;
- training a template-selection model.

## 4. Runtime architecture

```text
Template YAML/JSON
       |
       v
Structural Validator (JSON Schema 2020-12)
       |
       v
Semantic Validator
  - references and weights
  - policy consistency
  - override bounds
  - safety and capability checks
       |
       v
Template Compiler
  - normalized runtime sections
  - legacy compatibility projection
  - compiler version
  - SHA-256 fingerprint
       |
       +--------------------> Preview / Diff / Evaluation
       |
       v
CompiledTemplate Snapshot
       |
       +--> Planner config
       +--> Adaptive selector config
       +--> Conversation policy config
       +--> Analyzer/Evaluator contract
       +--> Report config
       +--> Voice config
       +--> Safety constraints
       |
       v
ExamSession (immutable snapshot reference)
```

The compiler is deterministic. Identical canonical input, compiler version and
feature flags must produce byte-equivalent canonical output and the same fingerprint.

## 5. Template contract

Authoring files use this top-level shape:

```yaml
schema_version: "1.0"
template:
  slug: academic.thesis_defense
  version: 1.0.0
  category: academic
  title:
    zh-CN: 论文答辩训练
    en: Thesis Defense Practice
  description:
    zh-CN: 基于材料证据的论文答辩训练
  trust_level: built_in_reviewed
  intended_use: practice_and_advisory
  risk_tier: moderate

capabilities:
  required: [documents, evidence, assessment]
  optional: [voice, adaptive_questions, long_term_memory]

objectives:
  - id: contribution
    title: {zh-CN: 核心贡献}
    weight: 0.20
    required_evidence: document_and_answer

question_policy:
  allowed_types: [explain, evidence, limitation, counterexample, transfer]
  coverage:
    contribution: {minimum_questions: 1}
  difficulty:
    initial: 3
    minimum: 1
    maximum: 5
    adaptive: true

assistance_policy:
  mode: bounded
  hints: {allowed: true, maximum_per_question: 1}
  corrections: {allowed: true, timing: after_independent_attempt}
  answer_disclosure: {allowed: false}

conversation_policy:
  max_followups_per_question: 2
  allowed_actions: [ASK_FOLLOWUP, ASK_FOR_EVIDENCE, CHALLENGE, GIVE_HINT, MOVE_ON, END]
  interruption: {level: low, user_can_disable: true}

assessment_policy:
  scale: {minimum: 0, maximum: 5}
  dimensions:
    - id: correctness
      weight: 0.30
      evidence_required: true
  assisted_performance: report_separately
  aggregate: weighted_dimensions

report_policy:
  sections: [summary, objective_scores, evidence, weaknesses, improvement_path]
  show_total_score: true
  required_disclaimer: practice_not_formal_decision

safety_policy:
  prohibited_uses: [automatic_admission_decision, automatic_employment_decision]
  human_review_required: true
  protected_trait_inference: forbidden

overrides:
  question_limit: {kind: bounded, minimum: 3, maximum: 15, default: 8}
  voice: {kind: selectable, values: [openai, qwen, disabled], default: disabled}
  safety_policy: {kind: locked}
```

Localized user-facing fields must include the installation default language. Missing
translations fall back explicitly and are reported by validation.

## 6. Structural and semantic validation

JSON Schema validates types, required fields, enums and additional properties.
Semantic validation additionally enforces:

- template slug and semantic version uniqueness;
- objective IDs and all references are resolvable;
- objective and dimension weights each sum to `1.0 +/- 0.0001` when weighted;
- question coverage references valid objectives;
- difficulty ranges are ordered and within platform limits;
- policy actions belong to the platform action registry;
- report sections belong to the report-section registry;
- every scored dimension requires answer evidence;
- assistance cannot classify a hinted answer as independent performance;
- a template cannot enable a platform-forbidden use;
- high-risk intent cannot remove human review or disclaimers;
- locked and bounded override rules are internally consistent;
- required capabilities exist in the current deployment;
- no arbitrary executable or prompt-control fields are present.

Validation returns stable machine-readable issue codes with JSON Pointer paths.

## 7. Data model

### ScenarioTemplate

```text
id
slug                    unique stable identity
category
owner_scope             built_in | local
status                   active | deprecated
created_at
```

### ScenarioTemplateVersion

```text
id
template_id
semantic_version
schema_version
status                   draft | candidate | published | deprecated
source_json
compiled_json            nullable until valid compilation
compiler_version
fingerprint
created_from_version_id  optional
created_at
published_at             optional
```

Unique: `(template_id, semantic_version)`. Published `source_json`, `compiled_json`,
compiler version and fingerprint are immutable.

### TemplateValidationRun

```text
id
template_version_id
validator_version
status                   passed | failed
issues_json
capability_snapshot_json
created_at
```

### ProjectTemplateBinding

```text
id
project_id
template_version_id
default_overrides_json
created_at
superseded_at            optional
```

### ExamSession additions

```text
template_version_id      nullable for migrated legacy sessions
template_snapshot_json   exact effective compiled configuration
template_fingerprint
template_compiler_version
template_overrides_json
```

The snapshot is authoritative for a running or completed session. Loading a newer
template version must never change an existing session.

## 8. Compiler and runtime adapters

`TemplateCompiler.compile()` produces a `CompiledTemplate` with fixed sections:

```text
identity
planner
question_selection
conversation
assessment
report
voice
safety
presentation
override_audit
```

Runtime adapters receive only their section:

- Planner receives objectives, question taxonomy, evidence requirements and language;
- Adaptive selector receives coverage, difficulty and diversity constraints;
- Policy receives allowed actions, follow-up bounds and assistance rules;
- Analyzer/Evaluator receive dimensions, rubric anchors and evidence requirements;
- Reporter receives registered sections, aggregate policy and disclaimer IDs;
- Voice receives role, speaking style and interruption bounds;
- Memory receives only template/category metadata, never scoring-policy shortcuts.

This keeps Agent responsibilities separated and prevents a template from becoming a
second unstructured super-prompt.

## 9. Override model

Each overridable path declares one of:

```text
locked       no project or session override
bounded      numeric/string length constraints and default
selectable   finite allowed values and default
toggle       boolean with optional one-way restriction
```

Safety constraints are always locked. A one-way toggle may permit a user to disable
interruptions but not enable them when the template forbids them. Compilation records
requested, accepted and rejected overrides with issue codes.

## 10. Built-in template set

The first implementation should ship seven reviewed templates:

1. `academic.thesis_defense`
2. `academic.grant_review_practice`
3. `education.course_oral_practice`
4. `engineering.technical_interview_practice`
5. `enterprise.product_knowledge_training`
6. `enterprise.sales_objection_training`
7. `operations.project_review_facilitator`

An SOP training template may be added after safety escalation behavior is tested.
Medical diagnosis, real hiring selection and formal admission templates are excluded.

## 11. Legacy compatibility

Existing sessions and clients can omit `template_version_id`.

```text
mode=defense   -> academic.thesis_defense@legacy-v1
mode=teaching  -> education.course_oral_practice@legacy-v1
mode=interview -> engineering.technical_interview_practice@legacy-v1
mode=retest    -> internal.retest@legacy-v1
```

The compatibility compiler must reproduce current v0.7 behavior. New clients select
a published template version. The old mode fields remain readable through v0.8 and
are deprecated only after telemetry shows no active legacy clients.

## 12. Template lifecycle

```text
create draft
  -> validate
  -> preview with deterministic fixtures
  -> mark candidate
  -> run behavioral evaluation
  -> publish immutable version
  -> bind project/session
  -> deprecate when replaced
```

Publishing requires successful validation and evaluation metadata. Models may suggest
content, but only an explicit local action publishes it.

## 13. Security and safety

- YAML parsing must use a safe loader and reject aliases beyond bounded limits;
- imports have size, depth, collection and string-length limits;
- unknown fields are rejected, not silently ignored;
- templates cannot define URLs, tools, Python imports, HTML or shell commands;
- localized text is escaped at render time;
- system prompt fragments are generated by trusted code from structured values;
- template exports contain no API keys, documents, transcripts or learner memory;
- template risk tier and intended use are visible in the selector and report;
- high-stakes claims always require human review and an appeal path in later versions.

## 14. Deployment and migration

The migration is additive and remains SQLite/PostgreSQL compatible. Startup seeds
built-in templates idempotently by slug and semantic version. It never edits a
published row.

Upgrade order:

```text
backup
-> migrate schema
-> seed built-in template versions
-> verify legacy mappings
-> start API and worker
-> run template health check
```

Downgrade removes template bindings and tables only after confirming no session relies
on a v0.8 snapshot. The deployment script must refuse destructive downgrade by
default.

## 15. Implementation sequence

```text
schema + compiler + fixtures
-> persistence and lifecycle
-> legacy compatibility adapter
-> session snapshot binding
-> Planner/Policy/Evaluator/Reporter adapters
-> built-in templates
-> template evaluation runner
-> library/editor UI
-> import/export and release hardening
```

The first vertical slice should compile one thesis-defense template and prove exact
v0.7 behavior compatibility before adding new scenarios.
