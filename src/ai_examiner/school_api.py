"""Published exams are shared; source workspaces and answer keys are not."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agents.analyzer import AnswerAnalyzer
from .agents.base import AgentContext
from .agents.evaluator import Evaluator
from .config import get_settings
from .db import get_db
from .model_catalog import estimate_cost
from .models import (
    Blueprint,
    Document,
    ExamPaper,
    Organization,
    OrganizationMembership,
    Principal,
    Project,
    PublishedExam,
    SchoolAttempt,
    StoredObject,
    TeacherExamPreview,
    TeachingGrant,
    UsageEvent,
    utcnow,
)
from .providers.factory import parse_profile, profile_ready
from .services.audit import append_audit_event
from .services.authorization import effective_capabilities, require_authenticated_principal
from .services.budget import assert_budget
from .services.model_governance import governed_provider
from .services.prompts import prompt_contents
from .services.storage import StorageError, StorageService
from .services.tenancy import set_tenant_context

Db = Annotated[Session, Depends(get_db)]
User = Annotated[Principal, Depends(require_authenticated_principal)]


class SchoolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PublishExam(SchoolInput):
    request_id: UUID
    blueprint_id: UUID
    title: str = Field(min_length=2, max_length=200)
    teacher_name: str = Field(min_length=1, max_length=100)
    instructions: str = Field(default="", max_length=3000)
    profile: str = Field(min_length=3, max_length=200)
    question_count: int = Field(default=6, ge=1, le=20)
    share_material_confirmed: bool


class JoinExam(SchoolInput):
    student_name: str = Field(min_length=1, max_length=100)
    student_number: str = Field(default="", max_length=100)


class ExamAnswer(SchoolInput):
    request_id: UUID
    position: int = Field(ge=0, le=19)
    answer: str = Field(min_length=1, max_length=12000)


class ReviewGrade(SchoolInput):
    score: float = Field(ge=0, le=100, allow_inf_nan=False)
    note: str = Field(min_length=2, max_length=2000)
    version: int = Field(ge=0)


class ReviewAnswer(SchoolInput):
    request_id: UUID
    score: float = Field(ge=0, le=5, allow_inf_nan=False)
    note: str = Field(min_length=2, max_length=2000)


def bind_user(db: Session, user: Principal) -> None:
    set_tenant_context(db, organization_id=None, principal_id=user.id)


def teacher_scope(db: Session, user: Principal) -> TeachingGrant:
    bind_user(db, user)
    grant = db.get(TeachingGrant, user.id)
    if not grant or not grant.active:
        raise HTTPException(403, "教师身份尚未开通，请联系管理员")
    set_tenant_context(db, organization_id=grant.organization_id, principal_id=user.id)
    org = db.get(Organization, grant.organization_id)
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == grant.organization_id,
        OrganizationMembership.principal_id == user.id,
        OrganizationMembership.status == "active",
    ))
    if not org or org.status != "active" or not membership or (
        "blueprint.create" not in effective_capabilities(membership.role)
    ):
        raise HTTPException(403, "教师工作空间不可用，请联系管理员")
    return grant


def audit(db: Session, user: Principal, organization_id: str, action: str, resource_id: str):
    append_audit_event(
        db, organization_id=organization_id, actor_type="principal", actor_id=user.id,
        authentication_method="authenticated_principal", action=action,
        resource_type="school_exam", resource_id=resource_id, outcome="succeeded",
        reason_code="authorized", request_id=str(uuid4()), trace_id=uuid4().hex,
    )


def exam_payload(exam: PublishedExam, *, material=False) -> dict:
    result = {
        "id": exam.id, "title": exam.title, "instructions": exam.instructions,
        "teacher_name": exam.teacher_name, "material_name": exam.material_name,
        "question_count": exam.question_count, "status": exam.status,
        "created_at": exam.created_at.isoformat(),
    }
    if material:
        result["material_text"] = exam.material_text
    return result


def owned_exam(db: Session, user: Principal, exam_id: str) -> PublishedExam:
    grant = teacher_scope(db, user)
    exam = db.scalar(select(PublishedExam).where(
        PublishedExam.id == exam_id, PublishedExam.teacher_id == user.id,
        PublishedExam.organization_id == grant.organization_id,
    ))
    if not exam:
        raise HTTPException(404, "考试不存在")
    return exam


def available_exam(db: Session, user: Principal, exam_id: str) -> PublishedExam:
    bind_user(db, user)
    exam = db.get(PublishedExam, exam_id)
    attempt = db.scalar(select(SchoolAttempt.id).where(
        SchoolAttempt.exam_id == exam_id, SchoolAttempt.student_id == user.id,
    ))
    if not exam or (exam.status != "published" and not attempt and exam.teacher_id != user.id):
        raise HTTPException(404, "考试不存在或未开放")
    # A validated publication, never a client-supplied tenant, authorizes this scope.
    set_tenant_context(db, organization_id=exam.organization_id, principal_id=user.id)
    org = db.get(Organization, exam.organization_id)
    if not org or org.status != "active":
        raise HTTPException(404, "考试暂不可用")
    return exam


def own_attempt(db: Session, user: Principal, attempt_id: str) -> SchoolAttempt:
    bind_user(db, user)
    attempt = db.scalar(select(SchoolAttempt).where(
        SchoolAttempt.id == attempt_id, SchoolAttempt.student_id == user.id,
    ))
    if not attempt:
        raise HTTPException(404, "答卷不存在")
    available_exam(db, user, attempt.exam_id)
    return attempt


def attempt_payload(db: Session, attempt: SchoolAttempt | TeacherExamPreview, *, teacher=False) -> dict:
    exam = db.get(PublishedExam, attempt.exam_id)
    paper = db.get(ExamPaper, attempt.exam_id)
    position = len(attempt.answers)
    finished = attempt.status == "completed"
    preview = isinstance(attempt, TeacherExamPreview)
    result = {
        "id": attempt.id, "exam_id": exam.id, "title": exam.title,
        "status": attempt.status, "position": position, "question_count": exam.question_count,
        "is_preview": preview,
        "student_name": "教师试答" if preview else attempt.student_name,
        "student_number": "" if preview else attempt.student_number,
        "score": attempt.score if finished else None,
        "reviewed_score": attempt.reviewed_score if finished else None,
        "final_score": (
            attempt.reviewed_score if attempt.reviewed_score is not None else attempt.score
        ) if finished else None,
        "review_note": attempt.review_note, "review_version": attempt.review_version,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "question": None,
        "answers": attempt.answers if teacher or preview or finished else [
            {"position": a["position"], "question": a["question"], "answer": a["answer"]}
            for a in attempt.answers
        ],
    }
    if not finished and position < len(paper.questions):
        result["question"] = {"text": paper.questions[position]["text"], "position": position}
    if (teacher or preview) and attempt.pending:
        result["pending_answer"] = attempt.pending["answer"]
        result["pending_request_id"] = attempt.pending["request_id"]
    return result


def school_me(user: User, db: Db):
    bind_user(db, user)
    try:
        grant = teacher_scope(db, user)
        teacher = True
        organization_id = grant.organization_id
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        teacher, organization_id = False, None
    return {"principal_id": user.id, "teacher": teacher, "teacher_organization_id": organization_id}


def list_exams(user: User, db: Db, offset: int = 0):
    if offset < 0:
        raise HTTPException(422, "无效页码")
    bind_user(db, user)
    attempts = {a.exam_id: a for a in db.scalars(select(SchoolAttempt).where(
        SchoolAttempt.student_id == user.id,
    ))}
    exams = db.scalars(select(PublishedExam).where(or_(
        PublishedExam.status == "published", PublishedExam.id.in_(attempts),
    )).order_by(PublishedExam.created_at.desc(), PublishedExam.id).offset(offset).limit(50))
    return [{**exam_payload(e), "attempt_id": attempts[e.id].id if e.id in attempts else None,
             "attempt_status": attempts[e.id].status if e.id in attempts else None} for e in exams]


def get_exam(exam_id: UUID, user: User, db: Db):
    exam = available_exam(db, user, str(exam_id))
    return {**exam_payload(exam, material=True), "is_owner": exam.teacher_id == user.id}


def exam_material(exam_id: UUID, user: User, db: Db):
    exam = available_exam(db, user, str(exam_id))
    paper = db.get(ExamPaper, exam.id)
    document = db.scalar(select(Document).where(
        Document.id == paper.document_id, Document.organization_id == exam.organization_id,
    ))
    if not document:
        raise HTTPException(404, "考试材料不可用")
    if document.storage_object_id:
        stored = db.get(StoredObject, document.storage_object_id)
        if not stored or stored.organization_id != exam.organization_id or stored.status != "active":
            raise HTTPException(404, "考试材料不可用")
        try:
            content = StorageService(db, get_settings()).read_bytes(stored)
        except StorageError:
            raise HTTPException(503, "材料存储暂不可用，请稍后重试") from None
        # Keep downloads on the authenticated origin; never send bearer tokens to S3.
        return Response(content, media_type=document.content_type, headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(document.filename, safe=""),
            "Cache-Control": "private, no-store",
        })
    if not document.storage_path or not Path(document.storage_path).is_file():
        raise HTTPException(404, "考试原文件不可用")
    return FileResponse(document.storage_path, media_type=document.content_type, filename=document.filename)


def teacher_exams(user: User, db: Db, offset: int = 0):
    if offset < 0:
        raise HTTPException(422, "无效页码")
    grant = teacher_scope(db, user)
    return [exam_payload(e) for e in db.scalars(select(PublishedExam).where(
        PublishedExam.teacher_id == user.id, PublishedExam.organization_id == grant.organization_id,
    ).order_by(PublishedExam.created_at.desc(), PublishedExam.id).offset(offset).limit(50))]


def teacher_exam(exam_id: UUID, user: User, db: Db):
    return {**exam_payload(owned_exam(db, user, str(exam_id)), material=True), "is_owner": True}


def own_preview(db: Session, user: Principal, preview_id: str) -> TeacherExamPreview:
    grant = teacher_scope(db, user)
    preview = db.scalar(select(TeacherExamPreview).where(
        TeacherExamPreview.id == preview_id, TeacherExamPreview.teacher_id == user.id,
        TeacherExamPreview.organization_id == grant.organization_id,
    ))
    if not preview:
        raise HTTPException(404, "试答记录不存在")
    owned_exam(db, user, preview.exam_id)
    return preview


def exam_preview(exam_id: UUID, user: User, db: Db):
    exam = owned_exam(db, user, str(exam_id))
    preview = db.scalar(select(TeacherExamPreview).where(
        TeacherExamPreview.exam_id == exam.id, TeacherExamPreview.teacher_id == user.id,
    ))
    return attempt_payload(db, preview) if preview else None


def start_preview(exam_id: UUID, user: User, db: Db):
    exam = owned_exam(db, user, str(exam_id))
    existing = exam_preview(exam_id, user, db)
    if existing:
        return existing
    preview = TeacherExamPreview(
        exam_id=exam.id, organization_id=exam.organization_id, teacher_id=user.id,
    )
    db.add(preview)
    try:
        db.flush()
        audit(db, user, exam.organization_id, "school.preview.start", preview.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = exam_preview(exam_id, user, db)
        if existing:
            return existing
        raise HTTPException(409, "试答创建冲突，请刷新") from None
    return attempt_payload(db, preview)


def get_preview(preview_id: UUID, user: User, db: Db):
    return attempt_payload(db, own_preview(db, user, str(preview_id)))


def submit_preview(preview_id: UUID, payload: ExamAnswer, user: User, db: Db):
    return score_answer(own_preview(db, user, str(preview_id)), payload, user, db)


def publish_exam(payload: PublishExam, user: User, db: Db):
    grant = teacher_scope(db, user)
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(PublishedExam).where(
        PublishedExam.teacher_id == user.id, PublishedExam.publish_key == str(payload.request_id),
    ))
    if existing:
        if existing.request_digest != digest:
            raise HTTPException(409, "发布请求编号已被另一份配置使用")
        return exam_payload(existing)
    if not payload.share_material_confirmed:
        raise HTTPException(422, "发布前必须确认材料可供所有已登录学生查看")
    blueprint = db.scalar(select(Blueprint).where(
        Blueprint.id == str(payload.blueprint_id), Blueprint.organization_id == grant.organization_id,
    ))
    if not blueprint:
        raise HTTPException(404, "蓝图不存在")
    document = db.scalar(select(Document).where(
        Document.id == blueprint.document_id, Document.organization_id == grant.organization_id,
    ))
    project = db.get(Project, blueprint.project_id)
    if not document or not project or project.organization_id != grant.organization_id:
        raise HTTPException(404, "材料不存在")
    if project.data_classification == "restricted":
        raise HTTPException(403, "受限材料不得公开发布为考试")
    questions = copy.deepcopy(blueprint.data.get("questions", [])[:payload.question_count])
    if len(questions) != payload.question_count or any(
        not q.get("text") or not q.get("expected_points") for q in questions
    ):
        raise HTTPException(422, "蓝图题目或评分要点不足，请先检查蓝图")
    try:
        provider, _ = parse_profile(payload.profile)
        ready = provider != "mock" and profile_ready(get_settings(), payload.profile)
    except ValueError:
        ready = False
    if not ready:
        raise HTTPException(422, "请选择已配置的真实评分模型")
    exam = PublishedExam(
        teacher_id=user.id, organization_id=grant.organization_id,
        publish_key=str(payload.request_id), request_digest=digest,
        title=payload.title, instructions=payload.instructions, teacher_name=payload.teacher_name,
        material_name=document.filename, material_text=document.content_text,
        question_count=len(questions),
    )
    db.add(exam)
    try:
        db.flush()
        db.add(ExamPaper(exam_id=exam.id, organization_id=grant.organization_id,
                         project_id=project.id, blueprint_id=blueprint.id,
                         document_id=document.id, questions=questions, profile=payload.profile))
        audit(db, user, grant.organization_id, "school.exam.publish", exam.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(PublishedExam).where(
            PublishedExam.teacher_id == user.id,
            PublishedExam.publish_key == str(payload.request_id),
        ))
        if existing and existing.request_digest == digest:
            return exam_payload(existing)
        raise HTTPException(409, "发布冲突，请刷新考试列表") from None
    return exam_payload(exam)


def close_exam(exam_id: UUID, user: User, db: Db):
    exam = owned_exam(db, user, str(exam_id))
    exam.status = "closed"
    audit(db, user, exam.organization_id, "school.exam.close", exam.id)
    db.commit()
    return exam_payload(exam)


def join_exam(exam_id: UUID, payload: JoinExam, user: User, db: Db):
    exam = available_exam(db, user, str(exam_id))
    if exam.teacher_id == user.id:
        raise HTTPException(409, "教师不能参加自己发布的考试")
    existing = db.scalar(select(SchoolAttempt).where(
        SchoolAttempt.exam_id == exam.id, SchoolAttempt.student_id == user.id,
    ))
    if existing:
        return attempt_payload(db, existing)
    db.refresh(exam, with_for_update=True)
    if exam.status != "published":
        raise HTTPException(409, "考试已停止接收新答卷")
    attempt = SchoolAttempt(
        exam_id=exam.id, organization_id=exam.organization_id, teacher_id=exam.teacher_id,
        student_id=user.id, student_name=payload.student_name, student_number=payload.student_number,
    )
    db.add(attempt)
    try:
        db.flush()
        audit(db, user, exam.organization_id, "school.attempt.start", attempt.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(SchoolAttempt).where(
            SchoolAttempt.exam_id == exam.id, SchoolAttempt.student_id == user.id,
        ))
        if existing:
            return attempt_payload(db, existing)
        raise HTTPException(409, "答卷创建冲突，请刷新考试") from None
    return attempt_payload(db, attempt)


def get_attempt(attempt_id: UUID, user: User, db: Db):
    return attempt_payload(db, own_attempt(db, user, str(attempt_id)))


def submit_answer(attempt_id: UUID, payload: ExamAnswer, user: User, db: Db):
    return score_answer(own_attempt(db, user, str(attempt_id)), payload, user, db)


def score_answer(attempt: SchoolAttempt | TeacherExamPreview, payload: ExamAnswer,
                 user: Principal, db: Session):
    model = type(attempt)
    is_preview = isinstance(attempt, TeacherExamPreview)
    previous = next((a for a in attempt.answers if a["request_id"] == str(payload.request_id)), None)
    if previous:
        if previous["answer"] != payload.answer or previous["position"] != payload.position:
            raise HTTPException(409, "同一提交编号不能更改答案")
        return attempt_payload(db, attempt)
    if attempt.status != "active" or payload.position != len(attempt.answers):
        raise HTTPException(409, "答卷状态已变化，请刷新；评分中请勿重复提交")
    paper = db.get(ExamPaper, attempt.exam_id)
    question = copy.deepcopy(paper.questions[payload.position])
    pending = payload.model_dump(mode="json")
    # Commit the reservation before network IO. A lost response must not bill twice.
    reserved_at = utcnow()
    result = db.execute(update(model).where(
        model.id == attempt.id, model.status == "active",
        model.updated_at == attempt.updated_at,
    ).values(status="grading", pending=pending, updated_at=reserved_at))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "已有提交正在处理，请刷新答卷")
    db.commit()
    settings = get_settings()
    try:
        assert_budget(db, settings, paper.project_id)
        provider = governed_provider(db, settings, paper.profile, project_id=paper.project_id)
        usage = []
        analyzer = AnswerAnalyzer(AgentContext(
            provider=provider, record_usage=lambda agent, value: usage.append((agent, value)),
            prompt_overrides=prompt_contents(db),
        ))
        # Release read transactions before a provider's independent quota transaction.
        db.commit()
        analysis = analyzer.analyze(question=question, answer=payload.answer, history=[])
        evaluation = Evaluator().evaluate(question=question, answer=payload.answer, analysis=analysis)
        db.refresh(attempt)
        if attempt.status != "grading" or attempt.pending != pending:
            raise HTTPException(409, "答卷已由教师处理，请刷新")
        answers = [*attempt.answers, {
            **pending, "question": question["text"], "evaluation": evaluation,
        }]
        completed = len(answers) == len(paper.questions)
        updated = db.execute(update(model).where(
            model.id == attempt.id, model.status == "grading",
            model.updated_at == attempt.updated_at,
        ).values(answers=answers, pending=None, status="completed" if completed else "active",
                 updated_at=utcnow(), completed_at=utcnow() if completed else None,
                 score=round(sum(a["evaluation"]["score"] for a in answers) / len(answers) * 20, 2)
                 if completed else None))
        if updated.rowcount != 1:
            raise HTTPException(409, "答卷已由教师处理，请刷新")
        for agent, item in usage:
            db.add(UsageEvent(
                project_id=paper.project_id, agent=agent, provider=item.provider, model=item.model,
                input_tokens=item.input_tokens, output_tokens=item.output_tokens,
                estimated_cost_usd=estimate_cost(item.provider, item.model, item.input_tokens, item.output_tokens),
                latency_ms=item.latency_ms, retry_count=item.retry_count,
                json_repair_used=item.json_repair_used,
            ))
        action = "school.preview.answer.submit" if is_preview else "school.answer.submit"
        audit(db, user, attempt.organization_id, action, attempt.id)
        db.commit()
    except HTTPException:
        retain_failed_answer(db, model, attempt.id, reserved_at)
        raise
    except Exception:
        retain_failed_answer(db, model, attempt.id, reserved_at)
        raise HTTPException(503, "答案已保留，自动评分未完成；请联系教师复核，不要重复提交") from None
    return attempt_payload(db, attempt)


def retain_failed_answer(db: Session, model, attempt_id: str, reserved_at):
    db.rollback()
    # Do not overwrite a newer submission after a concurrent teacher recovery.
    db.execute(update(model).where(
        model.id == attempt_id, model.status == "grading", model.updated_at == reserved_at,
    ).values(status="needs_review", updated_at=utcnow()))
    db.commit()


def grades(exam_id: UUID, user: User, db: Db, offset: int = 0):
    if offset < 0:
        raise HTTPException(422, "无效页码")
    exam = owned_exam(db, user, str(exam_id))
    return [{
        "id": a.id, "student_name": a.student_name, "student_number": a.student_number,
        "status": a.status, "answered": len(a.answers), "score": a.score,
        "final_score": a.reviewed_score if a.reviewed_score is not None else a.score,
        "reviewed": a.reviewed_score is not None,
    } for a in db.scalars(select(SchoolAttempt).where(
        SchoolAttempt.exam_id == exam.id, SchoolAttempt.teacher_id == user.id,
    ).order_by(SchoolAttempt.created_at, SchoolAttempt.id).offset(offset).limit(50))]


def teacher_attempt(attempt_id: UUID, user: User, db: Db):
    teacher_scope(db, user)
    attempt = db.scalar(select(SchoolAttempt).where(
        SchoolAttempt.id == str(attempt_id), SchoolAttempt.teacher_id == user.id,
    ))
    if not attempt:
        raise HTTPException(404, "答卷不存在")
    owned_exam(db, user, attempt.exam_id)
    return attempt_payload(db, attempt, teacher=True)


def review_grade(attempt_id: UUID, payload: ReviewGrade, user: User, db: Db):
    teacher_attempt(attempt_id, user, db)
    attempt = db.get(SchoolAttempt, str(attempt_id))
    if attempt.status != "completed":
        raise HTTPException(409, "请等待答卷完成后复核总分")
    updated = db.execute(update(SchoolAttempt).where(
        SchoolAttempt.id == attempt.id, SchoolAttempt.review_version == payload.version,
    ).values(reviewed_score=payload.score, review_note=payload.note,
             review_version=payload.version + 1, updated_at=utcnow()))
    if updated.rowcount != 1:
        raise HTTPException(409, "成绩已被修改，请刷新后再复核")
    audit(db, user, attempt.organization_id, "school.grade.review", attempt.id)
    db.commit()
    db.refresh(attempt)
    return attempt_payload(db, attempt, teacher=True)


def review_answer(attempt_id: UUID, payload: ReviewAnswer, user: User, db: Db):
    teacher_attempt(attempt_id, user, db)
    attempt = db.get(SchoolAttempt, str(attempt_id))
    return recover_answer(attempt, payload, user, db)


def review_preview_answer(preview_id: UUID, payload: ReviewAnswer, user: User, db: Db):
    return recover_answer(own_preview(db, user, str(preview_id)), payload, user, db)


def recover_answer(attempt: SchoolAttempt | TeacherExamPreview, payload: ReviewAnswer,
                   user: Principal, db: Session):
    model = type(attempt)
    updated_at = attempt.updated_at
    when = updated_at.replace(tzinfo=UTC) if updated_at.tzinfo is None else updated_at
    abandoned = attempt.status == "grading" and when < utcnow() - timedelta(minutes=30)
    if (attempt.status != "needs_review" and not abandoned) or not attempt.pending or (
        attempt.pending["request_id"] != str(payload.request_id)
    ):
        raise HTTPException(409, "只能处理待复核或超过 30 分钟未返回的原始答案")
    paper = db.get(ExamPaper, attempt.exam_id)
    position = len(attempt.answers)
    answers = [*attempt.answers, {
        **attempt.pending, "question": paper.questions[position]["text"],
        "evaluation": {"score": payload.score, "reasoning": payload.note,
                       "missing_points": [], "source": "teacher_review"},
    }]
    completed = len(answers) == len(paper.questions)
    updated = db.execute(update(model).where(
        model.id == attempt.id, model.status == attempt.status,
        model.updated_at == updated_at,
    ).values(answers=answers, pending=None, status="completed" if completed else "active",
             updated_at=utcnow(), completed_at=utcnow() if completed else None,
             score=round(sum(a["evaluation"]["score"] for a in answers) / len(answers) * 20, 2)
             if completed else None))
    if updated.rowcount != 1:
        raise HTTPException(409, "答卷已变化，请刷新后重试")
    action = "school.preview.answer.review" if isinstance(attempt, TeacherExamPreview) else "school.answer.review"
    audit(db, user, attempt.organization_id, action, attempt.id)
    db.commit()
    db.refresh(attempt)
    return attempt_payload(db, attempt, teacher=True)


ROUTES = (
    ("GET", "/api/v1/school/me", school_me),
    ("GET", "/api/v1/school/exams", list_exams),
    ("GET", "/api/v1/school/exams/{exam_id}", get_exam),
    ("GET", "/api/v1/school/exams/{exam_id}/material", exam_material),
    ("POST", "/api/v1/school/exams/{exam_id}/join", join_exam),
    ("GET", "/api/v1/school/attempts/{attempt_id}", get_attempt),
    ("POST", "/api/v1/school/attempts/{attempt_id}/answers", submit_answer),
    ("GET", "/api/v1/school/teacher/exams", teacher_exams),
    ("POST", "/api/v1/school/teacher/exams", publish_exam),
    ("GET", "/api/v1/school/teacher/exams/{exam_id}", teacher_exam),
    ("GET", "/api/v1/school/teacher/exams/{exam_id}/preview", exam_preview),
    ("POST", "/api/v1/school/teacher/exams/{exam_id}/preview", start_preview),
    ("GET", "/api/v1/school/teacher/previews/{preview_id}", get_preview),
    ("POST", "/api/v1/school/teacher/previews/{preview_id}/answers", submit_preview),
    ("POST", "/api/v1/school/teacher/previews/{preview_id}/review-answer", review_preview_answer),
    ("POST", "/api/v1/school/teacher/exams/{exam_id}/close", close_exam),
    ("GET", "/api/v1/school/teacher/exams/{exam_id}/grades", grades),
    ("GET", "/api/v1/school/teacher/attempts/{attempt_id}", teacher_attempt),
    ("POST", "/api/v1/school/teacher/attempts/{attempt_id}/review", review_grade),
    ("POST", "/api/v1/school/teacher/attempts/{attempt_id}/review-answer", review_answer),
)


def register_routes(app: FastAPI):
    from .services.authorization import ROUTE_POLICIES, RoutePolicy

    for method, path, endpoint in ROUTES:
        ROUTE_POLICIES[(method, path)] = RoutePolicy(
            "required", None, "school_owner_or_publication", "read_sensitive" if method == "GET" else "administrative",
        )
        app.add_api_route(path, endpoint, methods=[method], tags=["school"])
