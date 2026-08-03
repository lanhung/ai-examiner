from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _runtime_database_url() -> str:
    migration_url = make_url(os.environ["DATABASE_URL"])
    if not migration_url.drivername.startswith("postgresql"):
        raise RuntimeError("The runtime-login verifier requires PostgreSQL")
    username = os.environ.get("POSTGRES_APP_USER", "")
    password = os.environ.get("POSTGRES_APP_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "POSTGRES_APP_USER and POSTGRES_APP_PASSWORD are required"
        )
    return migration_url.set(username=username, password=password).render_as_string(
        hide_password=False
    )


def verify(*, worker_count: int = 20, read_count: int = 100) -> dict[str, object]:
    if worker_count < 1 or read_count < 2:
        raise ValueError("worker_count must be positive and read_count must be at least 2")

    migration_engine = create_engine(os.environ["DATABASE_URL"], future=True)
    runtime_engine = create_engine(
        _runtime_database_url(),
        future=True,
        pool_size=worker_count,
        max_overflow=0,
        pool_timeout=30,
    )
    if migration_engine.dialect.name != "postgresql":
        raise RuntimeError("The runtime-login verifier requires PostgreSQL")

    organization_a = str(uuid4())
    organization_b = str(uuid4())
    project_a = str(uuid4())
    project_b = str(uuid4())
    cross_tenant_project = str(uuid4())
    app_user = os.environ["POSTGRES_APP_USER"]

    def visible_projects(organization_id: str | None) -> list[str]:
        with runtime_engine.connect() as connection:
            transaction = connection.begin()
            try:
                if organization_id is not None:
                    connection.execute(
                        text(
                            "SELECT set_config('app.organization_id', "
                            ":organization_id, true)"
                        ),
                        {"organization_id": organization_id},
                    )
                return list(
                    connection.execute(
                        text("SELECT id FROM projects ORDER BY id")
                    ).scalars()
                )
            finally:
                transaction.rollback()

    fixtures_created = False
    try:
        with migration_engine.begin() as connection:
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                    "FROM pg_roles WHERE rolname = :role"
                ),
                {"role": app_user},
            ).one_or_none()
            if role is None:
                raise RuntimeError(f"PostgreSQL application login does not exist: {app_user}")
            connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, slug, display_name, status, version, created_at, updated_at) "
                    "VALUES (:a, :slug_a, 'Runtime A', 'active', 1, now(), now()), "
                    "(:b, :slug_b, 'Runtime B', 'active', 1, now(), now())"
                ),
                {
                    "a": organization_a,
                    "b": organization_b,
                    "slug_a": f"runtime-a-{organization_a}",
                    "slug_b": f"runtime-b-{organization_b}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, domain, language, created_at) "
                    "VALUES (:project_a, :a, 'Runtime Project A', 'test', "
                    "'en', now()), (:project_b, :b, 'Runtime Project B', "
                    "'test', 'en', now())"
                ),
                {
                    "project_a": project_a,
                    "project_b": project_b,
                    "a": organization_a,
                    "b": organization_b,
                },
            )
        fixtures_created = True

        missing_context = visible_projects(None)
        visible_a = visible_projects(organization_a)
        visible_b = visible_projects(organization_b)

        def concurrent_read(index: int) -> bool:
            if index % 2:
                return visible_projects(organization_b) == [project_b]
            return visible_projects(organization_a) == [project_a]

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            reads = list(executor.map(concurrent_read, range(read_count)))

        cross_tenant_write_blocked = False
        try:
            with runtime_engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT set_config('app.organization_id', "
                        ":organization_id, true)"
                    ),
                    {"organization_id": organization_b},
                )
                connection.execute(
                    text(
                        "INSERT INTO projects "
                        "(id, organization_id, name, domain, language, created_at) "
                        "VALUES (:id, :organization_id, 'Cross tenant', "
                        "'test', 'en', now())"
                    ),
                    {"id": cross_tenant_project, "organization_id": organization_a},
                )
        except Exception:
            cross_tenant_write_blocked = True

        result = {
            "status": "passed",
            "runtime_role_superuser": bool(role.rolsuper),
            "runtime_role_create_role": bool(role.rolcreaterole),
            "runtime_role_create_db": bool(role.rolcreatedb),
            "runtime_role_bypass_rls": bool(role.rolbypassrls),
            "missing_context_count": len(missing_context),
            "organization_a_visible": len(visible_a),
            "organization_b_visible": len(visible_b),
            "concurrent_reads_passed": sum(reads),
            "concurrent_reads_total": len(reads),
            "cross_tenant_write_blocked": cross_tenant_write_blocked,
        }
        expected = {
            "runtime_role_superuser": False,
            "runtime_role_create_role": False,
            "runtime_role_create_db": False,
            "runtime_role_bypass_rls": False,
            "missing_context_count": 0,
            "organization_a_visible": 1,
            "organization_b_visible": 1,
            "concurrent_reads_passed": read_count,
            "concurrent_reads_total": read_count,
            "cross_tenant_write_blocked": True,
        }
        failures = {
            key: {"expected": value, "actual": result[key]}
            for key, value in expected.items()
            if result[key] != value
        }
        if failures:
            raise RuntimeError(f"Runtime PostgreSQL isolation failed: {failures}")
        return result
    finally:
        runtime_engine.dispose()
        if fixtures_created:
            with migration_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM projects WHERE id IN (:a, :b, :cross)"),
                    {"a": project_a, "b": project_b, "cross": cross_tenant_project},
                )
                connection.execute(
                    text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                    {"a": organization_a, "b": organization_b},
                )
        migration_engine.dispose()


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
