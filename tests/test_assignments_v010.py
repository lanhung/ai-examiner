from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID, ROLE_CAPABILITIES
from ai_examiner.models import (
    Assignment,
    AssignmentAttempt,
    ExamSession,
    Organization,
    OrganizationMembership,
    Principal,
)
from ai_examiner.services import assignments as assignment_service
from ai_examiner.services.assignments import (
    JOIN_CODE_ALPHABET,
    AssignmentError,
    ensure_attempt_allowed,
    freeze_session_settings,
    generate_join_code,
    hash_attempt_token,
    issue_attempt_token,
    learner_report_view,
    lock_conversation_policy,
    normalize_join_code,
    verify_attempt_token,
    window_state,
)
from ai_examiner.services.conversation_policy import effective_conversation_policy

ROOT = Path(__file__).resolve().parents[1]
TOKEN_HEADER = "X-AI-Examiner-Attempt-Token"
MATERIAL = (
    "本文提出一种面向科学计算的自适应代理方法。核心贡献包括状态建模、证据化评分和追问策略。"
    "实验比较了三种基线，并讨论了数据分布变化时的局限。"
) * 10
ANSWERS = [
    "核心问题是现有系统只会回答，不能持续诊断理解。因为缺少状态建模，所以追问不稳定。",
    "新增之处是将分析、策略和评分拆开，并用实验与基线比较验证。",
    "如果去掉这一设计，追问会失去依据，评分也无法对应证据。",
    "局限是数据分布变化时效果下降，需要更多验证。",
    "补充说明：实验覆盖了三种基线。",
    "最后总结：方法在证据化评分上更稳定。",
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _prepare_blueprint(client, headers: dict | None = None) -> tuple[str, dict]:
    headers = headers or {}
    project = client.post("/api/projects", json={"name": "期中考试"}, headers=headers)
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    uploaded = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": ("paper.txt", MATERIAL.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    planned = client.post(
        f"/api/projects/{project_id}/blueprints",
        params={"document_id": uploaded.json()["id"]},
        headers=headers,
    )
    assert planned.status_code == 201, planned.text
    return project_id, {**planned.json(), "project_id": project_id}


def _publish(client, *, headers: dict | None = None, blueprint=None, **overrides):
    if blueprint is None:
        project_id, blueprint = _prepare_blueprint(client, headers)
    else:
        project_id = blueprint["project_id"]
    body = {
        "project_id": project_id,
        "blueprint_id": blueprint["id"],
        "title": "第一单元测验",
        "mode": "practice",
        "intro_text": "请独立完成。",
        "session_settings": {"question_limit": 2, "max_followups_per_question": 0},
    }
    body.update(overrides)
    created = client.post("/api/assignments", json=body, headers=headers or {})
    assert created.status_code == 201, created.text
    return created.json(), blueprint


def _join(client, code: str, *, headers: dict | None = None, **body):
    response = client.post(
        f"/api/join/{code}/attempts",
        json={"display_name": "张三", **body},
        headers=headers or {},
    )
    return response


def _token_headers(token: str, extra: dict | None = None) -> dict:
    return {TOKEN_HEADER: token, **(extra or {})}


def _finish(client, attempt_id: str, headers: dict) -> list[dict]:
    responses = []
    started = client.post(f"/api/attempts/{attempt_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    responses.append(started.json())
    for answer in ANSWERS:
        answered = client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"answer": answer},
            headers=headers,
        )
        assert answered.status_code == 200, answered.text
        responses.append(answered.json())
        if answered.json()["completed"]:
            return responses
    raise AssertionError("attempt did not complete")


def _organization_with_roles(*roles: str) -> tuple[str, dict[str, dict]]:
    with SessionLocal() as db:
        organization = Organization(
            slug=f"assign-{'-'.join(roles)}-{datetime.now(UTC).timestamp()}".replace(
                ".", ""
            )[:90],
            display_name="Assignment org",
            status="active",
        )
        db.add(organization)
        db.flush()
        headers = {}
        for role in roles:
            principal = Principal(
                issuer="https://issuer.example.test",
                subject=f"{organization.id}-{role}",
                display_name=role,
                status="active",
            )
            db.add(principal)
            db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    principal_id=principal.id,
                    role=role,
                    status="active",
                )
            )
            headers[role] = {
                "X-AI-Examiner-Organization": organization.id,
                "X-AI-Examiner-Principal": principal.id,
            }
        db.commit()
        return organization.id, headers


# --------------------------------------------------------------------------
# Unit
# --------------------------------------------------------------------------


def test_join_code_alphabet_excludes_ambiguous_characters():
    for character in "IO01":
        assert character not in JOIN_CODE_ALPHABET
    assert len(set(JOIN_CODE_ALPHABET)) == len(JOIN_CODE_ALPHABET) == 32
    for _ in range(300):
        code = generate_join_code()
        assert len(code) == 6
        assert set(code) <= set(JOIN_CODE_ALPHABET)


