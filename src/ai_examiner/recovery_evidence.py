from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def file_manifest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _psycopg_url(database_url: str, *, database: str | None = None) -> str:
    parsed = make_url(database_url)
    driver = parsed.drivername.split("+")[0]
    return parsed.set(drivername=driver, database=database or parsed.database).render_as_string(
        hide_password=False
    )


def _command_environment(database_url: str) -> tuple[dict[str, str], list[str]]:
    parsed = make_url(database_url)
    environment = dict(os.environ)
    if parsed.password:
        environment["PGPASSWORD"] = parsed.password
    connection = [
        "--host",
        parsed.host or "127.0.0.1",
        "--port",
        str(parsed.port or 5432),
        "--username",
        parsed.username or "postgres",
    ]
    return environment, connection


def _table_counts(database_url: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "ORDER BY tablename"
            )
            for (table_name,) in cursor.fetchall():
                cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name)))
                counts[table_name] = int(cursor.fetchone()[0])
    return counts


def rehearse(
    repo_root: Path,
    *,
    database_url: str,
    object_root: Path,
    output: Path,
) -> dict[str, Any]:
    source_commit = _git(repo_root, "rev-parse", "HEAD")
    source_counts = _table_counts(database_url)
    source_manifest = file_manifest(object_root)
    restore_database = f"ai_examiner_restore_{uuid4().hex[:12]}"
    environment, connection_args = _command_environment(database_url)
    started = time.perf_counter()
    restore_created = False
    restore_dropped = False
    restored_counts: dict[str, int] = {}
    restored_manifest: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="ai-examiner-recovery-") as temporary:
        temporary_root = Path(temporary)
        database_dump = temporary_root / "database.dump"
        restored_objects = temporary_root / "objects"
        backup_started = time.perf_counter()
        subprocess.run(
            [
                "pg_dump",
                *connection_args,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(database_dump),
                make_url(database_url).database or "",
            ],
            check=True,
            env=environment,
            capture_output=True,
        )
        if object_root.exists():
            shutil.copytree(object_root, restored_objects)
        else:
            restored_objects.mkdir()
        backup_duration = time.perf_counter() - backup_started

        admin_url = _psycopg_url(database_url, database="postgres")
        try:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_database)))
                restore_created = True
            restore_started = time.perf_counter()
            subprocess.run(
                [
                    "pg_restore",
                    *connection_args,
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    restore_database,
                    str(database_dump),
                ],
                check=True,
                env=environment,
                capture_output=True,
            )
            restored_url = _psycopg_url(database_url, database=restore_database)
            restored_counts = _table_counts(restored_url)
            restored_manifest = file_manifest(restored_objects)
            rto_seconds = time.perf_counter() - restore_started
        finally:
            if restore_created:
                with psycopg.connect(admin_url, autocommit=True) as admin:
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(restore_database)
                        )
                    )
                    restore_dropped = True

    database_restore_verified = bool(source_counts) and restored_counts == source_counts
    object_restore_verified = bool(source_manifest) and restored_manifest == source_manifest
    source_database_healthy = _table_counts(database_url) == source_counts
    passed = (
        database_restore_verified
        and object_restore_verified
        and restore_dropped
        and source_database_healthy
    )
    payload = {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "status": "passed" if passed else "failed",
        "environment": "isolated_host_restore",
        "rpo_seconds": round(backup_duration, 3),
        "rto_seconds": round(rto_seconds, 3),
        "database_restore_verified": database_restore_verified,
        "database_table_count": len(source_counts),
        "database_row_count": sum(source_counts.values()),
        "object_restore_verified": object_restore_verified,
        "object_count": len(source_manifest),
        "rollback_success": restore_dropped and source_database_healthy,
        "source_environment_untouched": source_database_healthy,
        "temporary_restore_removed": restore_dropped,
        "total_rehearsal_seconds": round(time.perf_counter() - started, 3),
        "contains_database_dump": False,
        "contains_object_content": False,
        "contains_credentials": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an isolated PostgreSQL/object restore rehearsal.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--database-url", default=os.getenv("ENTERPRISE_MIGRATION_DATABASE_URL", ""))
    parser.add_argument("--object-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/evaluation/evidence/v0_9/disaster-recovery.json"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or ENTERPRISE_MIGRATION_DATABASE_URL is required")
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    payload = rehearse(
        repo_root,
        database_url=args.database_url,
        object_root=args.object_root.resolve(),
        output=output,
    )
    print(json.dumps(payload, indent=2))
    if payload["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
