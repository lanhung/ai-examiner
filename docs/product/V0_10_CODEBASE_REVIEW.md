# AI Examiner v0.10 Codebase Review

Date: 2026-10-02
Scope: full-project review of `ai-examiner` at commit 7d79846 (`main`, v0.10.0).
Method: local test and lint runs plus five parallel code reviews covering backend
architecture, exam-path security, frontend, the AI layer, and engineering process.
Highest-impact claims were spot-checked directly in the source.

Online copy: https://claude.ai/code/artifact/dc906f19-73c9-4c2b-986e-aa7da31c6468

## Current health

The project is in good shape for its size: every gate passes locally, and the
enterprise substrate is solid. The risks are concentrated in the new
classroom-pilot path, in a handful of fail-open defaults, and in a 6,637-line
`main.py`.

| Check | Result |
| --- | --- |
| ruff check | passed |
| pytest (SQLite, mock provider) | 405 passed, 0 failed, 153 warnings |
| Suite wall time | 9 min 26 s |
| Slowest test | 23.6 s (SQLite migration round trip) |
| Source size | 110 Python files, 38,171 lines |
| Test size | 60 files, 14,329 lines |
| Routes in main.py | 167, no APIRouter |
| Alembic revisions | 18, single head, all with downgrade |
| v0.10.0 git tag | missing (README claims it) |
| Branch protection on main | none |
| Remote branches | 19, of which 15 already merged |

What works well: declarative route policies validated at startup, PostgreSQL
row-level security with a separate runtime role, append-only audit on its own
engine, idempotent jobs with leases and recovery, and a deterministic mock
provider that keeps LLM-dependent tests stable. The student exam page
(`exam.js`) is the best-written frontend file: no `innerHTML`, request timeouts,
double-submit guard, and post-failure reconciliation.

The suite's 9.5 minutes come from dropping and recreating the whole schema for
every test on one shared SQLite file (`tests/conftest.py:71-80`), plus 13 tests
that shell out to Alembic or CLIs.

## 1. Close the pilot-path gaps before more classes use it

These are real defects rather than style. Each is a day or less of work.

| Finding | Severity | Evidence | Fix |
| --- | --- | --- | --- |
| Workbench routes under `/api/*` fetch by primary key with no organization check; only PostgreSQL RLS in enforce mode isolates tenants | High on SQLite or RLS off | `main.py:2449` `get_session`, `:2487` `get_report`, `:2041` `get_golden_dataset`; 130 `db.get` lookups vs 4 `authorize_workbench_resource` calls; `config.py:380-389` accepts OIDC without RLS enforce | Add a `scoped_get(db, Model, id)` helper or a `with_loader_criteria` hook on the tenant mixin; reject `auth_mode=oidc` without `postgres_rls_mode=enforce` |
| Analyzer fails open on relevance | Medium | `agents/analyzer.py:197` and `:407` default `question_relevance` to 1.0; `:198` and `:408` default `directly_addresses_question` to true; `template_assessment.py:215` same. Qwen and Ollama do not enforce the schema natively | Treat omission as a contract violation and run the existing repair pass at `analyzer.py:146`; or default to 0.5 and record `relevance_unverified` |
| Two concurrent answer submissions on one attempt are both graded | Medium | `main.py:3093-3140` and `orchestrator.py:164-168` check only `status == active`; no `with_for_update`, no version check; 150-thread pool | Per-attempt lock or a version column with a conditional UPDATE returning 409 to the loser; add a two-thread test |
| Assignment, join and attempt routes sit outside the route-policy registry | Medium | `authorization.py:551` and `tests/test_authorization_v09.py:177` walk only `/api/v1`; `audit.py:368-374` skips audit when no policy, so publishing an exam or viewing the student dashboard leaves no audit event | Register the 11 new route pairs in `ROUTE_POLICIES`; widen the completeness test to all `/api/` routes; update the capability matrix doc |
| Teacher CSRF defence relies on `Sec-Fetch-Site` | Medium | `Caddyfile.pilot:30-38`; WeChat webviews and Safari before 16.4 do not send it; body-less POST routes such as `/api/sessions/{id}/start` and `/api/prompts/{id}/activate` are form-submittable | Add an Origin or Referer check for write methods in Caddy, or require a custom header the workbench already sends |
| Project deletion on PostgreSQL conflicts with the migration | Medium | Migration 0018 revokes DELETE on assignment tables from the runtime role; `delete_project` relies on FK cascade; only tested on SQLite | Decide pilot is SQLite-only and document it, or add a reviewed deletion path and a PostgreSQL test |
| No request body cap in front of learner endpoints | Low | `Caddyfile.pilot` has no `request_body max_size`; 20,000-char Pydantic limit applies only after the body is parsed | `request_body { max_size 64KB }` inside the learner handle |
| `/health` is public and reveals configuration | Low | `main.py:895-920` returns auth mode, provider, model, RLS mode, storage backend | Return `{"status":"ok"}` publicly; move details to `/ready` behind auth |
| Attempt tokens never expire and cannot be revoked | Low | `services/assignments.py:189-200`; token persists in localStorage on shared devices | Add `token_expires_at` and `revoked_at`; forget the token after an exam-mode report |
| Audit source IP and learner rate-limit IP use different headers | Low | `audit.py:209-212` uses `request.client.host` (always the Caddy IP); `main.py:2894-2902` honours `X-Forwarded-For` | One shared `client_ip` helper |
| Rate limiter is process-local | Low | `services/rate_limit.py`; safe with the single uvicorn process in `Dockerfile:33`, silently multiplied by `--workers N` | Document the single-process requirement, or back it with the Redis already required |

