# v0.9 Enterprise Threat Model and Security Requirements

Status: Research draft
Method: asset/trust-boundary review with abuse cases

## 1. Protected assets

- unpublished papers, presentations, transcripts and evidence images;
- learner identity, memory, preferences and performance history;
- organization membership and role assignments;
- assessment reports and human-review decisions;
- model provider credentials and private gateway configuration;
- service-account secrets and OIDC tokens;
- template, prompt and policy versions;
- usage, cost and audit records;
- backups and exports.

## 2. Trust boundaries

```text
User browser
  -> reverse proxy
  -> FastAPI
  -> PostgreSQL / Redis / object storage
  -> Celery worker
  -> external or private model provider
  -> telemetry backend
```

Document content, user answers, template imports, model output and externally supplied
identity claims are untrusted inputs.

## 3. Primary threats and controls

### T1. Cross-tenant object access

Attack: a valid user substitutes another project, document, evidence, learner or job ID.

Controls:

- explicit organization ownership on rows;
- resource resolution inside organization context;
- capability checks on every object operation;
- PostgreSQL FORCE RLS;
- non-owner runtime database role;
- BOLA matrix tests for every route.

Release rule: zero successful cross-tenant reads or mutations in the mandatory suite.

### T2. Privilege escalation

Attack: a member grants themselves owner, publishes a template, changes model policy
or reaches an administrative route.

Controls:

- server-owned role/capability registry;
- no role claims trusted directly from client bodies;
- last-owner invariant;
- optimistic concurrency for membership changes;
- step-up/recent-auth requirement for sensitive operations;
- append-only audit;
- function-level authorization tests.

### T3. Token theft, replay or confusion

Controls:

- Authorization Code with PKCE;
- exact redirect URI matching;
- access token `iss`, `aud`, signature, expiry and type validation;
- asymmetric algorithm allowlist;
- no implicit flow;
- no ID token as API token;
- short service-token display, hashing, expiry, rotation and revocation;
- HTTPS only in enterprise mode;
- secrets and authorization headers redacted from logs and traces.

### T4. Worker confused deputy

Attack: a forged or stale task causes a worker to process another tenant's document or
use a prohibited model.

Controls:

- authoritative job row in PostgreSQL;
- organization/actor/policy task envelope;
- worker re-resolves all IDs under tenant context;
- model policy checked at execution time and snapshot recorded;
- idempotency and bounded retries;
- unknown job kinds default-deny;
- task payload excludes provider secrets.

### T5. Storage key traversal or URL leakage

Controls:

- application-generated object keys;
- tenant prefix;
- database authorization before streaming/presigning;
- short presigned expiry;
- content hash and size verification;
- TLS and encryption-at-rest configuration;
- object deletion reconciliation;
- no public buckets.

### T6. Prompt injection and model data exfiltration

Controls:

- documents remain untrusted data;
- model policy restricts provider by data classification and task;
- prompts delimit evidence and prohibit tool/secret access;
- provider credentials never enter model input;
- model output cannot grant permissions or change policy;
- sensitive model calls are auditable by metadata, not content.

### T7. Audit or telemetry disclosure

Controls:

- no document, transcript, prompt, email, token or API key in telemetry attributes;
- keyed hashes for high-cardinality identifiers where needed;
- audit metadata allowlist and redaction;
- restricted `audit.read`;
- bounded retention and protected exports.

### T8. Denial of service and cost abuse

Controls:

- body and upload limits;
- per-principal and per-organization rate limits;
- concurrent model-call limit;
- hard and soft cost quotas;
- queued long-running work;
- cancellation and stale-job cleanup;
- provider timeout and retry budget;
- metrics and alerts on denial, queue age and cost velocity.

### T9. Destructive deletion or retention abuse

Controls:

- explicit capability and recent authentication;
- idempotency key;
- review state for organization-wide and learner-wide deletion;
- legal/operational hold;
- dependency plan and verification phase;
- backup policy and recovery rehearsal;
- audit retained without deleted content.

### T10. Backup compromise or incomplete restore

Controls:

- encrypted backup destination;
- PostgreSQL-consistent snapshot;
- object manifest with hashes;
- secret backup handled separately;
- restore into isolated environment;
- periodic restore rehearsal and RPO/RTO measurement;
- backup role cannot serve application traffic.

## 4. Data classification

```text
public
internal
confidential
restricted
```

Default classifications:

- published built-in templates: public;
- project metadata and operational metrics: internal;
- uploaded materials, transcripts and reports: confidential;
- learner identity/memory, credentials and human-review cases: restricted.

An organization model policy can prohibit external providers for restricted data.

## 5. Logging and redaction denylist

Never log:

```text
Authorization
Cookie / Set-Cookie
OIDC code or token
service-account secret
provider API key
raw document or transcript
full prompt or model response
presigned URL query
memory export contents
```

Error records expose stable error codes to clients. Internal exceptions are correlated
by request ID.

## 6. Security test corpus

Minimum automated cases:

- two organizations with same role and similarly named resources;
- swapped UUID on every route;
- nested resource with mismatched parent;
- forged organization header;
- suspended membership and organization;
- owner removal race;
- expired, wrong-audience, wrong-issuer and unknown-key tokens;
- service token after revocation;
- RLS context missing and pooled-connection reuse;
- worker payload with foreign resource ID;
- presigned URL after membership removal and expiry;
- import file containing prompt injection and path traversal names;
- telemetry snapshot containing canary secrets;
- quota race across API and worker;
- deletion retry and orphaned object;
- backup restore with RLS enabled.

## 7. Security release blockers

- any cross-tenant data access;
- any route without declared capability;
- application runtime role bypasses RLS;
- production can start with unsafe auth without explicit override;
- secrets appear in logs, traces, audit or API responses;
- model policy can be bypassed by choosing a provider in request JSON;
- deletion reports complete before storage verification;
- backup cannot be restored into an isolated environment;
- AI output can write a final high-stakes decision.

## 8. References

- OAuth 2.0 Security Best Current Practice:
  https://www.rfc-editor.org/rfc/rfc9700.html
- OpenID Connect Core:
  https://openid.net/specs/openid-connect-core_1_0.html
- OWASP API Security Top 10:
  https://owasp.org/www-project-api-security/
- PostgreSQL Row Security:
  https://www.postgresql.org/docs/current/ddl-rowsecurity.html
