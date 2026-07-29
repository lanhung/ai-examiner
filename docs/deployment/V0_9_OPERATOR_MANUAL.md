# AI Examiner v0.9 Enterprise Operator Manual

Status: release-candidate preparation. The `research/v0.9.0` branch is not a
production release and must not be tagged until the machine-readable release gate
reports `release_ready`.

## 1. Deployment topology

The enterprise profile runs PostgreSQL, Redis, the API, Celery worker and Caddy.
MinIO and the observability stack are optional Compose overlays.

```text
Caddy -> API -> PostgreSQL
              -> Redis -> Worker
              -> MinIO/S3
              -> OTLP collector
```

Use a dedicated Vultr staging host before production promotion. Do not reuse a
development `.env`, SQLite database or local object directory as enterprise
evidence.

## 2. Initial staging deployment

```bash
git clone https://github.com/lanhung/ai-examiner.git
cd ai-examiner
git checkout research/v0.9.0

cp .env.enterprise.example .env.enterprise
chmod 600 .env.enterprise
nano .env.enterprise
```

At minimum configure:

```text
APP_ENV=production
AUTH_MODE=oidc
OIDC_ISSUER_URL
OIDC_AUDIENCE
OIDC_CLIENT_ID
OIDC_CLIENT_SECRET
OIDC_REDIRECT_URI
AUTH_SESSION_SECRET
AUDIT_IP_HASH_KEY
MEMORY_IDENTITY_SECRET
POSTGRES_MIGRATION_PASSWORD
POSTGRES_APP_PASSWORD
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
DASHSCOPE_API_KEY or OPENAI_API_KEY
```

Never place secret values in Git, command history, release evidence, screenshots or
support messages.

Start the complete staging profile:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
USE_HTTPS=true \
./deploy/enterprise/start-enterprise.sh
```

Verify:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
USE_HTTPS=true \
VERIFY_READY=true \
./deploy/enterprise/verify-enterprise.sh
```

## 3. Normal update

The update path preserves `.env`, PostgreSQL, Redis, MinIO and Caddy volumes.

```bash
cd /opt/ai-examiner

APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
USE_HTTPS=true \
DEPLOY_BRANCH=research/v0.9.0 \
./deploy/enterprise/update-enterprise.sh
```

The script takes a backup, fetches the branch, rebuilds images, runs Alembic through
the migration identity, starts the new application and verifies the deployment.

Never use this during an ordinary update:

```bash
docker compose down -v
```

`-v` deletes named volumes and is reserved for disposable CI projects.

## 4. Stop and start

Stop without deleting data:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
USE_HTTPS=true \
./deploy/enterprise/stop-enterprise.sh
```

Start again with the command in section 2. PostgreSQL and object data must remain
present after restart.

## 5. Backup, restore and rollback

Create a consistent database and object backup:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
./deploy/enterprise/backup-enterprise.sh
```

Run an isolated recovery rehearsal:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
RESTORE_PROJECT_NAME=ai-examiner-restore-drill \
./deploy/enterprise/rehearse-enterprise.sh
```

Application-code rollback:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
USE_HTTPS=true \
./deploy/enterprise/rollback-enterprise.sh
```

Rollback does not perform an automatic database downgrade. Migrations in v0.9 are
additive; a destructive downgrade requires an approved recovery plan and a verified
backup.

Initial single-host objectives:

```text
RPO <= 24 hours
RTO <= 4 hours
database and object verification = 100%
```

## 6. Real-provider governance probe

Run exactly one bounded call after Qwen or OpenAI is configured:

```bash
uv sync --extra dev --extra providers

uv run ai-examiner-probe-model-governance \
  --profile qwen:qwen-plus \
  --output data/release-evidence/quota-model-policy.json
```

The artifact contains only provider/model identity, policy version and digest,
Token counts, latency, estimated cost and ledger consistency. It never stores the
prompt, response or API key.

Review the artifact, then archive the sanitized copy:

```bash
mkdir -p docs/evaluation/evidence/v0_9
cp data/release-evidence/quota-model-policy.json \
  docs/evaluation/evidence/v0_9/quota-model-policy.json
```

## 7. Release evidence

The required evidence schema is documented in:

```text
docs/evaluation/evidence/v0_9/README.md
```

Run deterministic and promotion checks:

```bash
uv sync --extra dev

uv run ai-examiner-verify-v09-release \
  --output data/release-evidence/v0_9-release-gate.json
```

To make a release pipeline fail until every external artifact is accepted:

```bash
uv run ai-examiner-verify-v09-release \
  --require-release-ready \
  --output data/release-evidence/v0_9-release-gate.json
```

Exit codes:

```text
0 deterministic checks passed
1 deterministic or security check failed
2 deterministic checks passed but release evidence is incomplete
```

Only `status=release_ready` authorizes version promotion to `0.9.0rc1`.

## 8. Daily operations

Check application readiness:

```bash
curl -fsS https://YOUR_DOMAIN/health
curl -fsS https://YOUR_DOMAIN/ready
```

Inspect services:

```bash
docker compose \
  --env-file .env.enterprise \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.enterprise.yml \
  -f docker-compose.minio.yml \
  -f docker-compose.observability.yml \
  -f docker-compose.https.yml \
  ps
```

Inspect bounded logs:

```bash
docker compose \
  --env-file .env.enterprise \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.enterprise.yml \
  logs --tail=200 ai-examiner worker
```

Provider errors, OIDC outages, quota denials, audit write failures, dead-letter jobs,
database pool saturation and backup age require operator review.

## 9. Incident priorities

1. Preserve audit, database and object evidence.
2. Stop new writes if tenant isolation, authorization or audit integrity is in doubt.
3. Revoke exposed credentials at the provider, not only in `.env`.
4. Record source commit, deployment profile, first observed time and affected tenant.
5. Restore into an isolated Compose project before replacing live volumes.
6. Do not copy uploaded content or tokens into issue trackers.

## 10. RC promotion

Promotion is a separate change after every release gate passes:

1. create `develop/v0.9.0` from the accepted source commit;
2. set all version surfaces to `0.9.0rc1`;
3. commit release notes and the sanitized evidence manifest;
4. run the full release gate again;
5. create immutable annotated tag `v0.9.0-rc.1`;
6. deploy that exact tag to staging;
7. do not move or rewrite the tag.

