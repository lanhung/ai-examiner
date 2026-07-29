from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
RUNTIME_ROLE = "ai_examiner_runtime"
AUDIT_MAINTENANCE_ROLE = "ai_examiner_audit_maintenance"
GLOBAL_NOLOGIN_ROLES = (RUNTIME_ROLE, AUDIT_MAINTENANCE_ROLE)


def _database_dsn() -> str:
    configured = os.environ.get("DATABASE_URL", "")
    url = make_url(configured)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Enterprise database bootstrap requires PostgreSQL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _app_credentials() -> tuple[str, str]:
    username = os.environ.get("POSTGRES_APP_USER", "")
    password = os.environ.get("POSTGRES_APP_PASSWORD", "")
    if not ROLE_PATTERN.fullmatch(username):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    if username == RUNTIME_ROLE:
        raise RuntimeError("POSTGRES_APP_USER must be a separate login role")
    if len(password) < 24:
        raise RuntimeError("POSTGRES_APP_PASSWORD must contain at least 24 characters")
    return username, password


def prepare_roles() -> str:
    username, password = _app_credentials()
    with psycopg.connect(_database_dsn(), autocommit=True) as connection:
        with connection.cursor() as cursor:
            for role in GLOBAL_NOLOGIN_ROLES:
                cursor.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s",
                    (role,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        sql.SQL(
                            "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOINHERIT NOBYPASSRLS"
                        ).format(sql.Identifier(role))
                    )
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (username,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "INHERIT NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(username), sql.Literal(password))
                )
            else:
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "INHERIT NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(username), sql.Literal(password))
                )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(RUNTIME_ROLE),
                    sql.Identifier(username),
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET statement_timeout = '120s'").format(
                    sql.Identifier(username)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET lock_timeout = '10s'").format(
                    sql.Identifier(username)
                )
            )
    return username


def migrate() -> dict[str, str]:
    username = prepare_roles()
    alembic = Config("/app/alembic.ini")
    alembic.set_main_option(
        "sqlalchemy.url",
        os.environ["DATABASE_URL"].replace("%", "%%"),
    )
    command.upgrade(alembic, "head")
    username = prepare_roles()
    _seed_global_data()
    return {
        "status": "ready",
        "runtime_login": username,
        "runtime_role": RUNTIME_ROLE,
    }


def _seed_global_data() -> None:
    from ai_examiner.db import SessionLocal
    from ai_examiner.services.enterprise_identity import ensure_legacy_organization
    from ai_examiner.services.prompts import seed_prompt_registry
    from ai_examiner.services.templates import seed_builtin_templates

    prompt_directory = Path("/app/prompts")
    with SessionLocal() as database:
        ensure_legacy_organization(database)
        database.commit()
        seed_prompt_registry(database, prompt_directory)
        seed_builtin_templates(database)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("prepare-roles", "migrate"),
        default="migrate",
        nargs="?",
    )
    args = parser.parse_args()
    if args.action == "prepare-roles":
        result = {
            "status": "roles_ready",
            "runtime_login": prepare_roles(),
            "runtime_role": RUNTIME_ROLE,
        }
    else:
        result = migrate()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
