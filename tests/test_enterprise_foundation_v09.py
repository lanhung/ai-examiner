from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import (
    LEGACY_ORGANIZATION_ID,
    LOCAL_IDENTITY_ISSUER,
)
from ai_examiner.models import OrganizationMembership, Principal
from ai_examiner.services.enterprise_identity import (
    EnterpriseIdentityError,
    bootstrap_owner,
    resolve_organization_context,
    transition_principal_status,
)


def test_legacy_organization_context_is_observe_only_and_owns_new_projects(client):
    context_response = client.get("/api/v1/context")
    assert context_response.status_code == 200
    context = context_response.json()
    assert context["organization_id"] == LEGACY_ORGANIZATION_ID
    assert context["organization"]["slug"] == "legacy"
    assert context["source"] == "legacy_default"
    assert context["authorization_enforced"] is False
    assert context["mode"] == "observe_only"

    project_response = client.post("/api/projects", json={"name": "Tenant seed"})
    assert project_response.status_code == 201
    assert project_response.json()["organization_id"] == LEGACY_ORGANIZATION_ID
    listed = client.get("/api/projects").json()
    assert listed[0]["organization_id"] == LEGACY_ORGANIZATION_ID


def test_bootstrap_owner_is_idempotent_and_context_resolves_membership(client):
    with SessionLocal() as db:
        first = bootstrap_owner(
            db,
            issuer=LOCAL_IDENTITY_ISSUER,
            subject="bootstrap-owner",
            display_name="Bootstrap owner",
            email="owner@example.test",
        )
        second = bootstrap_owner(
            db,
            issuer=LOCAL_IDENTITY_ISSUER,
            subject="bootstrap-owner",
            display_name="Bootstrap owner",
            email="owner@example.test",
        )
        assert tuple(item.id for item in first) == tuple(item.id for item in second)
        assert len(db.scalars(select(Principal)).all()) == 1
        assert len(db.scalars(select(OrganizationMembership)).all()) == 1
        context = resolve_organization_context(
            db,
            requested_organization_id=LEGACY_ORGANIZATION_ID,
            requested_principal_id=first[1].id,
        )
        assert context.organization_id == LEGACY_ORGANIZATION_ID
        assert context.principal_id == first[1].id
        assert context.role == "owner"
        principal_id = first[1].id

    response = client.get(
        "/api/v1/context",
        headers={
            "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID,
            "X-AI-Examiner-Principal": principal_id,
        },
    )
    assert response.status_code == 200
    assert response.json()["role"] == "owner"
    assert response.json()["authorization_enforced"] is False
    assert "organization.read" in response.json()["capabilities"]
    assert "member.manage" in response.json()["capabilities"]


def test_principal_status_lifecycle_is_bounded():
    with SessionLocal() as db:
        principal = Principal(
            issuer="https://issuer.example.test",
            subject="subject-1",
            status="pending",
        )
        db.add(principal)
        db.commit()
        db.refresh(principal)

        transition_principal_status(db, principal, "active")
        transition_principal_status(db, principal, "suspended")
        transition_principal_status(db, principal, "active")
        transition_principal_status(db, principal, "disabled")
        assert principal.disabled_at is not None

        with pytest.raises(EnterpriseIdentityError, match="invalid principal"):
            transition_principal_status(db, principal, "active")


def test_membership_role_registry_is_enforced_by_database():
    with SessionLocal() as db:
        principal = Principal(
            issuer="https://issuer.example.test",
            subject="invalid-role-subject",
            status="active",
        )
        db.add(principal)
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=LEGACY_ORGANIZATION_ID,
                principal_id=principal.id,
                role="superuser",
                status="active",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_unknown_explicit_organization_context_is_rejected(client):
    response = client.get(
        "/api/v1/context",
        headers={"X-AI-Examiner-Organization": "missing-organization"},
    )
    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


def test_bootstrap_admin_cli_is_idempotent(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "bootstrap-owner.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "bootstrap-cli-test-secret",
    }
    command = [
        sys.executable,
        "-m",
        "ai_examiner.enterprise_cli",
        "--subject",
        "bootstrap-cli-owner",
        "--display-name",
        "Bootstrap CLI owner",
    ]

    results = []
    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        results.append(json.loads(result.stdout))

    assert results[0]["principal"]["id"] == results[1]["principal"]["id"]
    assert results[0]["membership"]["id"] == results[1]["membership"]["id"]
    bootstrap_engine = create_engine(database_url)
    with bootstrap_engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM principals")) == 1
        assert (
            connection.scalar(text("SELECT COUNT(*) FROM organization_memberships"))
            == 1
        )
    bootstrap_engine.dispose()


def test_sqlite_migration_backfills_legacy_organization_without_data_loss(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "enterprise-foundation.db"
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
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    alembic("upgrade", "20260723_0007")
    migration_engine = create_engine(database_url)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, name, domain, language, created_at) "
                "VALUES "
                "('legacy-project-v09', 'Legacy v0.9 project', "
                "'research_defense', 'zh-CN', '2026-07-27 00:00:00')"
            )
        )

    alembic("upgrade", "head")
    inspector = inspect(migration_engine)
    assert {
        "organizations",
        "principals",
        "organization_memberships",
    } <= set(inspector.get_table_names())
    assert "organization_id" in {
        column["name"] for column in inspector.get_columns("projects")
    }
    with migration_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT name, organization_id FROM projects "
                "WHERE id = 'legacy-project-v09'"
            )
        ).one()
        assert row.name == "Legacy v0.9 project"
        assert row.organization_id == LEGACY_ORGANIZATION_ID
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM organizations "
                "WHERE id = :organization_id"
            ),
            {"organization_id": LEGACY_ORGANIZATION_ID},
        ) == 1

    alembic("downgrade", "20260723_0007")
    inspector = inspect(migration_engine)
    assert "organizations" not in inspector.get_table_names()
    assert "organization_id" not in {
        column["name"] for column in inspector.get_columns("projects")
    }
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM projects WHERE id = 'legacy-project-v09'")
        ) == 1
    migration_engine.dispose()
