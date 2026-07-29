# Changelog

AI Examiner 的重要变更记录在此文件。版本号遵循 Semantic Versioning；开发版本使用 PEP 440 标识，例如 `0.5.0.dev0`。

## [Unreleased]

### Added

- Add WP-12 recoverable enterprise Docker Compose with PostgreSQL, Redis, API,
  worker and Caddy plus optional private MinIO and observability overlays.
- Separate migration and runtime database credentials, force external schema
  management and verify the application login remains subject to RLS.
- Add consistent PostgreSQL/object backup manifests, guarded isolated restore,
  RPO/RTO evidence and non-destructive update/application rollback scripts.
- Add deterministic operations tests and a Linux Compose restart plus
  backup/restore rehearsal in GitHub Actions.
- Add WP-11 failure-isolated OpenTelemetry instrumentation for FastAPI,
  SQLAlchemy, HTTPX and Celery with allowlist-based span redaction.
- Add backward-compatible worker task envelope v2 request and W3C trace
  correlation plus low-cardinality HTTP and job metrics.
- Add an optional Collector, Tempo, Prometheus, Grafana and Alertmanager
  Compose profile with provisioned dashboards and alert rules.
- Add telemetry privacy, endpoint validation, backend-outage and correlation
  regression tests.
- Add the v0.9 enterprise-platform research package covering organization tenancy,
  external OIDC identity, scoped service accounts, capability RBAC, PostgreSQL RLS,
  S3-compatible storage, tenant-aware jobs, audit, model governance, retention,
  OpenTelemetry, disaster recovery and a staged implementation backlog.
- Define the v0.9 API authorization contract, threat model, cross-tenant evaluation
  gates and restartable SQLite/file-to-PostgreSQL/object-storage migration strategy.
- Inventory every current model and API family by tenant ownership, required
  capability, resource resolver and migration invariant.
- Correct the PostgreSQL CI false-positive by allowing a guarded test-only database
  override and running the complete regression suite against PostgreSQL.
- Add an isolated Mock-only PostgreSQL Compose rehearsal, dedicated test image and
  Docker build-context exclusions for secrets, runtime data and generated archives.
- Add the v0.9 organization and principal foundation with deterministic legacy
  project ownership, external `(issuer, subject)` identity, unique memberships and
  bounded principal lifecycle.
- Add an idempotent first-owner bootstrap CLI and `/api/v1/context` observe-only
  organization context without prematurely enabling authentication or authorization.
- Add additive migration `20260727_0008` with legacy project backfill, guarded
  downgrade and SQLite/PostgreSQL verification.
- Add WP-03 OIDC discovery, bounded JWKS caching, strict access-token validation,
  Authorization Code + PKCE login, principal provisioning and revocable hashed
  browser sessions.
- Add `/api/v1/auth/login`, callback, logout and `/api/v1/me`, plus live `/ready`
  authentication checks and fail-closed production configuration validation.
- Add additive migration `20260727_0009` and an ephemeral-RSA invalid-token,
  key-rotation, PKCE, session, readiness and rollback test matrix.
- Add WP-04 centralized capability RBAC with reviewed role bundles, fail-closed
  organization membership resolution and cross-organization resource protection.
- Add complete `/api/v1` route policy registration with startup validation and
  generated `x-ai-examiner-policy` OpenAPI metadata.
- Add organization membership list/create/update/revoke APIs with strong ETags,
  bounded lifecycle transitions, owner-only owner mutation and last-owner protection.
- Replace the OIDC template-authoring compatibility seam with real author, reviewer
  and publisher capabilities while retaining disabled-mode deterministic tests.
- Add WP-05 direct organization ownership across project, learner, template, prompt,
  usage and background-job records with a two-phase legacy backfill.
- Add transaction-local SQLAlchemy tenant/principal context, tenant-aware Celery job
  dispatch and fail-closed worker resource loading.
