# AI Examiner v0.8.0 Development and v0.9.0 Research Status

## Current state

- Version: `0.8.0.dev0`
- Current branch: `research/v0.9.0`
- Base candidate: `v0.7.0-rc.2`
- Release tag: not created
- Deployment status: research only; not approved for production
- Alembic head: `20260728_0013`

v0.9 WP-01 through WP-07 are implemented. WP-07 adds tenant-scoped immutable task
envelopes, idempotency, atomic leases, heartbeats, execution-time authorization,
bounded retry, cancellation, dead-letter state and stale-worker recovery. The
package version intentionally remains `0.8.0.dev0`.

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

## Increment G: reviewed built-in scenarios

Delivered:

- seven bilingual reviewed scenario identities and nine immutable versions;
- thesis defense practice;
- grant review practice;
- course oral practice;
- technical interview practice;
- product knowledge training;
- sales objection practice;
- blameless project review facilitation;
- materially different objectives, taxonomy, difficulty, assistance,
  conversation, assessment, reporting and presentation policies;
- pairwise behavior-signature tests requiring at least three runtime differences;
- high-risk technical interview boundaries prohibiting automatic employment
  decisions;
- human review, protected-trait and personality/emotion scoring protections on
  every built-in scenario;
- no-total evidence reports for sales coaching and project facilitation;
- persisted catalog health for seven identities and nine versions.

## Increment H: safe template transfer and semantic comparison

Delivered:

- bounded YAML/JSON import through the existing safe parser;
- forced local ownership, `draft` lifecycle and `local_draft` trust on every
  imported template;
- source-only JSON/YAML export with no document, memory, prompt, credential or
  runtime state;
- deterministic recursive diff with JSON Pointer paths;
- behavioral changes grouped by template, objectives, questioning, assistance,
  conversation, assessment, reporting, safety, presentation, voice,
  compatibility and override policy;
- stable missing-version, invalid-format, unsafe-document and oversized-document
  errors;
- dynamic-response `Cache-Control: no-store` regression coverage;
- an explicit authoring-context dependency that documents the current
  single-user local boundary and can be replaced by v0.9 RBAC.

## Increment I: structured scenario template studio

Delivered:

- responsive template catalog with search, category, risk and lifecycle filters;
- visible template version, trust, intended-use and risk metadata before session
  selection;
- structured local-draft editing for objectives, questioning, assistance,
  assessment, report and safety policies;
- optional advanced JSON editing without making raw YAML/JSON the primary path;
- effective-policy preview with fingerprint and override audit;
- validation, compilation, clone, candidate, draft, publish, deprecate,
  import/export and semantic-diff browser flows;
- published-template selection shared by blueprint generation, text sessions and
  realtime voice sessions;
- read-only built-in and published versions, with local drafts as the only mutable
  browser artifacts;
- contract-safe correction timing controls and persistent save feedback;
- desktop and 390-by-844 mobile browser verification without horizontal overflow.

## Increment J: deterministic template evaluation

Delivered:

- one `template-evaluation-v1` machine-readable report contract;
- seven latest-scenario and nine packaged-version validation;
- deterministic recompilation and platform invariant gates;
- all 21 pairwise scenario distinctness checks;
- 112 valid/invalid override boundary probes;
- local validation and compilation p50/p95 timings;
- an explicit release-evidence hold that deterministic and Mock results cannot
  clear.

## Increment K: real-provider probes and deployment rehearsal harness

Delivered:

- a `template-provider-probe-v1` CLI using the real Session Planner path;
- Qwen `qwen-plus` contract samples across thesis defense, course oral and
  technical interview templates;
- OpenAI `gpt-5.4-mini` independent samples across the same three templates;
- actual provider/model, token, latency, coverage and violation evidence without
  secrets or rendered prompts;
- one bounded full-blueprint repair attempt for provider output outside the
  immutable template contract;
- provider evidence ingestion that releases only the Qwen and independent-provider
  sample gates;
- isolated Compose environment/data injection and a temporary-project rehearsal
  script covering build, migration, health, deterministic evaluation and backup
  inspection.

Held:

- cross-provider blind scenario-relevance judging;
- actual Docker Compose rehearsal on a Docker host;
- Vultr upgrade and rollback rehearsal.

## Increment L: frozen scenario-relevance corpus

Delivered:

- a fingerprinted `v0.8-scenario-relevance-v1` corpus for all seven built-ins;
- deterministic expansion to 210 cases, with 30 cases per template;
- exact balancing across `zh-CN`/English, difficulty levels 2/3/4 and five answer
  quality classes;
