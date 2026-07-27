# ADR-006: Enterprise Tenancy, Identity and Authorization

Status: Proposed for v0.9 research review
Date: 2026-07-27
Decision owners: Product, Architecture, Security
Target branch after acceptance: `develop/v0.9.0`

## Context

AI Examiner currently operates as a trusted single-user installation. Resources use
random identifiers, but an API caller who knows an identifier can generally read or
modify the resource. `template_authoring_context()` intentionally provides a local
authorization seam without enforcing identity or permissions. This is acceptable for
the existing evaluation deployment and is not acceptable for an institutional system.

v0.9 must support multiple organizations on one deployment without weakening:

- evidence-backed assessment;
- immutable session template snapshots;
- learner memory controls;
- provider and cost governance;
- Docker Compose deployment on a single Vultr host.

The enterprise boundary cannot be added only in the web UI. Every API, worker task,
database row and object key must carry authoritative tenant ownership.

## Decision

### 1. Organization is the tenant boundary

`Organization` is the top-level isolation boundary. Every non-global resource has an
explicit `organization_id`, including resources that can already be reached through a
project. The duplication is deliberate: it enables database row security, efficient
queries, explicit audit ownership and safe background jobs.

Global resources are limited to reviewed built-in template versions and deployment
configuration. Organization-authored templates, prompts and model policies are tenant
resources.

### 2. Authentication is delegated to OpenID Connect

v0.9 will not build a password database. Interactive users authenticate with an
external OpenID Connect provider. Browser login uses Authorization Code with PKCE.
The API validates access tokens against configured issuer metadata and JWKS.

Validation must check:

- signature and an explicit asymmetric algorithm allowlist;
- `iss`, `aud`, `exp` and `nbf`;
- subject presence;
- configured clock skew;
- token type and required scopes.

An ID token is not accepted as an API bearer token. Redirect URIs use exact matching.
The implicit flow is not supported.

`Principal` identity is keyed by `(issuer, subject)`. Email is profile data and is
never the stable identity key.

### 3. Service accounts use separate credentials

Non-interactive clients use organization-scoped service accounts. Tokens:

- are generated once and shown once;
- store only a strong hash and a short lookup prefix;
- have explicit scopes and optional expiry;
- can be rotated and revoked;
- never share interactive browser sessions.

Service account support follows interactive identity and RBAC. It is not a shortcut
around authorization.

### 4. Authorization uses explicit capabilities

Roles are bundles of capabilities. Endpoint code asks for a capability on a resolved
resource; it does not contain ad hoc role-name checks.

Initial organization roles:

| Role | Intended authority |
|---|---|
| `owner` | organization lifecycle, administrators, policy and destructive operations |
| `admin` | members, projects, templates, providers, quotas and audits |
| `examiner` | create projects, materials, sessions and reports |
| `template_author` | author local drafts and submit versions for review |
| `reviewer` | review templates, reports and human-review cases |
| `learner` | access explicitly assigned sessions and own memory controls |
| `auditor` | read audit, usage and policy evidence without content mutation |

Capabilities include `project.read`, `project.write`, `document.read`,
`document.create`, `session.conduct`, `report.read`, `template.author`,
`template.publish`, `member.manage`, `policy.manage`, `audit.read`,
`learner_memory.read_self` and `learner_memory.admin`.

Published built-in templates remain readable to all authenticated organizations but
cannot be modified by organization roles.

### 5. Application checks and PostgreSQL RLS are both required

The application authorization layer is the primary policy engine. PostgreSQL Row-Level
Security is defense in depth for tenant-scoped tables.

For each transaction, the application sets local database context:

```sql
SET LOCAL app.organization_id = '<uuid>';
SET LOCAL app.principal_id = '<uuid>';
```

RLS policies compare row ownership with `current_setting('app.organization_id', true)`.
Protected tables use `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.

The runtime database role:

- does not own protected tables;
- is not superuser;
- does not have `BYPASSRLS`;
- cannot disable policies.

Migrations and backup operations use separate operational roles. Worker jobs restore
the organization and actor context from a signed/validated task envelope before
opening business transactions.

RLS does not replace object-level authorization. OWASP BOLA tests remain mandatory.

### 6. Development compatibility is explicit

Authentication modes:

```text
disabled   local development and deterministic tests only
oidc       enterprise interactive deployment
```

Production refuses `disabled` unless
`ALLOW_UNSAFE_AUTH_DISABLED_IN_PRODUCTION=true` is explicitly configured. The health
endpoint reports an unsafe deployment state without returning secrets.

SQLite remains supported for unit tests, demos and migration source data. Enterprise
mode requires PostgreSQL and cannot claim tenant isolation on SQLite.

### 7. High-stakes decisions remain human-controlled

Roles and auditability do not authorize AI-only employment, academic, medical or other
high-stakes decisions. Templates retain prohibited-use controls. v0.9 adds review-case
and appeal evidence, not autonomous rejection or approval.

## Data ownership invariants

1. A project has exactly one organization.
2. A child resource has the same organization as its parent.
3. A cross-tenant foreign key is rejected before commit and, where practical, by a
   composite database constraint.
4. A worker job cannot run without an organization except for an allowlisted system
   maintenance job.
5. Audit events always record organization, actor or system actor, action, outcome and
   request correlation.
6. Deleting membership does not erase audit history.
7. Learner identity and memory never cross organizations unless a future explicit,
   consented federation design is accepted.

## Rejected alternatives

### UI-only organization switching

Rejected because direct API calls would remain cross-tenant vulnerable.

### Deriving tenant only through `project_id`

Rejected because many records have nullable or indirect project links, background jobs
need direct ownership, and RLS would require fragile joins.

### Local passwords in v0.9

Rejected because secure password recovery, MFA, session revocation and breach handling
would consume the version without differentiating the product.

### RLS as the only authorization mechanism

Rejected because RLS does not express every function-level permission, response field
rule or high-stakes review boundary.

### One database schema per tenant

Rejected for the initial enterprise line because migrations, pooling and operations
would become substantially more complex. Dedicated deployments remain available for
customers needing physical separation.

## Consequences

Positive:

- explicit and testable tenant isolation;
- compatibility with institutional identity providers;
- auditable cost and model ownership;
- a path from one-host Compose to private cloud.

Costs:

- every resource query and task must carry authorization context;
- migrations need a careful legacy-organization backfill;
- tests must run against PostgreSQL in addition to SQLite;
- backup and support tooling must understand tenant and operational roles.

## Acceptance conditions

This ADR is accepted only when:

- the capability matrix is reviewed;
- the ownership matrix covers every current model;
- the two-phase backfill and rollback strategy is executable;
- cross-tenant API and worker tests default-deny;
- PostgreSQL runtime and migration roles are documented;
- OIDC failure and key-rotation behavior is tested;
- production Compose cannot silently start with unsafe authentication.

## Standards and references

- OpenID Connect Core 1.0:
  https://openid.net/specs/openid-connect-core-1_0.html
- OAuth 2.0 Security Best Current Practice, RFC 9700:
  https://www.rfc-editor.org/rfc/rfc9700.html
- PostgreSQL Row Security Policies:
  https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- OWASP API1:2023 Broken Object Level Authorization:
  https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/
- OWASP API5:2023 Broken Function Level Authorization:
  https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/
