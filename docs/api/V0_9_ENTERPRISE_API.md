# v0.9 Enterprise API Contract

Status: Research draft
Base path: `/api/v1`

## 1. Compatibility policy

The existing unversioned `/api/*` endpoints remain available only for:

- `AUTH_MODE=disabled`;
- migration tooling;
- an explicitly bounded compatibility window.

Enterprise clients use `/api/v1`. A request never gains access by sending an
organization header alone; the authenticated principal must have an active
membership.

## 2. Common request context

Interactive request:

```http
Authorization: Bearer <access-token>
X-AI-Examiner-Organization: <organization-id>
X-Request-ID: <optional-client-id>
```

Service client:

```http
Authorization: Bearer axe_<prefix>_<secret>
X-AI-Examiner-Organization: <organization-id>
```

The server returns:

```http
X-Request-ID: <server-correlation-id>
```

No endpoint accepts `principal_id`, role or capability from a request body as proof of
authority.

## 3. Error contract

```json
{
  "error": {
    "code": "authorization_denied",
    "message": "The requested operation is not permitted.",
    "request_id": "uuid",
    "details": {}
  }
}
```

Codes:

```text
authentication_required
token_invalid
organization_context_required
membership_inactive
authorization_denied
resource_not_found
conflict
quota_exceeded
rate_limited
policy_denied
retention_hold
dependency_unavailable
```

Cross-tenant lookups normally return `resource_not_found`.

## 4. Identity and current context

```text
GET  /api/v1/context
GET  /api/v1/me
GET  /api/v1/auth/login
GET  /api/v1/auth/callback
POST /api/v1/auth/logout
```

WP-03 authenticates `/api/v1/context` and `/api/v1/me` in OIDC mode. The context
endpoint still returns `authorization_enforced: false` until WP-04, but
`X-AI-Examiner-Principal` is ignored and cannot replace the verified principal.
Disabled mode retains the WP-02 observe-only compatibility behavior.

`GET /api/v1/auth/login` begins Authorization Code + PKCE and redirects to the
configured provider. `GET /api/v1/auth/callback` consumes one-time state, validates
access and ID tokens, resolves the principal and sets an opaque `HttpOnly` browser
session cookie. `POST /api/v1/auth/logout` revokes that session and clears the cookie.

`GET /me`:

```json
{
  "principal": {
    "id": "uuid",
    "display_name": "Example User",
    "status": "active"
  },
  "organizations": [
    {
      "id": "uuid",
      "role": "examiner",
      "membership_id": "uuid"
    }
  ],
  "authentication": {
    "method": "oidc_session",
    "issuer": "https://id.example.edu"
  }
}
```

Provider access tokens and raw token claims are never returned.

Operational readiness is exposed at `GET /ready`. It returns `503` when the database,
static OIDC configuration, discovery or JWKS endpoint is unavailable. `GET /health`
does not contact the identity provider.

## 5. Organizations and memberships

```text
POST   /api/v1/organizations
GET    /api/v1/organizations/{organization_id}
PATCH  /api/v1/organizations/{organization_id}
GET    /api/v1/organizations/{organization_id}/memberships
POST   /api/v1/organizations/{organization_id}/memberships
POST   /api/v1/organizations/{organization_id}/invitations
PATCH  /api/v1/organizations/{organization_id}/memberships/{membership_id}
DELETE /api/v1/organizations/{organization_id}/memberships/{membership_id}
```

Role changes use optimistic concurrency:

```http
If-Match: "<membership-version>"
```

The last active owner cannot be removed or demoted.

WP-04 implements direct administration of pre-provisioned principals through
`POST /memberships`. Invitation delivery and acceptance remain deferred. Every
membership mutation requires `If-Match`; owner creation or mutation additionally
requires `member.grant_owner`, which is not included in the default admin role.

## 6. Service accounts

```text
POST   /api/v1/organizations/{organization_id}/service-accounts
GET    /api/v1/organizations/{organization_id}/service-accounts
POST   /api/v1/organizations/{organization_id}/service-accounts/{id}/tokens
DELETE /api/v1/organizations/{organization_id}/service-accounts/{id}/tokens/{token_id}
POST   /api/v1/organizations/{organization_id}/service-accounts/{id}/disable
```

Token creation returns the secret only once. List endpoints return prefix, scopes,
created time, expiry and last-used time.

## 7. Tenant-scoped resource paths

New project entry points:

```text
POST /api/v1/organizations/{organization_id}/projects
GET  /api/v1/organizations/{organization_id}/projects
GET  /api/v1/organizations/{organization_id}/projects/{project_id}
```

Nested resources preserve project paths where useful:

```text
POST /api/v1/organizations/{organization_id}/projects/{project_id}/documents
POST /api/v1/organizations/{organization_id}/projects/{project_id}/blueprints
POST /api/v1/organizations/{organization_id}/projects/{project_id}/sessions
GET  /api/v1/organizations/{organization_id}/projects/{project_id}/usage
```

Session, evidence and report convenience routes remain available but resolve
organization from authenticated context and enforce object authorization:

```text
GET /api/v1/sessions/{session_id}
GET /api/v1/sessions/{session_id}/report
GET /api/v1/evidence/{asset_id}/file
```

## 8. Model policies and quota

```text
GET /api/v1/organizations/{organization_id}/model-policy
PUT /api/v1/organizations/{organization_id}/model-policy
GET /api/v1/organizations/{organization_id}/quota
PUT /api/v1/organizations/{organization_id}/quota
GET /api/v1/organizations/{organization_id}/usage
GET /api/v1/organizations/{organization_id}/usage/export
```