Verified sound: join codes use a 32-character alphabet, so the space is about
1.07 billion, not 1 million; attempt tokens are 256-bit, hashed at rest,
constant-time compared, and bound to organization and attempt; student display
names and IDs never reach audit, telemetry, or logs; exam mode strips hints,
corrections, and answer disclosure at session creation; the OIDC cookie is
HttpOnly, SameSite=Lax, and Secure.

## 2. Product changes for adoption

The adoption review in `docs/product/V0_10_ADOPTION_AND_OPERATIONS_REVIEW.md` is
good and mostly still accurate. Do its first three items, with these corrections
and additions from the code.

- **The waiting complaint is stale.** `exam.js:306-317` already renders a
  "考官正在思考" bubble with a `role="status"` and reduced-motion support. What is
  missing is an elapsed-time hint after about 8 seconds and a slow-network note
  after 30 seconds. Correct the doc. The workbench equivalent at `app.js:1080`
  still shows agent jargon ("Answer Analyzer、Evaluator 和 Policy Controller") to
  teachers.
- **Student drafts are lost on webview kill.** `remember()` at `exam.js:48-56`
  persists only the attempt ID and token, while three error strings promise the
  answer is kept. Persist the textarea to localStorage on input, restore in
  `openChat()`, clear on successful submit. About 15 lines, no backend change.
- **The interviewer never calls a model.** `agents/interviewer.py:5-27` picks
  from template tuples by CRC; the weak-answer case is already honest. Add a
  cheap phrasing call fed the policy decision, the missing point, and the
  student's quote, with the template as fallback on error or timeout. Keep
  `PolicyController` deterministic.
- **The follow-up picker can repeat itself.** `policy.py:46` indexes candidates
  by attempt count, so attempt 2 with one candidate asks the same follow-up
  again. Track asked follow-ups per session and skip near-duplicates.
- **The analyzer prompt never defines a good follow-up.** `followup_candidates`
  is only a schema key at `analyzer.py:84`. Add explicit guidance: probe the
  specific gap, one issue, never reveal the point.
- **The student report leads with a large score.** `exam.js:177-184` renders
  `overall_score / max_score` at 2rem above strengths. Reorder to strengths and
  next steps first; show the score as a small band or progress bar.
- **Practice mode has no reference answers.** `answer_disclosure` is off in both
  modes. Enable it for practice-mode reports only, with the per-point "your
  answer vs reference point" comparison. The policy switch already exists.
- **No funnel data.** Add self-hosted events before the two-week pilot: opened
  join page, started, completed, viewed report, returned within 7 days, plus an
  optional thumbs up or down per question. Without this the pilot's pass criteria
  (completion above 70 percent, voluntary return above 30 percent) cannot be
  measured.
- **Mobile hardening on `exam.js`.** Focus the chat log rather than the textarea
  on open (`exam.js:216` raises the keyboard and scrolls the first question
  away); add `online` and `offline` listeners; warn on `beforeunload` while
  submitting; add `aria-busy` and a label change on the disabled submit button,
  whose 0.5 opacity drops contrast to about 2.9:1.

## 3. AI layer robustness and cost

