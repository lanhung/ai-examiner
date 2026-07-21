# v0.7 Implementation Backlog

## 1. Execution rules

- Keep `research/v0.7.0` documentation and disposable experiments only.
- Do not change package version or deploy the research branch.
- Create `develop/v0.7.0` only after ADR-004, architecture and evaluation review.
- Base implementation on the accepted v0.6 integration/release commit, not on an
  older production branch.
- Use `feature/v0.7-<short-name>` branches from `develop/v0.7.0`.
- Preserve project-scoped anonymous sessions when long-term memory is disabled.
- Do not enable cross-project aggregation, active retest scheduling or inferred
  preferences before their individual gates pass.
- Every work package includes migration, tests, API/docs and deletion coverage.

## 2. Work packages

### WP-01: Memory policy and opaque identity

Branch: `feature/v0.7-memory-identity`

Deliverables:

- `LearnerIdentity`, `LearnerIdentityLink` and memory-settings schemas;
- HMAC-based opaque external reference mapping;
- explicit link/revoke flow;
- memory-disabled compatibility behavior;
- additive Alembic migration and downgrade.

Acceptance:

- raw external reference is neither persisted nor logged;
- no automatic identity matching;
- unlinked/project-only sessions behave exactly as v0.6;
- revoked links stop future cross-project aggregation;
- cross-identity access tests pass with zero leakage.

### WP-02: Canonical concept registry

Branch: `feature/v0.7-concept-registry`

Deliverables:

- `Concept` and `KnowledgeUnitConceptMap` tables;
- namespace, relation, confidence, evidence and lifecycle fields;
- deterministic candidate validation;
- model-proposal interface with abstention;
- mapping review API and fixtures.

Acceptance:

- existing `KnowledgeUnit.code` remains local and backward compatible;
- only accepted exact/narrower mappings feed longitudinal state;
- ambiguous candidates abstain;
- accepted mapping precision gate passes on the frozen set;
- changing an accepted mapping queues a rebuild.

### WP-03: Longitudinal memory event ledger

Branch: `feature/v0.7-memory-events`

Deliverables:

- `LearnerMemoryEvent` table and allowed event vocabulary;
- idempotent import from existing knowledge evidence;
- supersession/correction semantics;
- deterministic policy gate;
- disallowed-category adversarial tests.

Acceptance:

- one source event imports at most once;
- every durable event has category, provenance and policy version;
- model output cannot bypass the policy gate;
- unrestricted summary, personality, emotion, trait and secret candidates are
  rejected;
- events are included in scoped deletion.

### WP-04: Longitudinal state builder

Branch: `feature/v0.7-longitudinal-state`

Deliverables:

- `LearnerConceptState` rebuildable aggregate;
- observed versus predicted value separation;
- `no_decay`, `fixed_half_life` and `evidence_half_life` strategies;
- dry-run rebuild comparison;
- growth-series API.

Acceptance:

- replay with same inputs/version is exactly reproducible;
- confidence decreases for sparse/stale/contradictory evidence;
- assisted performance never becomes independent recall evidence;
- calculation failure falls back to last observation, not a fabricated prediction;
- retention baseline report is generated.

### WP-05: Retest planner in shadow mode

Branch: `feature/v0.7-retest-shadow`

Deliverables:

- `RetestPlan` and `RetestItem` tables;
- deterministic ranking and hard constraints;
- reason codes and source-state version;
- baseline evaluation runner;
- candidate-question novelty check.

Acceptance:

- planner cannot modify live sessions in shadow mode;
- unresolved misconceptions and overdue low-retention concepts are explainable;
- prerequisite violations are zero in Golden cases;
- exact repeated questions are avoided when alternatives exist;
- random/oldest/lowest-mastery baseline comparison is published.

### WP-06: Retest recommendation integration

Branch: `feature/v0.7-retest-ui`

Deliverables:

- due-retest list and reason display;
- user accept/dismiss/start actions;
- session creation from accepted plan;
- outcome linkage to source `RetestItem`;
- feature flag for recommendation-only mode.

Acceptance:

- the user initiates every v0.7 retest;
- dismissed items do not silently reappear before policy cooldown;
- outcomes are independent attempts before retention calibration use;
- no plan exists for an unaccepted concept mapping.

### WP-07: Confirmed preference memory

Branch: `feature/v0.7-preferences`

Deliverables:

- registry of allowed preference keys;
- explicit, proposed, active, rejected and expired lifecycle;
- confirmation UI/API;
- evidence and contradiction handling;
- interaction-only application boundary.

Acceptance:

- explicit settings round-trip exactly;
- inferred proposals require repeated evidence and confirmation;
- rejected/expired entries no longer affect interaction;
- no preference reaches Analyzer/Evaluator scoring input;
- adversarial sensitive/personality candidates are rejected.

### WP-08: Memory center

Branch: `feature/v0.7-memory-center`

Deliverables:

- memory settings and scope;
- observed/predicted concept states with dates and uncertainty;
- evidence drill-down and growth view;
- preference review;
- due retest view;
- responsive and accessible UI.

Acceptance:

- estimates are visibly labeled and never shown as observed facts;
- no global intelligence/personality score;
- long labels and multilingual content fit desktop/mobile;
- source session/evidence is reachable;
- memory can be disabled from the same view.

### WP-09: Export, correction and deletion

Branch: `feature/v0.7-memory-control`

Deliverables:

- JSON export background job and short-lived artifact;
- correction/supersession API;
- scoped hard-deletion job;
- rebuild of unaffected state;
- backup-retention operational documentation.

Acceptance:

- export covers 100% of active in-scope memory;
- deletion covers source memory events, derived caches and generated exports;
- project-local records outside the requested scope are preserved;
- failed deletion blocks new writes and can resume;
- deletion completion audit contains counts, not deleted content.

### WP-10: Longitudinal evaluation runner

Branch: `feature/v0.7-memory-evals`

Deliverables:

- synthetic longitudinal fixtures;
- concept-mapping Golden set runner;
- retention calibration metrics;
- retest baseline comparison;
- preference adversarial suite;
- lifecycle and isolation report.

Acceptance:

- offline evaluation requires no paid API for frozen fixtures;
- every report records dataset, algorithm, policy, prompt and model versions;
- CI fails on identity leakage, replay mismatch or deletion regression;
- statistical metrics report sample count and uncertainty.

### WP-11: PostgreSQL readiness

Branch: `feature/v0.7-postgres-readiness`

Deliverables:

- domain queries that work on SQLite and PostgreSQL;
- indexes and uniqueness constraints reviewed for both;
- optional CI service for PostgreSQL migration/tests;
- database portability report;
- no forced production migration.

Acceptance:

- SQLite Docker Compose remains supported;
- migration suite passes on both backends where CI permits;
- no provider-specific JSON query is required in core memory calculations;
- PostgreSQL completion can be deferred without changing the memory domain model.

### WP-12: Release hardening

Branch: `release/v0.7.0`

Deliverables:

- migration/downgrade rehearsal on copied v0.6 data;
- Docker Compose upgrade and rollback;
- backup/restore and deletion-retention rehearsal;
- secret and fixture scan;
- API, architecture, evaluation and deployment documentation;
- release candidate report.

Acceptance:

- v0.5 adaptive and v0.6 voice/assessment regressions pass;
- memory-disabled mode is behaviorally compatible;
- all v0.7 gates in the evaluation plan pass or the corresponding feature remains
  shadow/disabled;
- no API keys, user data, exports or runtime databases are committed;
- clean install and production-like Compose smoke test pass.

## 3. Dependency order

```text
WP-01 identity/policy
  -> WP-02 concept registry
  -> WP-03 memory ledger
  -> WP-04 state builder
       -> WP-05 retest shadow -> WP-06 recommendation UI
       -> WP-07 preferences
       -> WP-08 memory center
  -> WP-09 export/deletion
  -> WP-10 evaluation
  -> WP-11 PostgreSQL readiness
  -> WP-12 release hardening
```

WP-09 begins schema review during WP-01 and WP-03; deletion is not an afterthought.

## 4. Suggested implementation increments

### Increment 1: Safe memory foundation

WP-01 through WP-03. No user-visible intelligence yet.

### Increment 2: Measurable longitudinal state

WP-04 and WP-10 retention fixtures. Predictions remain internal/shadow.

### Increment 3: Actionable but user-controlled recommendations

WP-05 and WP-06. Users choose whether to start retests.

### Increment 4: Preference and transparency

WP-07 through WP-09. Complete review/export/delete control.

### Increment 5: Portability and release

WP-11 and WP-12.

## 5. Definition of done

v0.7 is not complete merely because it stores history. It is complete when:

- longitudinal conclusions are evidence-bound and replayable;
- observed results and predictions are never confused;
- cross-project concepts are mapped conservatively;
- retest planning beats or safely falls back to simple baselines;
- preferences are confirmed and score-independent;
- memory is inspectable, exportable, correctable and deletable;
- memory-disabled users retain the existing product experience;
- release artifacts prove isolation, lifecycle and regression gates.
