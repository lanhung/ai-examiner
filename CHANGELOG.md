# Changelog

AI Examiner 的重要变更记录在此文件。版本号遵循 Semantic Versioning；开发版本使用 PEP 440 标识，例如 `0.5.0.dev0`。

## [Unreleased]

### Added

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