The deterministic core is well separated from the stochastic parts. The gaps are
in output validation, provenance, grounding depth, and turning the quality lab
into a gate.

- **One parse-and-validate loop.** Qwen (`qwen_provider.py:253-290`) and Ollama
  (`ollama_provider.py:482-521`) each have their own repair loop; OpenAI has
  `_parse_json` without `json_repair`; Anthropic and Gemini have none beyond SDK
  retries. Nothing validates against the JSON schema client-side, and
  `ModelOutputValidationError` in `providers/base.py:9` is never raised.
  `Settings.max_model_retries` is referenced nowhere. Put one loop in the base
  agent: parse, `jsonschema.validate`, one targeted repair, then raise. Make
  every provider set `retry_count` and `json_repair_used`; today only Qwen does.
- **Stamp provenance on conclusions.** The roadmap requires prompt, model, and
  policy versions on every conclusion. `PLANNER_PROMPT_VERSION` is used only by
  the relevance probe; blueprints carry no model or prompt version;
  `Turn.analysis` has `assessment_version` but no model; reports have a template
  fingerprint but no model. A `DEFAULT_PROMPTS["answer_analyzer"]` one-liner is
  silently prepended to every analyzer call because the name matches at
  `base.py:28-32`, while the planner's never applies because its name is
  `session_planner`. Fix the mismatch or delete `DEFAULT_PROMPTS`; introduce a
  `PromptSpec(name, version, text, schema_hint)` registry.
- **Grounding depth.** The planner stuffs the whole document (`planner.py:151`)
  after a head-only cut at 180,000 chars, and may resend it up to six times
  through language and contract repair loops. The analyzer sees only
  `question.source_excerpt`; page text is already stored but unused for grading.
  Pass the full source page to the analyzer, resend only offending questions
  during repair, and summarize per page for documents over the cap.
- **Score calibration.** `_adjudicate_open_answer` (`analyzer.py:243-331`) can
  only raise scores, never lower them, and silent failures degrade to
  `unavailable`. `supporting_quote` is `answer[:260]` rather than the
  point-level quotes that already exist. Thresholds (0.72 coverage, 2.5 and 3.7
  risk, 3.8 strength) are hard-coded. Make adjudication symmetric, use
  point-level quotes in reports, and derive thresholds from the lab's persona
  tiers.
- **Quality lab as a gate.** It measures question quality, Spearman, false pass,
  injection, judge MAE, cost, and p50/p95 latency, but `quality-lab.yml` never
  fails on regression and there is no baseline comparison in code. The
  `judge_fraction` input default is 0.3 while the env fallback is 1.0, so
  scheduled and manual runs differ. Add
  `--baseline prev/summary.json --fail-on-drop 0.03 --fail-on-injection 0`,
  track `summary.json`, and run a small real-model weekly job with a 2 USD cap.
- **Prompt injection defence.** One sentence per provider plus a single fixed
  attack string in `quality_lab/personas.py:40-46`. Add 8 to 10 variants
  (indirect rubric claims, role-play, JSON-looking payloads, mid-answer
  instructions) and a cheap runtime `manipulation_suspected` flag stored on the
  turn and shown to teachers.
- **Cost.** No prompt caching anywhere; the Anthropic adapter puts the document
  inside one JSON user string, so nothing is cacheable across the repair loop.
  `estimate_cost` returns 0 for any model not in the static catalog, so
  overrides look free. The reservation estimate is `len/4`, which under-reserves
  Chinese text by 2 to 3 times. Split the document into its own cacheable block,
  alert on unpriced models, and weight CJK characters at about one token.
- **Per-agent model routing.** Governance already keys on `task_type=agent`
  (`model_governance.py:1048-1054`) but a session has one profile for all
  agents. A settings map of agent to default profile would let the adjudicator,
  language repair, and phrasing call use a cheap model while the planner stays
  strong.
- **Provider adapters diverge.** Timeouts are 60 s OpenAI, 120 s Anthropic, none
  Gemini, 240 s Qwen, 300 s Ollama. A 180,000-char planner call on OpenAI will
  often hit 60 s and then triple cost through SDK retries. No streaming anywhere.
  Only three provider tests exist, all Qwen happy-path. Add settings-driven
  timeouts with planner defaults of at least 180 s, and a contract test per
  adapter against recorded fixtures covering parse, usage, repair flag, and
  timeout.