- Add tenant-aware uniqueness, critical composite ownership constraints and forced
  PostgreSQL RLS policies for the restricted `ai_examiner_runtime` role.
- Add a PostgreSQL pre-pytest RLS proof covering missing context, context switching
  and cross-tenant writes, while retaining SQLite local-evaluation compatibility.
- Separate schema-management and runtime responsibilities: enforced RLS requires
  `DATABASE_SCHEMA_MANAGEMENT=external`, so API and worker startup cannot run DDL or
  global seed writes with the restricted runtime credential.
- Add WP-06 tenant object storage with one Local/S3-compatible backend contract,
  canonical organization-prefixed object keys and normalized `StoredObject`
  locators protected by PostgreSQL FORCE RLS.
- Route new document, evidence and memory-export writes through checksum-verified
  storage while retaining nullable legacy paths only for migration compatibility.
- Add authorized `/api/v1` document, evidence, highlighted evidence and memory
  export downloads with private streaming or bounded presigned redirects.
- Add restartable legacy-path migration, atomic checkpoints, source retention,
  missing-object reconciliation and a downgrade guard that prevents orphaning
  migrated objects.
- Add an optional private MinIO Compose profile, storage readiness checks and
  Local/S3 contract, resume, checksum, authorization and Alembic regression tests.
- Add WP-07 durable tenant-aware job delivery with strict persisted task envelopes,
  organization-scoped idempotency keys and atomic lease ownership.
- Recheck active organization, principal, membership and required capability in the
  worker before loading any protected resource.
- Add bounded transient retries, cooperative cancellation, terminal/dead-letter
  states, heartbeat renewal and expired-worker recovery.
- Add authorized enterprise job list, read, cancel, retry and recovery APIs that
  omit broker identifiers, lease owners and raw exception details.
- Add migration `20260728_0013` and deterministic duplicate-delivery,
  authorization-revocation, cancellation, recovery and migration tests.
- Add WP-08 append-only `AuditEvent` evidence with server request IDs, W3C trace
  correlation, keyed source-IP hashing and user-agent family reduction.
- Audit authentication, administrative, sensitive-read, authorization-denial and
  worker-terminal activity through the centralized route and job policy layers.
- Add tenant-scoped redacted audit list and bounded JSONL export APIs requiring
  `audit.read`.
- Add positive metadata allowlisting, secret/canary redaction, event digests and
  retention eligibility without a runtime deletion path.
- Add migration `20260728_0014` with SQLite mutation triggers and PostgreSQL
  runtime privilege revocation, FORCE RLS, native immutability trigger and a
  separate privileged aging role.
- Add deterministic audit rollback, leakage, isolation, correlation, immutability,
  API/export and migration tests, plus PostgreSQL runtime mutation verification.
- Add WP-09 organization model policy with provider/model/task allowlists,
  project data classification and fail-closed external-provider boundaries.
- Add durable quota reservations, immutable usage evidence, actual provider/model
  settlement and organization/project/task cost summaries.
- Add atomic Redis request, token and concurrency admission with hard/soft quotas,
  stable denial codes, bounded fallback and explicit fail-open behavior.
- Govern text, multimodal, dataset, benchmark and realtime voice connection paths
  before provider construction, with redacted policy/quota/usage APIs and export.
- Add migration `20260728_0015`, forced PostgreSQL tenant RLS, runtime DELETE
  revocation and deterministic governance, concurrency, voice and rollback tests.
- Add WP-10 versioned organization retention policies, scoped legal holds and
  fail-closed deletion blocking across both reviewed and legacy project paths.
- Add checksum-verified asynchronous organization/project/learner exports with
  immutable manifests, bounded lifetime, optional private object inclusion and
  authorization revalidation on every download.
- Add idempotent data-subject export/delete requests with independent human
  approval, legal-hold blocking, resumable jobs and relational/object convergence
  evidence.
