from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError

import ai_examiner.main as main_module
from ai_examiner.config import Settings
from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    AuditEvent,
    Organization,
    OrganizationMembership,
    Principal,
)
from ai_examiner.services.audit import (
    AUDITED_BEHAVIORS,
    AuditWriteError,
    append_audit_event,
    redact_audit_metadata,
)
from ai_examiner.services.authorization import ROUTE_POLICIES
from ai_examiner.services.tenancy import set_tenant_context


def _organization_with_actor(
    slug: str,
    *,
    role: str = "owner",
) -> tuple[Organization, Principal]:
    with SessionLocal() as db:
        organization = Organization(
            slug=slug,
            display_name=slug,
            status="active",
            version=1,
        )
        principal = Principal(
            issuer="https://issuer.example",
            subject=f"{slug}-actor",
            status="active",
        )
        db.add_all([organization, principal])
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                principal_id=principal.id,
                role=role,
                status="active",
                version=1,
            )
        )
        db.commit()
        return organization, principal


def _append_test_event(
    organization: Organization,
    principal: Principal,
    *,
    metadata: dict | None = None,
) -> str:
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        event = append_audit_event(
            db,
            organization_id=organization.id,
            actor_type="principal",
            actor_id=principal.id,
            authentication_method="disabled",
            action="membership.update",
            resource_type="organization_membership",
            resource_id="membership-1",
            outcome="succeeded",
            reason_code="",
            request_id="request-1",
            trace_id="trace-1",
            source_ip_class="loopback",
            source_ip_hash="0" * 64,
            user_agent_family="python-httpx",
            metadata=metadata,
            retention_class="administrative",
        )
        db.commit()
        return event.id


def test_audit_configuration_fails_closed_in_production():
    settings = Settings(
        app_env="production",
        audit_required=True,
        audit_ip_hash_key=None,
    )
    assert settings.audit_configuration_issues() == [
        "missing_audit_ip_hash_key"
    ]
    configured = Settings(
        app_env="production",
        audit_required=True,
        audit_ip_hash_key="test-audit-key",
    )
    assert configured.audit_configuration_issues() == []


def test_sensitive_route_policy_inventory_has_audit_behavior():
    valid_behaviors = AUDITED_BEHAVIORS | {"none", "read"}
    assert all(policy.audit in valid_behaviors for policy in ROUTE_POLICIES.values())
    for (method, _path), policy in ROUTE_POLICIES.items():
        if policy.authentication == "public":
            assert policy.audit == "authentication"
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            assert policy.audit in {"authentication", "administrative"}
        if policy.resource_resolver in {
            "document",
            "evidence_asset",
            "memory_export_artifact",
            "background_job",
        }:
            assert policy.audit == "read_sensitive" or method != "GET"


def test_audit_metadata_allowlist_redacts_canaries_and_secrets():
    fake_provider_key = "sk-" + "proj-" + "secret"
    raw = {
        "status_code": 201,
        "job_kind": "CANARY_document_sentence",
        "route_template": "/api/v1/organizations/{organization_id}/memberships",
        "prompt": "CANARY_prompt_sentence",
        "token": "Bearer secret-token",
        "provider_key": fake_provider_key,
        "changed_fields": ["role", "status", "answer text"],
    }
    redacted = redact_audit_metadata(raw)
    serialized = json.dumps(redacted, sort_keys=True)

    assert redacted["status_code"] == 201
    assert redacted["job_kind"] == "[REDACTED]"
    assert redacted["route_template"].startswith("/api/v1/")
    assert redacted["changed_fields"] == ["role", "status"]
    assert "CANARY_prompt_sentence" not in serialized
    assert "secret-token" not in serialized
    assert fake_provider_key not in serialized
    assert "prompt" not in redacted
    assert "token" not in redacted


