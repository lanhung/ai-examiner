# Migration from v0.7 Candidate to v0.8 Development

## Status

This migration documents the current `0.8.0.dev0` development branch. It is not a
production promotion instruction and does not replace the stable deployment line.

## Database change

Alembic revision `20260723_0006` adds:

```text
scenario_templates
scenario_template_versions
template_validation_runs
project_template_bindings
```

Alembic revision `20260723_0007` adds nullable columns to `exam_sessions`:

```text
template_version_id
template_snapshot_json
template_fingerprint
template_compiler_version
template_overrides_json
```

Existing v0.7 projects, documents, blueprints, text sessions, voice sessions,
learner memory and evidence rows remain readable. Old sessions retain null template
columns and are reported as legacy sessions.

Startup seeds source-controlled built-in templates by slug and semantic version.
Repeated startup is idempotent. If an existing built-in version has different
source or a different compiler fingerprint, startup fails and requires a semantic
version bump; it never edits the published row.

## Development upgrade

Back up `.env` and `data/` before testing:

```bash
cd /opt/ai-examiner
./deploy/backup.sh
git fetch origin
git checkout develop/v0.8.0
git pull --ff-only origin develop/v0.8.0
docker compose down --remove-orphans
docker compose up -d --build --remove-orphans
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/templates/health
```

Do not use `docker compose down -v`; volumes and database data must be preserved.

## Verification

Expected template health:

```json
{
  "status": "ok",
  "expected_builtin_count": 3,
  "persisted_template_count": 1,
  "persisted_version_count": 3,
  "issues": []
}
```

Check the migration head:

```bash
docker compose exec ai-examiner alembic current
```

Expected revision:

```text
20260723_0007
```

## Downgrade

The migration can return to `20260721_0005` while no exam session references a v0.8
template snapshot:

```bash
docker compose exec ai-examiner alembic downgrade 20260721_0005
```

Once bound sessions exist, revision `20260723_0007` refuses destructive downgrade
so historical examinations cannot silently lose their effective policy. Restore
from backup, explicitly archive those sessions, or retain the v0.8 schema instead.