def test_join_code_normalization():
    assert normalize_join_code(" ab-c 23d ") == "ABC23D"
    assert normalize_join_code("abc23d") == "ABC23D"
    assert normalize_join_code("ABCO23") is None
    assert normalize_join_code("ABC123") is None
    assert normalize_join_code("ABC23") is None
    assert normalize_join_code("ABC23DE") is None
    assert normalize_join_code("") is None


def test_mode_defaults_are_frozen_per_mode():
    practice = freeze_session_settings("practice", {})
    exam = freeze_session_settings("exam", {"question_limit": 3})
    assert practice["allow_hints"] is True
    assert practice["allow_corrections"] is True
    assert practice["exam_lock"] is False
    assert exam["allow_hints"] is False
    assert exam["allow_corrections"] is False
    assert exam["exam_lock"] is True
    assert exam["question_limit"] == 3
    # Freezing copies the defaults instead of sharing them.
    practice["question_limit"] = 99
    assert freeze_session_settings("practice", {})["question_limit"] == 5


def test_exam_mode_rejects_assistance_and_unknown_settings():
    with pytest.raises(AssignmentError) as hints:
        freeze_session_settings("exam", {"allow_hints": True})
    assert hints.value.code == "assignment_exam_assistance_forbidden"
    with pytest.raises(AssignmentError) as corrections:
        freeze_session_settings("exam", {"allow_corrections": True})
    assert corrections.value.status_code == 422
    with pytest.raises(AssignmentError) as unknown:
        freeze_session_settings("practice", {"reveal_answers": True})
    assert unknown.value.code == "assignment_setting_unknown"
    with pytest.raises(AssignmentError):
        freeze_session_settings("homework", {})


def test_lock_conversation_policy_removes_every_assistance_path():
    policy = effective_conversation_policy(
        None,
        user_allows_active_interruption=False,
        legacy_config={"allow_hints": True, "allow_corrections": True},
    )
    policy["allowed_actions"] = ["ASK_FOLLOWUP", "GIVE_HINT", "CORRECT", "MOVE_ON"]
    policy["answer_disclosure"] = {"allowed": True}
    locked = lock_conversation_policy(policy)
    assert "GIVE_HINT" not in locked["allowed_actions"]
    assert "CORRECT" not in locked["allowed_actions"]
    assert locked["allowed_actions"] == ["ASK_FOLLOWUP", "MOVE_ON", "END"]
    assert locked["hints"]["allowed"] is False
    assert locked["corrections"]["allowed"] is False
    assert locked["answer_disclosure"]["allowed"] is False
    assert locked["exam_lock"] is True
    # The input policy is not mutated.
    assert "GIVE_HINT" in policy["allowed_actions"]
    assert policy["hints"]["allowed"] is True


def test_window_state_and_attempt_limits():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    assignment = Assignment(
        status="published",
        opens_at=None,
        closes_at=None,
        max_attempts=2,
        require_learner_key=False,
    )
    assert window_state(assignment, now) == "open"
    assignment.opens_at = (now + timedelta(hours=1)).replace(tzinfo=None)
    assert window_state(assignment, now) == "scheduled"
    assignment.opens_at = now - timedelta(hours=2)
    assignment.closes_at = now - timedelta(minutes=1)
    assert window_state(assignment, now) == "ended"
    assignment.closes_at = now + timedelta(hours=1)
    assert window_state(assignment, now) == "open"
    assert ensure_attempt_allowed(
        assignment, prior_attempts=1, learner_key=None, now=now
    ) == 2
    with pytest.raises(AssignmentError) as exhausted:
        ensure_attempt_allowed(assignment, prior_attempts=2, learner_key=None, now=now)
    assert exhausted.value.code == "attempt_limit_reached"
    assignment.require_learner_key = True
    with pytest.raises(AssignmentError) as missing_key:
        ensure_attempt_allowed(assignment, prior_attempts=0, learner_key=None, now=now)
    assert missing_key.value.code == "learner_key_required"
    assignment.status = "closed"
    assert window_state(assignment, now) == "closed"
    with pytest.raises(AssignmentError) as closed:
        ensure_attempt_allowed(
            assignment, prior_attempts=0, learner_key="s1", now=now
        )
    assert closed.value.code == "assignment_closed"


def test_attempt_token_is_hashed_and_compared_in_constant_time(monkeypatch):
    token, token_hash = issue_attempt_token()
    assert token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in token_hash
    assert hash_attempt_token(token) == token_hash

    calls = []
    real_compare = assignment_service.hmac.compare_digest

    def recording_compare(left, right):
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(assignment_service.hmac, "compare_digest", recording_compare)
    assert verify_attempt_token(token, token_hash) is True
    assert verify_attempt_token(token + "x", token_hash) is False
    assert verify_attempt_token(None, token_hash) is False
    assert verify_attempt_token("", token_hash) is False
    assert len(calls) == 2


