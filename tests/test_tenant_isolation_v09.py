from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from ai_examiner.config import Settings
from ai_examiner.db import Base, SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.models import (
    Concept,
    Document,
    Organization,
    OrganizationMembership,
    Principal,
    Project,
    PromptVersion,
    ScenarioTemplate,
)
from ai_examiner.services import jobs as job_service
from ai_examiner.services.jobs import enqueue_job
from ai_examiner.services.tenancy import (
    clear_tenant_context,
    current_tenant_context,
    set_tenant_context,
)

ROOT = Path(__file__).resolve().parents[1]

GLOBAL_OR_TENANT_MODELS = {
    ScenarioTemplate,
    PromptVersion,
    Concept,
}

UNOWNED_MODELS = {
    Organization,
    Principal,
}


def test_every_business_model_declares_direct_tenant_ownership():
    missing = []
    for mapper in Base.registry.mappers:
        model = mapper.class_
        table_name = mapper.local_table.name
        if model in UNOWNED_MODELS or table_name in {
            "oidc_login_transactions",
            "browser_auth_sessions",
        }:
            continue
        if "organization_id" not in mapper.local_table.c:
            missing.append(table_name)
    assert missing == []


def test_required_tenant_rows_inherit_transaction_context():
    organization = Organization(
        slug="tenant-context",
        display_name="Tenant context",
        status="active",
        version=1,
    )
    with SessionLocal() as db:
        db.add(organization)
        db.flush()
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=None,
        )
        project = Project(
            organization_id=organization.id,
            name="Tenant project",
            domain="test",
            language="en",
        )
        db.add(project)
        db.flush()
        document = Document(
            project_id=project.id,
            filename="tenant.txt",
            content_type="text/plain",
            storage_path="tenant.txt",
            content_text="tenant",
        )
        db.add(document)
        db.flush()
        assert document.organization_id == organization.id

        db.commit()
        assert current_tenant_context(db).organization_id == organization.id
        clear_tenant_context(db)
        assert current_tenant_context(db).organization_id is None


def test_global_resources_can_remain_unowned():
    with SessionLocal() as db:
        template = ScenarioTemplate(
            organization_id=None,
            slug="global-template",
            category="test",
            owner_scope="built_in",
            status="active",
        )
        prompt = PromptVersion(
            organization_id=None,
            name="global-prompt",
            version=1,
            role="test",
            content="global",
            status="active",
        )
        db.add_all([template, prompt])
        db.flush()
        assert template.organization_id is None
        assert prompt.organization_id is None


def test_job_envelope_carries_tenant_and_actor(monkeypatch):
    calls = []

    class StubTask:
        @staticmethod
        def delay(*args):
            calls.append(args)

            class Result:
                id = "celery-test-id"

            return Result()

    monkeypatch.setitem(job_service.TASKS, "golden_dataset", StubTask())
    with SessionLocal() as db:
        organization = Organization(
            slug="job-tenant",
            display_name="Job tenant",
            status="active",
            version=1,
        )
        actor = Principal(
            issuer="https://issuer.example",
            subject="job-actor",
            status="active",
        )
        db.add_all([organization, actor])
        db.flush()
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=actor.id,
        )
        project = Project(
            organization_id=organization.id,
            name="Job project",
            domain="test",
            language="en",
        )
        db.add(project)
        db.commit()

        job = enqueue_job(
            db,
            kind="golden_dataset",
            project_id=project.id,
            payload={"project_id": project.id},
        )

    assert job.organization_id == organization.id
    assert job.actor_principal_id == actor.id
    assert len(calls) == 1
    assert calls[0][0] == job.envelope_json
    assert calls[0][0]["job_id"] == job.id
    assert calls[0][0]["organization_id"] == organization.id
    assert calls[0][0]["actor_principal_id"] == actor.id
    assert calls[0][0]["required_capability"] == "dataset.manage"


