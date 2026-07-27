# AI Examiner Version Plan

## 1. Purpose

This file is the authoritative version and branch status for Codex and other coding agents. Read it before changing code.

## 2. Current state

| Line | Version | Branch or tag | Status | Deployment |
|---|---|---|---|---|
| Stable | 0.4.1 | `main`, `v0.4.1` | Released | Production evaluation |
| Development | 0.5.0rc4 | `develop/v0.5.0` | Feature frozen | Separate worktree only |
| Release snapshot | 0.5.0rc4 | `release/v0.5.0`, `v0.5.0-rc.4` | Awaiting final acceptance | Staging evaluation |
| Research | 0.6.0 | `research/v0.6.0` | Architecture and evaluation design | Not deployable |
| Next development | 0.6.0.dev0 | `develop/v0.6.0` | Assessment stabilization complete; real Qwen regression verified | Local evaluation only |
| Next research | 0.7.0 | `research/v0.7.0` | Long-term learner intelligence architecture and evaluation design | Not deployable |
| Next implementation | 0.7.0rc2 | `develop/v0.7.0` | WP-01 to WP-12 complete; real Qwen, browser and real-audio acceptance passed | Staging only |
| v0.7 candidate | 0.7.0rc2 | `v0.7.0-rc.2` | Candidate release; Vultr Compose promotion gate remains | Staging only |
| Upcoming research | 0.8.0 | `research/v0.8.0` | Industry template architecture, API, evaluation and implementation design | Not deployable |
| Current implementation | 0.8.0.dev0 | `develop/v0.8.0` | Software and AI quality gates pass, including three reciprocal 30-case templates; Docker/Vultr promotion rehearsal remains held | Local evaluation only |
| Current research | 0.9.0 | `research/v0.9.0` | Enterprise design complete; WP-01 PostgreSQL full-suite parity gate in validation | Not deployable |
| Release candidate | 0.5.0rc4 | `v0.5.0-rc.4` | Ready for staging | Staging only |
| Final | 0.5.0 | `main`, `v0.5.0` | Not created | Production after acceptance |

## 3. Branch policy

- `main` must always be deployable with the documented Docker Compose commands.
- `develop/v0.5.0` is the v0.5 integration branch.
- `release/v0.5.0` is the immutable-source release snapshot while v0.5 final
  acceptance is pending. Corrections require a new RC commit and tag.
- `research/v0.6.0` contains design documents and experiments only. It must not be
  deployed and must not change the package version.
- ADR-003 and the v0.6 evaluation plan are accepted for implementation.
  `develop/v0.6.0` is based on the v0.5 release snapshot plus the approved research
  documents.
- v0.6 feature branches use `feature/v0.6-<short-name>` and branch from
  `develop/v0.6.0`.
- `research/v0.7.0` contains design documents and disposable experiments only. It
  must not be deployed and must not change the package version.
- ADR-004, the v0.7 architecture and evaluation plan are accepted for the first
  implementation increment. `develop/v0.7.0` is based on the accepted v0.6
  integration plus the reviewed v0.7 research documents.
- v0.7 feature branches use `feature/v0.7-<short-name>` and branch from
  `develop/v0.7.0`.
- `research/v0.8.0` contains template-platform design documents and disposable
  experiments only. It must not be deployed and must not change the package version.
- v0.8 implementation begins on `develop/v0.8.0` only after ADR-005 and all research
  gates are accepted. Feature branches use `feature/v0.8-<short-name>`.
- `research/v0.9.0` contains enterprise architecture, API, security, migration and
  evaluation design only. It must not be deployed and must keep package version
  `0.8.0.dev0`.
- Do not create `develop/v0.9.0` until ADR-006 and the full v0.9 research gate are
  accepted. Feature branches will use `feature/v0.9-<short-name>`.
