from ai_examiner.db import SessionLocal
from ai_examiner.models import BackgroundJob, Blueprint
from ai_examiner.services.jobs import dispatch_job_by_id


def _project_and_document(client) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": "Async blueprint project"},
    ).json()
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={
            "file": (
                "paper.txt",
                (
                    "The method uses calibrated evidence. "
                    "The evaluation compares two baselines and reports limitations."
                ),
                "text/plain",
            )
        },
    ).json()
    return project, document


def test_async_blueprint_is_idempotent_and_preserves_sync_contract(
    client,
    monkeypatch,
):
    project, document = _project_and_document(client)
    actual_dispatch = dispatch_job_by_id
    monkeypatch.setattr(
        "ai_examiner.main.dispatch_job_by_id",
        lambda _job_id: None,
    )
    payload = {
        "document_id": document["id"],
        "profile": "mock:heuristic-v2",
        "mode": "defense",
    }
    headers = {"Idempotency-Key": "async-blueprint-one"}
    queued = client.post(
        f"/api/projects/{project['id']}/blueprints/async",
        json=payload,
        headers=headers,
    )
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    job_id = queued.json()["id"]

    with SessionLocal() as db:
        assert db.get(BackgroundJob, job_id).status == "queued"
        assert db.query(Blueprint).count() == 0

    actual_dispatch(job_id)
    completed = client.get(f"/api/jobs/{job_id}")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    blueprint = completed.json()["result"]["blueprint"]
    assert blueprint["id"] == completed.json()["result"]["blueprint_id"]
    assert blueprint["data"]["questions"]

    duplicate = client.post(
        f"/api/projects/{project['id']}/blueprints/async",
        json=payload,
        headers=headers,
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == job_id
    assert duplicate.json()["status"] == "completed"
    with SessionLocal() as db:
        assert db.query(BackgroundJob).count() == 1
        assert db.query(Blueprint).count() == 1

    synchronous = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json=payload,
    )
    assert synchronous.status_code == 201
    assert synchronous.json()["data"]["questions"]
    assert synchronous.json()["version"] == 2


def test_blueprint_page_exposes_async_progress_and_cancel_controls(client):
    page = client.get("/")
    script = client.get("/static/app.js")

    assert 'id="cancelBlueprint"' in page.text
    assert 'id="blueprintProgress"' in page.text
    assert "/blueprints/async" in script.text
    assert "pollBlueprintJob" in script.text
    assert "/cancel" in script.text


def test_synchronous_blueprint_provider_failure_remains_a_502(client, monkeypatch):
    project, document = _project_and_document(client)

    def fail_prepare(*_args, **_kwargs):
        raise RuntimeError("provider probe failed")

    monkeypatch.setattr(
        "ai_examiner.main.BlueprintGenerationService.prepare",
        fail_prepare,
    )
    response = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={
            "document_id": document["id"],
            "profile": "mock:heuristic-v2",
            "mode": "defense",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Blueprint generation failed: provider probe failed"
    )


def test_async_blueprint_can_be_cancelled_before_worker_claim(client, monkeypatch):
    project, document = _project_and_document(client)
    monkeypatch.setattr(
        "ai_examiner.main.dispatch_job_by_id",
        lambda _job_id: None,
    )
    queued = client.post(
        f"/api/projects/{project['id']}/blueprints/async",
        json={
            "document_id": document["id"],
            "profile": "mock:heuristic-v2",
        },
        headers={"Idempotency-Key": "cancel-blueprint"},
    ).json()

    cancelled = client.post(
        f"/api/jobs/{queued['id']}/cancel",
        json={"reason": "User cancelled blueprint generation"},
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    with SessionLocal() as db:
        assert db.query(Blueprint).count() == 0
