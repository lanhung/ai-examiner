# v0.9 Enterprise Platform Implementation Backlog

Status: Research draft
Rule: do not start broad implementation until the v0.9 research gate is accepted.

## Delivery strategy

v0.9 is delivered as vertical, reversible increments. Authentication enforcement and
RLS begin in observe mode and are enabled only after ownership coverage is complete.

## WP-00: Research gate and contracts

Deliver:

- accepted ADR-006;
- complete model ownership matrix;
- route/capability matrix;
- threat model;
- API contract;
- migration, backup and recovery objectives.

Acceptance:

- every current model classified as global, organization, project, learner or
  operational;
- every current route classified by authentication and capability;
- high-stakes human review boundary approved.

## WP-01: PostgreSQL parity

Status: completed on `research/v0.9.0`; SQLite and PostgreSQL CI gates pass.

Deliver:

- PostgreSQL Compose test service;
- CI integration profile;
- dialect compatibility fixes;
- migration test against PostgreSQL;
- no application feature changes.

Acceptance:

- full deterministic suite passes on SQLite;
- enterprise integration suite passes on PostgreSQL;
- migration upgrade/downgrade behavior documented;
- JSON, datetime and cascade semantics verified.

## WP-02: Organization and principal foundation

Status: implemented on `research/v0.9.0` in observe-only mode; acceptance requires
the complete SQLite and PostgreSQL CI gates.

Deliver:

- `Organization`, `Principal`, `Membership`;
- legacy organization backfill;
- principal status lifecycle;
- organization context object;
- bootstrap administrator CLI.

Acceptance:

- existing data belongs to one deterministic legacy organization;
- no current data lost;
- organization context remains observe-only.

## WP-03: OIDC authentication

Status: implemented on `research/v0.9.0`; deterministic SQLite tests pass and
PostgreSQL CI parity remains a required branch gate.

Deliver:

- issuer discovery and JWKS cache;
- strict access-token validator;
- browser code+PKCE integration;
- principal provisioning policy;
- logout/session handling;
- token failure tests.

Acceptance:

- invalid token matrix passes;
- tokens and claims are redacted;
- production readiness fails when required OIDC is unavailable or unsafe.

## WP-04: Capability RBAC

Status: implemented on `research/v0.9.0`; deterministic authorization tests pass and
the complete SQLite/PostgreSQL CI gate remains required.

Deliver:

- capability registry;
- organization roles;
- authorization dependency and resource resolvers;
- generated route/capability inventory;
- membership administration.

Acceptance:

- all `/api/v1` routes declare requirements;
- object-level and function-level negative tests pass;
- template authoring seam uses real authorization.

## WP-05: Tenant ownership propagation and RLS

Status: Implemented on `research/v0.9.0`; PostgreSQL CI evidence required.

Deliver:

- `organization_id` on tenant tables;
- two-phase backfill;
- composite ownership constraints;
- SQLAlchemy transaction context;
- PostgreSQL policies and runtime role;
- worker tenant context.

Implementation evidence:

- migrations `20260728_0010` and `20260728_0011`;
- direct ownership across the complete resource matrix;
- transaction-local SQLAlchemy tenant context;
- forced PostgreSQL RLS using `ai_examiner_runtime`;
- composite ownership constraints on critical parent chains;
- tenant/actor-aware Celery job dispatch;
- `deploy/verify-v09-rls.py`.

Acceptance:

- no unowned required row;
- missing tenant context returns zero protected rows;
- pooled connections do not leak prior context;
- cross-tenant matrix has zero successful access.

## WP-06: Storage backend

Status: completed on `research/v0.9.0`; SQLite and PostgreSQL CI gates pass.

Deliver:

- `StorageBackend` protocol;
- local implementation;
- S3-compatible implementation;
- storage locator schema;
- object migration/reconciliation CLI;
- authorized download and deletion.

Acceptance:

- backend contract suite passes twice;
- source and evidence hashes preserved;
- no public object access;
- interrupted migration resumes safely.

Implementation evidence:

- `src/ai_examiner/services/storage.py`;
- `src/ai_examiner/services/storage_migration.py`;
- `src/ai_examiner/storage_cli.py`;
- migration `20260728_0012`;
- `docker-compose.minio.yml`;
- authorized `/api/v1` document, evidence, highlight and memory-export downloads;
- `tests/test_storage_backend_v09.py`;
- `docs/architecture/V0_9_STORAGE_BACKEND.md`.

## WP-07: Job hardening

Status: completed on `research/v0.9.0`; SQLite and PostgreSQL CI gates pass.
PostgreSQL CI and Linux Redis/Celery process-restart rehearsal remain required.

Deliver:

- organization/actor task envelope;
- idempotency keys;
- job heartbeat and lease;
- retry classification;
- cancellation;
- terminal/dead-letter state;
- job capability checks.

Acceptance:

- duplicate delivery creates one billable result;
- foreign-tenant payload fails before resource access;
- worker restart recovery passes.

Implementation evidence:

- `src/ai_examiner/services/job_control.py`;
- unified execution in `src/ai_examiner/jobs.py`;
- additive migration `20260728_0013`;
- authorized job read, cancel, retry and recovery APIs;
- `tests/test_job_hardening_v09.py`;
- `docs/architecture/V0_9_JOB_DELIVERY_HARDENING.md`.

## WP-08: Audit system

Status: implemented on `research/v0.9.0`; deterministic gates pass and PostgreSQL
immutability/RLS verification is part of CI.

Deliver:

- append-only `AuditEvent`;
- request/trace correlation;
- administrative and denial events;
- redacted audit API and export;
- audit retention handling.

Acceptance:

- sensitive action coverage complete;
- canary secret/content leakage is zero;
- runtime application cannot update/delete audit rows.

## WP-09: Model policy, quota and rate limits

Status: implemented on `research/v0.9.0`; deterministic SQLite tests pass and the
PostgreSQL RLS/full-suite CI gates remain required before branch acceptance.

Deliver:

- organization model allowlist;
- data-classification policy;
- authoritative usage ledger;
- Redis rate counters;
- soft/hard quota modes;
- cost dashboard by organization/project/agent.

Acceptance:

- disallowed provider is never called;
- concurrent hard-limit tests pass;
- actual provider/model and policy snapshot are recorded.

Implementation contract:

- `docs/architecture/V0_9_MODEL_GOVERNANCE.md`.

## WP-10: Retention, export, deletion and review

Deliver:

- retention policies;
- organization export manifest;
- data-subject request workflow;
- verified deletion worker;
- review and appeal case foundation.

Acceptance:

- export authorization checked at download;
- deletion includes relational and object verification;
- AI cannot set final human-review decision.

## WP-11: OpenTelemetry and operations

Deliver:

- trace/metric bootstrap;
- FastAPI, SQLAlchemy, HTTPX and Celery instrumentation;
- OTLP collector profile;
- Prometheus/Grafana dashboards;
- alert rules;
- telemetry redaction tests.

Acceptance:

- request-to-worker trace correlation works;
- no raw content or secrets in telemetry;
- telemetry backend outage does not corrupt business state.

## WP-12: Enterprise Compose and recovery

Deliver:

- PostgreSQL/Redis/API/worker/Caddy profile;
- optional S3-compatible and observability profiles;
- database and object backup;
- isolated restore script;
- upgrade and rollback scripts;
- Vultr deployment guide.

Acceptance:

- one documented command starts the profile;
- restart preserves all authoritative data;
- disaster rehearsal meets agreed RPO/RTO;
- normal update never removes volumes.

## WP-13: Enterprise UI

Deliver:

- login state;
- organization switcher;
- membership and role administration;
- model policy and quota view;
- audit explorer;
- retention and deletion status;
- human review case view.

Acceptance:

- UI cannot reveal other-organization data through stale state;
- destructive actions require explicit confirmation;
- mobile and desktop layouts remain usable;
- text/template/voice core workflows remain direct.

## WP-14: Release hardening

Deliver:

- complete enterprise evaluation evidence;
- real-provider policy regression;
- dependency and secret scan;
- migration and recovery report;
- release notes and operator manual;
- `0.9.0rc1`.

Acceptance:

- every v0.9 release blocker cleared;
- v0.8 AI behavior gates remain passing;
- staging observation period completed;
- rollback rehearsal successful.

## Recommended commit sequence

```text
docs: define v0.9 enterprise tenancy architecture
test: add PostgreSQL enterprise integration profile
feat: add organization and principal foundation
feat: validate OIDC access tokens
feat: enforce capability-based authorization
feat: propagate tenant ownership and PostgreSQL RLS
feat: add S3-compatible storage backend
feat: harden tenant-aware background jobs
feat: add append-only enterprise audit
feat: govern models, quota and usage by organization
feat: add retention and review workflows
feat: instrument enterprise operations with OpenTelemetry
ops: add recoverable enterprise Compose profile
feat: add enterprise administration UI
release: AI Examiner v0.9.0-rc.1
```

## Explicitly deferred

- payment and subscription processor;
- public account signup;
- SCIM provisioning;
- organization marketplace;
- Kubernetes manifests;
- per-tenant database automation;
- customer-managed encryption keys;
- mobile native applications;
- hardware and device fleet management.
