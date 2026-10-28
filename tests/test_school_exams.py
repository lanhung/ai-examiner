from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ai_examiner import school_api
from ai_examiner.config import get_settings
from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    Blueprint,
    Document,
    ExamPaper,
    Organization,
    OrganizationMembership,
    Principal,
    Project,
    PublishedExam,
    SchoolAttempt,
    TeacherExamPreview,
)
from ai_examiner.providers.factory import build_provider
from ai_examiner.teaching_cli import grant_teacher

ROOT = "/api/v1/school"


@pytest.fixture
def classroom(monkeypatch):
    with SessionLocal() as db:
        org = Organization(slug="teacher", display_name="Teacher workspace")
        other = Organization(slug="student", display_name="Student workspace")
        teacher, student, stranger = [Principal(
            issuer="test", subject=str(i), status="active"
        ) for i in range(3)]
        db.add_all([org, other, teacher, student, stranger])
        db.flush()
        db.add_all([OrganizationMembership(
            organization_id=o.id, principal_id=p.id, role="examiner", status="active"
        ) for o, p in [(org, teacher), (other, student), (other, stranger)]])
        project = Project(organization_id=org.id, name="Teacher paper")
        db.add(project)
        db.flush()
        document = Document(
            organization_id=org.id, project_id=project.id, filename="paper.docx",
            content_type="application/docx", content_text="Public synthetic material.",
        )
        db.add(document)
        db.flush()
        blueprint = Blueprint(
            organization_id=org.id, project_id=project.id, document_id=document.id,
            provider="qwen", model="qwen-plus", data={"questions": [
                {"id": "Q1", "text": "What is the limitation?", "type": "limitation",
                 "expected_points": ["Hold out test data", "Check distribution shift"],
                 "followups": ["How would you verify it?"], "source_excerpt": "Public synthetic material."},
                {"id": "Q2", "text": "How do you validate the result?", "type": "evidence",
                 "expected_points": ["Independent validation"], "source_excerpt": "Public synthetic material."},
            ]},
        )
        db.add(blueprint)
        db.commit()
        grant_teacher(db, teacher.id, org.id, active=True, operator="test-admin")
        ids = dict(teacher=teacher.id, student=student.id, stranger=stranger.id,
                   organization=org.id, student_org=other.id, blueprint=blueprint.id)
    monkeypatch.setattr(school_api, "profile_ready", lambda *args: True)
    calls = []

    def provider(*args, **kwargs):
        calls.append(1)
        return build_provider(get_settings(), "mock:heuristic-v2")

    monkeypatch.setattr(school_api, "governed_provider", provider)
    ids["calls"] = calls
    return ids


def headers(c, who):
    return {"X-AI-Examiner-Principal": c[who]}


def publish(client, c, **overrides):
    payload = dict(request_id=str(uuid4()), blueprint_id=c["blueprint"], title="Paper exam",
                   teacher_name="Teacher", question_count=2, profile="qwen:qwen-plus",
                   share_material_confirmed=True)
    payload.update(overrides)
    return client.post(ROOT + "/teacher/exams", headers=headers(c, "teacher"), json=payload)


def join(client, c, exam_id, who="student"):
    return client.post(f"{ROOT}/exams/{exam_id}/join", headers=headers(c, who),
                       json={"student_name": who, "student_number": "S-01"})


def answer(client, c, attempt, position=0, request_id=None):
    return client.post(f"{ROOT}/attempts/{attempt}/answers", headers=headers(c, "student"),
                       json={"position": position, "request_id": request_id or str(uuid4()),
                             "answer": "Hold out test data and check distribution shift with independent validation."})


