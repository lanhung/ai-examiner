# Upgrade v0.6 Development to v0.7 Release Candidate

## Safety boundary

The v0.7 schema is additive. It does not delete projects, documents, sessions,
voice events or v0.5 cognitive evidence. Do not use `docker compose down -v`.

## Staging rehearsal

```bash
cd /path/to/ai-examiner
./deploy/backup.sh
git fetch --tags origin
git checkout develop/v0.7.0
git pull --ff-only origin develop/v0.7.0

docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml down --remove-orphans
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --no-deps ai-examiner alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/health
```

Expected migration head:

```text
20260721_0005
```

## Rollback rehearsal

Application rollback should normally restore the pre-upgrade backup and previous
image/commit. A schema-only downgrade is available for staging verification:

```bash
docker compose run --rm --no-deps ai-examiner alembic downgrade 20260721_0004
```

This removes v0.7 preference, export, deletion and retest lifecycle data. Never run
it on the only copy of real evaluation data.

## v0.7 environment

```env
MEMORY_IDENTITY_SECRET=<long-random-server-only-secret>
DATABASE_URL=sqlite:///./data/ai_examiner.db
```

Changing `MEMORY_IDENTITY_SECRET` creates different opaque identity hashes and will
make existing external references resolve to new identities. Back it up separately
from the repository.

