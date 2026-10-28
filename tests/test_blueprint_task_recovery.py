from datetime import UTC, datetime, timedelta

from ai_examiner.db import SessionLocal
from ai_examiner.main import find_blueprint_task
from ai_examiner.models import BackgroundJob, Principal
from ai_examiner.services.jobs import enqueue_job
from ai_examiner.services.tenancy import set_tenant_context


def test_lookup_recovers_completed_result_without_model_call(client, monkeypatch):
    monkeypatch.setattr("ai_examiner.main.provider_or_503", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Recovery must not call a provider")))
    project = client.post("/api/projects", json={"name": "Recovery test"}).json()["id"]
    document = client.post(f"/api/projects/{project}/documents",
                           files={"file": ("paper.txt", b"Independent evidence.")}).json()["id"]
    other = client.post(f"/api/projects/{project}/documents",
                        files={"file": ("other.txt", b"Other evidence.")}).json()["id"]
    with SessionLocal() as db:
        job = enqueue_job(db, kind="blueprint_generation", project_id=project,
                          payload={"project_id": project, "document_id": document},
                          idempotency_key="lost-receipt", dispatch=False)
        job.status = "completed"
        job.result = {"blueprint": {"id": "saved-blueprint", "data": {"questions": []}}}
        db.commit()
        job_id = job.id
    path = f"/api/projects/{project}/blueprint-task"
    result = client.get(path, params={"document_id": document}).json()["job"]
    assert result["id"] == job_id
    assert result["result"]["blueprint"]["id"] == "saved-blueprint"
    assert "lease_owner" not in result
    assert client.get(path, params={"document_id": other}).json() == {"job": None}
    assert client.get(path, params={"document_id": document, "request_id": "other-key"}).json() == {"job": None}
    assert client.get(path, params={"document_id": document, "request_id": "lost-receipt"}).json()["job"]["id"] == job_id
    wrong_project = client.post("/api/projects", json={"name": "Another project"}).json()["id"]
    assert client.get(f"/api/projects/{wrong_project}/blueprint-task", params={"document_id": document}).status_code == 404


def test_lookup_never_recovers_other_principals_job(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "Actor recovery"}).json()["id"]
    document = client.post(f"/api/projects/{project}/documents",
                           files={"file": ("paper.txt", b"Evidence.")}).json()["id"]
    with SessionLocal() as db:
        principals = [Principal(issuer="test", subject=name, status="active") for name in ("A", "B")]
        db.add_all(principals)
        db.flush()
        job = enqueue_job(db, kind="blueprint_generation", project_id=project,
                          payload={"project_id": project, "document_id": document},
                          idempotency_key="actor-receipt", dispatch=False)
        job.actor_principal_id = principals[0].id
        db.commit()
        org = job.organization_id
        monkeypatch.setattr("ai_examiner.main.authorize_workbench_resource", lambda *a: None)
        for actor, expected in [(principals[0].id, job.id), (principals[1].id, None)]:
            set_tenant_context(db, organization_id=org, principal_id=actor)
            found = find_blueprint_task(project, document, None, db, None)["job"]
            assert (found["id"] if found else None) == expected


def test_lookup_uses_latest_task_for_same_document(client):
    project = client.post("/api/projects", json={"name": "Latest task"}).json()["id"]
    document = client.post(f"/api/projects/{project}/documents",
                           files={"file": ("paper.txt", b"Evidence.")}).json()["id"]
    with SessionLocal() as db:
        old = enqueue_job(db, kind="blueprint_generation", project_id=project,
                          payload={"project_id": project, "document_id": document},
                          idempotency_key="old", dispatch=False)
        old.status = "failed"
        old.created_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()
        new = enqueue_job(db, kind="blueprint_generation", project_id=project,
                          payload={"project_id": project, "document_id": document},
                          idempotency_key="new", dispatch=False)
        new_id = new.id
    result = client.get(f"/api/projects/{project}/blueprint-task", params={"document_id": document})
    assert result.json()["job"]["id"] == new_id
    with SessionLocal() as db:
        assert db.get(BackgroundJob, new_id).status == "queued"
