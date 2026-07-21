from sqlalchemy import func, select

from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    LearnerIdentity,
    LearnerIdentityLink,
    LearnerMemoryEvent,
)
from ai_examiner.services.memory import LearnerMemoryService, MemoryPolicyError


def _create_subject_session(client, name: str, subject_key: str) -> dict:
    project = client.post("/api/projects", json={"name": name}).json()
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={
            "file": (
                f"{name}.txt",
                (
                    b"The method compares an explicit baseline, reports evidence, "
                    b"and limits conclusions to the measured distribution. "
                )
                * 20,
                "text/plain",
            )
        },
    ).json()
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={"document_id": document["id"], "profile": "mock:heuristic-v2"},
    ).json()
    session = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "learner_subject_key": subject_key,
            "question_strategy": "adaptive",
            "question_limit": 1,
            "max_followups_per_question": 0,
        },
    ).json()
    knowledge = client.get(f"/api/sessions/{session['id']}/knowledge-state").json()
    return {
        "project": project,
        "blueprint": blueprint,
        "session": session,
        "knowledge_unit_ids": [unit["id"] for unit in knowledge["units"]],
    }


def test_identity_concept_mapping_and_idempotent_memory_import(client):
    fixture = _create_subject_session(client, "Memory foundation", "learner-one")
    external_reference = "private-external-reference-001"
    identity_response = client.post(
        "/api/learner-identities",
        json={
            "external_subject_ref": external_reference,
            "display_name": "Evaluation learner",
            "memory_enabled": True,
            "memory_scope": "project_only",
        },
    )
    assert identity_response.status_code == 201
    identity = identity_response.json()
    assert identity["created"] is True
    assert "opaque_key_hash" not in identity
    assert external_reference not in identity_response.text

    duplicate = client.post(
        "/api/learner-identities",
        json={"external_subject_ref": external_reference},
    ).json()
    assert duplicate["id"] == identity["id"]
    assert duplicate["created"] is False

    linked = client.post(
        f"/api/learner-identities/{identity['id']}/links",
        json={
            "learner_subject_id": fixture["session"]["learner_subject_id"],
            "provenance": "explicit",
        },
    )
    assert linked.status_code == 201
    assert linked.json()["status"] == "confirmed"

    concept = client.post(
        "/api/concepts",
        json={
            "namespace": "Research Methods",
            "canonical_key": "Evidence and Validity",
            "title": "Evidence and validity",
            "language": "en",
        },
    ).json()
    assert concept["namespace"] == "research-methods"
    assert concept["canonical_key"] == "evidence-and-validity"

    chinese_concept = client.post(
        "/api/concepts",
        json={
            "namespace": "科研方法",
            "canonical_key": "证据与有效性",
            "title": "证据与有效性",
        },
    )
    assert chinese_concept.status_code == 201
    assert chinese_concept.json()["namespace"] == "科研方法"
    assert chinese_concept.json()["canonical_key"] == "证据与有效性"
    listed = client.get("/api/concepts", params={"namespace": "科研方法"}).json()
    assert [item["id"] for item in listed] == [chinese_concept.json()["id"]]

    for knowledge_unit_id in fixture["knowledge_unit_ids"]:
        mapping = client.post(
            f"/api/knowledge-units/{knowledge_unit_id}/concept-mappings",
            json={
                "concept_id": concept["id"],
                "relation": "exact",
                "confidence": 0.96,
                "source": "model",
                "evidence": {"reason": "Same rubric and source claim"},
                "model_profile": "mock:heuristic-v2",
                "prompt_version": "concept-map:v1",
            },
        )
        assert mapping.status_code == 201
        assert mapping.json()["status"] == "proposed"
        reviewed = client.patch(
            f"/api/concept-mappings/{mapping.json()['id']}",
            json={"status": "accepted"},
        )
        assert reviewed.status_code == 200

    assert client.post(f"/api/sessions/{fixture['session']['id']}/start").status_code == 200
    answer = client.post(
        f"/api/sessions/{fixture['session']['id']}/answers",
        json={
            "answer": (
                "The claim is supported by an explicit baseline and measured evidence, "
                "but it remains limited to the evaluated distribution."
            )
        },
    )
    assert answer.status_code == 200
    assert answer.json()["completed"] is True

    dry_run = client.post(
        f"/api/learner-identities/{identity['id']}/memory/import",
        json={"dry_run": True},
    ).json()
    assert dry_run["eligible"] == 1
    assert dry_run["imported"] == 1
    assert client.get(
        f"/api/learner-identities/{identity['id']}/memory"
    ).json()["events"] == []

    imported = client.post(
        f"/api/learner-identities/{identity['id']}/memory/import",
        json={"dry_run": False},
    ).json()
    assert imported["imported"] == 1
    repeated = client.post(
        f"/api/learner-identities/{identity['id']}/memory/import",
        json={"dry_run": False},
    ).json()
    assert repeated["imported"] == 0
    assert repeated["skipped"] == 1

    memory = client.get(
        f"/api/learner-identities/{identity['id']}/memory",
        params={"category": "concept_evidence"},
    ).json()
    assert len(memory["events"]) == 1
    event = memory["events"][0]
    assert event["concept_title"] == "Evidence and validity"
    assert event["payload"]["assistance_level"] == "direct"
    assert "answer" not in event["payload"]
    assert "content" not in event["payload"]
    assert event["policy_version"] == "memory-policy-v1"

    assert client.delete(f"/api/projects/{fixture['project']['id']}").status_code == 200
    after_project_delete = client.get(
        f"/api/learner-identities/{identity['id']}/memory"
    ).json()
    assert after_project_delete["events"] == []
    assert client.get(f"/api/learner-identities/{identity['id']}").json()["links"] == []


