# ADR-005: Versioned, compiled and policy-bounded scenario templates

Status: Proposed for v0.8 research
Date: 2026-07-23

## Context

AI Examiner currently represents a scenario through a small set of fields such as
`Project.domain`, `ExamSession.mode`, assistance flags and question strategy. Some
runtime behavior is selected by `if mode == ...` branches in the reporter, voice
instructions and session setup.

That is sufficient for defense and teaching demonstrations, but it cannot safely
support academic review, oral learning, technical interview practice, product
training, sales roleplay and SOP assessment. A prompt-only template would also be
unsafe: it could silently change scoring, disclose answers, weaken grounding or
override interruption and memory controls.

The platform therefore needs a scenario contract that changes the complete
assessment behavior while preserving the evidence, cognitive-state and memory
invariants established in v0.5-v0.7.

## Decision

v0.8 will introduce versioned scenario templates that are validated, compiled and
snapshotted before use.

1. A template describes objectives, question taxonomy, assistance, conversation,
   adaptive selection, assessment, reporting, safety and presentation policy.
2. Template authoring uses YAML or JSON. Canonical persistence uses normalized JSON.
3. Structural validation follows JSON Schema Draft 2020-12. Pydantic and deterministic
   semantic validators enforce cross-field rules that JSON Schema cannot express.
4. Published template versions are immutable. A change creates a new semantic
   version. Deprecation changes lifecycle metadata, not template content.
5. A deterministic compiler converts a template version into a runtime contract.
   Every session stores the compiled snapshot, compiler version and SHA-256
   fingerprint so historical behavior remains replayable.
6. Templates contain structured policy, not executable Python, Jinja, HTML or
   arbitrary system prompts. System-owned prompt builders render approved fields.
7. User overrides follow an explicit override lattice. Locked fields cannot change;
   bounded fields must stay within declared limits; selectable fields must use an
   allowlist. The effective configuration is persisted.
8. Existing sessions without a template remain compatible through built-in legacy
   mappings for `defense`, `teaching`, `interview` and `retest`.
9. Material blueprints and scenario templates remain separate. A blueprint contains
   document-specific knowledge and questions; a template controls how those items
   are selected, discussed and evaluated.
10. High-stakes automatic decisions are outside v0.8. Practice and advisory templates
    must state intended use, prohibited use, human-review requirements and report
    disclaimers.
11. Built-in templates live in source control and are seeded idempotently. Custom
    templates remain local to the installation until v0.9 adds organizations and
    authorization.
12. QTI 3 is treated as a future import/export adapter for assessment items. It does
    not replace the AI Examiner template contract because it does not model the full
    conversational policy, evidence and memory lifecycle.

## Template trust levels

```text
built_in_reviewed   shipped and reviewed with the application
local_draft         editable, cannot start a production-marked session
local_candidate     validated and eligible for sandbox evaluation
local_published     immutable and available for local sessions
deprecated          retained for replay, hidden from new-session defaults
```

Publishing is an explicit action. Model-generated template proposals always begin as
`local_draft` and cannot publish themselves.

## Policy precedence

From strongest to weakest:

```text
platform safety invariants
  > template locked constraints
  > template bounded/selectable constraints
  > project defaults
  > session overrides
  > model suggestions
```

No lower layer may weaken a higher layer. The compiler returns validation errors
rather than silently accepting an invalid override.

## Consequences

### Positive

- scenarios change real runtime behavior instead of only renaming the examiner;
- reports and scores remain reproducible after templates evolve;
- policy differences are testable with deterministic fixtures;
- built-in and custom templates share one contract;
- migration from current mode strings can be additive;
- future institutional sharing has a clear version and trust boundary.

### Costs

- template schema, compiler, registry, persistence and lifecycle APIs are required;
- Planner, Policy, Evaluator, Reporter and Voice need configuration injection points;
- built-in templates need behavioral fixtures, not only configuration tests;
- UI authoring must expose structured controls without allowing arbitrary code;
- old mode-specific branches must be removed gradually after compatibility tests.

## Rejected alternatives

### One prompt per industry

Rejected because prompts cannot reliably enforce scoring, help limits, evidence,
overrides, lifecycle or replay.

### Copy the application for every industry

Rejected because fixes, migrations, evaluations and provider integrations would
diverge across forks.

### Store a mutable template JSON on each project

Rejected because historical sessions would change meaning when the JSON is edited.

### Make QTI the native template format

Rejected for the core runtime. QTI is valuable for portable items and results, while
AI Examiner also needs dynamic follow-up, interruption, assistance, adaptive policy,
evidence and long-term memory controls. A later adapter can map the compatible subset.

### Add organizations and a public marketplace now

Rejected as v0.9 scope. v0.8 is a single-installation template platform with no
cross-tenant sharing or untrusted public execution.

## References

- JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12
- 1EdTech QTI specification documents: https://www.1edtech.org/standards/qti/index
- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- NIST AI RMF Generative AI Profile: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
