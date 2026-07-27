# v0.9 Organization and Principal Foundation

Status: implemented research increment  
Work package: WP-02  
Enforcement mode: observe-only  
Package version: unchanged at `0.8.0.dev0`

## 1. Scope

This increment establishes durable enterprise identity roots without claiming that
authentication or authorization is complete.

It adds:

- `Organization` as the future tenant root;
- `Principal` keyed by external `(issuer, subject)`;
- `OrganizationMembership` linking a principal to one organization role;
- deterministic ownership of every legacy project;
- a bounded principal status lifecycle;
- an idempotent first-owner bootstrap command;
- a read-only request organization context.

It deliberately does not add:

- password authentication;
- OIDC token validation;
- service-account credentials;
- capability enforcement;
- tenant filtering on existing `/api/*` routes;
- PostgreSQL Row-Level Security.

Those controls belong to WP-03 through WP-05. Until they are complete, the context
response always states `authorization_enforced: false`.

## 2. Persistence contract

### Organization

```text
id
slug                 unique
display_name
status               active | suspended | disabled
version
created_at
updated_at
```

### Principal

```text
id
issuer
subject
display_name
email
status               pending | active | suspended | disabled
created_at
updated_at
disabled_at

UNIQUE (issuer, subject)
```

Email is profile data. It is never the stable identity key.

### OrganizationMembership

```text
id
organization_id
principal_id
role
status               invited | active | suspended | revoked
version
created_at
updated_at

UNIQUE (organization_id, principal_id)
```

The role vocabulary is:

```text
owner
admin
examiner
template_author
reviewer
learner
auditor
```

Roles are persisted now, but they do not authorize requests until WP-04 introduces
the capability registry and resource resolvers.

## 3. Legacy organization

All pre-v0.9 project data is assigned to:

```text
id:           00000000-0000-0000-0000-000000000001
slug:         legacy
display_name: Legacy workspace
```

The identifier is a product constant, not a randomly generated migration value.
This makes source validation, migration rehearsal and rollback deterministic across
SQLite and PostgreSQL.

Migration `20260727_0008`:

1. creates the organization, principal and membership tables;
2. inserts the legacy organization idempotently;
3. adds nullable `projects.organization_id`;
4. backfills every existing project;
5. makes the column non-null;
6. adds the organization foreign key and lookup index.

Child-resource ownership is still inferred through `project_id` in this increment.
WP-05 will add direct `organization_id` columns and cross-tenant constraints to all
tenant tables.

Downgrade preserves legacy projects and removes only the new ownership column and
identity tables. Downgrade refuses to proceed after principals have been created,
because silently discarding bootstrapped identity would be data loss.

## 4. Principal lifecycle

Allowed transitions:

```text
pending   -> active | disabled
active    -> suspended | disabled
suspended -> active | disabled
disabled  -> terminal
```

Calling a transition with the current state is idempotent. A disabled principal is
not silently reactivated. Future administrative APIs must use this service contract
instead of assigning arbitrary status strings.

## 5. Bootstrap owner

The first owner is created from the server CLI:

```bash
uv run ai-examiner-bootstrap-admin \
  --issuer "https://identity.example.edu" \
  --subject "administrator-subject" \
  --display-name "Platform administrator" \
  --email "admin@example.edu"
```

For local evaluation, omitting `--issuer` uses:

```text
urn:ai-examiner:local
```

The command:

- applies all migrations;
- ensures the deterministic legacy organization exists;
- creates or resolves the `(issuer, subject)` principal;
- creates one active `owner` membership;
- is idempotent for the same active owner;
- refuses to overwrite a conflicting or inactive membership;
- prints identifiers and profile fields as JSON;
- stores no password, bearer token or provider API key.

## 6. Observe-only request context

Research endpoint:

```text
GET /api/v1/context
```

Default response resolves the legacy organization:

```json
{
  "organization_id": "00000000-0000-0000-0000-000000000001",
  "principal_id": null,
  "principal_status": null,
  "membership_id": null,
  "membership_status": null,
  "role": null,
  "source": "legacy_default",
  "authorization_enforced": false,
  "mode": "observe_only"
}
```

In disabled local mode, tests may send:

```text
X-AI-Examiner-Organization
X-AI-Examiner-Principal
```

These headers only exercise context resolution. They are not proof of identity and
do not grant access. WP-03 will replace principal headers with validated access-token
claims. WP-04 will then load capabilities from the active membership.

Existing unversioned project create/list responses now expose `organization_id` so
migration behavior is visible without changing their authorization semantics.

## 7. Verification

Required deterministic checks:

```bash
uv run ruff check src tests
uv run pytest -q
node --check src/ai_examiner/static/app.js
uv run alembic upgrade head
uv run alembic current
```

The migration test creates a v0.8 database, inserts a legacy project, upgrades to
head, verifies deterministic ownership, downgrades to v0.8 and confirms the project
still exists.

GitHub CI runs the full suite on both SQLite and a dedicated PostgreSQL test
database. WP-02 is not complete until both jobs pass.

## 8. Next work

WP-03 adds strict OIDC access-token validation and principal provisioning. WP-04 adds
capability-based authorization and membership administration. WP-05 propagates
tenant ownership to every resource and enables PostgreSQL RLS.
