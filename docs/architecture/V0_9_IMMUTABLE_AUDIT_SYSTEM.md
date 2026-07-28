# v0.9 Immutable Audit System

Status: implemented on `research/v0.9.0`

Work package: WP-08

## 1. Purpose

WP-08 adds security and administrative evidence that is separate from domain content
and operational logs. It records who attempted a sensitive operation, for which
organization and resource, with what outcome and correlation identifiers.

Audit data is not a transcript store. It must never contain uploaded material,
answers, prompts, provider credentials, bearer tokens, cookies, presigned URLs or
other request content.

## 2. Event contract

`AuditEvent` is append-only:

```text
id
schema_version
organization_id
actor_type
actor_id
authentication_method
action
resource_type
resource_id
outcome
reason_code
request_id
trace_id
source_ip_class
source_ip_hash
user_agent_family
metadata_json
event_digest
retention_class
retention_until
occurred_at
```

Allowed actor types:

```text
anonymous
principal
system
worker
```

Allowed outcomes:

```text
succeeded
denied
failed
```

The event has no mutable status or `updated_at` field.

## 3. Correlation

Every HTTP request receives a server-generated UUID in:

```text
X-Request-ID
```

The audit event stores the same request ID. A valid W3C `traceparent` header supplies
the 32-character trace ID. Invalid, malformed or all-zero trace IDs are ignored and
the request UUID becomes the trace seed.

The application does not trust an incoming `X-Request-ID` as authoritative.

Worker terminal events use:

```text
request_id = job:<job_id>
trace_id = persisted envelope digest
```

OpenTelemetry request-to-worker propagation remains WP-11. WP-08 provides stable
correlation fields without introducing a telemetry backend dependency.

## 4. Request audit policy

`ROUTE_POLICIES` remains the authoritative route inventory. The following policy
behaviors generate events:

```text
authentication
administrative
read_sensitive
```

Authorization denials on required routes are audited even when a route would not
otherwise emit a success event.

The initial administrative transaction integration covers membership create, update
and revoke. The membership change and its required audit event are flushed and
committed in one database transaction. If the audit insert fails, the administrative
change is rolled back and the API returns:

```json
{
  "detail": {
    "code": "audit_unavailable",
    "message": "Required audit evidence is unavailable."
  }
}
```

Other policy-declared request events are written by the request middleware after the
response is produced. Worker terminal events are committed with their terminal job
state.

## 5. Denial behavior

Authentication and authorization dependencies attach only stable public reason codes:

```text
authentication_required
token_invalid
authorization_denied
resource_not_found
membership_inactive
```

Cross-organization attempts remain HTTP 404 to the caller. An existing target
organization can still receive a tenant-scoped denial event without exposing its
existence to the caller.

Request bodies, query values and authorization headers are never inspected or copied
by the audit middleware.

## 6. Metadata redaction

Audit metadata uses a positive allowlist:

```text
audit_class
capability
changed_fields
http_method
job_kind
membership_role
membership_status
recovered_count
route_template
status_code
terminal_status
```

Unknown keys are dropped. Keys associated with tokens, secrets, prompts, documents,
answers, transcripts, request bodies, headers, cookies and URLs are always dropped.

Allowed scalar values must be short identifier-like values. Secret-shaped or canary
values are replaced with `[REDACTED]`.

`source_ip_hash` is HMAC-SHA256, not a raw address. The HMAC key is supplied through:

```text
AUDIT_IP_HASH_KEY
```

Production startup fails when required auditing is enabled without this key.

Only a coarse IP classification is retained:

```text
loopback
private
public
unknown
```

User agents are reduced to a family such as `chrome`, `firefox`, `edge`, `curl` or
`python-httpx`; the raw header is not retained.

## 7. Immutability controls

### ORM

SQLAlchemy `before_update` and `before_delete` listeners reject mutation.

### SQLite

Native `BEFORE UPDATE` and `BEFORE DELETE` triggers reject direct SQL mutation. This
protects development and deterministic test environments in addition to ORM access.

### PostgreSQL

Migration `20260728_0014`:

- revokes `UPDATE` and `DELETE` from `ai_examiner_runtime`;
- grants runtime only `SELECT` and `INSERT`;
- enables and forces row-level security;
- creates tenant-scoped select and insert policies;
- creates a native mutation-rejection trigger;
- creates a separate `ai_examiner_audit_maintenance` role.

Normal application credentials must never be a member of
`ai_examiner_audit_maintenance`.

## 8. Retention boundary

Every event receives:

```text
retention_class
retention_until
```

The duration is configured by:

```text
AUDIT_RETENTION_DAYS
```

The runtime API reports how many events are eligible for privileged aging but has no
delete endpoint and no delete privilege.

PostgreSQL aging requires all of the following:

1. a separate database identity;
2. explicit membership in `ai_examiner_audit_maintenance`;
3. `SET app.audit_maintenance = 'on'`;
4. execution outside the API and worker runtime;
5. export and operational approval defined by WP-10.

SQLite audit rows are not aged by the application. This is deliberate: SQLite is not
the v0.9 enterprise retention backend.

Alembic downgrade refuses to drop `audit_events` while evidence exists.

## 9. API

List:

```text
GET /api/v1/organizations/{organization_id}/audit-events
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

The cursor is opaque and pagination is ordered by `occurred_at DESC, id DESC`.

Export:

```text
GET /api/v1/organizations/{organization_id}/audit-events/export
```

The response is redacted newline-delimited JSON:

```text
Content-Type: application/x-ndjson
```

The first record is a manifest. Export is bounded by:

```text
AUDIT_EXPORT_MAX_ROWS
```

Both endpoints require `audit.read` and are themselves audited as sensitive reads.

## 10. Worker coverage

Terminal background job transitions emit one domain event for:

```text
completed
failed
cancelled
dead_letter
authorization_revoked
queue_unavailable
```

Transient `retry_scheduled` transitions are not terminal and do not create terminal
evidence. Administrative retry/cancel/recovery requests remain covered by route
policy auditing.

## 11. Configuration

```env
AUDIT_REQUIRED=true
AUDIT_IP_HASH_KEY=<high-entropy-secret>
AUDIT_RETENTION_DAYS=365
AUDIT_EXPORT_MAX_ROWS=10000
```

Generate the HMAC key independently of provider credentials:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do not reuse `AUTH_SESSION_SECRET`, model API keys or storage credentials.

## 12. Verification

Deterministic tests cover:

- route-policy audit inventory;
- administrative success;
- authentication and authorization denial;
- cross-tenant audit isolation;
- request ID and traceparent correlation;
- metadata canary and credential redaction;
- API and JSONL export redaction;
- ORM and direct-SQL mutation rejection;
- required-audit rollback;
- worker terminal evidence;
- migration trigger creation;
- downgrade refusal with evidence.

`deploy/verify-v09-rls.py` additionally verifies on PostgreSQL:

- all four audit RLS policies;
- runtime has no update/delete privilege;
- organization-scoped visibility;
- runtime update is blocked;
- runtime delete is blocked.

## 13. Remaining enterprise work

WP-08 does not implement:

- organization-custom retention policies;
- legal holds;
- organization-wide data exports;
- data-subject deletion workflows;
- OpenTelemetry span propagation;
- the audit explorer UI.

These remain assigned to WP-10, WP-11 and WP-13.
