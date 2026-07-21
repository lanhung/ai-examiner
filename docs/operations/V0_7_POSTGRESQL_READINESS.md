# v0.7 PostgreSQL Readiness

## Scope

v0.7 keeps SQLite as the default for single-server evaluation. The memory domain,
Alembic migrations and CI also support PostgreSQL through `psycopg`; production is
not migrated automatically.

## Compatibility rules

- Core memory calculations load typed rows and do not depend on database-specific
  JSON operators.
- Identity, concept mapping, source-event and preference uniqueness is enforced by
  ordinary constraints supported by both databases.
- Time values are declared timezone-aware. Services normalize legacy naive SQLite
  values to UTC before comparisons.
- Scoped deletion uses SQLAlchemy expressions and Python filtering only where JSON
  portability would otherwise be lost.
- Migration `20260721_0005` supports upgrade, downgrade and re-upgrade on SQLite;
  CI runs the v0.7 migration and domain suite against PostgreSQL 17.

## Optional PostgreSQL evaluation

```bash
export DATABASE_URL='postgresql+psycopg://examiner:password@postgres:5432/examiner'
docker compose run --rm --no-deps ai-examiner alembic upgrade head
```

Before changing a live database, restore a backup into a separate environment and
run the complete suite. Switching `DATABASE_URL` does not transfer SQLite data.

## Remaining production work

- Define backup, point-in-time recovery and connection-pool limits for the target
  deployment.
- Rehearse a separately reviewed SQLite-to-PostgreSQL data migration.
- Load-test concurrent workers and deletion jobs.
- Add tenant authorization before exposing memory APIs beyond an operator boundary.

