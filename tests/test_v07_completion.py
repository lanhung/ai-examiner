import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    LearnerMemoryEvent,
    MemoryDeletionAudit,
    RetestItem,
)


def _memory_fixture(client, suffix: str = "one") -> dict:
    project = client.post(
        "/api/projects", json={"name": f"Longitudinal {suffix}"}
    ).json()
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={
            "file": (
                f"{suffix}.txt",
                (
                    b"The experiment compares a baseline and reports bounded evidence. "
                    b"The conclusion is limited to the evaluated distribution. "
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
            "learner_subject_key": f"subject-{suffix}",
            "question_limit": 1,
            "max_followups_per_question": 0,
        },
    ).json()
    unit_id = client.get(
        f"/api/sessions/{session['id']}/knowledge-state"
    ).json()["units"][0]["id"]
    identity = client.post(
        "/api/learner-identities",
        json={
            "external_subject_ref": f"identity-{suffix}",
            "display_name": f"Learner {suffix}",
            "memory_enabled": True,
        },
    ).json()
    assert client.post(
        f"/api/learner-identities/{identity['id']}/links",
        json={"learner_subject_id": session["learner_subject_id"]},
    ).status_code == 201
    concept = client.post(
        "/api/concepts",
        json={
            "namespace": "research-methods",
            "canonical_key": f"evidence-{suffix}",
            "title": f"Evidence {suffix}",
        },
    ).json()
    mapping = client.post(
        f"/api/knowledge-units/{unit_id}/concept-mappings",
        json={
            "concept_id": concept["id"],
            "relation": "exact",
            "confidence": 0.98,
            "source": "human",
        },
    ).json()
    assert client.patch(
        f"/api/concept-mappings/{mapping['id']}", json={"status": "accepted"}
    ).status_code == 200
    with SessionLocal() as db:
        db.add(
            LearnerMemoryEvent(
                learner_identity_id=identity["id"],
                learner_subject_id=session["learner_subject_id"],
                concept_id=concept["id"],
                event_type="concept_evidence",
                payload_json={
                    "observation": 0.2,
                    "evidence_weight": 1.0,
                    "assistance_level": "direct",
                    "detected_misconceptions": ["claim exceeds evidence"],
                    "resolved_misconceptions": [],
                },
                occurred_at=datetime.now(UTC) - timedelta(days=40),
                policy_version="test-v1",
                algorithm_version="memory-ledger-v1",
            )
        )
        db.commit()
    rebuilt = client.post(
        f"/api/learner-identities/{identity['id']}/memory/rebuild",
        json={"algorithm_version": "evidence-half-life-v1"},
    )
    assert rebuilt.status_code == 200
    return {
        "project": project,
        "blueprint": blueprint,
        "session": session,
        "identity": identity,
        "concept": concept,
    }


def test_retest_lifecycle_runs_exact_user_started_session(client):
    fixture = _memory_fixture(client, "retest")
    identity_id = fixture["identity"]["id"]
    plan = client.post(
        f"/api/learner-identities/{identity_id}/retest-plans",
        json={"horizon_days": 30, "max_items": 5},
    ).json()
    item = plan["items"][0]
    accepted = client.patch(
        f"/api/learner-identities/{identity_id}/retest-items/{item['id']}",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    started = client.post(
        f"/api/learner-identities/{identity_id}/retest-items/{item['id']}/start",
        json={
            "blueprint_id": fixture["blueprint"]["id"],
            "profile": "mock:heuristic-v2",
        },
    )
    assert started.status_code == 200
    started_data = started.json()
    assert started_data["retest_item"]["status"] == "started"
    assert started_data["turn"]["question_id"] == started_data["retest_item"][
        "selected_question_id"
    ]

    answered = client.post(
        f"/api/sessions/{started_data['session_id']}/answers",
        json={
            "answer": (
                "The baseline and bounded evidence support the measured result, "
                "but do not justify claims outside the evaluated distribution."
            )
        },
    )
    assert answered.status_code == 200
    result = answered.json()
    assert result["completed"] is True
    assert result["retest_item"]["status"] == "completed"
    assert result["retest_item"]["outcome_event_id"]
    states = client.get(
        f"/api/learner-identities/{identity_id}/concept-states"
    ).json()["states"]
    assert states[0]["evidence_count"] == 2


def test_preference_confirmation_registry_and_score_isolation(client):
    fixture = _memory_fixture(client, "preference")
    identity_id = fixture["identity"]["id"]
    explicit = client.post(
        f"/api/learner-identities/{identity_id}/preferences",
        json={
            "preference_key": "explanation_style",
            "value": "example_first",
            "source": "explicit",
        },
    )
    assert explicit.status_code == 201
    assert explicit.json()["status"] == "active"
    unsafe = client.post(
        f"/api/learner-identities/{identity_id}/preferences",
        json={
            "preference_key": "personality_type",
            "value": "introvert",
            "source": "explicit",
        },
    )
    assert unsafe.status_code == 409

    disabled_inference = client.post(
        f"/api/learner-identities/{identity_id}/preferences",
        json={
            "preference_key": "response_pace",
            "value": "deliberate",
            "source": "inferred",
            "evidence": [{"source": "s1"}, {"source": "s2"}],
        },
    )
    assert disabled_inference.status_code == 409
    assert client.patch(
        f"/api/learner-identities/{identity_id}/memory-settings",
        json={"preference_inference_enabled": True},
    ).status_code == 200
    proposed = client.post(
        f"/api/learner-identities/{identity_id}/preferences",
        json={
            "preference_key": "response_pace",
            "value": "deliberate",
            "source": "inferred",
            "evidence": [
                {"source": "session", "reference_id": "a"},
                {"source": "session", "reference_id": "b"},
            ],
        },
    ).json()
    assert proposed["status"] == "proposed"
    confirmed = client.patch(
        f"/api/learner-identities/{identity_id}/preferences/{proposed['id']}",
        json={"action": "confirm"},
    ).json()
    assert confirmed["status"] == "active"
    assert confirmed["confirmation_count"] == 1
    session = client.get(f"/api/sessions/{fixture['session']['id']}").json()
    assert "preferences" not in session
    assert "score" not in explicit.json()


def test_memory_correction_export_and_scoped_deletion(client):
    first = _memory_fixture(client, "control-a")
    second = _memory_fixture(client, "control-b")
    identity_id = first["identity"]["id"]
    memory = client.get(f"/api/learner-identities/{identity_id}/memory").json()
    original = next(
        event for event in memory["events"] if event["event_type"] == "concept_evidence"
    )
    corrected = client.post(
        f"/api/learner-identities/{identity_id}/memory/{original['id']}/correct",
        json={"observation": 0.85, "reason": "The prior import was mis-scored"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["supersedes_event_id"] == original["id"]
    state = client.get(
        f"/api/learner-identities/{identity_id}/concept-states"
    ).json()["states"][0]
    assert state["evidence_count"] == 1
    assert state["observed_mastery"] == 0.85

    exported_job = client.post(
        f"/api/learner-identities/{identity_id}/memory/export",
        json={"include_source_quotes": False},
    )
    assert exported_job.status_code == 202
    job = client.get(f"/api/jobs/{exported_job.json()['id']}").json()
    assert job["status"] == "completed"
    artifact = job["result"]
    exported = client.get(artifact["download_url"])
    assert exported.status_code == 200
    payload = json.loads(exported.content)
    assert payload["identity"]["id"] == identity_id
    assert "opaque_key_hash" not in exported.text

    deleted = client.request(
        "DELETE",
        f"/api/learner-identities/{identity_id}/memory",
        json={
            "scope": "concept",
            "concept_id": first["concept"]["id"],
            "confirmation": "delete",
        },
    )
    assert deleted.status_code == 202
    audit_id = deleted.json()["audit_id"]
    with SessionLocal() as db:
        audit = db.get(MemoryDeletionAudit, audit_id)
        assert audit.status == "completed"
        assert audit.counts_json["events"] == 2
    assert client.get(
        f"/api/learner-identities/{identity_id}/concept-states"
    ).json()["states"] == []
    other_events = client.get(
        f"/api/learner-identities/{second['identity']['id']}/memory"
    ).json()["events"]
    assert any(event["event_type"] == "concept_evidence" for event in other_events)


def test_memory_center_and_offline_longitudinal_evaluation(client):
    fixture = _memory_fixture(client, "center")
    identity_id = fixture["identity"]["id"]
    center = client.get(
        f"/api/learner-identities/{identity_id}/memory-center"
    )
    assert center.status_code == 200
    assert center.json()["concept_states"][0]["concept_title"] == "Evidence center"
    assert "observed" in center.json()["labels"]
    assert "predicted" in center.json()["labels"]

    report = client.post("/api/evaluations/longitudinal")
    assert report.status_code == 200
    data = report.json()
    assert data["report_version"] == "longitudinal-eval-v1"
    assert data["sample_counts"]["retention_attempts"] == 6
    assert data["gates"]["active_automatic_retests"] == "disabled"
    assert data["gates"]["mapping_activation"].startswith("held")

    with SessionLocal() as db:
        items = db.scalars(select(RetestItem)).all()
        assert items == []


def test_failed_deletion_blocks_writes_and_can_resume(client):
    fixture = _memory_fixture(client, "retry")
    identity_id = fixture["identity"]["id"]
    preference = client.post(
        f"/api/learner-identities/{identity_id}/preferences",
        json={
            "preference_key": "hint_style",
            "value": "progressive",
            "source": "explicit",
        },
    ).json()
    queued = client.request(
        "DELETE",
        f"/api/learner-identities/{identity_id}/memory",
        json={
            "scope": "preference",
            "preference_id": "missing-preference",
            "confirmation": "delete",
        },
    )
    assert queued.status_code == 202
    assert queued.json()["job"]["status"] == "failed"
    audit_id = queued.json()["audit_id"]
    blocked = client.post(
        f"/api/learner-identities/{identity_id}/preferences",
        json={
            "preference_key": "response_pace",
            "value": "balanced",
            "source": "explicit",
        },
    )
    assert blocked.status_code == 409
    assert "blocked" in blocked.json()["detail"]

    with SessionLocal() as db:
        audit = db.get(MemoryDeletionAudit, audit_id)
        assert audit.status == "failed"
        audit.target_ref = preference["id"]
        db.commit()
    retried = client.post(f"/api/memory-deletions/{audit_id}/retry")
    assert retried.status_code == 202
    assert retried.json()["job"]["status"] == "completed"
    identity = client.get(f"/api/learner-identities/{identity_id}").json()
    assert identity["memory_write_blocked"] is False
    assert client.get(
        f"/api/learner-identities/{identity_id}/preferences"
    ).json()["preferences"] == []
