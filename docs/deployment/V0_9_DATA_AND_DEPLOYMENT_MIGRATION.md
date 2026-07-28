# v0.9 Data and Deployment Migration Strategy

Status: Research draft

## 1. Principles

- No in-place destructive experiment on the active v0.8 deployment.
- Back up database, files and configuration before migration.
- Copy and verify before switching reads.
- Keep a rollback point until acceptance completes.
- Redis is disposable coordination state, not authoritative data.
- Secrets are migrated separately and never enter backups committed to Git.

## 2. Target single-host topology

```text
Caddy
  -> FastAPI
  -> PostgreSQL
  -> Redis
  -> Celery worker
  -> S3-compatible storage or external S3
  -> OTLP collector (optional profile)
```

The initial v0.9 enterprise line remains compatible with a single Vultr machine.
Managed PostgreSQL or object storage can replace local Compose services later without
changing application contracts.

## 3. Database migration

### Phase A: source validation

```text
run current migrations
foreign key check
row counts by table
file locator existence
content hashes
backup and restore v0.8 in isolation
```

Migration stops on orphaned ownership. It never guesses between conflicting projects
or learner links.

### Phase B: enterprise schema in PostgreSQL

Create roles, schema and organization tables. Create one deterministic organization:

```text
slug: legacy-local
name: Migrated local deployment
```

Add nullable ownership columns and indexes.

### Phase C: data copy

Use a dedicated migration command, not application startup:

```bash
ai-examiner migrate-enterprise \
  --source sqlite:///... \
  --target postgresql+psycopg://... \
  --legacy-organization legacy-local \
  --verify
```

The command is restartable and records a migration manifest.

### Phase D: ownership verification

For every table:

- source and target count;
- primary key set hash;
- organization coverage;
- parent-child ownership agreement;
- JSON payload hash where stable;
- timestamps and status distribution.

### Phase E: constraints and RLS

Only after verification:

- make required ownership non-null;
- add composite foreign keys;
- create RLS policies;
- run application queries in observe mode;
- switch runtime role;
- enable and force RLS.

## 4. File-to-object migration

Inventory current paths from `Document`, `EvidenceAsset`, exports and memory artifacts.

For each object:

1. authorize source under the legacy organization;
2. compute SHA-256 and size;
3. upload to canonical tenant key;
4. read metadata or sample body to verify;
5. write storage locator;
6. mark migration item complete.

Do not delete local source files during the initial migration. Delete only after an
accepted rollback window.

## 5. Cutover

Recommended maintenance cutover:

```text
announce maintenance
stop API writes and workers
take final SQLite/file backup
run delta migration
verify manifests
start enterprise Compose in isolated project
run smoke and cross-tenant tests
switch Caddy upstream
observe
```

Keep v0.8 containers stopped but recoverable until acceptance.

## 6. Rollback

Before any v0.9-only writes, rollback is:

```text
stop v0.9
restore v0.8 configuration
start v0.8 against untouched source data
switch proxy upstream
```

After v0.9-only writes, automatic rollback to SQLite is not safe. Recovery then uses
the v0.9 PostgreSQL/object backup or an explicitly implemented reverse export.

The release must state the point of no automatic rollback.

## 7. Backup design

Backup set:

```text
PostgreSQL logical dump or managed snapshot
object inventory and version-aware copy
deployment configuration without raw secrets
migration version
template/prompt fingerprints
manifest with hashes and timestamps
```

Redis is not backed up for business recovery. Queued/running jobs are reconciled from
PostgreSQL after restore.

## 8. Restore rehearsal

Restore into a different Compose project name and empty volumes. Verify:

- migrations current;
- organization and membership counts;
- RLS default deny;
- documents and evidence hashes;
- report retrieval;
- learner memory controls;
- template fingerprints;
- usage and audit continuity;
- stale jobs reconciled.

## 9. Required configuration

Planned variables:

```env
ENTERPRISE_MODE=true
AUTH_MODE=oidc
OIDC_ISSUER_URL=
OIDC_AUDIENCE=
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
AUTHZ_ENFORCEMENT_MODE=enforce

DATABASE_URL=postgresql+psycopg://...
DATABASE_SCHEMA_MANAGEMENT=external
POSTGRES_RLS_MODE=enforce

STORAGE_BACKEND=s3
S3_ENDPOINT_URL=
S3_REGION=
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_REQUIRE_TLS=true
S3_PRESIGN_TTL_SECONDS=300

AUDIT_REQUIRED=true
RATE_LIMIT_MODE=enforce
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

`.env.example` eventually documents names with blank values. Real values remain only
in deployment secrets.

## 10. Promotion commands

The final implementation must retain a simple operator workflow:

```bash
./deploy/backup-enterprise.sh
git pull --ff-only origin main
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml build
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml \
  run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml \
  up -d --remove-orphans
./deploy/verify-enterprise.sh
```

Normal updates never use `docker compose down -v`.

The migration command uses a DDL-capable migration credential. API and worker
containers use a separate login role granted membership in `ai_examiner_runtime`.
With `DATABASE_SCHEMA_MANAGEMENT=external`, application startup checks connectivity
but does not run Alembic, `create_all` or global seed writes.