- Add human review, assignment, decision and appeal cases backed by append-only
  events; model-authored evidence can open a case but cannot write a final decision.
- Add migration `20260728_0016`, PostgreSQL FORCE RLS/runtime privilege controls
  and deterministic lifecycle, dual-control, export, legal-hold, review and
  rollback tests.

- Add complete Planner v6 reciprocal real-provider evidence for all seven built-in
  templates: 30 unique cases per template, 420 case evaluations and 840 anonymous
  A/B arms across Qwen and OpenAI.
- Add a focused open-answer adjudication path and structured semantic,
  functional-criterion, source-conflict, rubric-issue and error-classification
  evidence for defensible alternatives.
- Commit the compact aggregate Planner v6 evidence and full acceptance report while
  keeping large raw provider checkpoints outside Git.

- Add the v0.8 industry template platform research package covering immutable
  template versions, deterministic compilation, policy-bounded overrides, session
  snapshots, lifecycle APIs, behavioral evaluation and an implementation backlog.
- Start the v0.8 implementation line with a strict template contract, safe YAML/JSON
  parsing, semantic validation and deterministic compilation.
- Add the reviewed thesis-defense compatibility template, compact built-in catalog
  API, template health API and packaged-resource verification.
- Add immutable scenario-template persistence, lifecycle and authoring APIs,
  idempotent built-in seeding and additive Alembic migration `20260723_0006`.
- Add project default template bindings and optional text/voice session template
  selection with deterministic override precedence.
- Persist immutable effective template snapshots, compiler versions, overrides and
  SHA-256 fingerprints on exam sessions through migration `20260723_0007`.
- Add session-template inspection with fingerprint verification and preserve
  template-free compatibility for legacy teaching and interview requests.
- Add immutable `academic.thesis_defense@1.1.0` with bounded follow-up overrides
  while retaining the published `1.0.0` artifact.
- Add immutable `academic.thesis_defense@1.2.0` with assumption and critical
  reflection question types while retaining v1.0 and v1.1.
- Feed compiled objectives, allowed question types, coverage requirements,
  difficulty bounds and question limits into blueprint planning.
- Record objective mappings and explicit met/impossible coverage results on
  template-guided blueprints.
- Make adaptive selection honor the session snapshot's allowed types, difficulty
  bounds and unmet objective coverage, with the effective contract recorded in
  decision audit events.
- Add one effective conversation-policy contract shared by text, OpenAI Realtime
  and Qwen Realtime sessions.
- Authorize every text policy action against the template allowlist and record
  requested actions, effective actions and deterministic fallback reasons.
- Enforce template hint, correction and answer-disclosure boundaries in runtime
  configuration and realtime voice instructions.
- Require both template permission and user opt-in for proactive examiner
  interruption while preserving learner barge-in.
- Upgrade template validation through `template-validator-v3`, requiring every
  conversation policy to include a terminal `END` action and every assessment
  dimension to use a registered deterministic rubric.
- Add `template-assessment-v1` with exact weighted score recomputation, localized
  rubric anchors and answer/source evidence on every dimension score.
- Apply the immutable session snapshot's assessment scale, dimension weights,
  assisted-performance policy and aggregate policy to text and finalized voice
  answers.
- Add objective-weighted report aggregation, objective evidence, dimension
  evidence, template identity/fingerprint metadata and registered report sections.
- Support `no_total` coaching reports without exposing a total score while
  preserving deterministic internal diagnostics for adaptive selection.
- Resolve required disclaimers from a reviewed registry and keep interaction,
  preference, emotion and voice timing signals outside correctness scoring.
- Add six reviewed bilingual built-in scenarios for grant review, course oral
  practice, technical interview practice, product knowledge training, sales
  objection practice and project review facilitation.
- Give every built-in scenario distinct objectives, question taxonomy, difficulty,
  assistance, conversation, assessment, report, safety and presentation policies.
