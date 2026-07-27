# v0.9 Enterprise Evaluation Plan

Status: Research draft

## 1. Evaluation question

Can AI Examiner safely support multiple institutions on one deployment while
preserving v0.8 examination quality, traceability and single-host operability?

Enterprise acceptance is based on isolation, recovery and governance. A polished
admin screen cannot compensate for a failed tenant boundary.

## 2. Test environments

### Fast deterministic environment

- SQLite;
- auth disabled;
- local filesystem;
- Celery eager;
- Mock provider.

Purpose: existing regression and pure policy tests.

### Enterprise integration environment

- PostgreSQL;
- OIDC test issuer;
- Redis and normal worker;
- S3-compatible object store;
- OTLP collector;
- Mock provider by default.

Purpose: isolation, auth, storage, queue, audit and telemetry.

### Staging acceptance environment

- Vultr Docker Compose;
- production-like TLS;
- configured institutional or test OIDC provider;
- real Qwen/OpenAI calls in a bounded budget;
- backup target separate from live volumes.

Purpose: deployment, real provider governance and disaster rehearsal.

## 3. Mandatory quality gates

### 3.1 Regression

```text
existing pytest suite: 100% pass
Ruff: pass
JavaScript syntax: pass
template deterministic evaluation: pass
Planner v6 seven-template evidence: no regression
```

### 3.2 Tenant isolation

Generate at least:

- 10 organizations;
- 5 principals per organization;
- every role;
- projects, documents, evidence, sessions, learners, jobs and exports.

Run a full subject/resource/action matrix.

Targets:

```text
cross-tenant successful read: 0
cross-tenant successful write: 0
missing-context row visibility under RLS: 0
runtime role RLS bypass: impossible
unclassified route: 0
```

### 3.3 Authentication

Cases:

- valid access token;
- expired token;
- future `nbf`;
- wrong issuer;
- wrong audience;
- disallowed algorithm;
- unknown `kid` and JWKS rotation;
- missing subject;
- ID token presented as access token;
- revoked/expired service token;
- disabled principal or membership.

Target: all invalid tokens denied without internal detail leakage.

### 3.4 Authorization

Every API route declares:

```text
authentication mode
capability
resource resolver
audit behavior
```

Generate tests from this registry. Manual route enumeration and the generated registry
must match.

Targets:

```text
routes missing capability metadata: 0
owner/admin invariant violations: 0
cross-organization membership use: 0
```

### 3.5 PostgreSQL migration

Dataset:

- representative v0.8 SQLite database;
- all current tables populated;
- intentionally orphaned copy used to verify migration refusal.

Checks:

- counts and hashes before/after;
- organization ownership coverage;
- all non-null and composite constraints;
- migration restartability;
- upgrade, rollback-to-safe-point and re-upgrade;
- PostgreSQL dump and restore;
- application reads equivalent records.

### 3.6 Storage contract

Run the same test suite against local and S3 backends:

- put/open/delete/exists;
- duplicate idempotent write;
- content hash mismatch;
- malicious filename;
- wrong-tenant object ID;
- short-lived download;
- expired URL;
- interrupted upload;
- deletion retry;
- orphan reconciliation.

Targets:

```text
unauthorized object access: 0
database/object ownership mismatch: 0
verified deletion completion: 100%
```

### 3.7 Queue safety

- duplicate task delivery;
- worker restart mid-task;
- stale lease;
- foreign tenant ID in payload;
- policy changed while queued;
- provider timeout;
- terminal validation failure;
- cancellation race.

Targets:

```text
duplicate billable result: 0
job without authoritative database row executed: 0
policy-bypassing provider call: 0
terminal jobs without audit event: 0
```

### 3.8 Audit

For each sensitive action verify actor, tenant, action, resource, outcome, request ID
and timestamp.

Canary scan audit records for:

- bearer tokens;
- provider keys;
- raw prompts;
- document excerpts;
- transcript sentences;
- presigned query strings.

Target: zero canary leakage.

### 3.9 Quota and model governance

- concurrent requests around hard limit;
- API and worker race;
- fallback after provider failure;
- request attempts disallowed model;
- confidential/restricted material with external provider;
- monthly budget rollover.

Target: no provider call occurs after an authoritative hard denial.

### 3.10 Observability

Verify traces across:

```text
HTTP -> database -> queue -> worker -> provider -> storage
```

Required spans and metrics must exist. Canary content must not exist.

Telemetry outage must not break core examination unless `AUDIT_REQUIRED` fails; audit
is business evidence and has a stricter path than optional telemetry export.

### 3.11 Backup and disaster recovery

Rehearsal:

1. generate active projects, object files and queued jobs;
2. take database/object backup;
3. destroy isolated staging volumes;
4. restore into a new Compose project;
5. run migrations if required;
6. verify counts, hashes, RLS, reports and downloads;
7. record RPO and RTO.

Initial targets for single-server institutional deployment:

```text
RPO <= 24 hours
RTO <= 4 hours
restore evidence completeness = 100%
```

Organizations needing tighter objectives require external managed infrastructure or a
reviewed deployment profile.

## 4. AI behavior regression

Enterprise context must not enter answer scoring as a quality signal. Run:

- the frozen v0.8 seven-template suite;
- Planner v6 30-case suite;
- Analyzer open-answer calibration tests;
- fixed/adaptive comparison;
- voice transcript finalization tests.

Compare authenticated and disabled-mode runs for identical content inputs and policy
snapshots. Scores and next actions must be equivalent except for ownership metadata.

## 5. Performance targets

On the agreed Vultr staging size:

```text
p95 non-model API latency < 300 ms
p99 authorization context creation < 100 ms
OIDC/JWKS cache hit validation < 20 ms p95
audit write included in transaction
job enqueue p95 < 250 ms
database pool saturation alerts before exhaustion
```

Model and realtime latency retain their own existing gates.

## 6. Promotion sequence

```text
unit and deterministic tests
-> PostgreSQL/S3/OIDC integration
-> cross-tenant adversarial suite
-> migration rehearsal
-> backup/restore rehearsal
-> Vultr staging
-> bounded real-provider regression
-> security review
-> release candidate
```

## 7. Evidence artifacts

Release evidence directory:

```text
docs/evaluation/evidence/v0_9/
  tenant-isolation.json
  auth-token-matrix.json
  route-capability-coverage.json
  postgres-migration.json
  storage-contract.json
  queue-idempotency.json
  audit-redaction.json
  quota-model-policy.json
  telemetry-redaction.json
  disaster-recovery.json
  ai-regression.json
```

Evidence contains no keys, tokens, user data or uploaded documents.

## 8. Release blockers

Any security release blocker from the threat model, plus:

- Docker Compose cannot start from documented configuration;
- existing v0.8 user workflow regresses materially;
- migration requires destructive manual edits without a verified backup;
- rollback path is undocumented;
- an organization cannot export and delete its controlled data;
- costs cannot be attributed to an organization;
- worker and API disagree about authorization or model policy.