def test_learner_report_view_hides_unreleased_exam_results():
    report = {
        "overall_score": 3.5,
        "max_score": 5,
        "questions_answered": 2,
        "strengths": ["结构清楚"],
        "priority_weaknesses": [{"statement": "证据不足", "source_excerpt": "SECRET"}],
        "recommended_actions": ["补充证据"],
        "evidence": [{"source_excerpt": "SECRET"}],
    }
    completed = SimpleNamespace(status="completed")
    exam = SimpleNamespace(title="期末", mode="exam", results_released=False)
    hidden = learner_report_view(exam, completed, report)
    assert hidden == {
        "status": "submitted",
        "title": "期末",
        "mode": "exam",
        "results_available": False,
    }
    exam.results_released = True
    released = learner_report_view(exam, completed, report)
    assert released["status"] == "released"
    assert released["summary"]["overall_score"] == 3.5
    assert released["improvements"] == ["证据不足"]
    assert "SECRET" not in json.dumps(released, ensure_ascii=False)
    running = learner_report_view(exam, SimpleNamespace(status="active"), None)
    assert running["status"] == "in_progress"
    assert "summary" not in running


def test_capability_bundles_for_assignments():
    new = {"assignment.manage", "assignment.read", "assignment.attempt"}
    assert new <= ROLE_CAPABILITIES["examiner"]
    assert new <= ROLE_CAPABILITIES["owner"]
    assert new <= ROLE_CAPABILITIES["admin"]
    for role in ("reviewer", "auditor"):
        assert ROLE_CAPABILITIES[role] & new == {"assignment.read"}
    assert ROLE_CAPABILITIES["learner"] & new == {"assignment.attempt"}
    assert ROLE_CAPABILITIES["template_author"] & new == set()


# --------------------------------------------------------------------------
# Integration
# --------------------------------------------------------------------------


def test_practice_assignment_full_flow(client):
    assignment, _blueprint = _publish(client, max_attempts=2)
    code = assignment["join_code"]
    assert len(code) == 6
    assert assignment["status"] == "published"
    assert assignment["window_state"] == "open"
    assert assignment["session_settings"]["profile"] == "mock:heuristic-v2"
    assert assignment["session_settings"]["exam_lock"] is False

    listed = client.get("/api/assignments")
    assert [item["id"] for item in listed.json()] == [assignment["id"]]
    assert client.get(f"/api/assignments/{assignment['id']}").status_code == 200

    joined = client.get(f"/api/join/{code.lower()}")
    assert joined.status_code == 200
    assert joined.json()["title"] == "第一单元测验"
    assert joined.json()["question_limit"] == 2

    created = _join(client, code)
    assert created.status_code == 201, created.text
    token = created.json()["attempt_token"]
    attempt = created.json()["attempt"]
    assert attempt["status"] == "not_started"
    assert attempt["attempt_number"] == 1
    headers = _token_headers(token)

    _finish(client, attempt["id"], headers)
    fetched = client.get(f"/api/attempts/{attempt['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "submitted"
    assert len(fetched.json()["turns"]) >= 4

    report = client.get(f"/api/attempts/{attempt['id']}/report", headers=headers)
    assert report.status_code == 200
    body = report.json()
    assert body["status"] == "released"
    assert body["results_available"] is True
    assert body["summary"]["questions_answered"] == 2
    assert 0 <= body["summary"]["overall_score"] <= body["summary"]["max_score"]

    dashboard = client.get(f"/api/assignments/{assignment['id']}/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["counts"] == {
        "attempts": 1,
        "not_started": 0,
        "in_progress": 0,
        "submitted": 1,
    }
    row = dashboard.json()["attempts"][0]
    assert row["display_name"] == "张三"
    assert row["answers"] >= 2
    assert row["average_answer_score"] is not None


def test_exam_assignment_locks_policy_and_withholds_results(client):
    assignment, _ = _publish(
        client,
        mode="exam",
        session_settings={"question_limit": 2, "max_followups_per_question": 1},
    )
    assert assignment["session_settings"]["allow_hints"] is False
    assert assignment["session_settings"]["exam_lock"] is True
    created = _join(client, assignment["join_code"])
    token = created.json()["attempt_token"]
    attempt_id = created.json()["attempt"]["id"]

    with SessionLocal() as db:
        attempt = db.get(AssignmentAttempt, attempt_id)
        session = db.get(ExamSession, attempt.session_id)
        policy = session.config["conversation_policy"]
        assert session.config["exam_lock"] is True
        assert session.config["allow_hints"] is False
        assert session.config["allow_corrections"] is False
        assert "GIVE_HINT" not in policy["allowed_actions"]
        assert "CORRECT" not in policy["allowed_actions"]
        assert policy["hints"]["allowed"] is False
        assert policy["corrections"]["allowed"] is False
        assert policy["answer_disclosure"]["allowed"] is False

    headers = _token_headers(token)
    started = client.post(f"/api/attempts/{attempt_id}/start", headers=headers)
    assert started.status_code == 200
    # An empty answer would earn a hint in practice; exam mode must not hint.
    answered = client.post(
        f"/api/attempts/{attempt_id}/answers",
        json={"answer": "不知道"},
        headers=headers,
    )
    assert answered.status_code == 200
    assert "提示" not in answered.json()["turns"][1]["content"]
    with SessionLocal() as db:
        attempt = db.get(AssignmentAttempt, attempt_id)
        session = db.get(ExamSession, attempt.session_id)
        decisions = [
            (turn.analysis or {}).get("policy_decision", {}).get("action")
            for turn in session.turns
        ]
        assert "GIVE_HINT" not in decisions
    for answer in ANSWERS:
        result = client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"answer": answer},
            headers=headers,
        )
        if result.json()["completed"]:
            break
    assert result.json()["status"] == "submitted"

    withheld = client.get(f"/api/attempts/{attempt_id}/report", headers=headers)
    assert withheld.json() == {
        "status": "submitted",
        "title": "第一单元测验",
        "mode": "exam",
        "results_available": False,
    }

    released = client.patch(
        f"/api/assignments/{assignment['id']}",
        json={"results_released": True},
    )
    assert released.status_code == 200
    assert released.json()["results_released"] is True
    shown = client.get(f"/api/attempts/{attempt_id}/report", headers=headers)
    assert shown.json()["status"] == "released"
    assert "overall_score" in shown.json()["summary"]