def test_teacher_publishes_students_submit_teacher_reviews(client, classroom):
    c = classroom
    exam = publish(client, c).json()
    catalog = client.get(ROOT + "/exams", headers=headers(c, "student"))
    assert catalog.status_code == 200
    assert catalog.json()[0]["id"] == exam["id"]
    assert "expected_points" not in catalog.text
    detail = client.get(f"{ROOT}/exams/{exam['id']}", headers=headers(c, "student"))
    assert detail.json()["material_text"] == "Public synthetic material."
    assert "blueprint_id" not in detail.text
    attempt = join(client, c, exam["id"]).json()
    assert attempt["question"]["text"] == "What is the limitation?"
    assert "expected_points" not in str(attempt)
    assert join(client, c, exam["id"]).json()["id"] == attempt["id"]
    key = str(uuid4())
    first = answer(client, c, attempt["id"], request_id=key)
    assert first.status_code == 200, first.text
    assert first.json()["position"] == 1
    assert "evaluation" not in first.json()["answers"][0]
    assert answer(client, c, attempt["id"], request_id=key).status_code == 200
    assert len(c["calls"]) == 1
    second = answer(client, c, attempt["id"], position=1)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "completed"
    assert 0 <= second.json()["score"] <= 100
    grades = client.get(f"{ROOT}/teacher/exams/{exam['id']}/grades", headers=headers(c, "teacher"))
    assert grades.json()[0]["id"] == attempt["id"]
    assert grades.json()[0]["final_score"] == second.json()["score"]
    reviewed = client.post(f"{ROOT}/teacher/attempts/{attempt['id']}/review",
                          headers=headers(c, "teacher"), json={"score": 87, "note": "Human review", "version": 0})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["final_score"] == 87
    assert reviewed.json()["score"] == second.json()["score"]
    stale = client.post(f"{ROOT}/teacher/attempts/{attempt['id']}/review",
                        headers=headers(c, "teacher"), json={"score": 80, "note": "Stale", "version": 0})
    assert stale.status_code == 409
    result = client.get(f"{ROOT}/attempts/{attempt['id']}", headers=headers(c, "student"))
    assert result.json()["final_score"] == 87


def test_auth_student_cannot_elevate_publish_or_read_other_grades(client, classroom):
    c = classroom
    assert client.get(ROOT + "/exams").status_code == 401
    assert client.get(ROOT + "/me", headers=headers(c, "student")).json()["teacher"] is False
    exam = publish(client, c).json()
    attempt = join(client, c, exam["id"]).json()
    for path in [f"/teacher/exams/{exam['id']}/grades", f"/teacher/attempts/{attempt['id']}"]:
        assert client.get(ROOT + path, headers=headers(c, "student")).status_code == 403
    assert client.get(f"{ROOT}/attempts/{attempt['id']}", headers=headers(c, "stranger")).status_code == 404
    assert client.get(f"{ROOT}/attempts/{attempt['id']}", headers=headers(c, "teacher")).status_code == 404
    own = join(client, c, exam["id"], "stranger").json()
    assert own["id"] != attempt["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SchoolAttempt)) == 2
    assert join(client, c, exam["id"], "teacher").status_code == 409


def test_admission_never_requests_student_update_lock(client, classroom, monkeypatch):
    from sqlalchemy.orm import Session

    original = Session.refresh

    def refresh(db, instance, *args, **kwargs):
        if isinstance(instance, PublishedExam) and kwargs.get("with_for_update"):
            raise AssertionError("Student read permission cannot authorize FOR UPDATE")
        return original(db, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", refresh)
    c = classroom
    exam = publish(client, c, question_count=1).json()
    locks = []
    monkeypatch.setattr(school_api, "lock_exam_admission", lambda db, exam_id: locks.append(exam_id))
    assert join(client, c, exam["id"]).status_code == 200
    assert client.post(f"{ROOT}/teacher/exams/{exam['id']}/close", headers=headers(c, "teacher")).status_code == 200
    assert locks == [exam["id"], exam["id"]]


def test_close_winning_admission_lock_blocks_new_attempt(client, classroom, monkeypatch):
    from sqlalchemy import update

    c = classroom
    exam = publish(client, c, question_count=1).json()

    def close_before_lock_returns(db, exam_id):
        db.execute(update(PublishedExam).where(PublishedExam.id == exam_id).values(status="closed"))

    monkeypatch.setattr(school_api, "lock_exam_admission", close_before_lock_returns)
    assert join(client, c, exam["id"]).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SchoolAttempt)) == 0


def test_postgres_admission_lock_is_stable_and_transaction_scoped():
    from types import SimpleNamespace

    statements = []
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda statement, parameters: statements.append((str(statement), parameters)),
    )
    first, second = str(uuid4()), str(uuid4())
    for exam_id in (first, first, second):
        school_api.lock_exam_admission(db, exam_id)
    assert all(sql == "SELECT pg_advisory_xact_lock(:lock_key)" for sql, _ in statements)
    keys = [params["lock_key"] for _, params in statements]
    assert keys[0] == keys[1] and keys[0] != keys[2]
    assert all(-(2**63) <= key < 2**63 for key in keys)


