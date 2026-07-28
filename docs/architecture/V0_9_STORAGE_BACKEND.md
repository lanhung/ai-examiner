# v0.9 Tenant Object Storage

Status: WP-06 implemented on `research/v0.9.0`

## 1. Scope

WP-06 replaces new host-path persistence with a tenant-scoped object locator. It
supports the local filesystem for single-host evaluation and an S3-compatible
backend for AWS S3, MinIO and private compatible services.

This work does not promote v0.9 to a deployable release. The package version remains
`0.8.0.dev0` until the complete v0.9 research gate is accepted.

## 2. Invariants

- Application code never accepts a user-supplied object key.
- Every key starts with an organization ID.
- The database stores backend, bucket, key, size, SHA-256 and content type.
- New document, evidence and memory-export writes use `StoredObject`.
- Legacy `storage_path` is nullable and exists only for transition and rollback.
- A download first resolves and authorizes the database resource.
- S3 objects are never made public.
- Redirect downloads use bounded presigned URLs.
- Stream downloads verify the content SHA-256 before returning bytes.
- Delete operations first resolve the tenant-owned locator.

## 3. Object keys

Canonical keys are deterministic and contain only validated path segments:

```text
org/{organization_id}/project/{project_id}/documents/{document_id}/source.{ext}
org/{organization_id}/project/{project_id}/evidence/{asset_id}/{kind}-{page}-{sequence}.{ext}
org/{organization_id}/exports/{artifact_id}.json
```

Filenames determine only a bounded extension. They cannot change a directory or
identifier segment.

## 4. Database locator

`stored_objects` is directly tenant-owned and contains:

```text
organization_id
project_id
resource_type
resource_id
purpose
backend
bucket
object_key
content_type
size_bytes
sha256
status
created_at
deleted_at
```

The physical locator `(backend, bucket, object_key)` is unique. PostgreSQL adds a
composite `(organization_id, id)` ownership key and FORCE RLS. `documents`,
`evidence_assets` and `memory_export_artifacts` reference the locator.

Migration: `20260728_0012_storage_locator_backend.py`.

## 5. Backend contract

`StorageBackend` defines:

```python
put_bytes(...)
read_bytes(...)
stat(...)
delete(...)
exists(...)
local_path(...)
presigned_get(...)
check_ready()
```

`LocalStorageBackend` uses an atomic short temporary file, `fsync` and
`os.replace`. It rejects traversal and verifies SHA-256.

`S3StorageBackend` stores SHA-256 in object metadata, verifies size and metadata
after upload, maps missing objects to `StorageObjectMissing`, supports optional
SSE-S3 or SSE-KMS and can issue short-lived download URLs.

## 6. Download authorization

Enterprise download routes:

```text
GET /api/v1/documents/{document_id}/file
GET /api/v1/evidence/{asset_id}/file
GET /api/v1/evidence/{asset_id}/highlight
GET /api/v1/memory-exports/{artifact_id}/file
```

Document and evidence routes require `document.read`. Memory exports currently
require `learner_memory.admin`; self-service export authorization is deferred until
the authenticated principal-to-learner binding is implemented.

All routes perform an explicit organization check after capability resolution.
Unversioned file routes remain only as disabled-mode compatibility paths.

## 7. Runtime configuration

Local:

```env
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=./data/objects
STORAGE_DOWNLOAD_MODE=stream
```

External S3:

```env
STORAGE_BACKEND=s3
STORAGE_DOWNLOAD_MODE=redirect
S3_ENDPOINT_URL=https://s3.example.com
S3_REGION=us-east-1
S3_BUCKET=ai-examiner-private
S3_ACCESS_KEY_ID=<deployment-secret>
S3_SECRET_ACCESS_KEY=<deployment-secret>
S3_REQUIRE_TLS=true
S3_ALLOW_INSECURE_HTTP=false
S3_SERVER_SIDE_ENCRYPTION=AES256
S3_PRESIGN_TTL_SECONDS=300
```

Use `aws:kms` plus `S3_KMS_KEY_ID` when the provider supports KMS. Credentials stay
in deployment secrets and never enter Git.

## 8. Optional MinIO Compose profile

Set strong test credentials in `.env`:

```env
MINIO_ROOT_USER=<random-access-id>
MINIO_ROOT_PASSWORD=<long-random-secret>
S3_BUCKET=ai-examiner
```

Start:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.minio.yml \
  up -d --build --remove-orphans
```

The object API is internal to the Compose network. The console binds only to
`127.0.0.1:9001`. The init container creates a private bucket and explicitly
disables anonymous access.

This profile uses HTTP only inside the private Compose network and disables
server-side encryption for local evaluation. Enterprise external object storage
must use TLS and reviewed encryption policy.

## 9. Restartable migration

Run with a migration credential that can read all organizations:

```bash
uv run ai-examiner-migrate-storage \
  --checkpoint ./data/storage-migration.json
```

Safe sequence:

```bash
uv run ai-examiner-migrate-storage --dry-run
uv run ai-examiner-migrate-storage
uv run ai-examiner-migrate-storage --reconcile-only
```

In Docker Compose, run the same command inside the application image so legacy
volume paths remain valid:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.minio.yml \
  run --rm ai-examiner \
  ai-examiner-migrate-storage --checkpoint /app/data/storage-migration.json
```

Properties:

- one database commit per resource;
- an atomic checkpoint after each result;
- restart verifies an existing locator rather than trusting checkpoint text;
- deterministic keys make repeated uploads idempotent at the object layer;
- the checkpoint contains no source host path;
- source files remain by default;
- `--delete-source` removes a source only after upload, verification and commit.

The schema downgrade refuses to run while any resource depends only on a locator.
Restore verified legacy paths first if schema rollback is required.

## 10. Failure recovery

If migration stops:

1. Keep the target backend and checkpoint unchanged.
2. Re-run the same command.
3. Run `--reconcile-only`.
4. Investigate `failed`, `missing` or `mismatched` entries.
5. Do not use `--delete-source` until the cutover is accepted.

Reconciliation marks absent objects `missing`; it does not silently delete database
records or manufacture replacement data.

## 11. Acceptance evidence

`tests/test_storage_backend_v09.py` covers:

- the same contract against Local and fake S3;
- traversal rejection and tenant-prefixed keys;
- TLS and KMS configuration validation;
- locator and checksum verification;
- upload plus authorized download;
- interrupted migration resume;
- no duplicate locator rows on rerun;
- checkpoint path redaction;
- missing-object reconciliation;
- fresh-schema index/FK parity;
- Alembic upgrade and safe downgrade.

PostgreSQL CI additionally verifies `stored_objects` FORCE RLS before the full
regression suite.
