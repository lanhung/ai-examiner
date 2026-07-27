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

Deliver:

- `organization_id` on tenant tables;
- two-phase backfill;
- composite ownership constraints;
- SQLAlchemy transaction context;
- PostgreSQL policies and runtime role;
- worker tenant context.

Acceptance:

- no unowned required row;
- missing tenant context returns zero protected rows;
- pooled connections do not leak prior context;
- cross-tenant matrix has zero successful access.

## WP-06: Storage backend

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

## WP-07: Job hardening

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

## WP-08: Audit system

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