def test_frozen_questions_publish_idempotency_close_and_scope(client, classroom):
    c = classroom
    key = str(uuid4())
    exam = publish(client, c, request_id=key).json()
    assert publish(client, c, request_id=key).json()["id"] == exam["id"]
    assert publish(client, c, request_id=key, title="Different").status_code == 409
    assert publish(client, c, share_material_confirmed=False).status_code == 422
    assert publish(client, c, profile="mock:heuristic-v2").status_code == 422
    assert publish(client, c, question_count=3).status_code == 422
    with SessionLocal() as db:
        blueprint = db.get(Blueprint, c["blueprint"])
        blueprint.data = {"questions": []}
        db.commit()
        assert len(db.get(ExamPaper, exam["id"]).questions) == 2
    started = join(client, c, exam["id"]).json()
    assert client.post(f"{ROOT}/teacher/exams/{exam['id']}/close", headers=headers(c, "teacher")).status_code == 200
    assert join(client, c, exam["id"], "stranger").status_code == 404
    assert join(client, c, exam["id"]).json()["id"] == started["id"]
    assert answer(client, c, started["id"]).status_code == 200
    assert client.get(f"{ROOT}/teacher/exams/{exam['id']}", headers=headers(c, "teacher")).status_code == 200
    with SessionLocal() as db:
        grant_teacher(db, c["stranger"], c["student_org"], active=True, operator="test-admin")
    assert client.get(f"{ROOT}/teacher/exams/{exam['id']}/grades", headers=headers(c, "stranger")).status_code == 404
    assert client.post(ROOT + "/teacher/exams", headers=headers(c, "stranger"), json={
        "request_id": str(uuid4()), "blueprint_id": c["blueprint"], "title": "Foreign",
        "teacher_name": "Stranger", "profile": "qwen:qwen-plus", "share_material_confirmed": True,
    }).status_code == 404


def test_failed_model_preserves_answer_blocks_rebilling_and_teacher_recovers(client, classroom, monkeypatch):
    c = classroom
    exam = publish(client, c, question_count=1).json()
    attempt = join(client, c, exam["id"]).json()
    def fail(*args, **kwargs):
        raise RuntimeError("upstream error with secret data")
    monkeypatch.setattr(school_api, "governed_provider", fail)
    key = str(uuid4())
    response = answer(client, c, attempt["id"], request_id=key)
    assert response.status_code == 503
    assert "secret data" not in response.text
    assert answer(client, c, attempt["id"], request_id=key).status_code == 409
    saved = client.get(f"{ROOT}/teacher/attempts/{attempt['id']}", headers=headers(c, "teacher"))
    assert saved.json()["status"] == "needs_review"
    assert saved.json()["pending_answer"].startswith("Hold out")
    fixed = client.post(f"{ROOT}/teacher/attempts/{attempt['id']}/review-answer",
                        headers=headers(c, "teacher"), json={"request_id": key, "score": 4, "note": "Verified the original answer"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["score"] == 80
    assert fixed.json()["status"] == "completed"
    assert fixed.json()["answers"][0]["evaluation"]["source"] == "teacher_review"


def test_revoke_teacher_and_extra_fields_are_rejected(client, classroom):
    c = classroom
    assert client.get(ROOT + "/me", headers=headers(c, "teacher")).json()["teacher"] is True
    with SessionLocal() as db:
        grant_teacher(db, c["teacher"], c["organization"], active=False, operator="test-admin")
    assert publish(client, c).status_code == 403
    assert client.get(ROOT + "/me", headers=headers(c, "teacher")).json()["teacher"] is False
    assert client.post(ROOT + "/teacher/exams", headers=headers(c, "student"), json={"role": "teacher"}).status_code in [403, 422]
    assert client.get(ROOT + "/exams?offset=-1", headers=headers(c, "student")).status_code == 422


def test_publish_does_not_copy_private_identifiers_to_catalog(client, classroom):
    c = classroom
    exam = publish(client, c).json()
    assert "organization_id" not in exam
    assert "teacher_id" not in exam
    assert "profile" not in exam
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PublishedExam)) == 1


