from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select, text

from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    ScenarioTemplate,
    ScenarioTemplateVersion,
    TemplateValidationRun,
)
from ai_examiner.services.templates import seed_builtin_templates
from ai_examiner.templates.builtin import load_builtin_template


def _local_payload(
    *,
    slug: str = "local.thesis_defense",
    version: str = "0.1.0",
) -> dict:
    return {
        "slug": slug,
        "category": "academic",
        "semantic_version": version,
        "source": load_builtin_template("academic.thesis_defense.v1.yaml"),
    }


def test_builtin_template_seed_is_idempotent(client):
    assert client.get("/api/templates/health").json()["status"] == "ok"

    with SessionLocal() as db:
        before = (
            db.scalar(select(func.count(ScenarioTemplate.id))),
            db.scalar(select(func.count(ScenarioTemplateVersion.id))),
            db.scalar(select(func.count(TemplateValidationRun.id))),
        )
        seed_builtin_templates(db)
        seed_builtin_templates(db)
        after = (
            db.scalar(select(func.count(ScenarioTemplate.id))),
            db.scalar(select(func.count(ScenarioTemplateVersion.id))),
            db.scalar(select(func.count(TemplateValidationRun.id))),
        )

    assert before == after == (7, 9, 9)


def test_local_template_lifecycle_requires_validation_compilation_and_evaluation(client):
    created = client.post("/api/templates", json=_local_payload())
    assert created.status_code == 201
    payload = created.json()
    template_id = payload["template"]["id"]
    version_id = payload["version"]["id"]
    assert payload["version"]["status"] == "draft"
    assert payload["version"]["source"]["template"]["trust_level"] == "local_draft"

    compiled = client.post(f"/api/template-versions/{version_id}/compile")
    assert compiled.status_code == 200
    assert compiled.json()["fingerprint"].startswith("sha256:")
    assert compiled.json()["compiled"]["legacy"]["mode"] == "defense"

    candidate = client.post(
        f"/api/template-versions/{version_id}/status",
        json={"status": "candidate"},
    )
    assert candidate.status_code == 200
    assert candidate.json()["source"]["template"]["trust_level"] == "local_candidate"

    blocked = client.post(
        f"/api/template-versions/{version_id}/status",
        json={"status": "published"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "TEMPLATE_EVALUATION_REQUIRED"

    published = client.post(
        f"/api/template-versions/{version_id}/status",
        json={
            "status": "published",
            "evaluation_summary": {
                "status": "passed",
                "fixture_count": 8,
                "suite": "local-template-v1",
            },
        },
    )
    assert published.status_code == 200
    assert published.json()["published_at"]
    assert published.json()["source"]["template"]["trust_level"] == "local_published"

    immutable = client.put(
        f"/api/template-versions/{version_id}",
        json={"source": _local_payload()["source"]},
    )
    assert immutable.status_code == 409
    assert immutable.json()["detail"]["code"] == "TEMPLATE_VERSION_IMMUTABLE"

    detail = client.get(f"/api/templates/{template_id}")
    assert detail.status_code == 200
    assert detail.json()["versions"][0]["status"] == "published"
    catalog = client.get("/api/templates").json()
    assert {item["slug"] for item in catalog} == {
        "academic.grant_review",
        "academic.thesis_defense",
        "education.course_oral",
        "engineering.technical_interview",
        "enterprise.product_knowledge",
        "enterprise.sales_objection",
        "operations.project_review",
        "local.thesis_defense",
    }


def test_clone_creates_mutable_local_draft_without_changing_published_source(client):
    created = client.post("/api/templates", json=_local_payload()).json()
    version_id = created["version"]["id"]
    client.post(f"/api/template-versions/{version_id}/compile")
    client.post(
        f"/api/template-versions/{version_id}/status",
        json={"status": "candidate"},
    )
    client.post(
        f"/api/template-versions/{version_id}/status",
        json={
            "status": "published",
            "evaluation_summary": {"status": "passed", "fixture_count": 2},
        },
    )

    cloned = client.post(
        f"/api/template-versions/{version_id}/clone",
        json={"semantic_version": "0.2.0"},
    )
    assert cloned.status_code == 201
    clone = cloned.json()
    assert clone["status"] == "draft"
    assert clone["semantic_version"] == "0.2.0"
    assert clone["created_from_version_id"] == version_id
    assert clone["source"]["template"]["trust_level"] == "local_draft"

    original = client.get(f"/api/template-versions/{version_id}").json()
    assert original["status"] == "published"
    assert original["semantic_version"] == "0.1.0"


def test_mapper_guard_rejects_direct_published_content_mutation(client):
    built_in = client.get("/api/templates").json()[0]
    version_id = built_in["version_id"]

    with SessionLocal() as db:
        version = db.get(ScenarioTemplateVersion, version_id)
        mutated = copy.deepcopy(version.source_json)
        mutated["template"]["description"]["en"] = "Changed in place without a version bump"
        version.source_json = mutated
        with pytest.raises(ValueError, match="Published template version is immutable"):
            db.commit()
        db.rollback()

    with SessionLocal() as db:
        version = db.get(ScenarioTemplateVersion, version_id)
        db.delete(version)
        with pytest.raises(ValueError, match="cannot be deleted"):
            db.commit()
        db.rollback()


def test_builtin_seed_refuses_same_version_source_drift(client, monkeypatch):
    from ai_examiner.services import templates as template_service

    original_loader = template_service.load_builtin_template

    def changed_loader(filename: str) -> dict:
        source = original_loader(filename)
        source["template"]["description"]["en"] = "Unversioned source drift"
        return source

    monkeypatch.setattr(template_service, "load_builtin_template", changed_loader)
    with SessionLocal() as db:
        with pytest.raises(
            RuntimeError,
            match="changed without a semantic version bump",
        ):
            seed_builtin_templates(db)


def test_template_api_rejects_unbounded_source_and_bad_evaluation_types(client):
    oversized = _local_payload(slug="local.oversized")
    oversized["source"]["template"]["description"]["en"] = "x" * 300_000
    rejected = client.post("/api/templates", json=oversized)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "TEMPLATE_SOURCE_INVALID"

    created = client.post(
        "/api/templates",
        json=_local_payload(slug="local.bad_evaluation"),
    ).json()
    version_id = created["version"]["id"]
    client.post(f"/api/template-versions/{version_id}/compile")
    client.post(
        f"/api/template-versions/{version_id}/status",
        json={"status": "candidate"},
    )
    bad_evaluation = client.post(
        f"/api/template-versions/{version_id}/status",
        json={
            "status": "published",
            "evaluation_summary": {
                "status": "passed",
                "fixture_count": {"not": "an integer"},
            },
        },
    )
    assert bad_evaluation.status_code == 409
    assert bad_evaluation.json()["detail"]["code"] == "TEMPLATE_EVALUATION_REQUIRED"


def test_sqlite_migration_upgrade_downgrade_reupgrade_preserves_v07_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "template-migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "migration-test-secret",
    }

    def alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    alembic("upgrade", "20260721_0005")
    migration_engine = create_engine(database_url)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, name, domain, language, created_at) "
                "VALUES "
                "('legacy-project', 'Legacy project', 'research_defense', "
                "'zh-CN', '2026-07-23 00:00:00')"
            )
        )

    expected_tables = {
        "scenario_templates",
        "scenario_template_versions",
        "template_validation_runs",
        "project_template_bindings",
    }
    alembic("upgrade", "head")
    assert expected_tables <= set(inspect(migration_engine).get_table_names())
    assert {
        "template_version_id",
        "template_snapshot_json",
        "template_fingerprint",
        "template_compiler_version",
        "template_overrides_json",
    } <= {
        column["name"]
        for column in inspect(migration_engine).get_columns("exam_sessions")
    }
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM projects WHERE id = 'legacy-project'")
        ) == 1

    alembic("downgrade", "20260721_0005")
    assert not (expected_tables & set(inspect(migration_engine).get_table_names()))
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM projects WHERE id = 'legacy-project'")
        ) == 1

    alembic("upgrade", "head")
    assert expected_tables <= set(inspect(migration_engine).get_table_names())
    migration_engine.dispose()
