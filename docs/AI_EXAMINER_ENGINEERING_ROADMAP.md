# AI Examiner Engineering Roadmap

Document version: 2.0  
Audience: Codex and other coding agents  
Current development target: v0.6.0 implementation and v0.7.0 research

## 0. How to use this document

Before coding, read:

1. `README.md`
2. `docs/VERSION_PLAN.md`
3. this roadmap
4. the current version architecture and evaluation plan
5. relevant API and deployment documents

This roadmap defines product direction and non-negotiable boundaries. The current version design document defines implementation details. Existing code and tests remain the source of truth for actual behavior.

## 1. Product mission

AI Examiner is an inquiry-first AI platform. It should behave like a skilled examiner, teacher or research collaborator who discovers what the user understands by asking, following up, challenging, hinting and evaluating.

```text
AI Examiner
  = Question Engine
  + Conversation Engine
  + Assessment Engine
  + Knowledge Engine
  + Cognitive State
```

The goal is not to maximize generated answers. The goal is to gather evidence about understanding and help the user improve.

## 2. Non-negotiable principles

### Question first

Default behavior seeks the user's reasoning, missing evidence, assumptions and misconceptions before supplying an answer.

### Evidence-backed assessment

Every important conclusion must link to:

- the original user answer or transcript;
- the tested knowledge unit;
- the document evidence when applicable;
- the rubric and scoring reason;
- the model, prompt and policy versions.

### Separated responsibilities

Interviewer, Analyzer, Evaluator, Policy, Grounding and Reporter are separate responsibilities even if some deployments combine model calls for cost.

### Explicit control

Critical behavior such as one-question-at-a-time, question limits, assistance rules, interruption authorization and adaptive selection must be enforced in software, not only in prompts.

### Testable AI behavior

Prompt, model and policy changes require a frozen dataset comparison. Do not merge because an anecdotal conversation looked better.

### Safe evolution

Keep Docker Compose deployable, preserve `.env` and `data/`, use additive migrations, document rollback, and never commit keys or user data.

## 3. Current baseline: v0.4.1

The stable system includes:

- FastAPI, SQLAlchemy, SQLite, Redis and Celery;
- Docker Compose deployment on Vultr/AutoDL;
- PDF, PPTX, DOCX, TXT and Markdown ingestion;
- page-level evidence, previews, visual analysis and multi-document comparison;
- blueprint planning and grounded question generation;
- text examination with Analyzer, Policy, Evaluator and Reporter;
- AI-curated Golden Dataset, synthetic answers and model benchmarks;
- OpenAI and Qwen-compatible realtime voice paths;
- WebRTC or streaming voice, transcripts, VAD and interruption support;
- selectable models for blueprint and text examination;
- local Ollama provider and persistent model storage.

Known architectural debt:

- fixed question sequence;
- per-question JSON mastery rather than concept state;
- no migration framework;
- SQLite concurrency constraints;
- limited long-term learner identity;
- architecture/evaluation documents have version drift;
- some provider behavior still needs real-session latency and quality measurements.

## 4. v0.5.0: Adaptive Cognitive Engine

Objective: choose the next action and question based on evidence about the user's current knowledge.

Required capabilities:

- knowledge units and question mappings;
- append-only knowledge evidence events;
- session and pseudonymous learner state;
- mastery, uncertainty and misconception lifecycle;
- adaptive selector and bounded difficulty controller;
- fixed strategy compatibility and experimental control;
- auditable decision records;
- knowledge map, weakness map and improvement path;
- Golden Dataset comparison against fixed sequence;
- Alembic migration and rollback.

Authoritative design:

- `docs/architecture/V0_5_ADAPTIVE_COGNITIVE_ENGINE.md`
- `docs/evaluation/V0_5_EVALUATION_PLAN.md`
- `docs/decisions/ADR-002-ADAPTIVE-STATE-EVENTS.md`

Do not add active AI interruption, full accounts or a graph database to v0.5 unless required by an accepted architecture decision.

## 5. v0.6.0: Advanced conversation timing

Objective: make voice interaction more natural while preserving the cognitive engine as authority.

Planned capabilities:

- explicit listening, thinking, speaking, interrupted and recovering states;
- timing engine using audio, text completeness and session context;
- user interruption with unfinished-response recovery;
- configurable active AI interruption levels;
- off-topic and repetition detection;
- waiting tolerance and short thinking pauses;
- strict, normal and low-interruption preferences;
- latency, interruption success and false-interruption metrics.

