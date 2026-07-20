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