- **Voice.** Two realtime transports with no reconnection;
  `realtime/normalizers.py` has no production callers; `capabilities_for` does
  not recognize the default `qwen3-omni-flash-realtime`; post-hoc question
  matching uses `SequenceMatcher` at 0.20 similarity. Pick one supported realtime
  provider per region, mark the other experimental, and add reconnect with
  transcript dedupe before widening the pilot.
- **Planner language guard.** `_matches_language` (`planner.py:384-394`) passes
  if any CJK character appears and returns true for every non-Chinese language.
  Use a ratio check per question and apply it to English too.

## 4. Code structure and maintainability

The largest ongoing cost is `main.py`: 6,637 lines, 167 routes, 338 lines of
imports, zero `APIRouter`, and business logic living in handlers. Because
`ROUTE_POLICIES` is keyed by method and path and validated against the live app
at startup, a router-per-PR split that keeps paths identical is low risk, and
the 405 TestClient tests will catch regressions.

**Proposed router split** (line ranges in the current `main.py`):

| Module | Lines | Contents |
| --- | --- | --- |
| `api/deps.py` | 340-432, 2527-2535 | Annotated access aliases, `get_db` |
| `api/system.py` | 865-1022, 4184-4222, 6027-6048 | index pages, health, ready, providers, metrics |
| `api/auth.py` | 1030-1188 | context, OIDC login and callback, me, capabilities |
| `api/organizations.py` | 1188-1396 | organizations and memberships |
| `api/templates.py` | 1396-1759 | templates, versions, project binding |
| `api/projects.py` | 1759-1988, 4222-4330 | projects, upload, blueprints, delete |
| `api/golden.py` | 1988-2181, 4650-4687, 4747-4819 | golden datasets, benchmarks, ratings |
| `api/sessions.py` | 2181-2538 | sessions and report; move `_create_exam_session` to a service |
| `api/assignments.py` | 2538-3221 | assignments, join, attempts; move learner runtime to a service |
| `api/cognitive.py` | 3221-3358 | knowledge state, adaptive decisions |
| `api/learner_memory.py` | 3358-4184 | identities, concepts, memory, retest, preferences |
| `api/documents.py` | 4329-4650 | documents, evidence, visual and joint analyses |
| `api/prompts.py` | 4687-4747 | prompts |
| `api/jobs.py` | 4819-4990 | local and enterprise jobs |
| `api/model_governance.py` | 4990-5254 | model policy, quota, usage |
| `api/audit.py` | 5254-5378 | audit events and export |
| `api/data_lifecycle.py` | 5378-5884 | retention, legal holds, exports, data-subject requests |
| `api/review.py` | 5884-6027 | review cases |
| `api/costs.py` | 6048-6105 | cost dashboard; move the p50/p95 over 10,000 rows into SQL |
| `api/voice.py` | 6105-6637 | voice sessions and Qwen WebSocket |

**Other structural directions:**

- **One error mechanism.** Four `@app.exception_handler`s, five hand-written
  mappers, and about 75 per-route try/except blocks across 23 service error
  classes with mixed bases. Nine places map bare `ValueError` to 400 or 404 and
  can leak internal messages. Introduce
  `ServiceError(code, status_code, public_message)` and a single handler
  emitting `{"detail": {"code", "message"}}`, the shape `ModelGovernanceError`
  already uses.
- **Transaction ownership.** 61 commits in `main.py`; services also commit
  mid-flow (`model_governance.py` 7, `job_control.py` 13, `templates.py` 7).
  `_create_organization_export_job` commits three times; `delete_project`
  deletes storage objects before the DB commit. Services should take a session
  and never commit; the router or a `with transaction(db)` helper owns it. The
  `enqueue_job(dispatch=False)` plus `dispatch_persisted_job` pair already
  exists for dispatch-after-commit.
- **Tenant indexes.** `TenantOwnedMixin` at `models.py:39` declares
  `organization_id` without an index, and no migration adds one on 37 tenant
  tables. Every RLS policy and 52 tenant filters scan. One migration fixes it.
  Also move `Project` onto the mixin, use `version_id_col` for the 8 hand-bumped
  version columns, and add `relationship()` where loops re-query per row
  (`get_assignment_dashboard` does `db.get(ExamSession)` per attempt).