- Add behavior-signature tests requiring every intended-distinct scenario pair to
  differ in at least three runtime dimensions.
- Add explicit human-review, protected-trait, personality/emotion and automated
  employment/admission decision boundaries across the built-in catalog.
- Expand persisted built-in health checks to seven template identities and nine
  immutable versions.
- Add bounded YAML/JSON template import that always assigns local ownership,
  `draft` lifecycle and `local_draft` trust regardless of imported metadata.
- Add source-only JSON/YAML template export with explicit attachment, fingerprint
  and export-contract headers.
- Add deterministic semantic template diff grouped by behavioral policy section.
- Add stable transfer error contracts and an explicit local-authoring
  authorization dependency seam for the v0.9 identity and RBAC implementation.
- Add a responsive scenario-template library with category, risk and lifecycle
  filters, visible trust metadata and published-template session selection.
- Add a structured local-draft editor for objectives, questioning, assistance,
  assessment, report and safety policies, with advanced JSON kept optional.
- Add effective-policy preview, validation, compilation, clone, lifecycle,
  import/export and semantic-diff workflows to the browser application.
- Apply the selected published template consistently to blueprint generation,
  text sessions and realtime voice sessions.
- Add browser and static regression coverage for mobile layout, contract-safe
  correction timing and template request wiring.
- Add a deterministic v0.8 template evaluation runner and CLI covering validation,
  recompilation, platform invariants, 21-pair distinctness, override boundaries and
  local performance without paid-model calls.
- Keep real-provider relevance, Docker Compose and Vultr rehearsal gates explicitly
  held instead of allowing deterministic or Mock results to authorize release.
- Add a provider-contract probe for compiled scenario templates with actual model,
  token, latency, coverage and violation evidence but no credentials or prompts in
  its output.
- Add one bounded Planner repair attempt when a real provider returns a question
  type, difficulty or objective mapping outside the compiled template contract.
- Accept validated Qwen and independent-provider probe reports as evidence for only
  the corresponding provider gates; relevance, Compose and Vultr gates remain held.
- Allow Compose deployments to inject a separate environment file and host data
  directory while preserving `.env` and `./data` defaults.
- Add an isolated v0.8 Compose rehearsal for configuration, build, migration,
  health, template gates and SQLite backup inspection without touching the active
  project or using paid-model credentials.
- Add a fingerprinted frozen relevance corpus spanning all seven built-in
  scenarios, with 210 cases balanced across language, difficulty and answer
  quality.
- Add deterministic corpus validation plus cross-provider blind-judge evidence
  aggregation, confidence intervals and release thresholds for at least three
  complete scenarios.
- Reject Mock, self-judged, stale-fingerprint and incomplete relevance evidence
  instead of allowing structural provider probes to stand in for scenario quality.
- Add independent baseline/scenario generation, deterministic A/B blinding and
  reciprocal cross-provider judging for scenario relevance.
- Require release relevance artifacts to come from the production
  `SessionPlanner` path; keep batched contract generation as non-release
  calibration only.
- Feed scenario identity, presentation, assistance, assessment and report context
  into Planner generation so templates alter examiner behavior beyond taxonomy.
- Add reviewed role/style behavior guidance and require scenario-native questions
  that remain distinguishable without a visible role label.
- Detect stacked main questions, move secondary probes to follow-ups through bounded
  semantic repair, and fail closed after repeated contract violations.

### Changed

- Reconcile semantically equivalent and independently accepted defensible answers
  to full expected-point credit without promoting explicit source contradictions or
  vague answers.
- Refine the Planner v6 single-task validator so Chinese judgment markers and quoted
  customer questions are treated as context, while English `who ... and what ...`
  prompts are rejected as stacked tasks.
- Add atomic per-batch relevance checkpoints and metadata-safe `--resume`, verified
  by recovering a real Qwen timeout without losing completed cases.
