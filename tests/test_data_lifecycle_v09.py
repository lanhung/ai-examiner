from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from ai_examiner.config import get_settings
from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.models import (
    AuditEvent,
    DataSubjectRequest,
    HumanReviewCase,
    HumanReviewEvent,
    OrganizationExportArtifact,
    Project,
    StoredObject,
)
from ai_examiner.services.enterprise_identity import bootstrap_owner
from ai_examiner.services.storage import StorageService, document_object_key


def _owner(subject: str):
    with SessionLocal() as db:
        _organization, principal, _membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject=subject,
        )
        return principal.id


def _headers(principal_id: str, **extra: str) -> dict[str, str]:
    return {
        "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID,
        "X-AI-Examiner-Principal": principal_id,
        **extra,
    }


def _project_with_object() -> tuple[str, str]:
    with SessionLocal() as db:
        project = Project(
            organization_id=LEGACY_ORGANIZATION_ID,
            name="Lifecycle project",
            domain="research_defense",
            language="zh-CN",
        )
        db.add(project)
        db.flush()
        stored = StorageService(db, get_settings()).store_bytes(
            organization_id=LEGACY_ORGANIZATION_ID,
            project_id=project.id,
            resource_type="document",
            resource_id="document-proof",
            purpose="source",
            object_key=document_object_key(
                LEGACY_ORGANIZATION_ID,
                project.id,
                "document-proof",
                filename="proof.txt",
                content_type="text/plain",
            ),
            data=b"controlled lifecycle evidence",
            content_type="text/plain",
        )
        db.commit()
        return project.id, stored.id


def test_retention_policy_and_legal_hold_lifecycle(client):
    owner_id = _owner("retention-owner")
    project_id, _stored_id = _project_with_object()
    headers = _headers(owner_id)

    initial = client.get(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/retention-policy",
        headers=headers,
    )
    assert initial.status_code == 200
    assert initial.json()["policy_mode"] == "monitor"

    updated = client.put(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/retention-policy",
        headers=headers,
        json={
            "policy_mode": "enforce",
            "project_days": 730,
            "session_days": 365,
            "document_days": 180,
            "learner_memory_days": 365,
            "export_ttl_hours": 12,
            "deletion_grace_days": 14,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert len(updated.json()["policy_digest"]) == 64

    hold = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/legal-holds",
        headers=headers,
        json={
            "scope_type": "project",
            "scope_id": project_id,
            "reason": "Active litigation preservation requirement",
        },
    )
    assert hold.status_code == 201
    assert hold.json()["status"] == "active"

    released = client.post(
        f"/api/v1/legal-holds/{hold.json()['id']}/release",
        headers=headers,
        json={"reason": "Legal counsel released the preservation requirement"},
    )
    assert released.status_code == 200
    assert released.json()["status"] == "released"
    assert released.json()["release_reason"]


def test_organization_export_manifest_and_download_authorization(client):
    owner_id = _owner("export-owner")
    project_id, stored_id = _project_with_object()
    headers = _headers(owner_id, **{"Idempotency-Key": "org-export-1"})

    response = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/exports",
        headers=headers,
        json={
            "scope_type": "project",
            "scope_id": project_id,
            "include_objects": True,
        },
    )
    assert response.status_code == 202, response.text
    artifact = response.json()
    assert artifact["status"] == "completed"
    assert artifact["object_counts"]["included"] == 1
    assert len(artifact["manifest_digest"]) == 64
    repeated = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/exports",
        headers=headers,
        json={
            "scope_type": "project",
            "scope_id": project_id,
            "include_objects": True,
        },
    )
    assert repeated.status_code == 202
    assert repeated.json()["id"] == artifact["id"]

    download = client.get(artifact["download_url"], headers=_headers(owner_id))
    assert download.status_code == 200
    assert download.headers["etag"].startswith('"sha256:')
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert f"objects/{stored_id}" in names
        manifest = __import__("json").loads(archive.read("manifest.json"))
        assert manifest["organization_id"] == LEGACY_ORGANIZATION_ID
        assert manifest["scope"]["id"] == project_id
        assert manifest["protected_evidence"]["audit_events_retained"] is True

    with SessionLocal() as db:
        persisted = db.get(OrganizationExportArtifact, artifact["id"])
        assert persisted.storage_object_id
        assert persisted.manifest_digest == artifact["manifest_digest"]


