# AI Examiner v0.9 Acceptance Report

Date: 2026-07-30  
Branch: `research/v0.9.0`  
Validated server commit: `c398a6d`  
Latest local commit: `617481a`

## 1. Executive Summary

AI Examiner v0.9 passed the complete isolated enterprise backend protocol,
the principal browser workflows, responsive UI checks, real Qwen model calls,
and the full automated regression suite.

Release assessment:

- Suitable for continued development and controlled staging evaluation.
- The application-level v0.9 feature set is functionally complete.
- It is not yet approved as an enterprise production release because this
  AutoDL host cannot validate the Docker/PostgreSQL/Redis/MinIO/OIDC/OTLP
  production topology.

## 2. Test Environments

### AutoDL staging

- Application port: `6006`
- Runtime: direct Uvicorn process
- Database: SQLite
- Authentication: disabled development mode
- Storage: local
- Primary text model: `qwen:qwen-plus`
- Visual model: `qwen:qwen3-vl-plus`
- Realtime model: Qwen realtime

The staging server passed the backend acceptance protocol at commit
`c398a6d`. Immediately after that run, the AutoDL public port mapping began
returning the platform gateway's `404 Not Found`, and SSH port `37559` became
unreachable. The final compatibility commit `617481a` therefore remains local
until the instance is available again.

### Local browser acceptance

- URL: `http://127.0.0.1:8022`
- Browser engine: Microsoft Edge through Playwright
- Viewports: `1440x900` and `390x844`
- Model admission: in-memory staging limiter
- Model calls: real Qwen, not Mock

## 3. Enterprise Backend Acceptance

Result: **48 passed, 0 failed**

The protocol used a newly provisioned isolated organization with separate
Owner, Admin reviewer, candidate member, and outsider principals.

Validated areas:

| Area | Result |
|---|---|
| Health and readiness | Passed |
| Authentication boundary | Passed |
| Tenant context and outsider denial | Passed |
| Capability registry | Passed |
| Membership create, update, revoke | Passed |
| Model policy and hard quota | Passed |
| Tenant-bound project and document creation | Passed |
| Authorized document and evidence download | Passed |
| Real Qwen asynchronous Planner | Passed |
| Job health during model execution | Passed |
| Idempotent async requests | Passed |
| Usage ledger and JSONL export | Passed |
| Retention policy | Passed |
| Organization export and ZIP integrity | Passed |
| Legal hold creation and release | Passed |
| Dual-control self-approval denial | Passed |
| Hold-blocked deletion and verified retry | Passed |
| Human review assignment, decision, appeal | Passed |
| Job listing and recovery | Passed |
| Immutable audit listing and export | Passed |
| Template health | Passed |
| Voice configuration | Passed |

The real Qwen asynchronous Planner completed in approximately 112 seconds.

## 4. Browser Acceptance

### Workbench

Validated:

1. The v0.9 workbench loaded without console or HTTP errors.
2. Qwen Plus appeared in the text and blueprint model selectors.
3. Qwen3-VL Plus appeared in the visual model selector.
4. A project was created through the UI.
5. A Markdown research document was uploaded and parsed.
6. `qwen:qwen-plus` generated a six-question blueprint.
7. Two evidence objects were loaded, including one rendered page.
8. `qwen:qwen3-vl-plus` completed visual analysis.
9. A text defense session started with `qwen:qwen-plus`.
10. The answer analyzer scored and followed up on the submitted response.

The submitted answer was intentionally fluent but did not directly answer the
question. It received `0.8/5`, and the system asked for the missing direct
evidence. This confirms that scoring no longer rewards generic keyword overlap.

Browser errors: **0**  
Failed HTTP requests: **0**

### Enterprise console

All six views were opened and rendered:

- Overview
- Members and permissions
- Model governance
- Audit log
- Data retention
- Human review

The views showed the expected organization, role, capabilities, metrics,
forms, and data tables.

### Responsive behavior

At `1440x900` and `390x844`:

- No page-level horizontal overflow.
- No clipped visible buttons, selects, or inputs.
- Organization selector remained labelled and readable.
- All enterprise navigation views remained operable.

## 5. Voice Acceptance

Qwen realtime voice was previously validated in the browser with a browser
media track:

- Realtime connection established.
- Microphone track was live.
- Echo cancellation, noise suppression, and automatic gain control were active.
- The AI produced a natural opening question and transcript.
- Realtime events were persisted.

OpenAI Realtime could not be exercised from AutoDL because outbound HTTPS to
`api.openai.com:443` timed out. The UI now reports a structured upstream
connectivity error and recommends Qwen realtime instead.

Physical room acoustics, speaker echo, and actual device microphone quality
still require a human device test. Browser transport behavior is tested; the
complete acoustic experience is not claimed as validated.

## 6. Automated Regression

| Check | Result |
|---|---|
| Pytest | **321 passed** |
| Ruff | Passed |
| `app.js` syntax | Passed |
| `enterprise.js` syntax | Passed |
| Focused job/blueprint hardening tests | Passed |
| Tenant isolation tests | Passed |

On Windows, pytest prints an access violation while AnyIO/asyncio closes a
Proactor socket after all tests complete. The test process exits with code `0`.
This is tracked as a local runtime cleanup issue.

## 7. Defects Found and Corrected

### Answer relevance

Problem: a generic repeated answer could receive a high score across unrelated
questions.

Correction: assessment now requires semantic relevance and records duplicate
answer behavior. Retest reduced an unrelated answer to `2.25/5`; the browser
acceptance answer received `0.8/5`.

### Golden Dataset release gates

Problem: a dataset with zero grounded citations could be frozen.

Correction: backend and frontend now enforce grounding, completeness, text
hygiene, and lifecycle gates before freezing.

### Stale AutoDL process

Problem: a code update could leave the old Uvicorn process serving traffic.

Correction: an idempotent AutoDL stop script and reliable restart procedure
were added and tested.

### Realtime upstream errors

Problem: upstream connection failures were rendered as generic text errors.

Correction: the backend returns structured `502` errors and the frontend
renders the provider-specific failure reason.

### Tenant-bound workbench resources

Problem: core project and document routes could fall back to the legacy
organization even when enterprise headers were present.

Correction: project, document, and blueprint routes now authorize and bind
resources to the active tenant context.

### Model-generated blueprint contract failures

Problem: intermittent Qwen output validation failures were classified as
permanent job failures.

Correction: model output contract errors now have a dedicated exception type
and are retryable. Invalid resources and request values remain permanent.

### Single-organization workbench compatibility

Problem: a development principal with one organization but no explicit
organization header received `400`.

Correction: the sole active organization is inferred. Multi-organization
principals must still select an organization explicitly.

## 8. Remaining Release Boundaries

The following are not application regressions, but remain required before an
enterprise production release:

1. Run the enterprise Docker Compose topology on a host with Docker.
2. Validate PostgreSQL migrations and row-level security against a live server.
3. Validate Redis-backed rate limiting and Celery recovery.
4. Validate MinIO/S3 migration, presigned download, restore, and backup drills.
5. Validate a real OIDC provider, JWKS rotation, logout, and expired tokens.
6. Validate OpenTelemetry export and required-exporter fail-closed behavior.
7. Perform physical microphone/speaker tests on desktop and mobile devices.
8. Restore the AutoDL public mapping and deploy commit `617481a`.
9. Prefer asynchronous Golden Dataset jobs; synchronous multi-model generation
   can exceed six minutes.

## 9. Final Verdict

The v0.9 application behavior is accepted for controlled staging:

- Enterprise backend protocol: **48/48**
- Automated regression: **321/321**
- Real Qwen browser workflow: **Passed**
- Enterprise desktop/mobile UI: **Passed**
- Browser console and HTTP errors: **0**

Production approval remains conditional on the infrastructure and physical
audio checks listed above.