def test_exam_assignment_rejects_enabled_hints(client):
    project_id, blueprint = _prepare_blueprint(client)
    response = client.post(
        "/api/assignments",
        json={
            "project_id": project_id,
            "blueprint_id": blueprint["id"],
            "title": "期末",
            "mode": "exam",
            "session_settings": {"allow_hints": True},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "assignment_exam_assistance_forbidden"


def test_assignment_validation_and_frozen_fields(client):
    project_id, blueprint = _prepare_blueprint(client)
    base = {
        "project_id": project_id,
        "blueprint_id": blueprint["id"],
        "title": "期末",
    }
    now = datetime.now(UTC)
    bad_window = client.post(
        "/api/assignments",
        json={
            **base,
            "opens_at": now.isoformat(),
            "closes_at": (now - timedelta(hours=1)).isoformat(),
        },
    )
    assert bad_window.status_code == 422
    unknown_setting = client.post(
        "/api/assignments",
        json={**base, "session_settings": {"reveal_answers": True}},
    )
    assert unknown_setting.status_code == 422
    missing = client.post(
        "/api/assignments",
        json={**base, "blueprint_id": "00000000-0000-0000-0000-00000000dead"},
    )
    assert missing.status_code == 404

    created = client.post("/api/assignments", json=base)
    assert created.status_code == 201
    assignment_id = created.json()["id"]
    for frozen in ({"mode": "exam"}, {"session_settings": {}}, {"join_code": "AAAAAA"}):
        rejected = client.patch(f"/api/assignments/{assignment_id}", json=frozen)
        assert rejected.status_code == 422, frozen
    null_title = client.patch(f"/api/assignments/{assignment_id}", json={"title": None})
    assert null_title.status_code == 422
    renamed = client.patch(
        f"/api/assignments/{assignment_id}",
        json={"title": "期末（补考）", "max_attempts": 3},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "期末（补考）"
    assert renamed.json()["max_attempts"] == 3
    assert renamed.json()["join_code"] == created.json()["join_code"]


def test_join_codes_are_unique_within_organization(client):
    first, blueprint = _publish(client)
    second, _ = _publish(client, blueprint=blueprint)
    assert first["join_code"] != second["join_code"]
    with SessionLocal() as db:
        codes = db.scalars(select(Assignment.join_code)).all()
    assert len(codes) == len(set(codes)) == 2


def test_attempt_limits_and_learner_key(client):
    assignment, _ = _publish(client, require_learner_key=True, max_attempts=1)
    code = assignment["join_code"]
    missing = _join(client, code)
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "learner_key_required"
    first = _join(client, code, learner_key="S001")
    assert first.status_code == 201
    repeat = _join(client, code, learner_key=" s001 ")
    assert repeat.status_code == 409
    assert repeat.json()["detail"]["code"] == "attempt_limit_reached"
    other = _join(client, code, learner_key="S002")
    assert other.status_code == 201


def test_open_window_is_enforced(client):
    future = datetime.now(UTC) + timedelta(days=1)
    scheduled, blueprint = _publish(client, opens_at=future.isoformat())
    assert client.get(f"/api/join/{scheduled['join_code']}").json()["window_state"] == "scheduled"
    early = _join(client, scheduled["join_code"])
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "assignment_scheduled"

    live, _ = _publish(client, blueprint=blueprint)
    created = _join(client, live["join_code"])
    headers = _token_headers(created.json()["attempt_token"])
    attempt_id = created.json()["attempt"]["id"]
    assert client.post(f"/api/attempts/{attempt_id}/start", headers=headers).status_code == 200

    closed = client.patch(f"/api/assignments/{live['id']}", json={"status": "closed"})
    assert closed.json()["window_state"] == "closed"
    late_answer = client.post(
        f"/api/attempts/{attempt_id}/answers",
        json={"answer": ANSWERS[0]},
        headers=headers,
    )
    assert late_answer.status_code == 409
    assert late_answer.json()["detail"]["code"] == "assignment_closed"
    assert _join(client, live["join_code"]).status_code == 409

    past = datetime.now(UTC) - timedelta(minutes=1)
    reopened = client.patch(
        f"/api/assignments/{live['id']}",
        json={"status": "published", "closes_at": past.isoformat(), "opens_at": None},
    )
    assert reopened.json()["window_state"] == "ended"
    ended = _join(client, live["join_code"])
    assert ended.json()["detail"]["code"] == "assignment_ended"


def test_existing_session_api_is_unchanged(client):
    project_id, blueprint = _prepare_blueprint(client)
    created = client.post(
        "/api/sessions",
        json={
            "project_id": project_id,
            "blueprint_id": blueprint["id"],
            "question_limit": 1,
            "max_followups_per_question": 0,
        },
    )
    assert created.status_code == 201
    assert set(created.json()) == {
        "id",
        "status",
        "config",
        "question_strategy",
        "policy_version",
        "learner_subject_id",
        "template_version_id",
        "template_fingerprint",
    }
    config = created.json()["config"]
    assert "exam_lock" not in config
    assert "exam_lock" not in config["conversation_policy"]
    session_id = created.json()["id"]
    started = client.post(f"/api/sessions/{session_id}/start")
    assert set(started.json()) == {"session_id", "status", "turn"}
    assert "analysis" in started.json()["turn"]
    answered = client.post(
        f"/api/sessions/{session_id}/answers", json={"answer": ANSWERS[0]}
    )
    assert set(answered.json()) == {
        "completed",
        "analysis",
        "evaluation",
        "decision",
        "turns",
        "retest_item",
    }
    assert answered.json()["completed"] is True
    report = client.get(f"/api/sessions/{session_id}/report")
    assert report.status_code == 200
    assert report.json()["session_status"] == "completed"
    assert client.post("/api/sessions/missing/start").status_code == 404
    assert client.get("/api/sessions/missing/report").status_code == 404


def test_project_deletion_cascades_assignments(client):
    assignment, blueprint = _publish(client)
    _join(client, assignment["join_code"])
    deleted = client.delete(f"/api/projects/{blueprint['project_id']}")
    assert deleted.status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(Assignment)).all() == []
        assert db.scalars(select(AssignmentAttempt)).all() == []


def test_exam_pages_are_served(client):
    for path in ("/exam", "/x/ABC234"):
        page = client.get(path)
        assert page.status_code == 200
        assert "exam.js" in page.text
    script = client.get("/static/exam.js")
    assert script.status_code == 200
    assert TOKEN_HEADER in script.text


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------


def test_role_permissions_on_assignment_routes(client):
    _organization_id, headers = _organization_with_roles(
        "examiner", "reviewer", "auditor", "learner", "template_author"
    )
    assignment, _ = _publish(client, headers=headers["examiner"])
    assignment_id = assignment["id"]
    assert assignment["created_by_principal_id"] == headers["examiner"][
        "X-AI-Examiner-Principal"
    ]

    for role in ("reviewer", "auditor"):
        assert client.get("/api/assignments", headers=headers[role]).status_code == 200
        assert (
            client.get(
                f"/api/assignments/{assignment_id}/dashboard", headers=headers[role]
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/assignments/{assignment_id}",
                json={"title": "x"},
                headers=headers[role],
            ).status_code
            == 403
        )
        assert (
            _join(client, assignment["join_code"], headers=headers[role]).status_code
            == 403
        )

    learner = headers["learner"]
    assert client.get("/api/assignments", headers=learner).status_code == 403
    assert (
        client.get(f"/api/assignments/{assignment_id}", headers=learner).status_code
        == 403
    )
    assert client.get("/api/assignments", headers=headers["template_author"]).status_code == 403

    joined = _join(client, assignment["join_code"], headers=learner)
    assert joined.status_code == 201
    attempt_id = joined.json()["attempt"]["id"]
    # The learner's own account is enough; no token needed.
    assert client.post(f"/api/attempts/{attempt_id}/start", headers=learner).status_code == 200
    assert client.get(f"/api/attempts/{attempt_id}", headers=learner).status_code == 200
    with SessionLocal() as db:
        attempt = db.get(AssignmentAttempt, attempt_id)
        assert attempt.principal_id == learner["X-AI-Examiner-Principal"]

    # The examiner, a different principal, cannot read the learner's attempt.
    assert (
        client.get(f"/api/attempts/{attempt_id}", headers=headers["examiner"]).status_code
        == 404
    )


def test_learner_attempt_limit_is_per_account(client):
    _organization_id, headers = _organization_with_roles("examiner", "learner")
    assignment, _ = _publish(client, headers=headers["examiner"], max_attempts=1)
    first = _join(client, assignment["join_code"], headers=headers["learner"])
    assert first.status_code == 201
    second = _join(client, assignment["join_code"], headers=headers["learner"])
    assert second.status_code == 409


def test_cross_tenant_assignment_access_is_not_found(client):
    _org_a, headers_a = _organization_with_roles("examiner", "learner")
    org_b, headers_b = _organization_with_roles("examiner", "learner")
    assignment, _ = _publish(client, headers=headers_a["examiner"])
    assignment_id = assignment["id"]
    code = assignment["join_code"]

    other_examiner = headers_b["examiner"]
    assert client.get(f"/api/assignments/{assignment_id}", headers=other_examiner).status_code == 404
    assert (
        client.get(
            f"/api/assignments/{assignment_id}/dashboard", headers=other_examiner
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/assignments/{assignment_id}",
            json={"status": "closed"},
            headers=other_examiner,
        ).status_code
        == 404
    )
    assert client.get("/api/assignments", headers=other_examiner).json() == []
    assert client.get(f"/api/join/{code}", headers=headers_b["learner"]).status_code == 404
    assert (
        client.get(
            f"/api/join/{code}", headers={"X-AI-Examiner-Organization": org_b}
        ).status_code
        == 404
    )
    # A blueprint from another organization cannot be published.
    _, blueprint_a = _prepare_blueprint(client, headers_a["examiner"])
    stolen = client.post(
        "/api/assignments",
        json={
            "project_id": blueprint_a["project_id"],
            "blueprint_id": blueprint_a["id"],
            "title": "偷用",
        },
        headers=other_examiner,
    )
    assert stolen.status_code == 404

    # A token from organization A does not work when presented to organization B.
    joined = _join(client, code, headers={"X-AI-Examiner-Organization": _org_a})
    assert joined.status_code == 201
    token = joined.json()["attempt_token"]
    attempt_id = joined.json()["attempt"]["id"]
    assert (
        client.get(
            f"/api/attempts/{attempt_id}",
            headers=_token_headers(token, {"X-AI-Examiner-Organization": _org_a}),
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/attempts/{attempt_id}",
            headers=_token_headers(token, {"X-AI-Examiner-Organization": org_b}),
        ).status_code
        == 404
    )


def test_attempt_ownership_requires_matching_token(client):
    assignment, _ = _publish(client, max_attempts=3)
    first = _join(client, assignment["join_code"]).json()
    second = _join(client, assignment["join_code"]).json()
    attempt_id = first["attempt"]["id"]
    paths = [
        ("get", f"/api/attempts/{attempt_id}"),
        ("get", f"/api/attempts/{attempt_id}/report"),
        ("post", f"/api/attempts/{attempt_id}/start"),
    ]
    for method, path in paths:
        for headers in ({}, _token_headers("forged"), _token_headers(second["attempt_token"])):
            response = getattr(client, method)(path, headers=headers)
            assert response.status_code == 404, (path, headers)
            assert response.json()["detail"]["code"] == "attempt_not_found"
    answer = client.post(
        f"/api/attempts/{attempt_id}/answers",
        json={"answer": "x"},
        headers=_token_headers(second["attempt_token"]),
    )
    assert answer.status_code == 404
    assert client.get("/api/attempts/does-not-exist", headers=_token_headers(first["attempt_token"])).status_code == 404
    assert (
        client.get(
            f"/api/attempts/{attempt_id}",
            headers=_token_headers(first["attempt_token"]),
        ).status_code
        == 200
    )


# --------------------------------------------------------------------------
# Leakage
# --------------------------------------------------------------------------


FORBIDDEN_LEARNER_KEYS = {
    "analysis",
    "evaluation",
    "decision",
    "project_id",
    "blueprint_id",
    "session_id",
    "session_settings",
    "profile",
    "token_hash",
    "organization_id",
    "expected_points",
    "source_excerpt",
    "evidence",
    "rubric",
    "knowledge_map",
    "mastery_state",
    "retest_item",
    "config",
}


def _all_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


def _assert_learner_safe(payload, secrets: list[str]) -> None:
    leaked = _all_keys(payload) & FORBIDDEN_LEARNER_KEYS
    assert leaked == set(), leaked
    text = json.dumps(payload, ensure_ascii=False)
    for secret in secrets:
        assert secret not in text, secret


def test_learner_views_never_leak_internal_data(client):
    assignment, blueprint = _publish(
        client,
        mode="exam",
        session_settings={"question_limit": 2, "max_followups_per_question": 1},
    )
    questions = blueprint["data"]["questions"]
    secrets = [
        blueprint["id"],
        blueprint["project_id"],
        "mock:heuristic-v2",
        "heuristic",
        *[point for question in questions for point in question.get("expected_points", [])],
        questions[0]["source_excerpt"][:40],
    ]
    code = assignment["join_code"]
    payloads = [client.get(f"/api/join/{code}").json()]
    created = _join(client, code)
    token = created.json()["attempt_token"]
    payloads.append(created.json())
    attempt_id = created.json()["attempt"]["id"]
    headers = _token_headers(token)
    with SessionLocal() as db:
        attempt = db.get(AssignmentAttempt, attempt_id)
        secrets.append(attempt.session_id)
        assert attempt.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps(
            {column: str(getattr(attempt, column)) for column in attempt.__table__.c.keys()}
        )

    started = client.post(f"/api/attempts/{attempt_id}/start", headers=headers)
    payloads.append(started.json())
    payloads.append(
        client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"answer": "不知道"},
            headers=headers,
        ).json()
    )
    for answer in ANSWERS:
        answered = client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"answer": answer},
            headers=headers,
        )
        payloads.append(answered.json())
        if answered.json()["completed"]:
            break
    attempt_view = client.get(f"/api/attempts/{attempt_id}", headers=headers).json()
    payloads.append(attempt_view)
    assert "attempt_token" not in attempt_view
    before_release = client.get(f"/api/attempts/{attempt_id}/report", headers=headers).json()
    assert "summary" not in before_release
    assert "score" not in json.dumps(before_release)
    payloads.append(before_release)
    client.patch(f"/api/assignments/{assignment['id']}", json={"results_released": True})
    payloads.append(
        client.get(f"/api/attempts/{attempt_id}/report", headers=headers).json()
    )
    for payload in payloads:
        _assert_learner_safe(payload, secrets)
    # Only the attempt-creation response carries the token, exactly once.
    assert sum(token in json.dumps(payload) for payload in payloads) == 1