def test_project_deletion_requires_distinct_human_and_verifies_storage(client):
    requester_id = _owner("deletion-requester")
    reviewer_id = _owner("deletion-reviewer")
    project_id, stored_id = _project_with_object()
    create = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/data-subject-requests",
        headers=_headers(
            requester_id,
            **{"Idempotency-Key": "delete-project-1"},
        ),
        json={
            "request_type": "delete",
            "target_type": "project",
            "target_id": project_id,
            "reason": "Remove the completed evaluation project",
        },
    )
    assert create.status_code == 202
    request_id = create.json()["id"]

    self_approval = client.post(
        f"/api/v1/data-subject-requests/{request_id}/approve",
        headers=_headers(
            requester_id,
            **{"Idempotency-Key": "delete-project-self"},
        ),
        json={
            "decision": "approved",
            "reason": "Requester attempts to approve the same deletion",
        },
    )
    assert self_approval.status_code == 409
    assert self_approval.json()["detail"]["code"] == "dual_control_required"

    approved = client.post(
        f"/api/v1/data-subject-requests/{request_id}/approve",
        headers=_headers(
            reviewer_id,
            **{"Idempotency-Key": "delete-project-approved"},
        ),
        json={
            "decision": "approved",
            "reason": "Independent reviewer approved verified deletion",
        },
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert result["status"] == "completed"
    assert result["verification"]["verified"] is True
    assert result["verification"]["relational_remaining"] == 0
    assert result["verification"]["objects_remaining"] == 0
    repeated_approval = client.post(
        f"/api/v1/data-subject-requests/{request_id}/approve",
        headers=_headers(
            reviewer_id,
            **{"Idempotency-Key": "delete-project-approved"},
        ),
        json={
            "decision": "approved",
            "reason": "Independent reviewer approved verified deletion",
        },
    )
    assert repeated_approval.status_code == 200
    assert repeated_approval.json()["job_id"] == result["job_id"]

    with SessionLocal() as db:
        assert db.get(Project, project_id) is None
        stored = db.get(StoredObject, stored_id)
        assert stored.status == "deleted"
        assert stored.project_id is None
        request = db.get(DataSubjectRequest, request_id)
        assert request.final_decision == "approved"
        assert request.reviewer_principal_id == reviewer_id
        assert db.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == request_id,
                AuditEvent.action.contains("approve"),
            )
        )


