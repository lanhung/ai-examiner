# v0.9 Tenant Ownership and PostgreSQL RLS

Status: WP-05 implemented on `research/v0.9.0`

## 1. Goal

WP-05 makes organization ownership an authoritative database property instead of an
inference from a project ID or request header. Application capability checks remain
the primary authorization layer. PostgreSQL Row-Level Security is the second,
independent boundary.

The required invariant is:

```text
authenticated principal
  -> active organization membership
  -> transaction-local organization/principal context
  -> capability authorization
  -> resource query
  -> PostgreSQL RLS
```

## 2. Ownership classes

Required tenant rows have a non-null `organization_id`. This includes project
children, learner memory, usage records, background jobs and operational artifacts.

The following reviewed resources can be global or tenant-owned:

- scenario templates and versions;
- template validation runs;
- prompt versions;
- canonical concepts.

Global rows use `organization_id = NULL`. RLS permits authenticated tenant reads of
global rows but never permits the runtime role to create or mutate a global row.
Built-in/global seeding is therefore an operational migration action.

Deployment identity records remain outside ordinary content tenancy:

- `Principal`;
- OIDC login transactions;
- browser authentication sessions.

The runtime role receives reviewed DML privileges on these authentication control
tables because principal resolution and login-session validation occur before tenant
selection. They do not contain tenant content and remain guarded by the strict OIDC
and browser-session services. `Organization` and `OrganizationMembership` have
dedicated RLS policies.

## 3. Two-phase migration

### Phase A: `20260728_0010`

The first migration:

1. adds nullable ownership columns and indexes;
2. adds the background-job actor column;
3. derives ownership from projects, sessions, datasets, identities and other
   authoritative parents;
4. assigns unresolved legacy records to the deterministic legacy organization;
5. verifies that every required tenant table has zero unowned rows.

This phase does not make required columns non-null. Operators can stop after Phase A,
run reconciliation queries and remediate conflicts before enforcement.

### Phase B: `20260728_0011`

The enforcement migration:

1. makes required ownership columns non-null;
2. adds organization foreign keys;
3. replaces deployment-global uniqueness with tenant-aware uniqueness;
4. adds composite `(organization_id, parent_id)` constraints on critical ownership
   chains;
5. creates the non-login `ai_examiner_runtime` role;
6. grants only table DML and schema usage to that role;
7. enables and forces RLS on protected tables.

SQLite receives ownership columns and nullability constraints but not RLS. It remains
a local evaluation database and must not be described as an enterprise isolation
deployment.

## 4. Transaction context

`services/tenancy.py` stores context in `Session.info` and applies it to every new
PostgreSQL transaction:

```sql
SELECT set_config('app.organization_id', :organization_id, true);
SELECT set_config('app.principal_id', :principal_id, true);
```

The third argument is `true`, which is equivalent to transaction-local configuration.
Commit or rollback clears the database-side value. A SQLAlchemy `after_begin` hook
reapplies the trusted session context after service-layer commits.

OIDC authorization sets tenant context after authenticating the principal and before
resolving organization membership or protected resources. In disabled local mode the
legacy organization is installed explicitly.

Missing context is represented by an empty setting. Tenant policies compare against:

```sql
NULLIF(current_setting('app.organization_id', true), '')
```

No context therefore matches no protected row.

## 5. RLS policy

Required tenant tables use:

```sql
USING (
  organization_id =
  NULLIF(current_setting('app.organization_id', true), '')
)
WITH CHECK (
  organization_id =
  NULLIF(current_setting('app.organization_id', true), '')
)
```

Global-or-tenant reads additionally allow `organization_id IS NULL`. Their write
check still requires the active organization.

The runtime role is:

- not a login role;
- not superuser;
- not a database or role creator;
- `NOINHERIT`;
- not `BYPASSRLS`.

Production supplies a dedicated login role and explicitly grants it membership in
`ai_examiner_runtime`. The migration/backup role remains separate. The application
must not connect as a table owner or superuser when claiming RLS enforcement.

## 6. Composite ownership constraints

Critical project, session, evidence, learner and adaptive-state links receive
composite foreign keys. A child cannot claim organization A while referencing an
organization B parent, even when both row IDs are known.

Global references that intentionally allow either a global parent or same-tenant
parent remain application-validated because a single ordinary composite foreign key
cannot express that OR condition.

## 7. Worker context

Every queued business job now records:

```text
organization_id
actor_principal_id
project_id
```

Celery receives the immutable job ID plus organization and actor context. The worker
installs the tenant context before reading the authoritative job row. A missing or
foreign-tenant job fails before project, document, dataset or learner data is read.

Workers no longer run schema migrations at task start. Deployment applies migrations
with the operational database role before API and worker containers start.

Idempotency, leases, cancellation and signed task-envelope hardening remain WP-07.

## 8. Verification

SQLite tests verify:

- every business model has direct ownership;
- required rows inherit transaction context;
- global resources remain nullable;
- job envelopes carry organization and actor;
- foreign-tenant projects cannot be queued;
- upgrade and downgrade preserve legacy data.

PostgreSQL CI runs `deploy/verify-v09-rls.py` immediately after Alembic migration and
before pytest. It verifies:

- all required ownership columns are non-null;
- every expected RLS policy exists;
- the runtime role sees zero projects with missing context;
- organization A and B each see only their own project;
- switching context does not leak the previous organization;
- a cross-tenant insert is rejected.

## 9. Deployment requirements

Local evaluation:

```env
DATABASE_URL=sqlite:///./data/ai_examiner.db
POSTGRES_RLS_MODE=off
AUTH_MODE=disabled
```

Enterprise staging:

```env
DATABASE_URL=postgresql+psycopg://runtime-user:...@postgres/ai_examiner
DATABASE_SCHEMA_MANAGEMENT=external
POSTGRES_RLS_MODE=enforce
AUTH_MODE=oidc
```

`POSTGRES_RLS_MODE=enforce` refuses SQLite, disabled authentication or startup schema
management. The migration role runs `alembic upgrade head` and any reviewed global
seed step before API and worker startup. Runtime processes use
`DATABASE_SCHEMA_MANAGEMENT=external`; startup performs a connectivity check only and
never executes DDL or global seed writes.

Because protected tables use `FORCE ROW LEVEL SECURITY`, the migration/restore
credential must be a tightly controlled table owner with reviewed `BYPASSRLS` or
equivalent administrative authority. It is never supplied to API or worker
containers.

Research branches remain non-deployable until the dedicated runtime/migration-role
Compose topology and full migration rehearsal are accepted.

## 10. Deferred work

- S3-compatible tenant object ownership: WP-06;
- complete job lease/idempotency system: WP-07;
- append-only audit events: WP-08;
- runtime/migration role Compose packaging and restore rehearsal: later v0.9 work.
