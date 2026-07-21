# Migration from v0.6 development to v0.7 development

Status: v0.7 foundation increment
Migration revision: `20260721_0003`

## 1. Scope

This additive migration creates:

```text
learner_identities
learner_identity_links
concepts
knowledge_unit_concept_maps
learner_memory_events
```

It does not alter or backfill existing v0.5/v0.6 sessions, learner subjects,
knowledge states, evidence events, voice sessions or usage telemetry.

Long-term memory remains inactive until an operator configures
`MEMORY_IDENTITY_SECRET` and a user explicitly enables memory for an identity.

## 2. Before upgrading

```bash
cd /opt/ai-examiner
./deploy/backup.sh
git status --short
docker compose ps
```

Confirm the backup contains the SQLite database and that `.env` remains outside
Git.

Generate a persistent identity HMAC secret once:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Add the result to the server `.env`:

```env
MEMORY_IDENTITY_SECRET=<generated-value>
```

Do not rotate this value casually. Changing it prevents the same external opaque
reference from resolving to its existing identity. It is not sent to the browser or
stored in the database.

## 3. Upgrade

Development/staging only:

```bash
git fetch --tags --prune origin
git checkout develop/v0.7.0
git pull --ff-only origin develop/v0.7.0

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps ai-examiner alembic upgrade head

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --build --remove-orphans
```

The application startup also runs Alembic, but the explicit migration command makes
failure visible before switching the running container.

## 4. Verification

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/health

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps ai-examiner alembic current
```

Expected revision:

```text
20260721_0003 (head)
```

Existing text and voice sessions must remain usable without creating a long-term
identity.

## 5. Rollback rehearsal

Stop application writes and use a copied database. Do not downgrade the only
production copy.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down --remove-orphans

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps ai-examiner alembic downgrade 20260720_0002
```

The downgrade removes only the five v0.7 foundation tables. Existing v0.6 tables
remain intact. Any v0.7 long-term identities, mappings and memory events are lost,
so restore the pre-upgrade backup if those records must be retained.

Reapply:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps ai-examiner alembic upgrade head
```

## 6. Data behavior

- no existing learner is automatically linked to a cross-project identity;
- no existing evidence is imported automatically;
- an accepted `exact` or `narrower` concept mapping is required for import;
- imports are idempotent by source evidence, concept and event type;
- deleting a project removes its subject links, mappings and imported memory events;
- canonical concepts and unrelated learner identities remain after project deletion;
- disabling memory blocks new evidence imports but preserves reviewable existing
  memory until an explicit deletion workflow is implemented in a later work package.

## 7. Security notes

- do not put external email addresses or phone numbers in `external_subject_ref` when
  an opaque application identifier is available;
- the server HMAC-hashes the reference and never returns the hash through the API;
- the current endpoints are evaluation-only until authentication/authorization is
  added; keep the service behind the existing operator access boundary;
- never commit `.env`, database files, exports or learner data.
