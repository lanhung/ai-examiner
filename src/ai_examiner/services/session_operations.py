"""Durable, tenant-scoped receipts for a single personal conversation turn."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..agents.orchestrator import ExamOrchestrator
from ..config import get_settings
from ..models import BackgroundJob, Blueprint, ExamSession, Turn, UsageEvent, utcnow
from .job_control import (
    TERMINAL_JOB_STATUSES,
    JobLeaseLost,
    authorize_job_execution,
    reconcile_blueprint_job,
)
from .model_governance import ModelGovernanceError, governed_provider
from .tenancy import current_tenant_context


class SessionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    operation: Literal["start", "answer"]
    expected_turn_count: int = Field(ge=0)
    answer: str = Field(default="", max_length=20000)


def fence_job(db: Session, job: BackgroundJob) -> None:
    """Fence the result and its receipt in the same transaction as the new turns."""
    authorize_job_execution(db, get_settings(), job)
    changed = db.execute(update(BackgroundJob).where(
        BackgroundJob.id == job.id, BackgroundJob.organization_id == job.organization_id,
        BackgroundJob.status == "running", BackgroundJob.lease_token == job.lease_token,
        BackgroundJob.lease_expires_at > utcnow(), BackgroundJob.cancel_requested_at.is_(None),
    ).values(updated_at=utcnow()).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise JobLeaseLost("Operation lease expired before result commit")


def operation_receipt(db: Session, session: ExamSession, request_id: str) -> BackgroundJob | None:
    job = db.scalar(select(BackgroundJob).where(
        BackgroundJob.organization_id == session.organization_id,
        BackgroundJob.kind == "session_operation",
        BackgroundJob.idempotency_key == f"{session.id}:{request_id}",
        BackgroundJob.actor_principal_id == current_tenant_context(db).principal_id,
    ))
    if job:
        reconcile_blueprint_job(db, job)
        marker = session.config.get("operation_receipt") or {}
        if job.status in TERMINAL_JOB_STATUSES and marker.get("request_id") == request_id and session.state == "OPERATION_QUEUED":
            db.execute(update(ExamSession).where(
                ExamSession.id == session.id, ExamSession.state == "OPERATION_QUEUED",
            ).values(state=marker["previous_state"]))
            db.commit()
            db.refresh(session)
    return job


def queue_session_operation(db: Session, session: ExamSession, payload: SessionOperation, tasks: BackgroundTasks) -> dict:
    from .jobs import JobQueueUnavailable, dispatch_job_by_id, enqueue_job, serialize_job
    request_id = str(payload.request_id)
    data = {**payload.model_dump(mode="json"), "session_id": session.id}
    existing = operation_receipt(db, session, request_id)
    if existing:
        if existing.payload != data:
            raise HTTPException(409, "同一请求编号不能更改回答")
        return serialize_job(existing, include_internal=False)
    if payload.operation == "answer" and not payload.answer.strip():
        raise HTTPException(422, "回答不能为空")
    if payload.operation == "start" and (payload.answer or payload.expected_turn_count):
        raise HTTPException(422, "开始答辩不接受回答或已有轮次")
    valid_status = {"created", "ready"} if payload.operation == "start" else {"active"}
    if session.status not in valid_status or session.state == "OPERATION_QUEUED":
        raise HTTPException(409, "会话状态已变化或正在处理，请刷新")
    turn_count = select(func.count(Turn.id)).where(Turn.session_id == session.id).scalar_subquery()
    marker = {"request_id": request_id, "previous_state": session.state}
    changed = db.execute(update(ExamSession).where(
        ExamSession.id == session.id, ExamSession.state == session.state,
        ExamSession.status.in_(valid_status), turn_count == payload.expected_turn_count,
    ).values(state="OPERATION_QUEUED", config={**session.config, "operation_receipt": marker}))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "已有新回答或任务，请刷新；没有重复提交")
    try:
        job = enqueue_job(db, kind="session_operation", project_id=session.project_id,
                          payload=data, idempotency_key=f"{session.id}:{request_id}", max_attempts=30,
                          dispatch=not get_settings().celery_always_eager)
    except JobQueueUnavailable:
        job = operation_receipt(db, session, request_id)
    else:
        if get_settings().celery_always_eager:
            tasks.add_task(dispatch_job_by_id, job.id, job.organization_id, job.actor_principal_id)
    return serialize_job(job, include_internal=False)


def execute_session_operation(db: Session, job: BackgroundJob, heartbeat):
    from .retest import RetestLifecycleService
    data = job.payload
    session = db.get(ExamSession, data["session_id"])
    if not session or session.organization_id != job.organization_id or session.project_id != job.project_id:
        raise ValueError("Session scope mismatch")
    marker = session.config.get("operation_receipt") or {}
    if marker.get("request_id") != data["request_id"]:
        raise ValueError("Session receipt replaced")
    if marker.get("completed"):
        return {"session_id": session.id}, "答辩结果已保存"
    if session.state != "OPERATION_QUEUED" or len(session.turns) != data["expected_turn_count"]:
        raise ValueError("Session position changed")
    heartbeat.checkpoint()
    provider = governed_provider(db, get_settings(), session.config.get("profile"),
                                 project_id=session.project_id, session_id=session.id)
    orchestrator = ExamOrchestrator(db, provider, project_id=session.project_id, session_id=session.id)
    blueprint = db.get(Blueprint, session.blueprint_id)
    db.commit()

    def commit_receipt():
        fence_job(db, job)
        session.config = {**session.config, "operation_receipt": {**marker, "completed": True}}

    try:
        if data["operation"] == "start":
            orchestrator.start_session(session, blueprint, before_commit=commit_receipt)
        else:
            result = orchestrator.submit_answer(session, blueprint, data["answer"], before_commit=commit_receipt)
            if result["completed"]:
                RetestLifecycleService(db).complete_from_session(session, result["user_turn"])
                db.commit()
    except ModelGovernanceError as exc:
        if any(isinstance(row, UsageEvent) for row in db.new):
            raise ValueError("Admission denied after a paid call; automatic replay disabled") from exc
        raise
    return {"session_id": session.id}, "答辩结果已保存"