- **God modules.** `model_governance.py` (1,279 lines) holds policy helpers, two
  rate limiters, a lock registry, the service, a provider adapter, and usage
  reporting. `data_lifecycle.py` (1,005) mixes retention, legal holds, human
  review, ZIP export, and data-subject requests. `utcnow`, `canonical_json`, and
  `digest` are duplicated across three modules. Split along those seams and
  hoist the helpers.
- **Legacy and v1 route pairs diverge.** `/api/jobs/{id}` vs
  `/api/v1/jobs/{id}`, memory-export and evidence file downloads: the v1
  versions check organization, the legacy ones do not, and the legacy ones are
  hidden from OpenAPI but reachable. Route both paths to one handler with the
  same check, and set a deprecation date.
- **Config.** Six settings are dead (`max_questions`, `job_stale_minutes`,
  `benchmark_case_limit`, `render_dpi`, `max_concurrent_model_calls`,
  `max_model_retries`); `app_env` is a bare string compared in 10 places; nine
  enums are regex patterns; `get_settings()` creates six directories at import
  time. Delete or wire the dead fields, use `Literal`, move `mkdir` into
  `lifespan`, and pick one settings access pattern.
- **Typing and response models.** No mypy or pyright anywhere; ruff is not in
  CI; 0 of 167 routes declare `response_model` despite 62 Pydantic schemas, so
  OpenAPI has no response shapes and hand-built dicts are unchecked. Add pyright
  basic to CI and response models router by router during the split.
- **Release tooling in the runtime package.** `release_hardening.py`,
  `release_evidence.py`, `recovery_evidence.py`, `staging_observer.py`, and
  `model_governance_probe.py` (about 1,760 lines) ship in every wheel with
  v09-stamped CLI names. CI still uses them, so keep them, but move to
  `tools/release/` and rename without version numbers.
- **Broad excepts.** 41 `except Exception` in the package; the route-level ones
  at `main.py:1928`, `2018`, `2106`, `4614` return `str(exc)` to clients and can
  leak provider payloads. Narrow to the provider error hierarchy.
- **Blocking calls in request path.** `get_report` builds an orchestrator with a
  provider on every GET although the reporter is deterministic;
  `_submit_learner_answer` sleeps up to 6 s in a worker thread while holding a
  model-gate slot. Instantiate the reporter without a provider; move the wait
  outside any DB session.

**Frontend structure.** Vanilla JS is the right call for a solo developer with
coding agents; do not add a framework. Do add a build-less `static/shared.js` ES
module for the three divergent `api()` wrappers, two `escapeHtml`
implementations, and three job pollers, plus an auto-escaping `html` tagged
template. Split `app.js` along its existing seams (voice about 600 lines,
templates about 400, assignments about 200). Wrap the two unescaped URL
attributes at `app.js:1131` and `:1353`. Replace the four `window.alert` calls
with the toast and `ApiError` pattern `enterprise.js` already has.

## 5. Process, CI, tests and repository hygiene

CI was red from v0.9.0 to v0.10.0 without anyone noticing. The structural cause
is that nothing blocks on it: `main` has no branch protection and only 1 of 183
commits is a PR merge.

- **Protect main.** Require both CI jobs (`test` and `postgres`) to pass,
  require PRs, add a `concurrency` group, and schedule a nightly run so lockfile
  drift and new CVEs surface without a push. Switch `uv sync --extra dev` at
  `ci.yml:13` and `:106` to `uv sync --locked`; that alone would have caught the
  first root cause of the red streak. Add Dependabot for `uv` and GitHub
  Actions.
- **Remove `--maxfail=1` and `--disable-warnings` from pytest defaults**
  (`pyproject.toml`). The first hides every failure after the first, so a
  three-cause red streak looks like one bug. The second suppressed the 153
  warnings seen in this run, including SQLAlchemy delete-count warnings at
  `main.py:4298` and OpenTelemetry deprecations.
- **Fix test fixture cost.** `tests/conftest.py:71-80` drops and recreates the
  whole schema per test on one shared file path, which is why 405 tests take
  9.5 minutes and cannot run under `pytest-xdist`. Create the schema once per
  session, wrap each test in a transaction rollback, and derive the DB path from
  the worker ID. Mark the 13 subprocess and Alembic tests as `slow` and skip
  them in the PR lane.
