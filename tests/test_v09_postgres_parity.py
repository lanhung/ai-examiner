from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy.engine import make_url

from ai_examiner.db import engine

ROOT = Path(__file__).resolve().parents[1]


def test_test_database_override_is_explicit_and_safe():
    selected = make_url(os.environ["DATABASE_URL"])
    requested = os.environ.get("AI_EXAMINER_TEST_DATABASE_URL")
    if requested:
        assert selected == make_url(requested)
        database = (selected.database or "").lower()
        assert database == "test" or database.startswith("test_") or database.endswith("_test")
        assert engine.dialect.name == selected.get_backend_name()
    else:
        assert selected.drivername.startswith("sqlite")
        assert selected.database and "test" in selected.database.lower()


def test_ci_postgres_job_runs_the_complete_suite_on_postgres():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = workflow["jobs"]["postgres"]
    assert job["services"]["postgres"]["image"] == "postgres:17-alpine"
    assert job["env"]["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert job["env"]["AI_EXAMINER_TEST_DATABASE_URL"] == job["env"]["DATABASE_URL"]

    commands = [
        str(step["run"])
        for step in job["steps"]
        if isinstance(step, dict) and "run" in step
    ]
    pytest_commands = [command for command in commands if "pytest" in command]
    assert pytest_commands == [
        "uv run pytest --cov=ai_examiner --cov-report=term-missing"
    ]
    assert "tests/test_" not in pytest_commands[0]
    assert "uv run alembic upgrade head" in commands
    assert "uv run alembic current" in commands


def test_isolated_postgres_compose_rehearsal_is_mock_only():
    compose = yaml.safe_load(
        (ROOT / "docker-compose.postgres-test.yml").read_text(encoding="utf-8")
    )
    postgres = compose["services"]["postgres-test"]
    runner = compose["services"]["postgres-tests"]

    assert postgres["image"] == "postgres:17-alpine"
    assert postgres["environment"]["POSTGRES_DB"].endswith("_test")
    assert "/var/lib/postgresql/data" in postgres["tmpfs"]
    assert runner["environment"]["MODEL_PROVIDER"] == "mock"
    assert runner["environment"]["AI_EXAMINER_TEST_DATABASE_URL"].startswith(
        "postgresql+psycopg://"
    )
    assert "/app/data" in runner["tmpfs"]
    assert "OPENAI_API_KEY" not in runner["environment"]
    assert "DASHSCOPE_API_KEY" not in runner["environment"]

    command = " ".join(runner["command"])
    assert "alembic upgrade head" in command
    assert "pytest --cov=ai_examiner" in command

    script = (ROOT / "deploy" / "rehearse-v09-postgres.sh").read_text(
        encoding="utf-8"
    )
    assert "ai-examiner-v09-postgres-parity" in script
    assert "--exit-code-from postgres-tests" in script
    assert "trap cleanup EXIT" in script
    assert "down --remove-orphans -v" in script


def test_docker_context_excludes_secrets_and_runtime_data():
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {".git", ".env", "data", "*.db", "*.sqlite3"} <= ignored