def test_legal_hold_blocks_then_retry_completes_deletion(client):
    requester_id = _owner("hold-requester")
    reviewer_id = _owner("hold-reviewer")
    project_id, _stored_id = _project_with_object()
    hold = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/legal-holds",
        headers=_headers(reviewer_id),
        json={
            "scope_type": "project",
            "scope_id": project_id,
            "reason": "Preserve while a compliance inquiry remains open",
        },
    ).json()
    request = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/data-subject-requests",
        headers=_headers(
            requester_id,
            **{"Idempotency-Key": "hold-delete-create"},
        ),
        json={
            "request_type": "delete",
            "target_type": "project",
            "target_id": project_id,
            "reason": "Delete after the legal hold is released",
        },
    ).json()
    blocked = client.post(
        f"/api/v1/data-subject-requests/{request['id']}/approve",
        headers=_headers(
            reviewer_id,
            **{"Idempotency-Key": "hold-delete-approve"},
        ),
        json={
            "decision": "approved",
            "reason": "Deletion approved subject to legal-hold enforcement",
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["blocked_reason"] == "legal_hold"
    with SessionLocal() as db:
        assert db.get(Project, project_id) is not None

    client.post(
        f"/api/v1/legal-holds/{hold['id']}/release",
        headers=_headers(reviewer_id),
        json={"reason": "Compliance inquiry closed without preservation need"},
    )
    retried = client.post(
        f"/api/v1/data-subject-requests/{request['id']}/retry",
        headers=_headers(
            reviewer_id,
            **{"Idempotency-Key": "hold-delete-retry"},
        ),
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "completed"


def test_human_review_decision_is_append_only_and_ai_cannot_decide(client):
    owner_id = _owner("review-owner")
    created = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/review-cases",
        headers=_headers(owner_id),
        json={
            "case_type": "assessment_appeal",
            "resource_type": "exam_session",
            "resource_id": "session-proof",
            "title": "Review assessment evidence",
            "summary": "The learner disputes the evidence interpretation.",
            "evidence": [{"type": "score", "value": 2}],
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    decided = client.post(
        f"/api/v1/review-cases/{case_id}/decisions",
        headers=_headers(owner_id),
        json={
            "decision": "partially_upheld",
            "reason": "A human reviewer found one unsupported scoring claim",
        },
    )
    assert decided.status_code == 200
    assert decided.json()["final_decision"] == "partially_upheld"

    appealed = client.post(
        f"/api/v1/review-cases/{case_id}/appeals",
        headers=_headers(owner_id),
        json={
            "reason": "Additional evidence changes the interpretation",
            "evidence": [{"type": "transcript", "id": "turn-proof"}],
        },
    )
    assert appealed.status_code == 200
    assert appealed.json()["status"] == "appealed"

    with SessionLocal() as db:
        review_case = db.get(HumanReviewCase, case_id)
        db.add(
            HumanReviewEvent(
                organization_id=LEGACY_ORGANIZATION_ID,
                case_id=case_id,
                event_type="decision",
                actor_type="ai",
                actor_id="model-agent",
                payload_json={"decision": "deny"},
            )
        )
        with pytest.raises(ValueError, match="must be made by a human"):
            db.flush()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    """
                    INSERT INTO human_review_events (
                        id,
                        organization_id,
                        case_id,
                        event_type,
                        actor_type,
                        actor_id,
                        payload_json,
                        created_at
                    ) VALUES (
                        'ai-direct-decision',
                        :organization_id,
                        :case_id,
                        'decision',
                        'ai',
                        'model-agent',
                        '{}',
                        CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "organization_id": LEGACY_ORGANIZATION_ID,
                    "case_id": case_id,
                },
            )
            db.flush()
        db.rollback()
        decision = db.scalar(
            select(HumanReviewEvent).where(
                HumanReviewEvent.case_id == review_case.id,
                HumanReviewEvent.event_type == "decision",
            )
        )
        decision.payload_json = {"decision": "tampered"}
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(
                text(
                    "UPDATE human_review_events SET actor_id = 'tampered' "
                    "WHERE id = :event_id"
                ),
                {"event_id": decision.id},
            )


def test_data_lifecycle_migration_refuses_compliance_evidence_loss(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "data-lifecycle.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "lifecycle-migration-secret",
    }

    def alembic(*arguments: str, expected: int = 0):
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
    assert {
        "organization_retention_policies",
        "legal_holds",
        "organization_export_artifacts",
        "data_subject_requests",
        "human_review_cases",
        "human_review_events",
    } <= set(inspect(migration_engine).get_table_names())
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_subject_requests "
                "(id, request_type, target_type, target_id, "
                "requester_principal_id, status, final_decision, "
                "decision_reason, idempotency_key, verification_json, "
                "deletion_counts_json, blocked_reason, failure_code, "
                "requested_at, organization_id) VALUES "
                "('request-proof', 'delete', 'project', 'project-proof', "
                "'principal-proof', 'completed', 'approved', '', "
                "'idempotency-proof', '{}', '{}', '', '', "
                "CURRENT_TIMESTAMP, :organization_id)"
            ),
            {"organization_id": LEGACY_ORGANIZATION_ID},
        )
    failed = alembic("downgrade", "20260728_0015", expected=1)
    assert "refuses to destroy compliance evidence" in (
        failed.stdout + failed.stderr
    )
    assert "data_subject_requests" in inspect(migration_engine).get_table_names()
    migration_engine.dispose()