- Complete reciprocal Qwen/OpenAI 30-case blind evaluation for product knowledge,
  sales objection and project review; all three pass relevance, quality, grounding,
  single-question and safety thresholds.

### Fixed

- Reject semantically stacked main questions and follow-ups even when a model
  hides multiple requests behind one question mark.
- Preserve analytical difficulty during Planner contract repair instead of
  collapsing a question into page-location or term recall.
- Scope stacked-request detection to the final explicit request so declarative
  source phrases do not trigger false positives.
- Replace the Mock planner's compound assumption question with single-task main
  and follow-up questions.
- Prefer CJK-capable fonts for logical document previews and install Noto CJK in
  the Docker image so Chinese evidence remains readable to users and vision models.
- Require visual-evidence output to follow the document language, including
  Simplified Chinese for `zh-CN` projects.
- Show only the newest visual-analysis result for each evidence asset in the
  browser while preserving the complete backend audit history.
- Ignore isolated runtime-data and alternate virtual-environment directories so
  local acceptance artifacts cannot enter release commits.

## [0.7.0-rc.2] - 2026-07-23

### Added

- Complete the v0.7 long-term learner lifecycle with user-started retests,
  registry-limited confirmed preferences, a responsive memory center, append-only
  corrections, short-lived JSON export and scoped asynchronous deletion.
- Add deterministic longitudinal evaluation reports with explicit held gates,
  sample counts and uncertainty, plus PostgreSQL migration/domain CI.

- Add the first v0.7 implementation foundation: HMAC-derived opaque learner
  identities, explicit memory controls, confirmed subject links, canonical concepts,
  reviewed knowledge-unit mappings and an idempotent evidence-bound memory ledger.
- Add replayable longitudinal concept states with observed/predicted separation,
  three deterministic retention baselines, growth series and recommendation-only
  shadow retest plans with explainable ranking.
- Add the v0.7 long-term learner intelligence research package covering revocable
  memory, opaque identity links, canonical concepts, retention baselines, shadow
  retest planning, confirmed preferences and lifecycle evaluation.
- Add frozen provider-neutral realtime signal and capability schemas for v0.6.
- Add deterministic OpenAI and Qwen event normalizers with provider-event
  idempotency.
- Add sanitized unknown-event signals instead of silently dropping new provider
  events.
- Add recorded OpenAI and Qwen event traces and replay contract tests.
- Add a provider-neutral assessment contract with correctness aliases, strict
  unknown-label rejection and point-level expected-answer decisions.
- Add assessment report v2 with independent, assisted and learning-gain
  trajectories per main question.
- Add persisted provider latency, retry and JSON-repair telemetry with p50/p95
  metrics and a reversible Alembic migration.

### Changed

- Complete the v0.7 release hardening pass with dynamic API `no-store` headers,
  versioned browser assets and a real `qwen-plus` adaptive-session acceptance run.
- Start the v0.6 development line as `0.6.0.dev0` without changing active voice
  behavior.
- Label the browser application consistently as the v0.6 development line.
- Compute answer coverage deterministically from point assessments and score
  correctness, grounding, reasoning and boundary awareness separately.
- Use independent main-question performance for defense-mode totals while
  preserving assisted performance as a separate diagnostic signal.

### Fixed

- Gate microphone uplink until the examiner's initial realtime response completes,
  preventing ambient input from racing the opening question on both OpenAI WebRTC
  and Qwen WebSocket sessions.
- Measure first-response latency from `response.create`, ignore empty user
  transcripts, and surface a bounded Qwen opening-response timeout.
- Evaluate follow-up answers against the active follow-up text instead of the
  parent main question.
- Continue adaptive sessions after the follow-up limit when remaining questions
  reference prerequisites that are outside the current blueprint graph.
- Isolate automated tests from real provider defaults in a developer `.env`.
- Normalize real Qwen labels such as `correct` and `partially_correct` instead of
  silently under-scoring them as unknown values.
