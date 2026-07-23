from __future__ import annotations

import copy

from ai_examiner.db import SessionLocal
from ai_examiner.models import ExamSession
from ai_examiner.templates.builtin import load_builtin_template


def _project_and_blueprint(client):
    project = client.post(
        "/api/projects",
        json={"name": "Template session integration"},
    ).json()
    material = (
        "The study proposes an adaptive examiner with evidence-grounded "
        "questions, explicit policy decisions, and a cognitive state model. "
        "Its evaluation compares fixed and adaptive question selection and "
        "reports limitations in sample size and domain coverage. "
    ) * 20
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("paper.txt", material.encode(), "text/plain")},
    ).json()
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        params={"document_id": document["id"]},
    ).json()
    return project, blueprint


def _latest_builtin(client):
    templates = client.get("/api/templates").json()
    return next(
        item for item in templates if item["slug"] == "academic.thesis_defense"
    )


def test_legacy_text_session_resolves_latest_published_template_snapshot(client):
    project, blueprint = _project_and_blueprint(client)
    created = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
        },
    )

    assert created.status_code == 201
    session = created.json()
    assert session["template_version_id"] == _latest_builtin(client)["version_id"]
    assert session["template_fingerprint"].startswith("sha256:")
    assert session["config"]["template_resolution_source"] == "legacy"

    inspected = client.get(f"/api/sessions/{session['id']}/template")
    assert inspected.status_code == 200
    template = inspected.json()
    assert template["semantic_version"] == "1.2.0"
    assert template["integrity"] == "verified"
    assert template["resolution_source"] == "legacy"
    assert template["snapshot"]["legacy"]["question_limit"] == 6


def test_project_binding_defaults_and_request_overrides_have_clear_precedence(client):
    project, blueprint = _project_and_blueprint(client)
    version_id = _latest_builtin(client)["version_id"]

    bound = client.put(
        f"/api/projects/{project['id']}/template-binding",
        json={
            "template_version_id": version_id,
            "default_overrides": {
                "question_limit": 4,
                "max_followups_per_question": 1,
                "question_strategy": "adaptive",
            },
        },
    )
    assert bound.status_code == 200
    assert bound.json()["binding"]["template_version_id"] == version_id

    inherited = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
        },
    ).json()
    assert inherited["config"]["template_resolution_source"] == "project_default"
    assert inherited["config"]["question_limit"] == 4
    assert inherited["config"]["max_followups_per_question"] == 1
    assert inherited["question_strategy"] == "adaptive"

    explicit = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_limit": 3,
            "question_strategy": "fixed",
        },
    ).json()
    assert explicit["config"]["question_limit"] == 3
    assert explicit["config"]["max_followups_per_question"] == 1
    assert explicit["question_strategy"] == "fixed"
    inspected = client.get(f"/api/sessions/{explicit['id']}/template").json()
    assert inspected["overrides"]["question_limit"] == 3
    assert inspected["overrides"]["question_strategy"] == "fixed"

    cleared = client.delete(
        f"/api/projects/{project['id']}/template-binding"
    )
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    assert (
        client.get(f"/api/projects/{project['id']}/template-binding").json()[
            "binding"
        ]
        is None
    )


def test_explicit_draft_and_invalid_overrides_are_rejected_before_session_creation(
    client,
):
    project, blueprint = _project_and_blueprint(client)
    source = load_builtin_template("academic.thesis_defense.v1.yaml")
    draft = client.post(
        "/api/templates",
        json={
            "slug": "local.unpublished_defense",
            "category": "academic",
            "semantic_version": "0.1.0",
            "source": source,
        },
    ).json()

    rejected_draft = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "template_version_id": draft["version"]["id"],
        },
    )
    assert rejected_draft.status_code == 409
    assert (
        rejected_draft.json()["detail"]["code"]
        == "TEMPLATE_VERSION_NOT_SELECTABLE"
    )

    rejected_override = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "template_overrides": {"question_limit": 100},
        },
    )
    assert rejected_override.status_code == 422
    assert (
        rejected_override.json()["detail"]["code"]
        == "TEMPLATE_OVERRIDE_OUT_OF_RANGE"
    )


def test_equivalent_text_and_openai_voice_policies_share_a_fingerprint(client):
    project, blueprint = _project_and_blueprint(client)
    text = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_limit": 4,
            "max_followups_per_question": 1,
            "template_overrides": {"voice_provider": "openai"},
        },
    )
    assert text.status_code == 201

    voice = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "provider": "openai",
            "question_limit": 4,
            "max_followups": 1,
        },
    )
    assert voice.status_code == 201
    assert voice.json()["template_version_id"] == text.json()["template_version_id"]
    assert voice.json()["template_fingerprint"] == text.json()["template_fingerprint"]

    voice_template = client.get(
        f"/api/sessions/{voice.json()['exam_session_id']}/template"
    ).json()
    assert voice_template["integrity"] == "verified"
    assert voice_template["resolution_source"] == "legacy"
    assert voice_template["snapshot"]["voice"]["provider"] == "openai"


def test_qwen_snapshot_records_effective_safety_clamps(client):
    project, blueprint = _project_and_blueprint(client)
    voice = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "provider": "qwen",
            "voice": "Cherry",
            "question_limit": 12,
            "max_followups": 4,
        },
    )

    assert voice.status_code == 201
    payload = voice.json()
    assert payload["config"]["question_limit"] == 4
    assert payload["config"]["max_followups"] == 1
    inspected = client.get(
        f"/api/sessions/{payload['exam_session_id']}/template"
    ).json()
    assert inspected["snapshot"]["legacy"]["question_limit"] == 4
    assert inspected["snapshot"]["legacy"]["max_followups_per_question"] == 1
    assert inspected["snapshot"]["voice"]["provider"] == "qwen"


def test_non_defense_legacy_mode_remains_backward_compatible(client):
    project, blueprint = _project_and_blueprint(client)
    created = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "mode": "teaching",
        },
    )

    assert created.status_code == 201
    assert created.json()["template_version_id"] is None
    inspected = client.get(
        f"/api/sessions/{created.json()['id']}/template"
    ).json()
    assert inspected == {
        "bound": False,
        "legacy_session": True,
        "template_version_id": None,
        "fingerprint": None,
        "integrity": "not_applicable",
    }


def test_snapshot_integrity_detects_storage_tampering(client):
    project, blueprint = _project_and_blueprint(client)
    created = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
        },
    ).json()
    original = client.get(f"/api/sessions/{created['id']}/template").json()
    assert original["integrity"] == "verified"

    with SessionLocal() as db:
        session = db.get(ExamSession, created["id"])
        changed = copy.deepcopy(session.template_snapshot_json)
        changed["legacy"]["question_limit"] = 20
        session.template_snapshot_json = changed
        db.commit()

    inspected = client.get(f"/api/sessions/{created['id']}/template").json()
    assert inspected["integrity"] == "fingerprint_mismatch"
