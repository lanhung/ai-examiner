# v0.9 Enterprise Docker Compose and Recovery

Status: WP-12 implementation contract
Target: one-host institutional staging on Vultr

## 1. Topology

The mandatory profile is:

```text
Caddy
  -> FastAPI
  -> PostgreSQL 17
  -> Redis
  -> Celery worker
```

Optional overlays add:

- private MinIO object storage;
- OpenTelemetry Collector, Tempo, Prometheus, Alertmanager and Grafana.

PostgreSQL, Redis, MinIO, Caddy and observability data use named volumes. Normal
start, stop, update and application rollback never remove those volumes.

## 2. Security boundary

Database identities are separated:

- `POSTGRES_MIGRATION_USER` owns schema migration and backup operations;
- `POSTGRES_APP_USER` is a login role granted membership in the non-login
  `ai_examiner_runtime` role;
- API and worker receive only `ENTERPRISE_DATABASE_URL`;
- `database-bootstrap` receives `ENTERPRISE_MIGRATION_DATABASE_URL`;
- application startup uses `DATABASE_SCHEMA_MANAGEMENT=external`;
- `POSTGRES_RLS_MODE=enforce` and `AUTH_MODE=oidc` are forced by Compose.

The application login is checked to be non-superuser and without `BYPASSRLS`.
Passwords must be random, URL-safe and at least 24 characters.

## 3. Prepare Vultr

Install Docker Engine, the Compose plugin, Git and curl. Clone the branch:

```bash
sudo mkdir -p /opt/ai-examiner
sudo chown "$USER":"$USER" /opt/ai-examiner
git clone --branch research/v0.9.0 \
  https://github.com/lanhung/ai-examiner.git \
  /opt/ai-examiner
cd /opt/ai-examiner
```

Create the private environment:

```bash
cp .env.enterprise.example .env.enterprise
chmod 600 .env.enterprise
nano .env.enterprise
chmod +x deploy/enterprise/*.sh
```

Generate independent secrets:

```bash
openssl rand -base64 36 | tr -d '\n'
```

Do not reuse database, OIDC, audit, storage or model-provider secrets.

## 4. Start with one command

Core enterprise profile:

```bash
APP_ENV_FILE=.env.enterprise \
USE_HTTPS=true \
./deploy/enterprise/start-enterprise.sh
```

Full single-host profile:

```bash
APP_ENV_FILE=.env.enterprise \
USE_HTTPS=true \
USE_MINIO=true \
USE_OBSERVABILITY=true \
./deploy/enterprise/start-enterprise.sh
```

The script validates Compose, builds images, runs the one-shot database bootstrap,
starts services and verifies health, readiness, schema revision, least privilege
and PostgreSQL RLS.

The application port should remain bound to `127.0.0.1`; Caddy is the public TLS
entry point. Grafana and Prometheus also bind to localhost. Reach them through an
SSH tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 user@VULTR_IP
```

## 5. Stop without data loss

```bash
APP_ENV_FILE=.env.enterprise \
USE_HTTPS=true \
USE_MINIO=true \
USE_OBSERVABILITY=true \
./deploy/enterprise/stop-enterprise.sh
```

This uses `docker compose stop`. It does not run `down -v`, `volume rm` or a
database downgrade.

## 6. Consistent backup

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
USE_OBSERVABILITY=true \
./deploy/enterprise/backup-enterprise.sh
```

Each backup directory contains:

```text
postgres.dump
alembic-version.txt
metadata.json
manifest.sha256
objects/                 # when MinIO is enabled
objects-complete         # object mirror completion marker
```

`pg_dump` creates a transaction-consistent custom-format database backup while the
service remains online. Object data is copied with `mc mirror`. SHA-256 covers every
artifact. `.env` and provider credentials are never included.

The default path is `data/enterprise-backups`, but production should set
`ENTERPRISE_BACKUP_ROOT` to a separately mounted encrypted destination and copy
completed sets off-host.

Redis is not authoritative and is not backed up. Restored jobs are reconciled from
PostgreSQL through the WP-07 recovery API.

## 7. Isolated restore

Never restore directly over live volumes. Use a new project name and port:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
RESTORE_PROJECT_NAME=ai-examiner-restore-20260729 \
RESTORE_APP_PORT=18080 \
CONFIRM_ISOLATED_RESTORE=yes \
VERIFY_READY=true \
./deploy/enterprise/restore-enterprise.sh \
  /mnt/backup/ai-examiner/20260729T010000Z
```

The script:

1. verifies the SHA-256 manifest;
2. refuses a project name outside `ai-examiner-restore-*`;
3. refuses any target with existing volumes;
4. creates database roles before `pg_restore`;
5. restores PostgreSQL without changing the live project;
6. restores and re-downloads objects for hash comparison;
7. runs additive migrations to the current head;
8. verifies health, readiness, least privilege and RLS;
9. writes `disaster-recovery.json` with measured RPO and RTO.

The restored project is retained for human inspection. Volume removal is a
separate, explicit operator action after evidence review.

## 8. Full rehearsal

With the live enterprise profile healthy:

```bash
APP_ENV_FILE=.env.enterprise \
USE_MINIO=true \
RESTORE_PROJECT_NAME=ai-examiner-restore-drill \
RESTORE_APP_PORT=18080 \
./deploy/enterprise/rehearse-enterprise.sh
```

Initial single-host targets:

```text
RPO <= 24 hours
RTO <= 4 hours
manifest verification = 100%
database restore verification = passed
object hash verification = passed when object storage is enabled
```

The generated evidence contains timing, status and project identifiers only. It
does not contain tokens, user content or provider credentials.

## 9. Normal update

```bash
cd /opt/ai-examiner
APP_ENV_FILE=.env.enterprise \
USE_HTTPS=true \
USE_MINIO=true \
USE_OBSERVABILITY=true \
DEPLOY_BRANCH=research/v0.9.0 \
./deploy/enterprise/update-enterprise.sh
```

The update flow is:

```text
consistent backup
-> git fetch and fast-forward pull
-> build while current release remains online
-> stop API, worker and Caddy
-> run migration container
-> start all services
-> verify
```

The previous commit and backup path are saved under
`data/enterprise-release-state`.

## 10. Application rollback

```bash
APP_ENV_FILE=.env.enterprise \
USE_HTTPS=true \
USE_MINIO=true \
USE_OBSERVABILITY=true \
./deploy/enterprise/rollback-enterprise.sh COMMIT_OR_TAG
```

This rolls back application code only. It deliberately does not run Alembic
downgrade and does not restore a database over live volumes. All v0.9 migrations
must remain additive during the compatibility window.

After v0.9-only writes begin, rollback to the old SQLite deployment is not safe.
Recovery uses the PostgreSQL/object backup and the isolated restore procedure.

## 11. Operational checks

```bash
docker compose \
  --env-file .env.enterprise \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.enterprise.yml \
  ps

curl -fsS https://YOUR_DOMAIN/health
curl -fsS https://YOUR_DOMAIN/ready
```

Inspect API, worker, migration and proxy logs without printing environment values:

```bash
docker compose \
  --env-file .env.enterprise \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.enterprise.yml \
  -f docker-compose.https.yml \
  logs --tail=200 ai-examiner worker database-bootstrap caddy
```

Never use `docker compose down -v` against the live enterprise project.
