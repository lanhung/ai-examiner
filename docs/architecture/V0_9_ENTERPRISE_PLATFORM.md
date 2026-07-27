# v0.9 Enterprise Platform Architecture

Status: Research draft
Package version during research: unchanged (`0.8.0.dev0`)
First implementation version after gate acceptance: `0.9.0.dev0`

## 1. Objective

v0.9 turns the single-operator evaluation system into an institution-ready platform
without turning it into a collection of microservices.

The release must support:

- organizations, principals, memberships and capability-based RBAC;
- OIDC login and scoped service accounts;
- PostgreSQL tenant isolation;
- local and S3-compatible object storage;
- organization-owned model policy, quota and cost accounting;
- append-only audit evidence;
- retention, export and deletion workflows;
- OpenTelemetry observability;
- backup and disaster-recovery rehearsal;
- single-server Docker Compose and private-cloud configuration.

v0.9 is an enterprise foundation. Subscription billing, public signup, marketplace,
mobile apps and hardware remain outside this version.

## 2. Current gaps

| Area | v0.8 behavior | v0.9 requirement |
|---|---|---|
| Identity | trusted local operator/header seam | validated principal from OIDC or service account |
| Ownership | project UUID and indirect relationships | explicit `organization_id` on all tenant rows |
| Authorization | no general enforcement | centralized capabilities plus object checks |
| Database | SQLite default, PostgreSQL-compatible driver | PostgreSQL enterprise mode with RLS |
| Files | local paths in shared volume | storage backend and tenant-prefixed object keys |
| Jobs | project-aware Celery payloads | tenant/actor envelope, idempotency and dead-letter state |
| Cost | daily/project estimates | organization budgets, policy and authoritative ledger |
| Audit | domain-specific events | immutable security and administrative audit stream |
| Telemetry | health and JSON logs | OTLP traces/metrics with content redaction |
| Lifecycle | project deletion and memory controls | retention policy, export, deletion and appeal workflow |

## 3. Logical architecture

```text
Browser / API client
        |
        | OIDC code + PKCE / scoped service token
        v
Caddy / trusted reverse proxy
        |
        v
FastAPI
  |- Authentication middleware
  |- Organization context resolver
  |- Capability authorization service
  |- Existing examiner APIs
  |- Enterprise administration APIs
  |- Audit and telemetry interceptors
        |
        +---------------------+
        |                     |
        v                     v
PostgreSQL                StorageBackend
  |- tenant rows             |- LocalFilesystem (dev)
  |- FORCE RLS               |- S3-compatible (enterprise)
  |- usage ledger
  |- audit log
        |
        v
Redis / Celery
  |- organization task envelope
  |- idempotency key
  |- retries / dead-letter state
        |
        v
Model Gateway
  |- organization allowlist
  |- deployment secret references
  |- cost attribution

All services -> OTLP Collector -> Prometheus / trace backend / Grafana
```

The application remains a modular monolith with separate web and worker processes.
No microservice split is required by v0.9.

## 4. Domain model

### 4.1 Identity and organization

```text
Organization
  |- Membership -> Principal
  |- ServiceAccount
  |- OrganizationPolicy
  |- RetentionPolicy
  |- ModelPolicy
  |- Project
  |- AuditEvent
  |- UsageLedgerEntry

Principal
  |- issuer
  |- subject
  |- display profile
  |- status
```

Recommended tables:

```text
organizations
principals
organization_memberships
service_accounts
service_account_tokens
organization_policies
organization_model_policies
audit_events
usage_ledger_entries
retention_policies
data_subject_requests
review_cases
```

Membership uniqueness is `(organization_id, principal_id)`. Principal uniqueness is
`(issuer, subject)`.

### 4.2 Ownership matrix

Every table must be classified before migration:

| Ownership | Current resources |
|---|---|
| Global reviewed | built-in scenario template/version, provider catalog, schema registries |
| Organization | local templates/versions, prompt versions, concepts, model policy, audit, usage |
| Project | projects, documents, evidence, blueprints, sessions, turns, datasets, benchmarks, jobs, voice |
| Learner within organization | subjects, identities, links, memory, concept state, retest, preferences |
| Operational | migration records, backup manifests, system health |

Project and learner descendants receive direct `organization_id` even where a join
could infer it. Existing `project_id` remains.

### 4.3 Cross-tenant references

The service layer validates ownership before mutation. PostgreSQL constraints use
composite organization/resource keys where practical:

```sql
UNIQUE (organization_id, id)
FOREIGN KEY (organization_id, project_id)
  REFERENCES projects (organization_id, id)
```

This prevents a row with organization A from pointing at a project in organization B.

## 5. Request security pipeline

```text
request
-> request ID and trace context
-> authenticate bearer/session
-> resolve Principal
-> resolve selected Organization
-> load Membership and effective capabilities
-> open database transaction
-> SET LOCAL app.organization_id / app.principal_id
-> resolve resource inside tenant
-> authorize capability on resource
-> execute
-> append audit event
-> commit
```

Authorization failures return `404` when revealing resource existence would leak
tenant information. Administrative permission failures may return `403` when resource
existence is already authorized.

### 5.1 Identity modes

- `disabled`: tests and local demo only;
- `oidc`: interactive users;
- `service_token`: non-interactive API clients;
- `system`: allowlisted worker and maintenance operations.

The old `X-AI-Examiner-Actor` header is ignored outside disabled mode and removed after
the compatibility period.

### 5.2 Token handling

The API is a resource server. It validates access tokens and does not expose provider
tokens to model calls. Model API credentials stay server-side and are separate from
human identity tokens.

JWKS keys are cached with bounded TTL and refreshed after unknown `kid`. A refresh
failure does not make expired keys valid indefinitely.

## 6. Authorization design

Use a registry:

```python
authorize(
    principal=context.principal,
    organization=context.organization,
    capability="template.publish",
    resource=template_version,
)
```

Route handlers must not use direct `db.get(Model, external_id)` before tenant context.
Repositories accept organization context and issue tenant-scoped queries.

High-risk capabilities require a recent authentication signal or explicit review:

- `organization.delete`;
- `member.grant_owner`;
- `service_account.issue`;
- `template.publish`;
- `retention.reduce`;
- `data_subject.delete`;
- `model_policy.change`.

## 7. PostgreSQL and RLS

### 7.1 Roles

```text
ai_examiner_owner      schema owner/migrations, no application login
ai_examiner_runtime    API and worker, subject to FORCE RLS
ai_examiner_backup     backup/restore with audited operational access
ai_examiner_readonly   optional support/audit access
```

### 7.2 Transaction context

SQLAlchemy session hooks set transaction-local context. A transaction without
organization context sees no tenant rows. Context is cleared automatically at
transaction end, avoiding pooled-connection leakage.

### 7.3 SQLite compatibility

SQLite cannot enforce PostgreSQL RLS. Application authorization tests still run on
SQLite for speed; all tenant isolation and migration gates also run against a real
PostgreSQL container.

## 8. Object storage

Introduce:

```python
class StorageBackend(Protocol):
    put(...)
    open(...)
    delete(...)
    exists(...)
    presign_get(...)
    presign_put(...)
```

Implementations:

- `LocalFilesystemStorage` for development and legacy deployments;
- `S3Storage` for S3, MinIO or compatible private endpoints.

Canonical object keys:

```text
org/{organization_id}/project/{project_id}/document/{document_id}/source
org/{organization_id}/project/{project_id}/evidence/{asset_id}
org/{organization_id}/exports/{export_id}
```

Database rows store backend, bucket and object key, not host filesystem paths. Object
access always resolves the database resource and authorization before producing a
short-lived URL or streaming content.

Requirements:

- TLS in transit;
- server-side encryption configuration;
- SHA-256 and size stored at write;
- content type and extension validation;
- no user-controlled object key;
- bounded presigned URL duration;
- deletion queue with retry and orphan reconciliation;
- optional bucket versioning for recovery, governed by retention policy.

## 9. Job execution

Task envelope:

```json
{
  "organization_id": "uuid",
  "actor": {"type": "principal", "id": "uuid"},
  "request_id": "uuid",
  "job_id": "uuid",
  "idempotency_key": "stable-key",
  "policy_snapshot_id": "uuid",
  "payload": {}
}
```

Workers:

- resolve the job within the organization;
- set PostgreSQL tenant context;
- verify organization model policy before every provider call;
- update heartbeat and bounded progress;
- classify retryable versus terminal failures;
- never execute an unknown system job kind;
- write terminal failure and audit evidence.

Redis is not the authoritative job ledger. PostgreSQL remains authoritative.

## 10. Model governance and quotas

`OrganizationModelPolicy` defines:

- allowed providers and model patterns;
- allowed task types;
- private gateway base URL references;
- maximum document classification permitted for external providers;
- per-request and monthly cost limits;
- fallback policy;
- whether model output may be retained by the provider.

Provider credentials are referenced from deployment secrets. v0.9 does not store raw
provider keys in normal application tables.

Rate limits use Redis for fast counters. PostgreSQL usage ledger is authoritative for
cost reporting and quota reconciliation.

## 11. Audit design

`AuditEvent` is append-only and records:

```text
organization_id
actor_type / actor_id
action
resource_type / resource_id
outcome
reason_code
request_id / trace_id
source_ip classification or keyed hash
user_agent family
redacted change summary
occurred_at
```

Do not put document text, answer text, tokens, API keys or full prompts into audit
metadata. Domain evidence remains in its existing evidence tables.

Application code cannot update or delete audit events. Retention policy may export and
age them through a privileged operational process.

## 12. Data lifecycle

Retention policy is organization-specific but bounded by deployment policy.

Deletion is asynchronous:

```text
request
-> authorization / review
-> immutable deletion request
-> relational tombstone and dependency plan
-> object deletion
-> search/cache cleanup
-> verification
-> completion audit
```

Exports contain a manifest, record counts, hashes, policy versions and expiry. Export
downloads require authorization at access time; possession of an old database ID is
not sufficient.

## 13. Observability

Use OpenTelemetry SDK and instrumentation for FastAPI, SQLAlchemy, HTTPX and Celery,
exporting OTLP to an OpenTelemetry Collector.

Required trace attributes:

```text
service.name
deployment.environment
http.route
ai_examiner.organization_id_hash
ai_examiner.project_id_hash
ai_examiner.session_id_hash
ai_examiner.job_kind
ai_examiner.provider
ai_examiner.model
ai_examiner.prompt_version
ai_examiner.template_fingerprint
```

No raw answer, document, prompt, email, subject or token is a telemetry attribute.
High-cardinality identifiers are hashed or attached only to sampled traces.

Core metrics:

- request rate, latency and error by route;
- active and failed jobs;
- model call count, latency, retries and estimated cost;
- voice first-response and interruption metrics;
- authorization denials by capability;
- storage operation failures;
- database pool saturation;
- audit write failures;
- retention and deletion backlog.

## 14. Compose deployment profiles

### Minimum enterprise profile

```text
caddy
api
worker
postgres
redis
```

### Private data profile

Adds:

```text
minio (or external S3 endpoint)
```

### Observability profile

Adds:

```text
otel-collector
prometheus
grafana
```

The same application image is used across profiles. Secrets use environment files,
Docker secrets where available, or external secret injection. They are never baked
into the image.

## 15. Migration phases