def test_download_original_material_requires_publication_and_preserves_chinese_filename(client, classroom):
    from ai_examiner.services.storage import StorageService, document_object_key

    c = classroom
    with SessionLocal() as db:
        blueprint = db.get(Blueprint, c["blueprint"])
        document = db.get(Document, blueprint.document_id)
        document.filename = "答辩材料.docx"
        stored = StorageService(db, get_settings()).store_bytes(
            organization_id=c["organization"], project_id=document.project_id,
            resource_type="document", resource_id=document.id, purpose="source",
            object_key=document_object_key(c["organization"], document.project_id, document.id,
                                           filename="paper.docx", content_type="application/octet-stream"),
            data=b"synthetic office bytes", content_type="application/octet-stream",
        )
        document.storage_object_id = stored.id
        db.commit()
    exam = publish(client, c).json()
    path = f"{ROOT}/exams/{exam['id']}/material"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=headers(c, "student"))
    assert response.status_code == 200, response.text
    assert response.content == b"synthetic office bytes"
    assert "filename*=UTF-8''" in response.headers["Content-Disposition"]
    assert response.headers.get("Location") is None
    client.post(f"{ROOT}/teacher/exams/{exam['id']}/close", headers=headers(c, "teacher"))
    assert client.get(path, headers=headers(c, "stranger")).status_code == 404


def test_exam_source_cannot_be_deleted_before_files_are_preserved(client, classroom):
    c = classroom
    publish(client, c)
    with SessionLocal() as db:
        project_id = db.get(Blueprint, c["blueprint"]).project_id
        membership = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.principal_id == c["teacher"],
        ))
        membership.role = "owner"
        db.commit()
    response = client.delete(f"/api/projects/{project_id}", headers={
        **headers(c, "teacher"), "X-AI-Examiner-Organization": c["organization"],
    })
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.get(Project, project_id) is not None


def test_teacher_preview_uses_real_grading_path_but_never_enters_student_grades(client, classroom):
    c = classroom
    exam = publish(client, c).json()
    path = f"{ROOT}/teacher/exams/{exam['id']}/preview"
    assert client.get(path, headers=headers(c, "teacher")).json() is None
    detail = client.get(f"{ROOT}/exams/{exam['id']}", headers=headers(c, "teacher")).json()
    assert detail["is_owner"] is True
    assert client.get(f"{ROOT}/exams/{exam['id']}", headers=headers(c, "student")).json()["is_owner"] is False
    preview = client.post(path, headers=headers(c, "teacher")).json()
    assert preview["is_preview"] is True
    assert client.post(path, headers=headers(c, "teacher")).json()["id"] == preview["id"]
    answer_path = f"{ROOT}/teacher/previews/{preview['id']}/answers"
    payload = dict(request_id=str(uuid4()), position=0,
                   answer="Hold out test data and check distribution shift with independent validation.")
    first = client.post(answer_path, headers=headers(c, "teacher"), json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["position"] == 1
    assert "evaluation" in first.json()["answers"][0]
    assert client.post(answer_path, headers=headers(c, "teacher"), json=payload).status_code == 200
    assert len(c["calls"]) == 1
    changed = {**payload, "answer": "Changed answer"}
    assert client.post(answer_path, headers=headers(c, "teacher"), json=changed).status_code == 409
    completed = client.post(answer_path, headers=headers(c, "teacher"), json={
        **payload, "position": 1, "request_id": str(uuid4()),
    }).json()
    assert completed["status"] == "completed"
    assert 0 <= completed["final_score"] <= 100
    assert client.get(path, headers=headers(c, "teacher")).json()["final_score"] == completed["final_score"]
    assert client.get(f"{ROOT}/teacher/exams/{exam['id']}/grades", headers=headers(c, "teacher")).json() == []
    assert client.get(ROOT + "/exams", headers=headers(c, "teacher")).json()[0]["attempt_id"] is None
    assert join(client, c, exam["id"], "teacher").status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SchoolAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(TeacherExamPreview)) == 1
    student_attempt = join(client, c, exam["id"]).json()
    assert student_attempt["is_preview"] is False
    assert student_attempt["position"] == 0
    assert client.get(f"{ROOT}/teacher/exams/{exam['id']}/grades", headers=headers(c, "teacher")).json()[0]["id"] == student_attempt["id"]


