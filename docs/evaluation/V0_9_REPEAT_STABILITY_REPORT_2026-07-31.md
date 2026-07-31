# AI Examiner v0.9 Repeated Stability and Real-Provider Report

Date: 2026-07-31  
Branch: `research/v0.9.0`  
AutoDL application port: `6006`  
Public test URL: `https://u35756-7cf6-a3b4cec8.bjb1.seetacloud.com:8443/`

## 1. Purpose

This round repeated the v0.9 acceptance paths instead of relying on a single
successful run. It covered:

- the enterprise backend protocol;
- real Qwen Planner, Analyzer, visual and realtime paths;
- desktop and mobile browser workflows;
- concurrent voice event persistence and completion;
- local regression, lint and JavaScript checks;
- operational logging and provider configuration.

Runtime AI quality tests used real Qwen models. Mock providers were limited to
deterministic automated tests.

## 2. Environment

### AutoDL staging

- Runtime: direct Uvicorn process
- Database: SQLite
- Authentication: disabled development mode
- Storage: local filesystem
- Text model: `qwen:qwen-plus`
- Visual model: `qwen:qwen3-vl-plus`
- Voice model: Qwen realtime

This environment is suitable for functional staging. It does not validate the
enterprise Docker Compose topology with PostgreSQL, Redis, MinIO, OIDC and OTLP.

### Browser

- Microsoft Edge controlled with Playwright
- Desktop viewport: `1440x900`
- Mobile viewport: `390x844`
- Public HTTPS origin used for microphone and WebRTC validation

## 3. Results

| Test area | Repetitions | Result |
|---|---:|---|
| Enterprise direct-staging acceptance | 2 isolated organizations | 48/48 passed in both runs |
| Real Qwen Planner | 2 full runs | Passed |
| Real Qwen answer discrimination | 4 answer classes | Passed |
| Cross-question answer reuse guard | 1 targeted case | Passed |
| Real Qwen visual review | 2 runs | Passed |
| Enterprise desktop views | 6 views | Passed |
| Enterprise mobile views | 6 views | Passed |
| Realtime browser connection | Multiple sessions | Passed |
| Fake-capture microphone transcript flow | 1 complete session | Passed |
| Concurrent voice completion | 2 simultaneous requests | Passed after fix |
| Concurrent voice event persistence | 20 simultaneous writes | Passed after fix |
| Python regression suite | 327 tests | Passed |
| Ruff | Repository check | Passed |
| Browser JavaScript syntax | `app.js` | Passed |

No tested desktop or mobile view produced uncaught browser errors, failed API
requests, incoherent overlap or horizontal overflow.

## 4. Real-Provider Measurements

| Operation | Observed time |
|---|---:|
| Planner run 1 | about 166.7 seconds |
| Planner run 2 | about 40.1 seconds |
| Visual review run 1 | about 30.2 seconds |
| Visual review run 2 | about 38.8 seconds |
| Answer analysis | about 16.0-24.6 seconds |
| First realtime voice response | about 696 ms |
| Seven-fragment cognitive voice finalization | about 115.2 seconds |

The realtime speech path was responsive. Batch planning and post-session
cognitive processing had substantial latency and variance.

## 5. Answer-Quality Checks

The same real Qwen blueprint was tested with materially different answers:

| Answer | Score | Coverage | Support |
|---|---:|---:|---|
| Strong, relevant answer | 5.0 | 1.0 | Supported |
| Irrelevant answer | 0.4 | 0.0 | Unsupported |
| Explicitly unknown | 0.4 | 0.0 | Unsupported |
| Reused answer from previous question | 1.9 | Reduced | Duplicate detected |

The reused-answer case recorded similarity `1.0` and question relevance `0.2`.
The scoring guard prevented a polished but irrelevant answer from retaining the
original high score.

## 6. Confirmed Defects and Fixes

### P1: concurrent voice completion could lock SQLite

**Symptom**

Closing the page and pressing the end button could submit two completion
requests. Both attempted synchronous transcript analysis, one eventually
failed with `sqlite3.OperationalError: database is locked`, and the browser
could remain visually connected.

**Fix**

- atomically claim a voice session as `finalizing`;
- return `202` for duplicate requests while one request owns finalization;
- make completed sessions idempotently return `200`;
- release database write locks between governed transcript-analysis calls;
- complete the voice session with auditable failure metadata if cognitive
  post-processing fails;