def test_audit_events_are_immutable_in_orm_and_database():
    organization, principal = _organization_with_actor("immutable-audit")
    event_id = _append_test_event(organization, principal)

    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        event = db.get(AuditEvent, event_id)
        assert event is not None
        event.action = "tampered"
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()

        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(
                text(
                    "UPDATE audit_events SET action = 'tampered' "
                    "WHERE id = :event_id"
                ),
                {"event_id": event_id},
            )
        db.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(
                text("DELETE FROM audit_events WHERE id = :event_id"),
                {"event_id": event_id},
            )
        db.rollback()


def test_administrative_success_and_authorization_denial_are_audited(client):
    organization, owner = _organization_with_actor("audit-api")
    with SessionLocal() as db:
        target = Principal(
            issuer="https://issuer.example",
            subject="audit-target",
            status="active",
        )
        outsider = Principal(
            issuer="https://issuer.example",
            subject="audit-outsider",
            status="active",
        )
        db.add_all([target, outsider])
        db.commit()
        target_id = target.id
        outsider_id = outsider.id

    owner_headers = {
        "X-AI-Examiner-Organization": organization.id,
        "X-AI-Examiner-Principal": owner.id,
        "User-Agent": "python-httpx/audit-test",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-"
            "00f067aa0ba902b7-01"
        ),
    }
    created = client.post(
        f"/api/v1/organizations/{organization.id}/memberships",
        headers=owner_headers,
        json={
            "principal_id": target_id,
            "role": "reviewer",
            "status": "active",
        },
    )
    assert created.status_code == 201
    assert created.headers["X-Request-ID"]

    denied = client.get(
        f"/api/v1/organizations/{organization.id}/memberships",
        headers={
            "X-AI-Examiner-Organization": organization.id,
            "X-AI-Examiner-Principal": outsider_id,
        },
    )
    assert denied.status_code == 404

    audit_response = client.get(
        f"/api/v1/organizations/{organization.id}/audit-events",
        headers=owner_headers,
    )
    assert audit_response.status_code == 200
    items = audit_response.json()["items"]
    administrative = next(
        item
        for item in items
        if item["action"].endswith("memberships.create")
        and item["outcome"] == "succeeded"
    )
    denial = next(item for item in items if item["outcome"] == "denied")

    assert administrative["actor_id"] == owner.id
    assert administrative["request_id"] == created.headers["X-Request-ID"]
    assert administrative["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert administrative["metadata"]["status_code"] == 201
    assert denial["actor_id"] == outsider_id
    assert denial["reason_code"] == "resource_not_found"
    assert denial["source_ip_hash"] != "testclient"
    assert audit_response.json()["retention"]["runtime_deletion_allowed"] is False


def test_required_audit_failure_rolls_back_administrative_change(
    client,
    monkeypatch,
):
    organization, owner = _organization_with_actor("audit-required")
    with SessionLocal() as db:
        target = Principal(
            issuer="https://issuer.example",
            subject="audit-required-target",
            status="active",
        )
        db.add(target)
        db.commit()
        target_id = target.id

    def fail_required_audit(*_args, **_kwargs):
        raise AuditWriteError("audit sink unavailable")

    monkeypatch.setattr(
        main_module,
        "append_request_audit_event",
        fail_required_audit,
    )
    response = client.post(
        f"/api/v1/organizations/{organization.id}/memberships",
        headers={
            "X-AI-Examiner-Organization": organization.id,
            "X-AI-Examiner-Principal": owner.id,
        },
        json={
            "principal_id": target_id,
            "role": "reviewer",
            "status": "active",
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "audit_unavailable"
    with SessionLocal() as db:
        membership = db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.principal_id == target_id,
            )
        )
        assert membership is None


def test_audit_api_is_tenant_scoped_and_export_is_redacted(client):
    organization, owner = _organization_with_actor("audit-export")
    foreign, foreign_owner = _organization_with_actor("audit-export-foreign")
    canary = "CANARY_document_sentence"
    fake_provider_key = "sk-" + "proj-" + "never-store-this"
    event_id = _append_test_event(
        organization,
        owner,
        metadata={
            "job_kind": canary,
            "prompt": fake_provider_key,
        },
    )
    headers = {
        "X-AI-Examiner-Organization": organization.id,
        "X-AI-Examiner-Principal": owner.id,
    }

    listed = client.get(
        f"/api/v1/organizations/{organization.id}/audit-events",
        headers=headers,
        params={"resource_id": "membership-1"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [event_id]

    exported = client.get(
        f"/api/v1/organizations/{organization.id}/audit-events/export",
        headers=headers,
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-ndjson")
    assert canary not in exported.text
    assert fake_provider_key not in exported.text
    records = [json.loads(line) for line in exported.text.splitlines()]
    assert records[0]["type"] == "manifest"
    assert records[0]["organization_id"] == organization.id

    cross_tenant = client.get(
        f"/api/v1/organizations/{organization.id}/audit-events",
        headers={
            "X-AI-Examiner-Organization": organization.id,
            "X-AI-Examiner-Principal": foreign_owner.id,
        },
    )
    assert cross_tenant.status_code == 404
    assert foreign.id != organization.id


def test_job_terminal_event_has_audit_evidence(monkeypatch):
    from types import SimpleNamespace

    from ai_examiner.services import jobs as job_service
    from ai_examiner.services.jobs import enqueue_job

    class StubTask:
        @staticmethod
        def delay(_envelope):
            return SimpleNamespace(id="audit-delivery")

    monkeypatch.setitem(job_service.TASKS, "golden_dataset", StubTask)
    organization, owner = _organization_with_actor("job-audit")
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=owner.id,
        )
        job = enqueue_job(
            db,
            kind="golden_dataset",
            project_id=None,
            payload={"marker": "audit"},
            organization_id=organization.id,
            idempotency_key="audit-job",
        )
        job = job_service.cancel_persisted_job(
            db,
            job,
            principal_id=owner.id,
            reason="Operator cancelled",
        )
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.organization_id == organization.id,
                    AuditEvent.resource_id == job.id,
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].action == "job.cancelled"
        assert events[0].outcome == "succeeded"


def test_postgres_rls_rehearsal_checks_audit_privileges_and_mutation_guards():
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy" / "verify-v09-rls.py").read_text(
        encoding="utf-8"
    )
    assert "audit_tenant_select" in script
    assert "audit_maintenance_delete" in script
    assert "has_table_privilege" in script
    assert "Runtime audit update was not blocked" in script
    assert "Runtime audit delete was not blocked" in script


def test_audit_schema_migration_creates_triggers_and_refuses_evidence_loss(
    tmp_path,
):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "audit-schema.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "audit-migration-test-secret",
    }

    def alembic(*arguments: str, expected: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return result

    alembic("upgrade", "head")
    migration_engine = create_engine(database_url)
    assert "audit_events" in inspect(migration_engine).get_table_names()
    with migration_engine.begin() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = 'audit_events'"
                )
            )
        }
        assert {
            "audit_events_no_update",
            "audit_events_no_delete",
        } <= triggers
        connection.execute(
            text(
                "INSERT INTO audit_events "
                "(id, organization_id, schema_version, actor_type, "
                "authentication_method, action, resource_type, outcome, "
                "reason_code, request_id, trace_id, source_ip_class, "
                "user_agent_family, metadata_json, event_digest, "
                "retention_class, retention_until, occurred_at) VALUES "
                "('audit-proof', NULL, 1, 'system', 'system', "
                "'migration.proof', 'none', 'succeeded', '', "
                "'migration-request', 'migration-trace', 'unknown', "
                "'unknown', '{}', :digest, 'security', "
                "'2027-07-28 00:00:00', '2026-07-28 00:00:00')"
            ),
            {"digest": "0" * 64},
        )
    failed = alembic(
        "downgrade",
        "20260728_0013",
        expected=1,
    )
    assert "refuses to destroy immutable evidence" in (
        failed.stdout + failed.stderr
    )
    assert "audit_events" in inspect(migration_engine).get_table_names()
    migration_engine.dispose()