1. Add organization and identity tables.
2. Create a deterministic legacy organization.
3. Add nullable `organization_id` columns and indexes.
4. Backfill ownership through projects and learner links.
5. detect and stop on orphan or conflicting ownership;
6. add composite constraints and make required ownership non-null;
7. switch file records to storage locators and copy/verify objects;
8. enable application authorization in shadow telemetry;
9. enable enforcement in staging;
10. enable and force RLS;
11. rehearse rollback before any destructive cleanup.

RLS is never enabled before backfill verification and tenant-scoped query conversion.

## 16. Feature flags

```text
ENTERPRISE_MODE
AUTH_MODE
AUTHZ_ENFORCEMENT_MODE=disabled|observe|enforce
POSTGRES_RLS_MODE=disabled|observe|enforce
STORAGE_BACKEND=local|s3
AUDIT_REQUIRED
RATE_LIMIT_MODE=disabled|observe|enforce
RETENTION_WORKER_ENABLED
OTEL_ENABLED
```

Production health reports the effective state. A missing mandatory enterprise
dependency makes readiness fail; it does not silently downgrade.

## 17. Non-goals

- public self-service signup and payment;
- organization marketplace;
- per-customer custom code execution;
- local password/MFA implementation;
- automatic high-stakes decisions;
- Kubernetes requirement;
- microservice decomposition;
- per-tenant schema or database automation;
- customer-managed encryption keys in the first increment.

## 18. Research gate

Do not create `develop/v0.9.0` until:

- ADR-006 is accepted;
- the ownership and capability matrices are complete;
- OIDC and service-token threat cases are reviewed;
- PostgreSQL RLS proof tests pass;
- SQLite-to-PostgreSQL migration rehearsal is scripted;
- local/S3 storage contract tests pass in a prototype;
- backup and full restore objectives are agreed;
- release metrics and security gates are accepted.

## 19. Research implementation progress

### WP-01 PostgreSQL parity

The first parity increment corrects an earlier false-positive CI boundary: the
PostgreSQL job created and migrated a PostgreSQL service, but the shared pytest
configuration unconditionally replaced `DATABASE_URL` with SQLite before importing
the application.

The corrected gate:

- uses the dedicated `AI_EXAMINER_TEST_DATABASE_URL` variable;
- refuses non-SQLite databases whose database name is not explicitly test-scoped;
- runs the complete regression suite against PostgreSQL rather than three selected
  files;
- includes an isolated Mock-only Compose rehearsal with temporary PostgreSQL and
  application data;
- excludes `.env`, runtime data, databases and archives from Docker build context.

Local environments without Docker continue to run the complete SQLite suite. The
PostgreSQL result is authoritative only after GitHub Actions or the isolated Compose
rehearsal completes.

GitHub Actions run `30243642156` passed both the complete SQLite and PostgreSQL jobs
for this gate.

### WP-02 organization and principal foundation

The second increment introduces the persistence roots needed by later authentication
and authorization work:

- `Organization`, `Principal` and `OrganizationMembership`;
- deterministic legacy organization `00000000-0000-0000-0000-000000000001`;
- non-null organization ownership on every current project;
- unique external principal identity by `(issuer, subject)`;
- bounded principal status transitions;
- idempotent first-owner bootstrap CLI;
- `/api/v1/context` organization resolution in explicit observe-only mode.

This increment does not trust organization or principal headers as credentials and
does not filter existing routes. OIDC, capability enforcement and RLS remain WP-03
through WP-05. Detailed contract:

- `docs/architecture/V0_9_ORGANIZATION_PRINCIPAL_FOUNDATION.md`.

## References

- PostgreSQL Row Security:
  https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- OpenID Connect Core:
  https://openid.net/specs/openid-connect-core-1_0.html
- OAuth Security BCP:
  https://www.rfc-editor.org/rfc/rfc9700.html
- OpenTelemetry Python:
  https://opentelemetry.io/docs/languages/python/
- S3 presigned URLs:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
- S3 encryption:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryption.html