- objective and expected-question-type checks against the latest immutable
  template definitions;
- a blind-judge evidence contract that requires different non-Mock generator and
  judge providers;
- per-template relevance improvement, 95% confidence intervals, high-quality,
  grounding, single-question and unsafe-behavior metrics;
- a release threshold requiring at least three complete 30-case templates;
- corpus export and evidence aggregation through
  `ai-examiner-evaluate-template-relevance`;
- combined report ingestion through repeatable `--relevance-report` arguments.

Held:

- real cross-provider blind-judge reports have not been generated;
- the frozen corpus passing integrity checks does not by itself establish scenario
  quality.

## Increment M: runtime scenario relevance

Delivered:

- actual `SessionPlanner` execution for baseline and scenario arms;
- independent arm generation with no shared model context;
- deterministic A/B blinding and post-judge unblinding;
- reciprocal cross-provider and minimum-two-judge release requirements;
- release rejection for batched calibration output;
- full scenario identity, presentation, assistance, assessment and report context
  supplied to the Planner;
- a real Qwen-generated/OpenAI-judged two-case correction pilot.

Real pilot after the Planner correction:

```text
Scenario                       enterprise.sales_objection
Runtime cases                  2 / 30
Mean relevance improvement     +1.5
95% CI                         [-1.44, 4.44]
High-quality rate              100%
Grounded rate                  100%
Single-main-question rate      100%
Unsafe rate                    0%
```

This remains held because 2 cases cannot substitute for 30, the confidence
interval is wide, the reciprocal direction is absent and three templates are
required.

## Increment N: release quality

Delivered:

- explicit role/style behavior guidance in the production Planner;
- scenario-native question framing that cannot be satisfied by a role-name change;
- fail-closed detection and bounded repair of stacked main questions;
- operational blind-judge guidance for scenario behavior and follow-up separation;
- atomic per-batch checkpoints and metadata-safe `--resume`;
- a real timeout-and-resume rehearsal at 35/90 completed Qwen cases;
- reciprocal Qwen/OpenAI 30-case evidence for product knowledge, sales objection
  and project review.

Final real-provider results:

```text
Template                      Delta    95% CI             HQ      Ground  Single  Unsafe
enterprise.product_knowledge  +1.017   [0.772, 1.261]     98.3%   100%    100%    0%
enterprise.sales_objection    +1.500   [1.186, 1.814]     98.3%   100%    100%    0%
operations.project_review     +1.667   [1.494, 1.839]     100%    100%    100%    0%
```

The scenario-relevance gate is passed. The combined release evidence is held only
by Docker Compose and Vultr upgrade/rollback rehearsal.

## Verification

```text
WP-11 targeted tests          16 passed
WP-12 pre-Increment-L tests   32 passed
Increment L/M focused tests   11 passed
Targeted Ruff                 passed
Wheel built-in resource       packaged
Full pytest                   137 passed
Full Ruff                     passed
JavaScript syntax             passed
git diff --check              passed
Tracked-source secret scan    no key patterns found
Alembic single head           20260723_0007
Alembic metadata drift check  no new upgrade operations
Wheel build                   ai_examiner_mvp-0.8.0.dev0-py3-none-any.whl
Qwen template probe           3/3 scenarios passed
OpenAI template probe         3/3 scenarios passed
Frozen relevance corpus       210/210 cases valid
Blind relevance judging       passed (3/3 templates)
Docker Compose rehearsal      held (no capable Docker host)
```

The configured SeetaCloud instance was checked as a possible rehearsal host. It
contains a Docker client but runs inside a restricted container. `dockerd` cannot
create the Docker NAT chain because host `iptables` capabilities are unavailable.
No existing deployment directory, data or container was modified.

Pytest exits successfully, but the Windows interpreter still prints the existing
async-generator cleanup `access violation` message after completing all tests.
There is no failed test, but this platform-specific shutdown noise remains a known
diagnostic issue.

## Held gates

The following work remains intentionally disabled or unimplemented:

- no database-backed catalog editor;
- local authoring is demoted to local trust states and cannot claim
  `built_in_reviewed`;
- the current authoring dependency is a local single-user seam, not authentication
  or organization authorization;
- no public marketplace, organization model or executable plugin;
- no merge to `main`, final `v0.8.0` tag or production deployment.

The current branch has completed its software and AI quality gates, but remains a
development candidate until deployment rehearsal succeeds. It is not the completed
v0.8 release.