Requirements:

- active interruption can be disabled;
- every interruption has a reason and event record;
- assessment uses transcript content, not accent, voice or personality inference;
- text mode continues to work without voice services.

Accepted implementation order after architecture review:

```text
normalized provider events and shadow state machine
-> reliable user barge-in and recovery
-> observe-only active interruption
-> controlled low/normal rollout
-> release hardening
```

Detailed specifications:

- `docs/decisions/ADR-003-REALTIME-CONVERSATION-CONTROL.md`;
- `docs/architecture/V0_6_ADVANCED_CONVERSATION_TIMING.md`;
- `docs/evaluation/V0_6_VOICE_EVALUATION_PLAN.md`;
- `docs/product/V0_6_IMPLEMENTATION_BACKLOG.md`.

## 6. v0.7.0: Long-term learner intelligence

Objective: understand change across sessions without turning uncertain estimates into permanent labels.

Planned capabilities:

- secure user identity or external subject mapping;
- previous sessions and growth curves;
- spaced retest planning;
- preferred interaction and explanation style;
- concept retention and regression signals;
- memory review, export and deletion;
- PostgreSQL migration preparation or completion.

Long-term memory must store useful evidence and preferences, not unrestricted summaries of everything the user says.

Accepted research direction:

- preserve append-only assessment evidence as the source of observed performance;
- introduce an optional opaque cross-project identity without pulling full account
  and organization scope into v0.7;
- map project knowledge units to versioned canonical concepts conservatively;
- keep observed mastery separate from predicted retention;
- run retention and retest decisions in shadow mode before active use;
- persist only explicit or user-confirmed preferences from an allowed registry;
- provide memory inspection, correction, export, disable and deletion;
- keep calculations deterministic, versioned and rebuildable.

Detailed research specifications:

- `docs/decisions/ADR-004-LONG-TERM-LEARNER-MEMORY.md`;
- `docs/architecture/V0_7_LONG_TERM_LEARNER_INTELLIGENCE.md`;
- `docs/api/V0_7_LONG_TERM_MEMORY_API.md`;
- `docs/evaluation/V0_7_LONG_TERM_MEMORY_EVALUATION_PLAN.md`;
- `docs/product/V0_7_IMPLEMENTATION_BACKLOG.md`.

## 7. v0.8.0: Industry template platform

Objective: reuse the engine across academic, education and enterprise training scenarios.

Templates define:

```yaml
role:
goal:
allowed_assistance:
question_types:
difficulty_policy:
interruption_policy:
rubric:
report:
safety_rules:
```

Initial templates:

- paper and thesis defense;
- grant review and doctoral qualification;
- course oral examination;
- technical interview practice;
- product and sales training;
- customer service and SOP assessment;
- project review.

A template must change policy and evaluation behavior, not only rename the AI role.

## 8. v0.9.0: Enterprise platform

Objective: support real institutional deployment.

Planned capabilities:

- organizations, users, roles and permissions;
- PostgreSQL, S3/MinIO and robust queues;
- SSO/OIDC and audit logs;
- data retention, deletion and export;
- model allowlists and private model gateways;
- quotas, rate limits and cost ownership;
- OpenTelemetry, Prometheus/Grafana and alerts;
- backup, restore and disaster rehearsal;
- single-server and private-cloud Compose profiles.

AI remains decision support in high-stakes academic, hiring, medical or employment contexts. Human review and appeal paths are required.

## 9. v1.0.0: Commercial product

Objective: stable delivery rather than feature accumulation.

Required qualities:

- reliable onboarding and sample projects;
- accessible Chinese and English interfaces;
- subscriptions, licenses or quotas;
- documented Exam, Evaluation, Template and Voice APIs;
- versioned migrations and backward compatibility policy;
- SLA metrics, staged rollout and one-command rollback;
- administrator, deployment and user documentation;
- security and privacy review.

## 10. v1.1-v1.2: Hardware preparation and POC

Only begin after software usage demonstrates a need for a dedicated device.

v1.1 defines:

- device registration and authentication;
- kiosk mode;
- microphone, speaker, screen, button and light events;
- wake word/local VAD integration;
- offline queue and cloud synchronization;
- remote configuration, health and update protocol.