def test_join_errors_do_not_reveal_other_organizations(client):
    assignment, _ = _publish(client)
    missing = client.get("/api/join/ZZZZZZ")
    invalid = client.get("/api/join/not-a-code")
    assert missing.status_code == invalid.status_code == 404
    assert missing.json() == invalid.json()
    assert assignment["join_code"] not in json.dumps(missing.json())


def test_exam_page_hides_internal_vocabulary():
    static = ROOT / "src" / "ai_examiner" / "static"
    for name in ("exam.html", "exam.js"):
        text = (static / name).read_text(encoding="utf-8")
        for word in ("项目", "材料", "蓝图", "模型"):
            assert word not in text, (name, word)
    html = (static / "exam.html").read_text(encoding="utf-8")
    for screen in ("screenCode", "screenChat", "screenReport"):
        assert f'id="{screen}"' in html
    assert html.count('class="card') == 3


def test_migration_and_rls_registration():
    migration = (
        ROOT / "migrations" / "versions" / "20260924_0018_assignment_exam_window.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "20260810_0017"' in migration
    for statement in (
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "CREATE POLICY tenant_isolation",
        "REVOKE DELETE",
    ):
        assert statement in migration
    verifier = (ROOT / "deploy" / "verify-v09-rls.py").read_text(encoding="utf-8")
    assert '"assignments",' in verifier
    assert '"assignment_attempts",' in verifier


def test_alembic_has_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["20260924_0018"]


def test_oidc_mode_keeps_teacher_routes_private_but_allows_token_attempts(
    client, monkeypatch
):
    from ai_examiner import main as main_module
    from ai_examiner.config import Settings
    from ai_examiner.services import authorization as authorization_module

    assignment, _ = _publish(client)
    code = assignment["join_code"]
    oidc_settings = Settings(
        app_env="test",
        auth_mode="oidc",
        oidc_issuer_url="http://localhost:9100",
        oidc_audience="api",
        oidc_client_id="client",
        oidc_redirect_uri="http://localhost/callback",
        auth_session_secret="test-session-secret",
        oidc_allow_insecure_http=True,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: oidc_settings)
    monkeypatch.setattr(authorization_module, "get_settings", lambda: oidc_settings)

    legacy = {"X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID}
    assert client.get("/api/assignments", headers=legacy).status_code == 401
    assert (
        client.get(
            f"/api/assignments/{assignment['id']}/dashboard", headers=legacy
        ).status_code
        == 401
    )
    # A principal header is ignored outside disabled-auth mode.
    spoofed = client.get(
        "/api/assignments",
        headers={
            **legacy,
            "X-AI-Examiner-Principal": "00000000-0000-0000-0000-000000000099",
        },
    )
    assert spoofed.status_code == 401

    assert client.get(f"/api/join/{code}").status_code == 200
    created = _join(client, code)
    assert created.status_code == 201
    attempt_id = created.json()["attempt"]["id"]
    with SessionLocal() as db:
        assert db.get(AssignmentAttempt, attempt_id).principal_id is None
    headers = _token_headers(created.json()["attempt_token"])
    assert client.get(f"/api/attempts/{attempt_id}", headers=headers).status_code == 200
    assert client.get(f"/api/attempts/{attempt_id}").status_code == 404


# --------------------------------------------------------------------------
# Launch hardening
# --------------------------------------------------------------------------


def test_publish_rejects_template_that_does_not_match_blueprint(client):
    project_id, blueprint = _prepare_blueprint(client)
    templates = client.get("/api/templates").json()
    planned = (blueprint["data"].get("template_plan") or {}).get("template_version_id")
    other = next(
        template["version_id"]
        for template in templates
        if template["version_id"] != planned and template["lifecycle_status"] == "published"
    )
    response = client.post(
        "/api/assignments",
        json={
            "project_id": project_id,
            "blueprint_id": blueprint["id"],
            "title": "错配",
            "session_settings": {"template_version_id": other},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "BLUEPRINT_TEMPLATE_MISMATCH"


def test_sliding_window_limiter_expires_events():
    from ai_examiner.services.rate_limit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter()
    assert limiter.check("k", limit=2, window_seconds=10, now=0) is None
    assert limiter.check("k", limit=2, window_seconds=10, now=1) is None
    assert limiter.check("k", limit=2, window_seconds=10, now=2) == pytest.approx(8)
    assert limiter.check("other", limit=2, window_seconds=10, now=2) is None
    assert limiter.check("k", limit=2, window_seconds=10, now=10.5) is None


def test_learner_answers_are_rate_limited_and_length_capped(client, monkeypatch):
    from ai_examiner.config import get_settings

    monkeypatch.setattr(get_settings(), "learner_answers_per_attempt_per_minute", 2)
    assignment, _ = _publish(
        client, session_settings={"question_limit": 5, "max_followups_per_question": 2}
    )
    created = _join(client, assignment["join_code"]).json()
    headers = _token_headers(created["attempt_token"])
    attempt_id = created["attempt"]["id"]
    client.post(f"/api/attempts/{attempt_id}/start", headers=headers)

    too_long = client.post(
        f"/api/attempts/{attempt_id}/answers",
        json={"answer": "长" * 4001},
        headers=headers,
    )
    assert too_long.status_code == 422
    assert too_long.json()["detail"]["code"] == "answer_too_long"

    statuses = [
        client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"answer": "不知道"},
            headers=headers,
        )
        for _ in range(3)
    ]
    assert [response.status_code for response in statuses] == [200, 200, 429]
    assert statuses[2].json()["detail"]["code"] == "rate_limited"
    assert int(statuses[2].headers["Retry-After"]) >= 1


def test_attempt_creation_and_lookup_are_rate_limited_per_client(client, monkeypatch):
    from ai_examiner.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "learner_attempts_per_ip_per_10_minutes", 2)
    monkeypatch.setattr(settings, "learner_join_lookups_per_ip_per_minute", 3)
    assignment, _ = _publish(client, max_attempts=10)
    code = assignment["join_code"]
    assert [_join(client, code).status_code for _ in range(3)] == [201, 201, 429]
    assert [client.get(f"/api/join/{code}").status_code for _ in range(4)] == [
        200, 200, 200, 429,
    ]

    # Behind a trusted proxy each real client gets its own bucket.
    monkeypatch.setattr(settings, "trust_proxy_forwarded_for", True)
    for address in ("203.0.113.7", "203.0.113.8"):
        response = _join(client, code, headers={"X-Forwarded-For": f"10.0.0.1, {address}"})
        assert response.status_code == 201, address


def test_rate_limits_can_be_disabled(client, monkeypatch):
    from ai_examiner.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "learner_rate_limit_enabled", False)
    monkeypatch.setattr(settings, "learner_join_lookups_per_ip_per_minute", 1)
    assignment, _ = _publish(client)
    assert all(
        client.get(f"/api/join/{assignment['join_code']}").status_code == 200
        for _ in range(3)
    )