- Feature branches use `feature/v0.5-<short-name>` and branch from `develop/v0.5.0`.
- Bug fixes for the stable release use `fix/v0.4-<short-name>` and merge into `main`; required fixes are then forward-merged into development.
- Do not develop unreleased features in the production worktree.
- Do not rewrite a published release tag.

## 4. Worktree policy

The production and development trees are separate:

```text
/root/autodl-tmp/ai-examiner-mvp/ai-examiner-mvp-v0.4.0
  branch: main
  purpose: running stable service

/root/autodl-tmp/ai-examiner-mvp/ai-examiner-v0.5-dev
  branch: develop/v0.5.0
  purpose: v0.5 development and tests
```

Do not point the production startup script to the development worktree.

## 5. Version lifecycle

1. During development, package version is `0.5.0.dev0`.
2. At feature freeze, publish sequential immutable candidates such as `0.5.0rc1` / `v0.5.0-rc.1`; candidate fixes increment the RC number without rewriting prior tags.
3. Run migrations, regression tests, behavioral evals and a staging deployment from the release candidate.
4. After acceptance, set version to `0.5.0`, update changelog and release notes, merge to `main`, and create annotated tag `v0.5.0`.
5. Tags are immutable. Corrections after release use `v0.5.1`.

Version must agree in:

- `pyproject.toml`
- `src/ai_examiner/__init__.py`
- `README.md`
- `PROJECT_STATUS.md`
- `CHANGELOG.md`
- release notes

## 6. Commit policy

Use small, reviewable commits with one purpose:

```text
docs: define v0.5 adaptive cognitive architecture
feat: persist knowledge state events
feat: select next question adaptively
test: compare adaptive and fixed policies
release: AI Examiner v0.5.0
```

Do not commit generated archives, Base64 chunks, import parts, runtime databases, uploads, model files or API keys. Standard Git pushes must send normal source changes as a compressed packfile.

## 7. Release gate