- **Split CI into lanes.** Fast PR lane: ruff check and format, Alembic single
  head, SQLite pytest, Docker build. Merge or nightly lane: PostgreSQL full
  suite, enterprise Compose, pip-audit. Today the full suite runs twice (once
  inside the release gate, once in the postgres job) with no coverage floor, no
  `ruff format --check`, no type check, and JS checked only by `node --check`.
- **Missing test coverage.** Zero tests for provider timeouts, 5xx, or malformed
  JSON (`tests/test_providers.py` has 3 happy-path Qwen tests). No concurrent
  join or duplicate-submit test. No browser test; `tests/test_health.py:10-21`
  and `test_enterprise_ui_v09.py` assert on substrings of JS source. Add
  `httpx.MockTransport` adapter tests, a two-thread attempt test, and one
  `pytest-playwright` flow through join, two answers, and report against the
  mock provider.
- **Migration round trip.** All 18 revisions implement `downgrade()`, but only
  one targeted test exercises up and down, and the conftest `create_all` path
  means tests never run migrations against models. Add `tests/test_migrations.py`
  asserting single head, empty-DB upgrade-downgrade-upgrade on both databases,
  and `alembic check` for model drift.
- **Test naming.** 42 of 60 test files carry a release suffix (`_v03` to
  `_v010`); `test_assignments_v010.py` is 1,413 lines. Several tests pin CI YAML
  and shell-script contents. Rename by domain, split the assignments file into
  publish, join, attempt, and report, and move deployment-contract tests under
  `tests/infra/` with a marker.
- **Lint and formatting.** Ruff selects only `E, F, I, B, UP`; no formatter, no
  pre-commit, no typing. Add `ruff format --check`, the `S` (bandit) rules since
  the app handles tokens, `PT`, `SIM`, `RUF`, and a `.pre-commit-config.yaml`
  with `uv lock --check`.
- **Documentation sprawl.** 78 of 124 files in `docs/` are version-prefixed.
  Four files each claim to describe the current state at different versions:
  `PROJECT_STATUS.md` says v0.9.1, `docs/VERSION_PLAN.md` lists v0.5.0 as
  awaiting acceptance, the roadmap targets v0.8.0, and
  `agent_workspace/project_state.yaml` says 0.2.0. Target structure:
  `README.md` (what it is, quickstart, links), `CHANGELOG.md`,
  `CONTRIBUTING.md`, then `docs/getting-started`, `architecture` (topic pages,
  no version prefix), `api` (one reference), `operations`, `security`,
  `decisions`, `evaluation` (protocol plus quality lab, evidence by date), and
  `archive` for v0.2 to v0.9 plans, increment results, release notes, and the
  status files. Delete `agent_workspace/`; move `developer_agents/` to the
  archive.
- **README first screen.** Lines 1 to 9 describe the actual v0.10 product. Lines
  22 to 168 are v0.9 work-package bullets, lines 169 to 200 still say the
  current branch is v0.5 RC4, and lines 333 to 338 say there is no login or
  tenant isolation. Cut to about 120 lines: one paragraph, a GIF of the join
  flow, a 5-step quickstart with `make demo`, links to the pilot runbook and
  CONTRIBUTING.
- **Root release artifacts.** 13 `RELEASE_NOTES_*.md` in the root, a 40 KB
  `CHANGELOG.md` with three heading styles and an Unreleased section below
  released versions, and no `v0.10.0` tag although the README claims one. Fold
  notes into the changelog, move RC notes to the archive, tag `v0.10.0` on
  `7d79846`, and publish future notes as GitHub Releases.
- **Branches.** 19 remote branches; 15 already merged into main;
  `feature/wechat-miniapp` is unmerged from 2026-09-24, which answers the
  adoption review's question about whether that code is committed.
  `deploy/enterprise/update-enterprise.sh:17-18` still defaults to
  `research/v0.9.0`. Delete merged branches, tag and delete the dead ones,
  decide on the miniapp branch, and point the deploy default at `main`.
- **Compose and deploy sprawl.** 8 compose files; `deploy/compose-files.sh`
  knows only `pilot` and `https`, so other combinations are hand-assembled in CI
  and in 8 enterprise scripts. Version-named scripts
  (`rehearse-v08-compose.sh`, `verify-v09-*.py`) and 16 CLI entry points. Keep
  base, prod, and pilot as the supported path; move the rest under
  `deploy/compose/` as documented add-ons; rename by role. `Dockerfile.test`
  installs unlocked while `Dockerfile` uses the lockfile.

## Where to start

