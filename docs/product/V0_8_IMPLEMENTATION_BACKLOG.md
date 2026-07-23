# v0.8 Industry Template Platform Implementation Backlog

## 0. Implementation status

Current branch: `develop/v0.8.0`

Current package version: `0.8.0.dev0`

| Work package | Status | Current evidence |
|---|---|---|
| WP-01 | Increment A complete | Strict contract, generated JSON Schema, bounded parser, deterministic validation and adversarial tests |
| WP-02 | Increment A complete | Canonical compiler, fingerprints, override lattice and audit tests |
| WP-03 | Increment B complete | Four persistence models, immutable lifecycle service, additive `20260723_0006` migration and round-trip test |
| WP-04 | Partial | Thesis-defense compatibility template, idempotent persistence seed and catalog health delivered; remaining compatibility modes are pending |
| WP-05 to WP-12 | Not started | Runtime integration, UI, governance, evaluation and release hardening remain held |

Increment A is a compatibility foundation, not a complete v0.8 release. It does
not change session behavior or authorize production deployment.

## 1. Execution rules

- Keep `research/v0.8.0` documentation and disposable experiments only.
- Do not change the package version or deploy the research branch.
- Create `develop/v0.8.0` only after ADR-005, architecture and evaluation review.
- Base implementation on the accepted v0.7 candidate or final commit, never on the
  stable v0.4 branch.
- Use `feature/v0.8-<short-name>` branches from `develop/v0.8.0`.
- Preserve all v0.7 requests and stored sessions through legacy mappings.
- Do not add a public marketplace, organizations or executable template plugins.
- Each work package includes tests, API/docs, migration impact and rollback notes.
- A template must affect policy or assessment behavior, not only visible wording.

## 2. Work packages

### WP-01: Template schema, registries and safe parser

Branch: `feature/v0.8-template-schema`

Deliverables:

- JSON Schema Draft 2020-12 contract;
- Pydantic authoring and compiled-contract models;
- action, report-section, question-type and disclaimer registries;
- bounded safe YAML/JSON parser;
- structural and semantic validation issue vocabulary;
- valid, invalid and adversarial fixtures.

Acceptance:

- unknown fields and unsupported schema versions fail;
- unsafe YAML tags/aliases and excessive depth/size fail;
- weights, references and policy constraints validate deterministically;
- no paid model is called;
- frozen fixture agreement is 100%.

### WP-02: Deterministic compiler and override lattice

Branch: `feature/v0.8-template-compiler`

Deliverables:

- canonical normalization;
- compiled runtime sections;
- locked, bounded, selectable and one-way toggle overrides;
- capability validation;
- compiler version and SHA-256 fingerprint;
- compile/diff unit tests.

Acceptance:

- key ordering cannot change the fingerprint;
- identical inputs compile byte-equivalently;
- invalid overrides never reach session creation;
- requested/effective/rejected overrides are auditable;
- safety constraints cannot be weakened.

### WP-03: Persistence, migration and lifecycle

Branch: `feature/v0.8-template-persistence`

Deliverables:

- `ScenarioTemplate`, `ScenarioTemplateVersion`, `TemplateValidationRun` and
  `ProjectTemplateBinding` models;
- additive Alembic migration after `20260721_0005`;
- draft, candidate, published and deprecated lifecycle;
- published-row immutability guard;
- SQLite/PostgreSQL upgrade, downgrade and re-upgrade tests.

Acceptance:

- semantic versions are unique per template;
- published source and compiled content cannot mutate;
- deprecation preserves historical reads;
- migration preserves every v0.7 row;
- destructive downgrade is blocked when v0.8-bound sessions exist.

### WP-04: Built-in seed catalog and legacy compatibility

Branch: `feature/v0.8-template-compatibility`

Deliverables:

- source-controlled built-in template directory;
- idempotent seeding by slug and semantic version;
- compatibility templates for defense, teaching, interview and retest;
- effective-policy comparison runner against v0.7 fixtures;
- template/catalog health endpoint.

Acceptance:

- repeated startup creates no duplicate versions;
- legacy requests compile without a template ID;
- current text/voice behavior remains within frozen expectations;
- old sessions remain readable with null template columns;
- no existing mode string is silently reinterpreted.

### WP-05: Session binding and snapshot replay

Branch: `feature/v0.8-session-template-binding`

Deliverables:

- optional template fields on text and voice session creation;
- project default binding;
- immutable effective snapshot and fingerprint on each session;
- session template inspection endpoint;
- replay and version-upgrade tests.

Acceptance:

- new template versions cannot change old sessions;
- text and voice produce the same effective fingerprint for equivalent inputs;
- contradictory mode/template input fails explicitly;
- session start fails before provider calls when template compilation fails;
- existing API bodies remain valid.

### WP-06: Planner and adaptive selector integration

Branch: `feature/v0.8-template-questioning`

Deliverables:

- objective and question-taxonomy input for Planner;
- coverage and difficulty constraints for adaptive selection;
- scenario-specific question diversity and evidence rules;
- knowledge-unit compatibility mapping;
- provider-neutral structured-output tests.

Acceptance:

- every planned question maps to a valid template objective;
- required objective coverage is met or explicitly reported as impossible;
- difficulty remains inside template bounds;
- document grounding remains mandatory when declared;
- cross-template question distribution differs as expected.

### WP-07: Conversation and assistance policy integration