- disable the end control immediately and use a keepalive completion request on
  page unload.

**Server regression**

Two simultaneous completion requests returned one fast `202` and one successful
`200`. Exactly one finalization ran and the session ended as `completed`.

### P1: concurrent transcript callbacks lost voice metrics

**Symptom**

The event table preserved transcript rows, but the `metrics` JSON occasionally
reported fewer user or assistant turns because concurrent callbacks overwrote a
read-modify-write update.

**Fix**

- serialize writes with deterministic per-session process locks;
- use a row lock when PostgreSQL is available;
- refresh the session before updating aggregate metrics.

**Server regression**

Twenty concurrent event requests returned twenty `201` responses. The resulting
session contained:

- `user_turns = 10`;
- `assistant_turns = 10`;
- `events = 20`.

### P2: migration startup disabled Uvicorn loggers

**Symptom**

Application startup appeared healthy, but access and exception logs disappeared
after Alembic initialized logging.

**Fix**

Alembic now preserves existing loggers. Server access logs and exception
diagnostics remain available after startup.

### P2: blueprint failure logging referenced a voice-only identifier

**Symptom**

The synchronous blueprint exception branch attempted to log
`voice_session_id`, which is not defined in that endpoint. A provider failure
could therefore replace the intended upstream `502` detail with a `NameError`.

**Fix**

The endpoint now logs its project and document identifiers. A regression test
forces the provider preparation failure and verifies the original error remains
a structured `502`.

### P2: stale browser script could hide deployed fixes

**Symptom**

The main workbench retained its old static query version after voice JavaScript
changes.

**Fix**

The workbench CSS and JavaScript cache version was advanced to
`0.9.0-qa3`.

## 7. Remaining Risks

### Provider health reports configuration, not connectivity

`/api/provider-health` currently reports a provider as `available` when a key
and model are configured. On this AutoDL host, OpenAI was marked available even
though a direct network probe to the OpenAI API failed. Qwen connectivity was
healthy.

Recommended change:

- expose separate `configured`, `connectivity` and `last_probe_at` fields;
- run a cached, bounded, non-generation connectivity probe;
- prevent selection when connectivity is known to be unavailable;
- never make each page load perform a paid model call.

### Cognitive voice finalization is synchronous

The media connection closes promptly, but a longer voice session can keep the
completion HTTP request active while transcripts are analyzed. Seven transcript
fragments required about 115 seconds in this test.

Recommended change:

- close media and mark the session `finalizing` immediately;
- enqueue cognitive finalization as a durable background job;
- expose progress and retry status;
- transition to `completed` after the job commits all knowledge events.

### Qwen batch latency is variable

Planner latency varied from about 40 to 167 seconds for comparable acceptance
runs. Visual analysis remained around 30-39 seconds.

Recommended change:

- record latency percentiles by task and model;
- enforce task-specific timeout budgets;
- stream or checkpoint long planning tasks;
- use smaller bounded context for interactive paths;
- retain the stronger path for offline report and dataset generation.

### Production topology remains unverified on AutoDL

This host does not currently exercise:

- OIDC with an external issuer and rotating JWKS;
- PostgreSQL tenant isolation and RLS;
- Redis/Celery multi-process recovery;
- MinIO/S3 object migration;
- OTLP export and alerting;
- enterprise backup and disaster recovery under Docker Compose.

These remain release gates for an enterprise production tag.

### Windows test teardown emits an AnyIO/Proactor diagnostic

The 327-test local run completed at `100%` with exit code `0`, but the Windows
Conda Python process printed an access-violation traceback while closing a
Starlette `TestClient` AnyIO portal. This was not reproduced by Uvicorn on the
Linux staging server and did not fail an assertion.

Recommended change:

- reproduce with a standalone CPython environment outside Conda;
- upgrade or pin the compatible Starlette, HTTPX and AnyIO set;
- audit long-lived test clients and background tasks for deterministic teardown.

## 8. Release Assessment

The v0.9 research branch is suitable for continued controlled staging:

- repeated enterprise protocol runs pass;
- real Qwen text, visual and voice paths function;
- answer relevance and duplicate reuse guards behave correctly;
- browser desktop/mobile workflows pass;
- the two confirmed voice concurrency defects are fixed and server-verified.

The branch should remain a research/development release until provider
connectivity semantics, asynchronous voice finalization and the full enterprise
deployment topology are validated.