Do the pilot-path gaps first, because the pilot is live and each is a day or
less. Then the three product items with the biggest effect on whether students
come back. The router split can proceed in parallel, one PR at a time, and makes
everything after it cheaper.

1. **Week 1, safety.** Scoped tenant lookups on `/api/*`; fail-closed relevance;
   per-attempt lock; register the assignment routes in `ROUTE_POLICIES` and
   widen the completeness test; Origin check in Caddy; body size cap; minimal
   public `/health`.
2. **Week 1, one hour.** Branch protection on `main`, `uv sync --locked`, remove
   `--maxfail=1`, tag `v0.10.0`, delete the 15 merged branches.
3. **Week 2, retention.** Draft persistence in `exam.js`; natural phrasing call
   with template fallback; funnel events; practice-mode reference answers;
   report reordering.
4. **Weeks 2 to 4, in parallel.** Router split one module per PR, starting with
   `api/assignments.py` and `api/sessions.py` since they carry the pilot. Add
   response models and the `ServiceError` base as each router lands.
5. **Before changing any prompt or default model.** Quality lab baseline
   comparison that fails the job; the single parse-and-validate loop; provenance
   stamping.
6. **When the pilot has data.** Test fixture rewrite for a fast suite, docs
   archive and README cut, compose and deploy consolidation, tenant indexes,
   god-module splits.

## What is already good

Keep these intact while refactoring.

- **Enterprise substrate.** Capability-based RBAC with a declarative
  `ROUTE_POLICIES` table validated against the live app at startup; tenant
  context carried in `Session.info` and applied per transaction; PostgreSQL RLS
  with a dedicated runtime role; immutable audit tables on a separate engine so
  audit writes survive request rollbacks; idempotent job envelopes with lease,
  heartbeat, and recovery; explicit production configuration gates in
  `lifespan`.
- **Data model.** Consistent SQLAlchemy 2.0 style with `ondelete` on all 80
  foreign keys, 61 unique and check constraints, timezone-aware datetimes, and
  18 linear migrations that all implement `downgrade()` with explicit refusals
  to destroy evidence.
- **Tests.** Behavior-level HTTP tests through `TestClient` on both SQLite and
  PostgreSQL, a deterministic mock provider with no randomness or time
  dependence, a scripted assessment provider for contract tests, small targeted
  assertions rather than snapshots, and good coverage of tenant isolation, token
  leakage, idempotency, retries, dead-letter, and stale-worker recovery. The
  conftest refuses a non-test PostgreSQL database name.
- **Pilot security controls.** 32-character join-code alphabet with uniform 404s
  across organizations; 256-bit attempt tokens hashed at rest and bound to
  organization and attempt; anonymous principal header ignored in production and
  stripped by Caddy; exam mode strips hints, corrections, and disclosure at
  session creation; student names and IDs never reach audit, telemetry, or logs;
  HSTS and security headers set; API and HTML served `no-store`; answers
  rate-limited per attempt with a queue and a 503 busy signal instead of
  failure.
- **AI layer.** `PolicyController` decides actions deterministically with an
  audit trail; scores are computed reproducibly from analyzer components with
  versioned rubric anchors and can be recomputed; the analyzer schema is rich
  (point-level status, semantic match, error classification); the
  cross-question duplicate guard caps pasted answers; native structured output
  is used on OpenAI, Anthropic, Gemini, and Ollama; usage is recorded per call
  with provider, model, and latency; blueprint reuse across an assignment
  amortizes planner cost; the quality lab's design (blind judge, known-ability
  personas, Pareto cost and quality) is the right shape and only needs to become
  a gate.
- **Frontend.** `exam.js` renders all model and student text through
  `textContent`; across 61 `innerHTML` sites in the other two files, user- and
  model-provided text is consistently escaped; `enterprise.js` has a careful
  `api()` with an organization epoch that discards stale cross-tenant responses;
  the blueprint poller shows progress, elapsed time, and cancel; `exam.html`
  ships labels, live regions, dark-mode tokens, reduced-motion support, and AA
  contrast without a CSS framework.
- **Deployment.** `Dockerfile` installs hash-pinned dependencies from the
  lockfile; CI exercises a real enterprise Compose stack with restart
  persistence and backup-restore rehearsal; the release gate is
  machine-readable and checks single head, route policy coverage, secret
  scanning, and dependency audit; ADRs exist and the latest (`ADR-007`) is
  current.