Branch: `feature/v0.8-template-conversation-policy`

Deliverables:

- template-configured allowed actions and follow-up bounds;
- hint, correction, disclosure and interruption rules;
- platform-invariant policy wrapper;
- effective-policy event metadata;
- deterministic action fixtures.

Acceptance:

- one-question-at-a-time remains enforced;
- forbidden hints/disclosures never occur;
- assisted attempts remain separate from independent attempts;
- users can disable optional active interruption;
- model output cannot authorize an action outside the compiled allowlist.

### WP-08: Assessment and report integration

Branch: `feature/v0.8-template-assessment`

Deliverables:

- objective and dimension rubric registry;
- weighted and non-total aggregate policies;
- registered report-section builders;
- template metadata, disclaimer and objective scores in reports;
- exact deterministic score recomputation tests.

Acceptance:

- all scores cite answer and rubric evidence;
- weights and aggregate match the session snapshot;
- coaching templates may omit a total score without breaking reports;
- report sections and disclaimers follow the template;
- interaction preference and voice signals cannot affect correctness scores.

### WP-09: Built-in scenario templates

Branch: `feature/v0.8-built-in-templates`

Deliverables:

- thesis defense;
- grant review practice;
- course oral practice;
- technical interview practice;
- product knowledge training;
- sales objection training;
- project review facilitator;
- bilingual metadata and deterministic behavior fixtures.

Acceptance:

- each template passes all invariants;
- each intended-distinct pair differs in at least three runtime dimensions;
- prohibited-use and human-review language is explicit;
- no template impersonates a named employer, institution or individual;
- medical diagnosis and automatic employment/admission decisions remain absent.

### WP-10: Template API, diff, import and export

Branch: `feature/v0.8-template-api`

Deliverables:

- catalog, authoring, validation, compilation and lifecycle endpoints;
- semantic diff and clone;
- safe YAML/JSON import/export;
- stable error codes and OpenAPI documentation;
- endpoint authorization seam for v0.9.

Acceptance:

- imports always create local drafts;
- no import can claim built-in trust or published status;
- diff groups behavioral changes by policy section;
- exports contain no documents, memory, prompts or keys;
- API regression and cache-control tests pass.

### WP-11: Template library and structured editor

Branch: `feature/v0.8-template-ui`

Deliverables:

- compact template catalog with category, risk and lifecycle filters;
- project/session template selector;
- structured editor tabs for goals, questions, assistance, rubric, report and safety;
- validation issue navigation and effective-settings preview;
- clone, candidate, publish, deprecate, import and export flows;
- responsive desktop/mobile browser tests.

Acceptance:

- raw YAML is optional advanced editing, not the only path;
- numeric, binary and enum fields use appropriate controls;
- publish/deprecate actions require confirmation;
- long Chinese/English content never overlaps controls;
- risk, version and intended-use information is visible before session start.

### WP-12: Evaluation runner and release hardening

Branch: `feature/v0.8-template-evals`

Deliverables:

- schema, semantic, compiler and invariant suites;
- cross-template distinctness matrix;
- scenario relevance dataset and comparison runner;
- override, security and legacy compatibility reports;
- migration, Docker Compose, backup and rollback rehearsal;
- release notes and Vultr upgrade guide.

Acceptance:

- all gates in `V0_8_TEMPLATE_EVALUATION_PLAN.md` report sample counts and versions;
- current v0.7 regression suite passes;
- at least three templates pass relevance evaluation before RC;
- Qwen real-provider sample plus one independent provider sample is recorded when
  credentials and quota are available;
- standard Git push and immutable RC tag are used with no archive chunks.

## 3. Dependency order

```text
WP-01 -> WP-02 -> WP-03
              -> WP-04 -> WP-05
WP-05 + WP-02 -> WP-06 -> WP-07 -> WP-08
WP-06 + WP-07 + WP-08 -> WP-09
WP-03 + WP-02 -> WP-10 -> WP-11
all prior packages -> WP-12
```

Parallel work is safe only when file ownership is separate. Compiler and contract
changes must land before runtime integrations consume them.

## 4. Suggested implementation increments

### Increment A: compatibility vertical slice

- WP-01 and WP-02;
- one thesis-defense compatibility template;
- compile and compare to v0.7 behavior;
- no database or UI yet.

### Increment B: durable runtime

- WP-03 to WP-05;
- migrations, lifecycle and session snapshots;
- legacy clients still work.

### Increment C: behavior platform

- WP-06 to WP-09;
- three initial templates first: thesis defense, oral teaching, technical interview;
- expand to enterprise training only after invariants pass.

### Increment D: authoring and release

- WP-10 to WP-12;
- structured editor, all built-ins, evaluation and Vultr rehearsal.

## 5. Definition of done

v0.8 is complete only when:

1. published templates are immutable and replayable;
2. every session stores an effective template snapshot and fingerprint;
3. existing v0.7 session creation remains compatible;
4. at least three scenario templates demonstrate measured behavioral improvement;
5. all built-ins preserve evidence, memory, privacy and safety invariants;
6. text and voice use the same policy contract;
7. import/export, editor and lifecycle flows work on desktop/mobile;
8. migration and rollback are rehearsed under Docker Compose;
9. API, architecture, evaluation, deployment, changelog and release docs agree;
10. a standard Git commit/tag/push publishes the candidate without generated blobs.