def test_interviewer_never_calls_a_weak_answer_sufficient():
    from ai_examiner.agents.interviewer import (
        FOLLOWUP_OPENERS,
        MOVE_ON_ADEQUATE,
        MOVE_ON_WEAK,
        Interviewer,
    )

    interviewer = Interviewer()
    question = {"id": "Q1", "text": "第一题", "expected_points": ["要点"]}
    next_question = {"id": "Q2", "text": "第二题"}
    weak = interviewer.respond(
        decision={"action": "MOVE_ON"},
        analysis={"answered": True, "coverage": 0.3, "errors": []},
        question=question,
        next_question=next_question,
    )
    strong = interviewer.respond(
        decision={"action": "MOVE_ON"},
        analysis={"answered": True, "coverage": 0.9, "errors": []},
        question=question,
        next_question=next_question,
    )
    assert any(weak.startswith(option) for option in MOVE_ON_WEAK)
    assert any(strong.startswith(option) for option in MOVE_ON_ADEQUATE)
    assert "基本判断依据" not in weak
    assert weak.endswith("下一个问题：第二题")
    followups = {
        interviewer.respond(
            decision={"action": "ASK_FOLLOWUP", "followup": f"追问{index}"},
            analysis={},
            question=question,
            next_question=None,
        )
        for index in range(12)
    }
    assert len({text[: text.index("追问")] for text in followups}) > 1
    assert all(any(text.startswith(opener) for opener in FOLLOWUP_OPENERS) for text in followups)
    ended = interviewer.respond(
        decision={"action": "END"}, analysis={}, question=question, next_question=None
    )
    assert "答辩" not in ended


def test_workbench_can_publish_and_exam_page_is_resilient(client):
    html = client.get("/").text
    for element in (
        'id="publishAssignment"',
        'id="assignmentTitle"',
        'id="assignmentMode"',
        'id="assignmentList"',
        'id="assignmentDashboard"',
        'href="#assignmentPanel"',
    ):
        assert element in html
    script = client.get("/static/app.js").text
    assert "/api/assignments" in script
    assert "/dashboard" in script
    assert "results_released: true" in script
    exam = client.get("/static/exam.js").text
    assert "localStorage" in exam
    assert "AbortController" in exam
    assert "thinkingBubble" in exam
    assert "reconcile" in exam
