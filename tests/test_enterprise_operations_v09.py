from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTERPRISE_DIR = ROOT / "deploy" / "enterprise"
sys.path.insert(0, str(ENTERPRISE_DIR))
import bootstrap_database  # noqa: E402


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_enterprise_compose_separates_runtime_and_migration_roles() -> None:
    compose = _yaml("docker-compose.enterprise.yml")
    services = compose["services"]
    assert {
        "ai-examiner",
        "worker",
        "postgres",
        "database-bootstrap",
    }.issubset(services)
    assert services["ai-examiner"]["environment"]["DATABASE_URL"].startswith(
        "${ENTERPRISE_DATABASE_URL:"
    )
    assert services["database-bootstrap"]["environment"][
        "DATABASE_URL"
    ].startswith("${ENTERPRISE_MIGRATION_DATABASE_URL:")
    assert services["ai-examiner"]["environment"]["POSTGRES_RLS_MODE"] == "enforce"
    assert (
        services["ai-examiner"]["environment"]["DATABASE_SCHEMA_MANAGEMENT"]
        == "external"
    )
    assert services["database-bootstrap"]["read_only"] is True
    assert services["database-bootstrap"]["restart"] == "no"
    assert services["database-bootstrap"]["env_file"] == [
        "${APP_ENV_FILE:-.env}"
    ]
    assert services["database-bootstrap"]["volumes"] == [
        "${HOST_DATA_DIR:-./data}:/app/data",
        "./prompts:/app/prompts:ro",
    ]
    assert (
        services["database-bootstrap"]["environment"]["STORAGE_LOCAL_ROOT"]
        == "/app/data/objects"
    )
    assert services["postgres"]["volumes"] == [
        "postgres-data:/var/lib/postgresql/data"
    ]
    assert "ports" not in services["postgres"]


def test_enterprise_profiles_keep_private_bindings_and_named_volumes() -> None:
    base = _yaml("docker-compose.yml")
    assert base["services"]["ai-examiner"]["ports"] == [
        "${APP_BIND_ADDRESS:-0.0.0.0}:${APP_PORT:-8000}:8000"
    ]
    https = _yaml("docker-compose.https.yml")
    assert https["services"]["caddy"]["env_file"] == [
        "${APP_ENV_FILE:-.env}"
    ]
    minio = _yaml("docker-compose.minio.yml")
    assert "minio-data" in minio["volumes"]
    assert minio["services"]["object-tool"]["profiles"] == ["operations"]
    observability = _yaml("docker-compose.observability.yml")
    for volume in (
        "tempo-data",
        "prometheus-data",
        "alertmanager-data",
        "grafana-data",
    ):
        assert volume in observability["volumes"]


def test_enterprise_scripts_are_fail_closed_and_non_destructive() -> None:
    scripts = {
        path.name: path.read_text(encoding="utf-8")
        for path in ENTERPRISE_DIR.glob("*.sh")
    }
    assert scripts
    for content in scripts.values():
        assert "set -euo pipefail" in content

    update = scripts["update-enterprise.sh"]
    rollback = scripts["rollback-enterprise.sh"]
    assert "down -v" not in update
    assert "down --volumes" not in update
    assert "down -v" not in rollback
    assert "alembic downgrade" not in rollback

    backup = scripts["backup-enterprise.sh"]
    assert "pg_dump --format=custom" in backup
    assert "manifest.sha256" in backup
    assert ".env" not in "\n".join(
        line for line in backup.splitlines() if "APP_ENV" not in line
    )

    restore = scripts["restore-enterprise.sh"]
    assert "sha256sum --check --strict" in restore
    assert "CONFIRM_ISOLATED_RESTORE" in restore
    assert "ai-examiner-restore-" in restore
    assert "refusing non-empty target" in restore
    assert "pg_restore --exit-on-error" in restore


def test_enterprise_shell_scripts_parse_when_bash_is_available() -> None:
    bash = shutil.which("bash")
    if bash is None and os.name == "nt":
        candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(candidate) if candidate.exists() else None
    if bash is None:
        pytest.skip("bash is unavailable")
    scripts = [str(path) for path in sorted(ENTERPRISE_DIR.glob("*.sh"))]
    subprocess.run([bash, "-n", *scripts], check=True, cwd=ROOT)


def test_database_bootstrap_rejects_unsafe_runtime_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_APP_USER", "unsafe-role;drop")
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "x" * 32)
    with pytest.raises(RuntimeError, match="safe PostgreSQL identifier"):
        bootstrap_database._app_credentials()

    monkeypatch.setenv("POSTGRES_APP_USER", "ai_examiner_runtime")
    with pytest.raises(RuntimeError, match="separate login role"):
        bootstrap_database._app_credentials()

    monkeypatch.setenv("POSTGRES_APP_USER", "examiner_runtime_login")
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "too-short")
    with pytest.raises(RuntimeError, match="at least 24"):
        bootstrap_database._app_credentials()


def test_enterprise_example_contains_placeholders_without_provider_keys() -> None:
    example = (ROOT / ".env.enterprise.example").read_text(encoding="utf-8")
    required = (
        "ENTERPRISE_DATABASE_URL=",
        "ENTERPRISE_MIGRATION_DATABASE_URL=",
        "POSTGRES_APP_PASSWORD=",
        "POSTGRES_MIGRATION_PASSWORD=",
        "AUTH_SESSION_SECRET=",
        "AUDIT_IP_HASH_KEY=",
        "ENTERPRISE_BACKUP_ROOT=",
    )
    for name in required:
        assert name in example
    assert not re.search(
        r"(sk-proj-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|"
        r"AIza[0-9A-Za-z_-]{20,})",
        example,
    )


def test_normal_update_never_removes_authoritative_volumes() -> None:
    for relative in (
        "deploy/enterprise/update-enterprise.sh",
        "deploy/enterprise/rollback-enterprise.sh",
    ):
        content = (ROOT / relative).read_text(encoding="utf-8")
        destructive = re.compile(
            r"docker\s+compose[^\n]*(?:down\s+-v|down\s+--volumes|volume\s+rm)"
        )
        assert destructive.search(content) is None