A release cannot be tagged until all applicable checks pass:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests
node --check src/ai_examiner/static/app.js
git diff --check
```

Also required for v0.5:

- database migration and rollback rehearsal;
- fixed strategy regression suite;
- adaptive strategy behavioral evaluation;
- Golden Dataset comparison report;
- clean install and Docker Compose build;
- backup and restore verification;
- secret scan;
- updated API, architecture, migration and deployment documents.

## 8. Deployment policy

Only `main`, an RC tag, or a final tag may be deployed. Production update remains:

```bash
./deploy/backup.sh
git pull --ff-only origin main
docker compose down --remove-orphans
docker compose up -d --build --remove-orphans
```

Never use `docker compose down -v` during a normal update.

## 9. v0.6 research gate

Do not begin broad v0.6 implementation until all of the following are reviewed:

- `docs/decisions/ADR-003-REALTIME-CONVERSATION-CONTROL.md`;
- `docs/architecture/V0_6_ADVANCED_CONVERSATION_TIMING.md`;
- `docs/evaluation/V0_6_VOICE_EVALUATION_PLAN.md`;
- provider capability matrix for OpenAI and Qwen;
- migration strategy for append-only conversation and interruption events;
- feature-flag and rollback strategy.

v0.6 implementation order is fixed:

```text
normalized events and shadow FSM
-> user barge-in and recovery
-> observe-only active interruption
-> controlled low/normal rollout
-> release hardening
```

No v0.6 tag is created during research. The first implementation version is
`0.6.0.dev0`; release candidates begin only after all behavioral gates pass.

## 10. v0.7 research gate

Do not begin broad v0.7 implementation until all of the following are reviewed:

- `docs/decisions/ADR-004-LONG-TERM-LEARNER-MEMORY.md`;
- `docs/architecture/V0_7_LONG_TERM_LEARNER_INTELLIGENCE.md`;
- `docs/api/V0_7_LONG_TERM_MEMORY_API.md`;
- `docs/evaluation/V0_7_LONG_TERM_MEMORY_EVALUATION_PLAN.md`;
- `docs/product/V0_7_IMPLEMENTATION_BACKLOG.md`;
- concept identity and cross-project mapping policy;
- export, correction and deletion semantics;
- feature flags for shadow retention and retest planning.

v0.7 implementation order is fixed:

```text
memory policy and opaque identity
-> canonical concept mapping in shadow mode
-> longitudinal event ledger and replay
-> retention baselines and growth state
-> retest planner in shadow mode
-> user-confirmed preferences
-> memory center, export and deletion
-> longitudinal evaluation and release hardening
```

No v0.7 tag is created during research. The research branch remains on the v0.6
package version. The first implementation branch uses `0.7.0.dev0` only after the
research gate is accepted.

The first candidate used `0.7.0rc1` / `v0.7.0-rc.1`. The current corrected
candidate uses `0.7.0rc2` / `v0.7.0-rc.2`. The 300-pair concept-mapping
activation gate and automatic retest injection remain held; those features do not
block the candidate because their active behavior stays disabled.

## 11. v0.8 research gate

Do not create `develop/v0.8.0` until all of the following are reviewed:

- `docs/decisions/ADR-005-VERSIONED-SCENARIO-TEMPLATES.md`;
- `docs/architecture/V0_8_INDUSTRY_TEMPLATE_PLATFORM.md`;
- `docs/api/V0_8_TEMPLATE_API.md`;
- `docs/evaluation/V0_8_TEMPLATE_EVALUATION_PLAN.md`;
- `docs/product/V0_8_IMPLEMENTATION_BACKLOG.md`;
- template schema, compiler determinism and override precedence;
- built-in scenario list and prohibited-use boundary;
- legacy mode compatibility and session snapshot migration;
- behavioral distinctness and platform-invariant gates.

v0.8 implementation order is fixed:

```text
schema and safe parser
-> deterministic compiler and override lattice
-> persistence and immutable lifecycle
-> legacy mappings and session snapshots
-> Planner, Policy, Assessment and Report integration
-> reviewed built-in templates
-> API and structured editor
-> behavioral evaluation and release hardening
```

No v0.8 tag is created during research. This branch remains on package version
`0.7.0rc2`. The first implementation branch uses `0.8.0.dev0` only after the
research gate is accepted.

## 12. v0.9 research gate

Do not create `develop/v0.9.0` until all of the following are reviewed:

- `docs/decisions/ADR-006-ENTERPRISE-TENANCY-AND-IDENTITY.md`;
- `docs/architecture/V0_9_ENTERPRISE_PLATFORM.md`;
- `docs/api/V0_9_ENTERPRISE_API.md`;
- `docs/security/V0_9_ENTERPRISE_THREAT_MODEL.md`;
- `docs/security/V0_9_RESOURCE_AND_CAPABILITY_MATRIX.md`;
- `docs/evaluation/V0_9_ENTERPRISE_EVALUATION_PLAN.md`;
- `docs/product/V0_9_IMPLEMENTATION_BACKLOG.md`;
- `docs/deployment/V0_9_DATA_AND_DEPLOYMENT_MIGRATION.md`;
- complete model ownership and route/capability matrices;
- OIDC token validation and key-rotation prototype;
- PostgreSQL runtime/migration roles and RLS proof tests;
- restartable SQLite-to-PostgreSQL migration prototype;
- local/S3 storage contract prototype;
- cross-tenant API and worker adversarial tests;
- backup, object restore and disaster-recovery objectives.

v0.9 implementation order is fixed:

```text
PostgreSQL parity
-> organization and principal foundation
-> OIDC authentication
-> capability authorization
-> tenant ownership and RLS
-> object storage abstraction
-> tenant-aware job hardening
-> audit, model governance and quota
-> retention, export, deletion and human review
-> OpenTelemetry and enterprise Compose
-> UI, security evaluation and release hardening
```

No v0.9 tag is created during research. The branch remains on package version
`0.8.0.dev0`. The first implementation branch uses `0.9.0.dev0` only after this gate
is accepted.