def test_memory_scope_conflicts_controls_and_project_deletion(client):
    first = _create_subject_session(client, "First project", "same-human-a")
    second = _create_subject_session(client, "Second project", "same-human-b")
    identity = client.post(
        "/api/learner-identities",
        json={
            "external_subject_ref": "scope-test-user",
            "memory_enabled": True,
            "memory_scope": "project_only",
        },
    ).json()
    first_link = client.post(
        f"/api/learner-identities/{identity['id']}/links",
        json={"learner_subject_id": first["session"]["learner_subject_id"]},
    )
    assert first_link.status_code == 201

    cross_project = client.post(
        f"/api/learner-identities/{identity['id']}/links",
        json={"learner_subject_id": second["session"]["learner_subject_id"]},
    )
    assert cross_project.status_code == 409
    assert "project_only" in cross_project.json()["detail"]

    settings = client.patch(
        f"/api/learner-identities/{identity['id']}/memory-settings",
        json={"memory_scope": "linked_projects"},
    )
    assert settings.status_code == 200
    assert settings.json()["memory_scope"] == "linked_projects"
    control_events = client.get(
        f"/api/learner-identities/{identity['id']}/memory",
        params={"category": "memory_control"},
    ).json()["events"]
    assert len(control_events) == 1
    assert control_events[0]["learner_subject_id"] is None
    second_link = client.post(
        f"/api/learner-identities/{identity['id']}/links",
        json={"learner_subject_id": second["session"]["learner_subject_id"]},
    )
    assert second_link.status_code == 201

    other_identity = client.post(
        "/api/learner-identities",
        json={"external_subject_ref": "other-scope-user", "memory_enabled": True},
    ).json()
    collision = client.post(
        f"/api/learner-identities/{other_identity['id']}/links",
        json={"learner_subject_id": first["session"]["learner_subject_id"]},
    )
    assert collision.status_code == 409

    disabled = client.patch(
        f"/api/learner-identities/{identity['id']}/memory-settings",
        json={"memory_enabled": False},
    )
    assert disabled.status_code == 200
    blocked = client.post(
        f"/api/learner-identities/{identity['id']}/memory/import",
        json={"dry_run": False},
    )
    assert blocked.status_code == 409

    revoked = client.delete(
        f"/api/learner-identities/{identity['id']}/links/{first_link.json()['id']}"
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    assert client.delete(f"/api/projects/{first['project']['id']}").status_code == 200
    fetched = client.get(f"/api/learner-identities/{identity['id']}").json()
    assert all(
        link["learner_subject_id"] != first["session"]["learner_subject_id"]
        for link in fetched["links"]
    )


def test_memory_policy_rejects_unrestricted_categories(client):
    with SessionLocal() as db:
        service = LearnerMemoryService(db, "test-secret")
        try:
            service._validate_category("unrestricted_chat_summary")
        except MemoryPolicyError as exc:
            assert "not allowed" in str(exc)
        else:
            raise AssertionError("Disallowed memory category was accepted")

        assert db.scalar(select(func.count(LearnerMemoryEvent.id))) == 0
        assert db.scalar(select(func.count(LearnerIdentity.id))) == 0
        assert db.scalar(select(func.count(LearnerIdentityLink.id))) == 0