def test_preview_owner_checks_and_separate_id_namespace(client, classroom):
    c = classroom
    exam = publish(client, c).json()
    path = f"{ROOT}/teacher/exams/{exam['id']}/preview"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=headers(c, "student")).status_code == 403
    preview = client.post(path, headers=headers(c, "teacher")).json()
    preview_path = f"{ROOT}/teacher/previews/{preview['id']}"
    assert client.get(preview_path, headers=headers(c, "student")).status_code == 403
    for route in ["/attempts/", "/teacher/attempts/"]:
        assert client.get(ROOT + route + preview["id"], headers=headers(c, "teacher")).status_code == 404
    with SessionLocal() as db:
        grant_teacher(db, c["stranger"], c["student_org"], active=True, operator="test-admin")
    assert client.post(path, headers=headers(c, "stranger")).status_code == 404
    assert client.get(preview_path, headers=headers(c, "stranger")).status_code == 404
    with SessionLocal() as db:
        grant_teacher(db, c["teacher"], c["organization"], active=False, operator="test-admin")
    assert client.get(preview_path, headers=headers(c, "teacher")).status_code == 403
    assert client.post(preview_path + "/answers", headers=headers(c, "teacher"), json={
        "request_id": str(uuid4()), "position": 0, "answer": "not allowed",
    }).status_code == 403


def test_preview_failure_keeps_answer_and_manual_recovery_stays_isolated(client, classroom, monkeypatch):
    c = classroom
    exam = publish(client, c, question_count=1).json()
    preview = client.post(f"{ROOT}/teacher/exams/{exam['id']}/preview", headers=headers(c, "teacher")).json()
    path = f"{ROOT}/teacher/previews/{preview['id']}"
    def fail(*args, **kwargs):
        raise RuntimeError("sensitive upstream error")
    monkeypatch.setattr(school_api, "governed_provider", fail)
    payload = dict(request_id=str(uuid4()), position=0, answer="Synthetic preserved answer")
    response = client.post(path + "/answers", headers=headers(c, "teacher"), json=payload)
    assert response.status_code == 503
    assert "sensitive" not in response.text
    saved = client.get(path, headers=headers(c, "teacher")).json()
    assert saved["status"] == "needs_review"
    assert saved["pending_answer"] == payload["answer"]
    assert client.post(path + "/answers", headers=headers(c, "teacher"), json=payload).status_code == 409
    fixed = client.post(path + "/review-answer", headers=headers(c, "teacher"), json={
        "request_id": payload["request_id"], "score": 4, "note": "Synthetic manual recovery",
    })
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["status"] == "completed"
    assert fixed.json()["is_preview"] is True
    assert fixed.json()["final_score"] == 80
    assert fixed.json()["answers"][0]["evaluation"]["source"] == "teacher_review"
    assert client.get(f"{ROOT}/teacher/exams/{exam['id']}/grades", headers=headers(c, "teacher")).json() == []


@pytest.mark.parametrize("preview", [False, True])
def test_http_quota_failure_does_not_leave_answer_grading_forever(client, classroom, monkeypatch, preview):
    from fastapi import HTTPException

    c = classroom
    exam = publish(client, c, question_count=1).json()
    if preview:
        attempt = client.post(f"{ROOT}/teacher/exams/{exam['id']}/preview", headers=headers(c, "teacher")).json()
        path, actor = f"{ROOT}/teacher/previews/{attempt['id']}", "teacher"
    else:
        attempt = join(client, c, exam["id"]).json()
        path, actor = f"{ROOT}/attempts/{attempt['id']}", "student"
    def deny(*args, **kwargs):
        raise HTTPException(429, "Budget reached")
    monkeypatch.setattr(school_api, "assert_budget", deny)
    response = client.post(path + "/answers", headers=headers(c, actor), json={
        "request_id": str(uuid4()), "position": 0, "answer": "Preserved",
    })
    assert response.status_code == 429
    assert client.get(path, headers=headers(c, actor)).json()["status"] == "needs_review"


def preview_migration():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "migrations/versions/20261015_0019_teacher_exam_previews.py"
    spec = importlib.util.spec_from_file_location("teacher_preview_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_migration_handles_legacy_and_metadata_bootstrap():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from ai_examiner.db import engine

    migration = preview_migration()
    with engine.begin() as connection:
        TeacherExamPreview.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # Legacy initial migration may already create the table.
        assert inspect(connection).has_table("teacher_exam_previews")
        columns = {c["name"] for c in inspect(connection).get_columns("teacher_exam_previews")}
        assert columns == set(TeacherExamPreview.__table__.columns.keys())


def test_preview_migration_refuses_to_discard_existing_records(client, classroom):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ai_examiner.db import engine

    c = classroom
    exam = publish(client, c).json()
    preview = client.post(f"{ROOT}/teacher/exams/{exam['id']}/preview", headers=headers(c, "teacher")).json()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Preview records exist"):
                preview_migration().downgrade()
    with SessionLocal() as db:
        assert db.get(TeacherExamPreview, preview["id"]) is not None
