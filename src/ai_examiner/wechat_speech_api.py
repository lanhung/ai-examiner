"""Question-bound speech for personal sessions, student exams and teacher previews."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .config import get_settings
from .models import ExamPaper, ExamSession, Project, Turn
from .school_api import Db, User, own_attempt, own_preview
from .services.authentication import CurrentAuthentication
from .services.authorization import (
    ROUTE_POLICIES,
    AuthorizationError,
    RoutePolicy,
    authorization_http_error,
    resolve_authorization_context,
)
from .services.model_governance import ModelGovernanceService
from .services.wechat_speech import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    SEGMENT_CHARS,
    SpeechError,
    call_speech,
    validate_recording,
)

Kind = Literal["attempt", "preview", "session"]


@dataclass
class SpeechContext:
    project: Project
    question: str
    key: str
    resource_id: str


def speech_context(
    kind: Kind, resource_id: UUID, request: Request, user: User,
    authentication: CurrentAuthentication, db: Db,
) -> SpeechContext:
    identity = str(resource_id)
    if kind in {"attempt", "preview"}:
        attempt = (
            own_attempt(db, user, identity) if kind == "attempt"
            else own_preview(db, user, identity)
        )
        if attempt.status != "active":
            raise HTTPException(409, "答卷当前不可进行语音问答，请刷新状态")
        paper = db.get(ExamPaper, attempt.exam_id)
        position = len(attempt.answers)
        if not paper or position >= len(paper.questions):
            raise HTTPException(409, "当前没有待回答的题目")
        question = paper.questions[position]["text"]
        # The publication, not a client-supplied organization, selects the project.
        project = db.get(Project, paper.project_id)
        revision = str(position)
    else:
        try:
            auth = resolve_authorization_context(
                db, authentication=authentication,
                organization_id=request.headers.get("X-AI-Examiner-Organization"),
                required_capability="session.conduct",
                disabled_principal_id=request.headers.get("X-AI-Examiner-Principal"),
            )
        except AuthorizationError as exc:
            raise authorization_http_error(exc) from exc
        session = db.get(ExamSession, identity)
        if not session or session.organization_id != auth.organization_id:
            raise HTTPException(404, "会话不存在")
        if session.status != "active":
            raise HTTPException(409, "请先开始答辩，或当前会话已经结束")
        turn = db.scalar(select(Turn).where(
            Turn.session_id == identity, Turn.organization_id == auth.organization_id,
        ).order_by(Turn.created_at.desc(), Turn.id.desc()).limit(1))
        if not turn or turn.role != "assistant":
            raise HTTPException(409, "请等待考官完成提问")
        question, revision = turn.content, turn.id
        project = db.get(Project, session.project_id)
    if not project or not isinstance(question, str) or not question.strip():
        raise HTTPException(404, "题目所属项目不可用")
    digest = hashlib.sha256(f"{kind}:{identity}:{revision}:{question}".encode()).hexdigest()
    return SpeechContext(project, question, digest, identity)


Context = Annotated[SpeechContext, Depends(speech_context)]


class SpeechInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    segment: int = Field(default=0, ge=0, le=200)


def ready() -> None:
    settings = get_settings()
    if not settings.wechat_speech_enabled or not settings.dashscope_api_key:
        raise HTTPException(503, "小程序语音尚未启用或未配置千问密钥，请使用文字答题")


def check_key(context: SpeechContext, key: str) -> None:
    if context.key != key:
        raise HTTPException(409, "题目已变化，请刷新后重新录音或朗读")


def execute(context: SpeechContext, user, db, operation: str, content: str | bytes, units: int):
    settings = get_settings()
    model = settings.wechat_asr_model if operation == "asr" else settings.wechat_tts_model
    profile = f"qwen:{model}"
    governance = ModelGovernanceService(settings)
    project = context.project
    values = dict(
        organization_id=project.organization_id, principal_id=user.id,
        requested_profile=profile, task_type="voice",
        classification=project.data_classification,
    )
    # Release the reader transaction before governance writes its independent ledger.
    project_id = project.id
    db.commit()
    governance.candidates(**values)
    reservation = governance.reserve(
        **values, project_id=project_id, session_id=context.resource_id,
        candidate_profile=profile, fallback_from_profile=None, token_units=units,
        request_id=uuid4().hex, cost_estimate_usd=settings.wechat_speech_call_budget_usd,
    )
    try:
        result = call_speech(settings, operation=operation, content=content)
    except Exception as exc:
        governance.fail(reservation)
        if isinstance(exc, SpeechError):
            raise HTTPException(exc.status, str(exc)) from None
        raise
    governance.settle(
        reservation, result, cost_estimate_usd=settings.wechat_speech_call_budget_usd,
    )
    return {**result.data, "model": result.model, "question_key": context.key,
            "latency_ms": result.latency_ms}


def voice_context(context: Context, response: Response):
    from .wechat_realtime import available, max_seconds

    response.headers["Cache-Control"] = "private, no-store"
    settings = get_settings()
    return {
        "available": settings.wechat_speech_enabled and bool(settings.dashscope_api_key),
        "question_key": context.key, "max_seconds": MAX_AUDIO_SECONDS,
        "asr_model": settings.wechat_asr_model, "tts_model": settings.wechat_tts_model,
        "mode": "turn_based", "confirmation_required": True,
        "realtime": {"available": available(settings, context.project.organization_id),
                     "model": settings.qwen_realtime_model,
                     "max_seconds": max_seconds(settings)},
    }


def transcribe(
    context: Context, user: User, db: Db, response: Response,
    question_key: Annotated[str, Form(pattern=r"^[a-f0-9]{64}$")],
    file: Annotated[UploadFile, File()],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        ready()
        check_key(context, question_key)
        content = file.file.read(MAX_AUDIO_BYTES + 1)
        try:
            duration = validate_recording(content)
        except SpeechError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        return execute(context, user, db, "asr", content, int(duration * 25) + 1)
    finally:
        file.file.close()


def speak(payload: SpeechInput, context: Context, user: User, db: Db, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    ready()
    check_key(context, payload.question_key)
    chunks = [
        context.question[i:i + SEGMENT_CHARS]
        for i in range(0, len(context.question), SEGMENT_CHARS)
    ]
    if payload.segment >= len(chunks):
        raise HTTPException(422, "题目语音分段不存在")
    return {
        **execute(context, user, db, "tts", chunks[payload.segment], len(chunks[payload.segment])),
        "segment": payload.segment, "segments": len(chunks),
    }


def register_routes(app: FastAPI):
    root = "/api/v1/wechat/voice/{kind}/{resource_id}"
    for method, suffix, endpoint in (
        ("GET", "/context", voice_context),
        ("POST", "/transcribe", transcribe),
        ("POST", "/speech", speak),
    ):
        ROUTE_POLICIES[(method, root + suffix)] = RoutePolicy(
            "required", None, "speech_owned_resource", "read_sensitive",
        )
        app.add_api_route(root + suffix, endpoint, methods=[method], tags=["wechat-voice"])