def test_job_rejects_project_outside_transaction_tenant(monkeypatch):
    class StubTask:
        @staticmethod
        def delay(*_args):
            raise AssertionError("Foreign-tenant job must not be queued")

    monkeypatch.setitem(job_service.TASKS, "golden_dataset", StubTask())
    with SessionLocal() as db:
        organization = Organization(
            slug="job-tenant-a",
            display_name="Job tenant A",
            status="active",
            version=1,
        )
        foreign = Organization(
            slug="job-tenant-b",
            display_name="Job tenant B",
            status="active",
            version=1,
        )
        db.add_all([organization, foreign])
        db.flush()
        project = Project(
            organization_id=foreign.id,
            name="Foreign project",
            domain="test",
            language="en",
        )
        db.add(project)
        db.commit()
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=None,
        )
        with pytest.raises(ValueError, match="transaction context"):
            enqueue_job(
                db,
                kind="golden_dataset",
                project_id=project.id,
                payload={"project_id": project.id},
            )


def test_postgres_ci_runs_rls_verification_before_pytest():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    commands = [
        str(step["run"])
        for step in workflow["jobs"]["postgres"]["steps"]
        if isinstance(step, dict) and "run" in step
    ]
    assert "uv run alembic upgrade head" in commands
    assert "uv run python deploy/verify-v09-rls.py" in commands
    assert "uv run python deploy/verify-v09-runtime-login.py" in commands
    assert commands.index(
        "uv run python deploy/verify-v09-rls.py"
    ) < commands.index("uv run python deploy/verify-v09-runtime-login.py")
    assert commands.index(
        "uv run python deploy/verify-v09-runtime-login.py"
    ) < commands.index("uv run pytest --cov=ai_examiner --cov-report=term-missing")


def test_postgres_host_verifier_is_test_database_only():
    script = (
        ROOT / "deploy" / "enterprise" / "verify-postgres-rls-host.sh"
    ).read_text(encoding="utf-8")
    assert "_test$" in script
    assert "RESET_TEST_DATABASE" in script
    assert "dropdb --if-exists --force" in script
    assert "verify-v09-runtime-login.py" in script


def test_default_local_tenant_remains_legacy():
    with SessionLocal() as db:
        project = Project(name="Legacy", domain="test", language="en")
        db.add(project)
        db.flush()
        assert project.organization_id == LEGACY_ORGANIZATION_ID


def test_workbench_requests_bind_project_document_and_download_to_selected_tenant(client):
    suffix = uuid4().hex[:10]
    with SessionLocal() as db:
        organization = Organization(
            slug=f"workbench-{suffix}",
            display_name=f"Workbench {suffix}",
            status="active",
        )
        principal = Principal(
            issuer="urn:test:workbench",
            subject=suffix,
            display_name="Workbench owner",
            status="active",
        )
        db.add_all([organization, principal])
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                principal_id=principal.id,
                role="owner",
                status="active",
            )
        )
        db.commit()
        headers = {
            "X-AI-Examiner-Organization": organization.id,
            "X-AI-Examiner-Principal": principal.id,
        }

    project = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Tenant workbench project"},
    )
    assert project.status_code == 201
    assert project.json()["organization_id"] == organization.id
    listed = client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    assert {item["organization_id"] for item in listed.json()} == {organization.id}

    uploaded = client.post(
        f"/api/projects/{project.json()['id']}/documents",
        headers=headers,
        files={
            "file": (
                "tenant.txt",
                b"Tenant-isolated source material for authorized download.",
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 201
    downloaded = client.get(
        f"/api/v1/documents/{uploaded.json()['id']}/file",
        headers=headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == (
        b"Tenant-isolated source material for authorized download."
    )


def test_enforced_rls_requires_external_schema_management():
    settings = Settings(
        database_url="postgresql+psycopg://runtime@example.invalid/app",
        postgres_rls_mode="enforce",
        auth_mode="oidc",
    )
    assert "postgres_rls_requires_external_schema_management" in (
        settings.rls_configuration_issues()
    )

    external = Settings(
        database_url="postgresql+psycopg://runtime@example.invalid/app",
        database_schema_management="external",
        postgres_rls_mode="enforce",
        auth_mode="oidc",
    )
    assert external.rls_configuration_issues() == []