Model policy example:

```json
{
  "version": 4,
  "allowed_profiles": [
    {"provider": "qwen", "model_pattern": "qwen-plus", "tasks": ["planner", "analyzer"]},
    {"provider": "openai", "model_pattern": "gpt-realtime-*", "tasks": ["voice"]}
  ],
  "external_provider_max_classification": "confidential",
  "fallback_mode": "deny",
  "monthly_budget_usd": 500,
  "per_session_budget_usd": 4
}
```

Policy changes are audited. The server reports the effective model actually used.

## 9. Audit

```text
GET /api/v1/organizations/{organization_id}/audit-events
GET /api/v1/organizations/{organization_id}/audit-events/export
```

Filters:

```text
actor_id
action
resource_type
resource_id
outcome
occurred_after
occurred_before
request_id
cursor
limit
```

Audit responses contain redacted metadata only. Reading audit requires `audit.read`.

WP-08 implements both endpoints. List responses are cursor-paginated and include:

```json
{
  "items": [],
  "next_cursor": null,
  "retention": {
    "configured_days": 365,
    "eligible_for_privileged_aging": 0,
    "runtime_deletion_allowed": false
  }
}
```

Export uses `application/x-ndjson`; the first line is a manifest and all following
lines use the same redacted event contract as the list endpoint. Export is bounded by
`AUDIT_EXPORT_MAX_ROWS`. Both reads produce their own sensitive-read audit event.

Every API response under `/api/` also returns a server-generated:

```text
X-Request-ID
```

A valid W3C `traceparent` trace ID is retained for correlation. Raw request bodies,
headers, query values, cookies and user-agent strings are never copied into audit
metadata.

## 10. Retention, export and deletion

```text
GET  /api/v1/organizations/{organization_id}/retention-policy
PUT  /api/v1/organizations/{organization_id}/retention-policy
POST /api/v1/organizations/{organization_id}/exports
GET  /api/v1/organization-exports/{export_id}
GET  /api/v1/organization-exports/{export_id}/file
POST /api/v1/organizations/{organization_id}/data-subject-requests
GET  /api/v1/data-subject-requests/{request_id}
POST /api/v1/data-subject-requests/{request_id}/approve
POST /api/v1/data-subject-requests/{request_id}/cancel
POST /api/v1/data-subject-requests/{request_id}/retry
```

Destructive requests require an idempotency key:

```http
Idempotency-Key: <client-generated-value>
```

Deletion status:

```text
requested -> approved -> running -> verifying -> completed
                    \-> blocked
                    \-> failed
```

### 10.1 Implemented WP-06 private object downloads

```text
GET /api/v1/documents/{document_id}/file
GET /api/v1/evidence/{asset_id}/file
GET /api/v1/evidence/{asset_id}/highlight
GET /api/v1/memory-exports/{artifact_id}/file
```

Each route requires an authenticated organization context and the capability defined
in the resource matrix. The response either streams verified private bytes or
redirects to a bounded S3-compatible presigned URL. Object keys are not accepted as
request parameters.

## 11. Human review and appeal

```text
POST  /api/v1/organizations/{organization_id}/review-cases
GET   /api/v1/organizations/{organization_id}/review-cases
GET   /api/v1/review-cases/{case_id}
POST  /api/v1/review-cases/{case_id}/assign
POST  /api/v1/review-cases/{case_id}/decisions
POST  /api/v1/review-cases/{case_id}/appeals
```

AI evidence may initialize a case but cannot write the final human decision field.

## 12. Jobs

```text
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
GET  /api/v1/organizations/{organization_id}/jobs
POST /api/v1/organizations/{organization_id}/jobs/recover
```

Job responses include organization, policy snapshot, attempts and sanitized failure
codes. Celery task IDs and internal exception traces are not exposed.

Job reads require `job.read`; cancellation, manual retry and stale-worker recovery
require `job.manage`. Job IDs from another organization return 404. Retry is allowed
only for `failed`, `dead_letter` or `cancelled` jobs.

Asynchronous creation endpoints accept:

```http
Idempotency-Key: <1-to-160-character-client-key>
```

Reusing a key with the same organization, job kind, actor and payload returns the
existing job. Reusing it with another actor or payload is rejected.

Lifecycle:

```text
queued -> running -> completed
                 \-> retry_scheduled -> running
                 \-> failed
                 \-> dead_letter
                 \-> cancelling -> cancelled
```

## 13. Health and readiness

```text
GET /health
GET /ready
GET /api/v1/system/capabilities
```

`/health` is liveness and contains no provider details. `/ready` checks mandatory
enterprise dependencies and may require protected operator access for detail.

Readiness components:

```text
database
redis
object_storage
oidc_discovery
audit_sink
migrations
worker_heartbeat
```

## 14. Pagination and concurrency

Lists use opaque cursor pagination. Mutable administrative resources return `ETag`.
Updates use `If-Match` to prevent lost policy and membership changes.

## 15. API security tests

Every route with a resource identifier must test:

- anonymous access;
- inactive membership;
- same-role user in another organization;
- valid membership without capability;
- capability with a resource from another organization;
- service token with insufficient scope;
- suspended organization;
- stale policy version;
- deleted or retained resource;
- audit event generation for success and denial where appropriate.

WP-04 publishes each route's declared contract in OpenAPI:

```json
{
  "x-ai-examiner-policy": {
    "authentication": "required",
    "capability": "member.manage",
    "resource_resolver": "organization_membership",
    "audit": "administrative"
  }
}
```