- Enforce configured output language for generated blueprints with one bounded
  correction attempt.
- Clear the active-analysis hint after completion and version the browser script
  URL so deployments do not retain stale report rendering code.

## [0.5.0-rc.4] - 2026-07-16

### Added

- Add DashScope `qwen-plus` as a first-class text, structured-output and evaluation provider.
- Add DashScope `qwen3-vl-plus` for page, chart, table and formula visual review.
- Add an independent visual-model selector that only lists image-capable profiles.
- Record the actual visual model in usage and analysis audit data.

### Changed

- Share the server-side `DASHSCOPE_API_KEY` across Qwen text, vision and realtime voice without exposing it to the browser.

## [0.5.0-rc.3] - 2026-07-16

### Fixed

- Consume browser API response bodies exactly once so backend errors remain visible.
- Return an actionable JSON 503 when Redis/Celery cannot accept a background job.
- Support single-process visual-review testing with `CELERY_ALWAYS_EAGER=true`.

## [0.5.0-rc.2] - 2026-07-16

### Fixed

- Explicitly close SQLite backup connections so temporary snapshots can be removed on Windows.
- Read exported JSONL as UTF-8 in cross-platform CLI tests.
- Synchronize `uv.lock` with the Alembic dependency and release-candidate version.

## [0.5.0-rc.1] - 2026-07-16

### Added

- Alembic 迁移、Knowledge Unit、Question Mapping、Learner Subject、Knowledge State 和不可变 Evidence Event。
- Difficulty Controller、Adaptive Question Selector、跨会话状态继承和已问题目新颖度控制。
- 可审计的 Adaptive Decision，包含候选分、原因、策略权重和版本。
- `fixed` / `adaptive` 会话策略切换与确定性成对策略基准。
- Knowledge Map、Weakness Map、Improvement Path 以及知识点级回答证据。
- 自适应语音最终转录进入统一 Analyzer/Evaluator/Knowledge State 管线。

### Changed

- Docker 镜像包含 Alembic 配置和迁移文件。
- GitHub 更新脚本先拉取并构建，再短暂停服迁移和切换版本。
- UI 默认新评估会话使用自适应策略，旧 API 请求仍默认 `fixed`。

## [0.4.1] - 2026-07-16

### Added

- 蓝图生成可独立选择 OpenAI、Anthropic、Gemini 或 Ollama 模型。
- 文本答辩可独立选择模型，不再与蓝图生成模型绑定。
- AutoDL/Vultr Docker 部署持久化 Ollama 模型目录。

### Changed

- 将当前已部署、已验证的 v0.4 系列快照正式固化为可追溯版本。

## [0.4.0] - 2026-07-10

### Added

- OpenAI Realtime WebRTC 实时语音答辩。
- Semantic VAD、用户插话、实时字幕和按住说话模式。
- PDF/PPTX/DOCX 多模态证据、Golden Dataset 与 Benchmark。
- Redis/Celery 后台任务、Caddy HTTPS 和 Docker Compose 部署。

[Unreleased]: https://github.com/lanhung/ai-examiner/compare/v0.4.1...HEAD
[0.5.0-rc.4]: https://github.com/lanhung/ai-examiner/compare/v0.5.0-rc.3...v0.5.0-rc.4
[0.5.0-rc.3]: https://github.com/lanhung/ai-examiner/compare/v0.5.0-rc.2...v0.5.0-rc.3
[0.5.0-rc.2]: https://github.com/lanhung/ai-examiner/compare/v0.5.0-rc.1...v0.5.0-rc.2
[0.5.0-rc.1]: https://github.com/lanhung/ai-examiner/compare/v0.4.1...v0.5.0-rc.1
[0.4.1]: https://github.com/lanhung/ai-examiner/compare/9327580...v0.4.1
[0.4.0]: https://github.com/lanhung/ai-examiner/commit/9327580
