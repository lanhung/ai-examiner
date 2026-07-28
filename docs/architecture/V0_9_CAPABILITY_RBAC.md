# v0.9 Capability RBAC and Membership Administration

Status: WP-04 implemented on `research/v0.9.0`

## 1. Scope

WP-04 converts the verified principal introduced by WP-03 into a centralized,
organization-scoped authorization decision. It adds:

- one immutable capability registry;
- explicit role-to-capability bundles;
- a fail-closed authorization context resolver;
- FastAPI capability dependencies;
- resource organization mismatch protection;
- a complete `/api/v1` route policy registry;
- OpenAPI authorization metadata;
- membership list, create, update and revoke APIs;
- optimistic membership concurrency;
- last-active-owner protection;
- real OIDC capability checks on the legacy template-authoring seam.

WP-04 does not claim complete tenant isolation. Most existing business APIs are still
unversioned and do not yet have direct `organization_id`. WP-05 owns tenant ownership
propagation, scoped repositories and PostgreSQL RLS.

## 2. Policy model

Endpoint code requests capabilities:

```python
MemberManageAccess = Annotated[
    AuthorizationContext,
    Depends(require_capability("member.manage")),
]
```

It never grants access by checking role names directly. Roles are reviewed bundles
defined in `enterprise_constants.py`; the capability registry is authoritative.

Initial roles:

```text
owner
admin
examiner
template_author
reviewer
learner
auditor
```

High-risk capabilities are named separately. `member.grant_owner` is intentionally
owner-only, so an administrator with ordinary `member.manage` cannot create, demote,
suspend or revoke an owner.

## 3. Request decision pipeline

```text
validated AuthenticationContext
-> resolve path/header organization
-> require active Organization
-> require active Principal
-> require active OrganizationMembership
-> load role capability bundle
-> require declared capability
-> resolve resource within organization
-> execute operation
```

In OIDC mode:

- principal identity comes only from the validated bearer token or hashed browser
  session;
- `X-AI-Examiner-Principal` is ignored;
- organization selection does not grant membership;
- a same-role principal in another organization is denied.

In non-production `AUTH_MODE=disabled`, the principal header remains an explicit
deterministic-test compatibility mechanism. Production already refuses disabled
authentication unless the unsafe override is deliberately set.

## 4. Authorization context

Successful decisions produce:

```json
{
  "organization_id": "uuid",
  "principal_id": "uuid",
  "membership_id": "uuid",
  "role": "examiner",
  "capabilities": ["project.read", "session.conduct"],
  "authentication_method": "oidc_session",
  "authorization_enforced": true,
  "mode": "enforced"
}
```

No request body, role header, capability header or access-token custom role claim is
accepted as authorization proof.

## 5. Default-deny errors

Stable outcomes:

```text
authentication_required          401
organization_context_required    400
membership_inactive              403
authorization_denied             403
resource_not_found               404
```

A missing membership or resource belonging to another organization returns `404` to
avoid confirming its existence. Existing but inactive memberships and capability
failures return generic `403` messages without revealing the required role.

## 6. Route policy registry

Every `/api/v1` method/path pair has a `RoutePolicy` containing:

```text
authentication
capability
resource_resolver
audit
```

At startup, `bind_and_validate_route_policies()`:

1. enumerates FastAPI `/api/v1` routes;
2. fails startup when a route has no policy;
3. fails startup when a stale policy has no route;
4. writes the policy into OpenAPI as `x-ai-examiner-policy`.

CI independently compares the FastAPI inventory and registry. This prevents a new
enterprise route from silently bypassing authorization classification.

Public/conditional authentication endpoints are also classified; a route does not
disappear from the inventory merely because it has no business capability.

## 7. Membership API

Implemented:

```text
GET    /api/v1/organizations/{organization_id}
GET    /api/v1/organizations/{organization_id}/memberships
POST   /api/v1/organizations/{organization_id}/memberships
PATCH  /api/v1/organizations/{organization_id}/memberships/{membership_id}
DELETE /api/v1/organizations/{organization_id}/memberships/{membership_id}
```

Creation currently targets a pre-provisioned `Principal`. Email invitation delivery,
acceptance and identity-provider group synchronization are deferred.

Required capabilities:

```text
organization read        organization.read
membership list          member.read
create/update/revoke      member.manage
any owner mutation       member.grant_owner
```

## 8. Membership lifecycle

Allowed transitions:

```text
invited   -> active | revoked
active    -> suspended | revoked
suspended -> active | revoked
revoked   -> terminal
```

Role-only updates retain the current status. Every mutation increments `version`.

Updates and revocation require a strong `If-Match`:

```http
If-Match: "3"
```

Missing precondition returns `428`; stale or malformed versions return `412`.
Successful create/update/revoke responses return the current strong `ETag`.

## 9. Owner invariants

The service prevents:

- non-owner roles granting owner;
- administrators modifying an existing owner;
- demoting, suspending or revoking the last active owner;
- reviving a revoked membership.

The active-owner set is selected with `FOR UPDATE` where supported. This serializes
concurrent owner removals on PostgreSQL. SQLite remains a deterministic test and
migration environment, not an enterprise concurrency boundary.

## 10. Template authoring seam

The legacy `TemplateAuthoringAccess` compatibility seam now behaves differently by
mode:

```text
disabled, non-production -> explicit local compatibility
oidc                     -> active organization membership and capability RBAC
```

Operation requirements:

```text
create/import/clone/edit       template.author
validate/compile               template.author or template.review
publish/deprecate              template.publish
```

A reviewer can inspect and validate but cannot publish. A template author can draft
but cannot publish. Built-in/global ownership and local template `organization_id`
remain WP-05 work.

## 11. System capability API

`GET /api/v1/system/capabilities` requires an active authenticated principal and
returns:

- registered capabilities;
- reviewed role bundles;
- high-risk capability names.

It returns policy identifiers only, never membership data from another organization.

## 12. Deterministic test evidence

WP-04 focused tests cover:

- complete role/capability registry;
- authenticated system capability catalog;
- route inventory and OpenAPI metadata;
- role allow/deny matrix;
- same-role cross-organization denial;
- inactive principal, membership and organization;
- cross-organization resource substitution;
- anonymous and insufficient-capability requests;
- ETag creation and optimistic update;
- missing/stale preconditions;
- terminal revocation;
- admin owner-escalation denial;
- last-owner preservation;
- controlled second-owner handoff;
- OIDC template-authoring authorization.

The full SQLite and PostgreSQL suites remain required before the branch gate passes.

## 13. Deferred work

WP-05:

- propagate `organization_id` to all tenant resources;
- tenant-scoped repositories and composite ownership constraints;
- PostgreSQL transaction context and FORCE RLS;
- worker organization context.

Later packages:

- invitation acceptance;
- IdP group-to-role mapping;
- service accounts;
- recent-authentication enforcement for every high-risk capability;
- audit event persistence and correlation;
- assignment-level learner/session authorization.