v1.2 validates a simple desktop device using an off-the-shelf mini PC, microphone array, display, speaker, camera and physical mute control. Do not begin with a moving robot or custom mainboard.

## 11. Target architecture

```text
Web / Mobile / Device
        |
Realtime media and transcript normalization
        |
Conversation state machine
        |
Policy Controller ---- Adaptive Question Selector
        |                         |
Answer Analyzer            Knowledge State
        |                         |
Evaluator ---------------- Evidence Events
        |
Grounding / Rubric / Knowledge Units
        |
Reports, Replay, Benchmarks and Dataset Evolution
```

Provider integrations remain behind a model gateway. Provider-specific behavior must not leak into the core cognitive state contract.

## 12. Data strategy

The defensible asset is not a model name. It is a versioned corpus of:

- questions and knowledge mappings;
- answer variants;
- misconceptions and follow-ups;
- policy decisions and outcomes;
- evidence-backed evaluations;
- expert calibration;
- longitudinal improvement.

Maintain three datasets:

- Golden: expected high-quality behavior;
- Adversarial: injection, evasion, confident errors and edge cases;
- Regression: every real defect found in development or use.

AI may produce most annotations through independent models, criticism and consensus. A small human sample remains necessary to detect shared model bias.

## 13. Model strategy

- strong models for planning, consensus and difficult evaluation;
- lower-cost models or deterministic rules for classification and routine control;
- real-time models for natural speech, not final authoritative scoring;
- provider routing is configurable and recorded;
- local models are supported where privacy or unit economics justify them;
- no model identifier is a permanent product dependency.

Before training a specialized model, collect enough policy examples to define a stable input/output contract and a meaningful offline benchmark.

## 14. Engineering protocol for Codex

### Before editing

- inspect status and unrelated user changes;
- confirm current branch and version plan;
- read code before proposing architecture;
- run or record baseline tests;
- define acceptance criteria and migration impact.

### During editing

- follow existing module patterns;
- keep Agent responsibilities separate;
- use structured schemas;
- make state changes idempotent where retries are possible;
- add focused tests with each behavior change;
- preserve fixed-mode compatibility during v0.5;
- do not make unrelated refactors.

### After editing

- run tests, lint and JavaScript syntax check;
- run behavioral evals for Prompt/model/policy changes;
- update changelog, architecture, API and migration docs;
- verify Docker Compose configuration;
- inspect `git diff` and scan secrets;
- commit source changes directly with standard Git;
- tag only after release gates pass.

## 15. Git and release requirements

- Stable code lives on `main`.
- Development uses a version branch and separate worktree.
- Use annotated, immutable release tags.
- Never commit `.env`, keys, databases, uploads, evidence files, backups, model weights or generated archives.
- Do not upload Base64 chunks or construct releases from many temporary blobs.
- Use normal `git add`, `git commit` and `git push`; Git will pack changes efficiently.
- Production pulls must be fast-forward only.

See `docs/VERSION_PLAN.md` for the exact current branches and lifecycle.

## 16. Docker and data requirements

Every release must preserve:

- `.env`;
- `data/` and databases;
- uploads, evidence, reports and exports;
- Ollama models and provider configuration;
- Redis/Caddy volumes where applicable.

Required operational path:

```bash
./deploy/backup.sh
git pull --ff-only origin main
docker compose down --remove-orphans
docker compose up -d --build --remove-orphans
```

Do not use `down -v` in a routine update. Schema changes require migration and rollback documentation.

## 17. Security and responsible-use boundaries

- Uploaded documents and answers are untrusted data.
- Prompt injection in documents or answers cannot modify system policy or rubrics.
- API keys stay in environment variables and never reach browser code or logs.
- Keep model/provider usage attributable and auditable.
- Do not infer ability or personality from face, accent, emotion or disability-related signals.
- Provide uncertainty, evidence and human review for consequential use.
- Support deletion and retention controls as identity features arrive.

## 18. Product success metrics

Track together:

- question groundedness and importance;
- relevant follow-up and next-action rate;
- knowledge gap and misconception discovery;
- scoring agreement and evidence validity;
- state calibration and growth detection;
- repeated or wasted question rate;
- dialogue latency, interruption quality and completion rate;
- API errors, task recovery and data integrity;
- cost per document, session, report and quality point.

The project advances when inquiry and assessment improve measurably, not merely when more features are visible.
