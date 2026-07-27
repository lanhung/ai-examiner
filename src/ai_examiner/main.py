from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import websockets
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import __version__
from .agents.orchestrator import ExamOrchestrator
from .config import get_settings
from .db import SessionLocal, get_db, init_db
from .model_catalog import CATALOG
from .models import (
    AdaptiveDecision,
    BackgroundJob,
    BenchmarkRun,
    Blueprint,
    Concept,
    Document,
    EvidenceAsset,
    ExamSession,
    ExpertRating,
    GoldenDataset,
    JointAnalysis,
    KnowledgeEvidenceEvent,
    KnowledgeUnit,
    KnowledgeUnitConceptMap,
    LearnerConceptState,
    LearnerIdentity,
    LearnerIdentityLink,
    LearnerMemoryEvent,
    LearnerPreference,
    LearnerSubject,
    MemoryDeletionAudit,
    Organization,
    Project,
    PromptVersion,
    RetestPlan,
    ScenarioTemplate,
    ScenarioTemplateVersion,
    Turn,
    UsageEvent,
    VisualAnalysis,
    VoiceEvent,
    VoiceSession,
)
from .providers.factory import build_provider, parse_profile, profile_ready
from .schemas import (
    AnswerSubmit,
    BenchmarkCreate,
    BlueprintCreate,
    ConceptCreate,
    ConceptMappingCreate,
    ConceptMappingReview,
    DatasetStatusUpdate,
    ExpertRatingCreate,
    GoldenDatasetCreate,
    JointAnalysisCreate,
    LearnerIdentityCreate,
    LearnerIdentityLinkCreate,
    LongitudinalRebuildCreate,
    MemoryCorrectionCreate,
    MemoryDeletionCreate,
    MemoryExportCreate,
    MemoryImportCreate,
    MemorySettingsUpdate,
    PolicyBenchmarkCreate,
    PreferenceAction,
    PreferenceCreate,
    ProjectCreate,
    ProjectTemplateBindingUpdate,
    PromptVersionCreate,
    RetestItemAction,
    RetestPlanCreate,
    RetestSessionCreate,
    ScenarioTemplateCloneCreate,
    ScenarioTemplateCreate,
    ScenarioTemplateImport,
    ScenarioTemplatePreview,
    ScenarioTemplateSourceUpdate,
    ScenarioTemplateStatusUpdate,
    SessionCreate,
    VisualAnalyzeCreate,
    VoiceEventCreate,
    VoiceSessionComplete,
    VoiceSessionCreate,
)
from .services.agreement import agreement_summary
from .services.authentication import (
    CurrentAuthentication,
    authentication_http_error,
    get_oidc_authenticator,
)
from .services.benchmark import BenchmarkService
from .services.cognitive import CognitiveStateService
from .services.conversation_policy import effective_conversation_policy
from .services.datasets import dataset_diff, set_dataset_status
from .services.documents import parse_document, save_upload
from .services.enterprise_identity import (
    EnterpriseIdentityError,
    resolve_organization_context,
    serialize_organization,
)
from .services.evidence import create_highlighted_crop, persist_evidence, serialize_asset
from .services.golden import GoldenDatasetService
from .services.jobs import JobQueueUnavailable, enqueue_job, serialize_job
from .services.joint import JointAnalysisService
from .services.longitudinal import LongitudinalStateError, LongitudinalStateService
from .services.longitudinal_evaluation import LongitudinalEvaluationService
from .services.memory import (
    LearnerMemoryService,
    MemoryConflictError,
    MemoryPolicyError,
    canonical_token,
)
from .services.memory_control import MemoryControlError, MemoryControlService
from .services.oidc import OIDCError
from .services.policy_benchmark import PolicyBenchmarkService
from .services.preferences import PreferencePolicyError, PreferenceService
from .services.prompts import activate_prompt, create_prompt_version, prompt_manifest
from .services.retest import RetestLifecycleError, RetestLifecycleService
from .services.session_templates import (
    SessionTemplateService,
    serialize_project_template_binding,
)
from .services.template_access import (
    TemplateAuthoringContext,
    template_authoring_context,
)
from .services.template_transfer import (
    TEMPLATE_EXPORT_VERSION,
    export_template_document,
    import_template_document,
    semantic_template_diff,
)
from .services.templates import (
    TemplateLifecycleError,
    TemplateLifecycleService,
    persisted_template_catalog,
    persisted_template_health,
    serialize_template,
    serialize_template_version,
    serialize_validation_run,
)
from .services.visual import VisualEvidenceService
from .services.voice import (
    VOICE_PROVIDERS,
    create_realtime_call,
    create_voice_session,
    default_voice_for,
    model_for,
    qwen_realtime_session_config,
    record_voice_event,
    voice_provider_ready,
)
from .template_engine.compiler import (
    TemplateCompiler,
    TemplateOverrideError,
    TemplateValidationError,
)

settings = get_settings()
STATIC_DIR = Path(__file__).parent / "static"
TemplateAuthoringAccess = Annotated[
    TemplateAuthoringContext,
    Depends(template_authoring_context),
]
@asynccontextmanager
async def lifespan(app: FastAPI):
    auth_issues = settings.auth_configuration_issues()
    if settings.app_env == "production" and auth_issues:
        raise RuntimeError(
            "Unsafe authentication configuration: " + ", ".join(auth_issues)
        )
    init_db()
    yield


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def disable_dynamic_response_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/health" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(JobQueueUnavailable)
async def job_queue_unavailable_handler(_request: Request, exc: JobQueueUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(TemplateLifecycleError)
async def template_lifecycle_error_handler(
    _request: Request,
    exc: TemplateLifecycleError,
):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": str(exc)}},
    )


def provider_or_503(profile: str | None = None):
    try:
        return build_provider(settings, profile)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _profiles(raw: list[str], fallback: str) -> list[str]:
    profiles = raw or [item.strip() for item in fallback.split(",") if item.strip()]
    if not profiles:
        profiles = ["mock:heuristic-v2"]
    for profile in profiles:
        try:
            parse_profile(profile)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not profile_ready(settings, profile):
            raise HTTPException(503, f"Model profile is not configured: {profile}")
    return list(dict.fromkeys(profiles))


def serialize_turn(turn: Turn) -> dict:
    return {
        "id": turn.id,
        "role": turn.role,
        "kind": turn.kind,
        "content": turn.content,
        "question_id": turn.question_id,
        "analysis": turn.analysis,
        "evaluation": turn.evaluation,
        "created_at": turn.created_at.isoformat(),
    }


def serialize_dataset(dataset: GoldenDataset, *, include_data: bool = True) -> dict:
    payload = {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "document_id": dataset.document_id,
        "name": dataset.name,
        "version": dataset.version,
        "status": dataset.status,
        "generator_profiles": dataset.generator_profiles,
        "consensus_profile": dataset.consensus_profile,
        "quality_metrics": dataset.quality_metrics,
        "created_at": dataset.created_at.isoformat(),
    }
    if include_data:
        payload["data"] = dataset.data
    return payload


def serialize_benchmark(run: BenchmarkRun) -> dict:
    return {
        "id": run.id,
        "golden_dataset_id": run.golden_dataset_id,
        "status": run.status,
        "profiles": run.profiles,
        "config": run.config,
        "results": run.results,
        "summary": run.summary,
        "created_at": run.created_at.isoformat(),
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    profile = f"{settings.model_provider}:{settings.default_model_for(settings.model_provider)}"
    unsafe_auth_disabled = (
        settings.app_env == "production" and settings.auth_mode == "disabled"
    )
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": app.version,
        "provider": settings.model_provider,
        "model": settings.default_model_for(settings.model_provider),
        "provider_ready": profile_ready(settings, profile),
        "authentication": {
            "mode": settings.auth_mode,
            "unsafe_disabled_in_production": unsafe_auth_disabled,
        },
    }


@app.get("/ready")
def readiness(db: Annotated[Session, Depends(get_db)]):
    checks: dict[str, dict[str, object]] = {}
    issues = settings.auth_configuration_issues()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ready": True}
    except Exception:
        checks["database"] = {"ready": False, "code": "database_unavailable"}

    authentication_ready = not issues
    auth_check: dict[str, object] = {
        "ready": authentication_ready,
        "mode": settings.auth_mode,
    }
    if issues:
        auth_check["codes"] = issues
    elif settings.auth_mode == "oidc":
        try:
            authenticator = get_oidc_authenticator()
            authenticator.cache.get_metadata()
            authenticator.cache.get_jwks()
        except OIDCError as exc:
            authentication_ready = False
            auth_check = {
                "ready": False,
                "mode": settings.auth_mode,
                "codes": [exc.reason_code],
            }
    checks["authentication"] = auth_check
    ready = bool(checks["database"]["ready"]) and authentication_ready
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@app.get("/api/providers")
def providers():
    return [
        entry.public_dict(profile_ready(settings, entry.id))
        for entry in CATALOG
    ]


@app.get("/api/v1/context")
def enterprise_context(
    request: Request,
    authentication: CurrentAuthentication,
    db: Annotated[Session, Depends(get_db)],
):
    requested_principal_id = (
        authentication.principal_id
        if settings.auth_mode == "oidc"
        else request.headers.get("X-AI-Examiner-Principal")
    )
    try:
        context = resolve_organization_context(
            db,
            requested_organization_id=request.headers.get(
                "X-AI-Examiner-Organization"
            ),
            requested_principal_id=requested_principal_id,
        )
    except EnterpriseIdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    organization = db.get(Organization, context.organization_id)
    if organization is None:
        raise HTTPException(404, "Organization context not found")
    return {
        **context.public_dict(),
        "organization": serialize_organization(organization),
    }


@app.get("/api/v1/auth/login", include_in_schema=False)
def oidc_login(db: Annotated[Session, Depends(get_db)]):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC authentication is disabled")
    try:
        login = get_oidc_authenticator().begin_login(db)
    except OIDCError as exc:
        raise authentication_http_error(exc) from exc
    return RedirectResponse(
        login.authorization_url,
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/auth/callback", include_in_schema=False)
def oidc_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = Query(default=None, max_length=4000),
    state: str | None = Query(default=None, max_length=500),
    error: str | None = Query(default=None, max_length=200),
):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC authentication is disabled")
    if error or not code or not state:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_failed", "message": "Authentication failed."},
        )
    try:
        completed = get_oidc_authenticator().complete_login(
            db,
            code=code,
            state=state,
        )
    except OIDCError as exc:
        raise authentication_http_error(exc) from exc
    response = RedirectResponse(
        settings.oidc_post_login_redirect,
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )
    max_age = max(0, int((completed.expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        settings.oidc_session_cookie_name,
        completed.session_token,
        max_age=max_age,
        expires=completed.expires_at,
        path="/",
        secure=bool(
            settings.oidc_redirect_uri
            and settings.oidc_redirect_uri.startswith("https://")
        ),
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/api/v1/auth/logout")
def oidc_logout(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    cookie = request.cookies.get(settings.oidc_session_cookie_name)
    revoked = (
        get_oidc_authenticator().revoke_session(db, cookie)
        if settings.auth_mode == "oidc"
        else False
    )
    response = JSONResponse(
        {"logged_out": True, "session_revoked": revoked},
        headers={"Cache-Control": "no-store"},
    )
    response.delete_cookie(
        settings.oidc_session_cookie_name,
        path="/",
        secure=bool(
            settings.oidc_redirect_uri
            and settings.oidc_redirect_uri.startswith("https://")
        ),
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/api/v1/me")
def current_principal(
    authentication: CurrentAuthentication,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return get_oidc_authenticator().me(db, authentication)
    except OIDCError as exc:
        raise authentication_http_error(exc) from exc


@app.get("/api/templates")
def templates(
    db: Annotated[Session, Depends(get_db)],
    category: str | None = None,
    include_drafts: bool = False,
):
    return persisted_template_catalog(
        db,
        category=category,
        include_drafts=include_drafts,
    )


@app.get("/api/templates/health")
def template_health(db: Annotated[Session, Depends(get_db)]):
    return persisted_template_health(db)


@app.post("/api/templates", status_code=201)
def create_scenario_template(
    payload: ScenarioTemplateCreate,
    db: Annotated[Session, Depends(get_db)],
    _access: TemplateAuthoringAccess,
):
    template, version = TemplateLifecycleService(db).create_local(
        slug=payload.slug,
        category=payload.category,
        semantic_version=payload.semantic_version,
        source=payload.source,
    )
    return {
        "template": serialize_template(db, template),
        "version": serialize_template_version(db, version),
    }


@app.post("/api/templates/import", status_code=201)
def import_scenario_template(
    payload: ScenarioTemplateImport,
    db: Annotated[Session, Depends(get_db)],
    access: TemplateAuthoringAccess,
):
    template, version = import_template_document(
        db,
        document=payload.document,
        target_slug=payload.target_slug,
        semantic_version=payload.semantic_version,
    )
    return {
        "import_version": TEMPLATE_EXPORT_VERSION,
        "trust_assignment": "local_draft",
        "authorization": {
            "scope": access.scope,
            "enforced": access.authorization_enforced,
        },
        "template": serialize_template(db, template),
        "version": serialize_template_version(db, version),
    }


@app.get("/api/templates/{template_id}")
def get_scenario_template(
    template_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    template = db.get(ScenarioTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    return serialize_template(db, template)


@app.get("/api/template-versions/{version_id}")
def get_scenario_template_version(
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    return serialize_template_version(db, version)


@app.post("/api/template-versions/{version_id}/clone", status_code=201)
def clone_scenario_template_version(
    version_id: str,
    payload: ScenarioTemplateCloneCreate,
    db: Annotated[Session, Depends(get_db)],
    _access: TemplateAuthoringAccess,
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    cloned = TemplateLifecycleService(db).clone(
        version,
        semantic_version=payload.semantic_version,
    )
    return serialize_template_version(db, cloned)


@app.put("/api/template-versions/{version_id}")
def replace_scenario_template_version(
    version_id: str,
    payload: ScenarioTemplateSourceUpdate,
    db: Annotated[Session, Depends(get_db)],
    _access: TemplateAuthoringAccess,
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    updated = TemplateLifecycleService(db).replace_source(version, payload.source)
    return serialize_template_version(db, updated)


@app.post("/api/template-versions/{version_id}/validate")
def validate_scenario_template_version(
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    _access: TemplateAuthoringAccess,
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    run = TemplateLifecycleService(db).validate(version)
    return serialize_validation_run(run)


@app.post("/api/template-versions/{version_id}/compile")
def compile_scenario_template_version(
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    _access: TemplateAuthoringAccess,
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    compiled = TemplateLifecycleService(db).compile(version)
    return serialize_template_version(
        db,
        compiled,
        include_source=False,
        include_compiled=True,
    )


@app.post("/api/template-versions/{version_id}/preview")
def preview_scenario_template_version(
    version_id: str,
    payload: ScenarioTemplatePreview,
    db: Annotated[Session, Depends(get_db)],
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise TemplateLifecycleError(
            "TEMPLATE_VERSION_NOT_FOUND",
            "Template version not found",
            status_code=404,
        )
    try:
        preview = TemplateCompiler().compile(
            version.source_json,
            overrides=payload.overrides,
        )
    except TemplateOverrideError as exc:
        raise TemplateLifecycleError(
            "TEMPLATE_OVERRIDE_INVALID",
            "Template preview overrides are invalid",
            status_code=422,
        ) from exc
    except TemplateValidationError as exc:
        raise TemplateLifecycleError(
            "TEMPLATE_VALIDATION_FAILED",
            "Template preview source failed validation",
            status_code=422,
        ) from exc
    return {
        "preview_version": "template-preview-v1",
        "template_version_id": version.id,
        "fixture": payload.fixture,
        "fingerprint": preview.fingerprint,
        "compiler_version": preview.compiler_version,
        "effective_settings": preview.compiled,
        "override_audit": preview.override_audit,
    }


@app.post("/api/template-versions/{version_id}/status")
def transition_scenario_template_version(
    version_id: str,
    payload: ScenarioTemplateStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    _access: TemplateAuthoringAccess,
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    transitioned = TemplateLifecycleService(db).transition(
        version,
        status=payload.status,
        evaluation_summary=payload.evaluation_summary,
    )
    return serialize_template_version(db, transitioned)


@app.get("/api/template-versions/{version_id}/export")
def export_scenario_template_version(
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    output_format: str = Query(default="yaml", alias="format", pattern="^(json|yaml)$"),
):
    version = db.get(ScenarioTemplateVersion, version_id)
    if not version:
        raise TemplateLifecycleError(
            "TEMPLATE_VERSION_NOT_FOUND",
            "Template version not found",
            status_code=404,
        )
    payload, media_type = export_template_document(
        version,
        output_format=output_format,
    )
    filename = (
        f"{version.template.slug}-{version.semantic_version}."
        f"{'json' if output_format == 'json' else 'yaml'}"
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Template-Export-Version": TEMPLATE_EXPORT_VERSION,
            "X-Template-Fingerprint": version.fingerprint or "",
        },
    )


@app.get("/api/template-versions/{left_id}/diff/{right_id}")
def diff_scenario_template_versions(
    left_id: str,
    right_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    left = db.get(ScenarioTemplateVersion, left_id)
    right = db.get(ScenarioTemplateVersion, right_id)
    if not left or not right:
        raise TemplateLifecycleError(
            "TEMPLATE_VERSION_NOT_FOUND",
            "One or both template versions were not found",
            status_code=404,
        )
    return semantic_template_diff(left, right)


@app.get("/api/projects/{project_id}/template-binding")
def get_project_template_binding(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    binding = SessionTemplateService(db).active_binding(project.id)
    return {"binding": serialize_project_template_binding(binding)}


@app.put("/api/projects/{project_id}/template-binding")
def set_project_template_binding(
    project_id: str,
    payload: ProjectTemplateBindingUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    version = db.get(ScenarioTemplateVersion, payload.template_version_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not version:
        raise HTTPException(404, "Template version not found")
    binding = SessionTemplateService(db).bind_project(
        project,
        version,
        default_overrides=payload.default_overrides,
    )
    return {"binding": serialize_project_template_binding(binding)}


@app.delete("/api/projects/{project_id}/template-binding")
def clear_project_template_binding(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    binding = SessionTemplateService(db).clear_project_binding(project.id)
    return {
        "cleared": binding is not None,
        "binding": serialize_project_template_binding(binding),
    }


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate, db: Annotated[Session, Depends(get_db)]):
    project = Project(name=payload.name, domain=payload.domain, language=payload.language)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {
        "id": project.id,
        "organization_id": project.organization_id,
        "name": project.name,
        "domain": project.domain,
        "language": project.language,
    }


@app.get("/api/projects")
def list_projects(db: Annotated[Session, Depends(get_db)]):
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [
        {
            "id": project.id,
            "organization_id": project.organization_id,
            "name": project.name,
            "domain": project.domain,
            "language": project.language,
            "created_at": project.created_at,
        }
        for project in projects
    ]


@app.post("/api/projects/{project_id}/documents", status_code=201)
async def upload_document(
    project_id: str,
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    destination = settings.upload_dir / project_id
    try:
        path, raw = await save_upload(file, destination, settings.max_upload_bytes)
        evidence_output = settings.evidence_dir / project_id / path.stem
        parsed = parse_document(
            path, raw, settings.max_document_chars, evidence_output_dir=evidence_output
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    document = Document(
        project_id=project_id,
        filename=file.filename or path.name,
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(path),
        content_text=parsed.text,
        page_map=parsed.page_map,
        parse_warnings=parsed.warnings,
        char_count=len(parsed.text),
    )
    db.add(document)
    db.flush()
    assets = persist_evidence(
        db, project_id=project_id, document=document, drafts=parsed.evidence
    )
    db.commit()
    db.refresh(document)
    return {
        "id": document.id,
        "filename": document.filename,
        "document_kind": parsed.document_kind,
        "char_count": document.char_count,
        "page_count": len(document.page_map),
        "evidence_count": len(assets),
        "warnings": document.parse_warnings,
        "preview": document.content_text[:800],
    }


@app.post("/api/projects/{project_id}/blueprints", status_code=201)
def generate_blueprint(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    document_id: Annotated[str | None, Query()] = None,
    payload: Annotated[BlueprintCreate | None, Body()] = None,
):
    selected_document_id = payload.document_id if payload else document_id
    if not selected_document_id:
        raise HTTPException(422, "document_id is required")
    project = db.get(Project, project_id)
    document = db.get(Document, selected_document_id)
    if not project or not document or document.project_id != project_id:
        raise HTTPException(404, "Project or document not found")
    mode = payload.mode if payload else "defense"
    resolved_template = SessionTemplateService(db).resolve(
        project,
        mode=mode,
        template_version_id=payload.template_version_id if payload else None,
        template_overrides=payload.template_overrides if payload else {},
        request_overrides={},
    )
    provider = provider_or_503(payload.profile if payload else None)
    orchestrator = ExamOrchestrator(db, provider, project_id=project_id)
    try:
        data, grounding = orchestrator.build_blueprint(
            document_text=document.content_text,
            filename=document.filename,
            language=project.language,
            template_contract=(
                resolved_template.snapshot if resolved_template else None
            ),
        )
        if resolved_template:
            data["template_plan"].update(
                {
                    "template_version_id": resolved_template.template_version_id,
                    "fingerprint": resolved_template.fingerprint,
                    "compiler_version": resolved_template.compiler_version,
                    "resolution_source": resolved_template.resolution_source,
                }
            )
        page_assets = {
            asset.page_number: asset
            for asset in db.scalars(
                select(EvidenceAsset).where(
                    EvidenceAsset.document_id == document.id,
                    EvidenceAsset.kind == "page",
                )
            ).all()
        }
        for question in data.get("questions") or []:
            page_number = int(question.get("source_page") or 1)
            page_asset = page_assets.get(page_number)
            question["evidence_asset_ids"] = [page_asset.id] if page_asset else []
            question["page_preview_url"] = (
                f"/api/evidence/{page_asset.id}/file" if page_asset else None
            )
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"Blueprint generation failed: {exc}") from exc
    version = (
        db.scalar(select(func.count(Blueprint.id)).where(Blueprint.project_id == project_id)) or 0
    )
    blueprint = Blueprint(
        project_id=project_id,
        document_id=selected_document_id,
        version=version + 1,
        data=data,
        provider=provider.name,
        model=provider.model,
    )
    db.add(blueprint)
    db.commit()
    db.refresh(blueprint)
    return {
        "id": blueprint.id,
        "version": blueprint.version,
        "provider": blueprint.provider,
        "model": blueprint.model,
        "grounding": grounding,
        "template_plan": blueprint.data.get("template_plan"),
        "data": blueprint.data,
    }


@app.post("/api/projects/{project_id}/golden-datasets", status_code=201)
def generate_golden_dataset(
    project_id: str,
    payload: GoldenDatasetCreate,
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    document = db.get(Document, payload.document_id)
    if not project or not document or document.project_id != project_id:
        raise HTTPException(404, "Project or document not found")
    profiles = _profiles(payload.profiles, settings.golden_default_profiles)
    consensus_profile = payload.consensus_profile or profiles[0]
    if consensus_profile not in profiles:
        profiles.append(consensus_profile)
    _profiles([consensus_profile], settings.golden_default_profiles)
    service = GoldenDatasetService(db, settings, project_id, document)
    try:
        dataset = service.generate(
            profiles=profiles,
            consensus_profile=consensus_profile,
            question_count=payload.question_count,
            language=project.language,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"Golden Dataset generation failed: {exc}") from exc
    return serialize_dataset(dataset)


@app.get("/api/projects/{project_id}/golden-datasets")
def list_golden_datasets(project_id: str, db: Annotated[Session, Depends(get_db)]):
    datasets = db.scalars(
        select(GoldenDataset)
        .where(GoldenDataset.project_id == project_id)
        .order_by(GoldenDataset.created_at.desc())
    ).all()
    return [serialize_dataset(dataset, include_data=False) for dataset in datasets]


@app.get("/api/golden-datasets/{dataset_id}")
def get_golden_dataset(dataset_id: str, db: Annotated[Session, Depends(get_db)]):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    return serialize_dataset(dataset)


@app.get("/api/golden-datasets/{dataset_id}/export")
def export_golden_dataset(dataset_id: str, db: Annotated[Session, Depends(get_db)]):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    lines = []
    for case in dataset.data.get("cases") or []:
        record = {
            "dataset_id": dataset.id,
            "dataset_version": dataset.version,
            "document_id": dataset.document_id,
            "generator_profiles": dataset.generator_profiles,
            "consensus_profile": dataset.consensus_profile,
            **case,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    content = "\n".join(lines) + ("\n" if lines else "")
    filename = f"golden-dataset-v{dataset.version}.jsonl"
    return Response(
        content=content,
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/golden-datasets/{dataset_id}/benchmarks", status_code=201)
def run_benchmark(
    dataset_id: str,
    payload: BenchmarkCreate,
    db: Annotated[Session, Depends(get_db)],
):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    document = db.get(Document, dataset.document_id)
    project = db.get(Project, dataset.project_id)
    if not document or not project:
        raise HTTPException(404, "Dataset source document or project not found")
    profiles = _profiles(payload.profiles, settings.benchmark_default_profiles)
    service = BenchmarkService(db, settings, project.id, document, dataset)
    try:
        run = service.run(
            profiles=profiles,
            case_limit=payload.case_limit,
            run_planner=payload.run_planner,
            run_analyzer=payload.run_analyzer,
            language=project.language,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"Benchmark failed: {exc}") from exc
    return serialize_benchmark(run)


@app.get("/api/golden-datasets/{dataset_id}/benchmarks")
def list_benchmarks(dataset_id: str, db: Annotated[Session, Depends(get_db)]):
    runs = db.scalars(
        select(BenchmarkRun)
        .where(BenchmarkRun.golden_dataset_id == dataset_id)
        .order_by(BenchmarkRun.created_at.desc())
    ).all()
    return [serialize_benchmark(run) for run in runs]


@app.get("/api/benchmarks/{benchmark_id}")
def get_benchmark(benchmark_id: str, db: Annotated[Session, Depends(get_db)]):
    run = db.get(BenchmarkRun, benchmark_id)
    if not run:
        raise HTTPException(404, "Benchmark not found")
    return serialize_benchmark(run)


@app.post("/api/golden-datasets/{dataset_id}/ratings", status_code=201)
def add_expert_rating(
    dataset_id: str,
    payload: ExpertRatingCreate,
    db: Annotated[Session, Depends(get_db)],
):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    case_ids = {case.get("id") for case in dataset.data.get("cases") or []}
    if payload.case_id not in case_ids:
        raise HTTPException(400, "Unknown Golden Dataset case")
    rating = ExpertRating(
        golden_dataset_id=dataset_id,
        case_id=payload.case_id,
        rater=payload.rater,
        ratings={
            "relevance": payload.relevance,
            "difficulty": payload.difficulty,
            "groundedness": payload.groundedness,
            "answer_quality": payload.answer_quality,
        },
        notes=payload.notes,
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return {"id": rating.id, "case_id": rating.case_id, "ratings": rating.ratings}


@app.get("/api/golden-datasets/{dataset_id}/agreement")
def get_agreement(dataset_id: str, db: Annotated[Session, Depends(get_db)]):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    return agreement_summary(db, dataset)


@app.post("/api/sessions", status_code=201)
def create_session(payload: SessionCreate, db: Annotated[Session, Depends(get_db)]):
    project = db.get(Project, payload.project_id)
    blueprint = db.get(Blueprint, payload.blueprint_id)
    if not project or not blueprint or blueprint.project_id != project.id:
        raise HTTPException(404, "Project or blueprint not found")
    request_overrides: dict[str, object] = {}
    fields = payload.model_fields_set
    for field, override in (
        ("question_limit", "question_limit"),
        ("max_followups_per_question", "max_followups_per_question"),
        ("question_strategy", "question_strategy"),
        ("allow_hints", "hints_allowed"),
        ("allow_corrections", "corrections_allowed"),
    ):
        if field in fields:
            request_overrides[override] = getattr(payload, field)
    resolved_template = SessionTemplateService(db).resolve(
        project,
        mode=payload.mode,
        template_version_id=payload.template_version_id,
        template_overrides=payload.template_overrides,
        request_overrides=request_overrides,
    )
    profile = payload.profile or (
        f"{settings.model_provider}:{settings.default_model_for(settings.model_provider)}"
    )
    _profiles([profile], profile)
    cognitive = CognitiveStateService(db)
    cognitive.ensure_blueprint_graph(blueprint)
    subject = cognitive.get_or_create_subject(project.id, payload.learner_subject_key)
    config = payload.model_dump(
        exclude={
            "project_id",
            "blueprint_id",
            "mode",
            "question_strategy",
            "learner_subject_key",
            "template_version_id",
            "template_overrides",
        }
    )
    mode = payload.mode
    question_strategy = payload.question_strategy
    if resolved_template:
        legacy = resolved_template.legacy
        mode = resolved_template.effective_mode
        question_strategy = legacy["question_strategy"]
        config.update(
            {
                "allow_hints": legacy["allow_hints"],
                "allow_corrections": legacy["allow_corrections"],
                "question_limit": legacy["question_limit"],
                "max_followups_per_question": legacy[
                    "max_followups_per_question"
                ],
                "template_resolution_source": (
                    resolved_template.resolution_source
                ),
            }
        )
    conversation_policy = effective_conversation_policy(
        resolved_template.snapshot if resolved_template else None,
        user_allows_active_interruption=payload.allow_interruptions,
        legacy_config=config,
    )
    config.update(
        {
            "allow_hints": conversation_policy["hints"]["allowed"],
            "allow_corrections": conversation_policy["corrections"]["allowed"],
            "allow_interruptions": conversation_policy["active_interruption"][
                "enabled"
            ],
            "max_followups_per_question": conversation_policy[
                "max_followups_per_question"
            ],
            "conversation_policy": conversation_policy,
        }
    )
    config["profile"] = profile
    session = ExamSession(
        project_id=project.id,
        blueprint_id=blueprint.id,
        mode=mode,
        config=config,
        status="created",
        template_version_id=(
            resolved_template.template_version_id if resolved_template else None
        ),
        template_snapshot_json=(
            resolved_template.snapshot if resolved_template else None
        ),
        template_fingerprint=(
            resolved_template.fingerprint if resolved_template else None
        ),
        template_compiler_version=(
            resolved_template.compiler_version if resolved_template else None
        ),
        template_overrides_json=(
            resolved_template.overrides if resolved_template else None
        ),
        learner_subject_id=subject.id if subject else None,
        question_strategy=question_strategy,
        policy_version=(
            (
                "adaptive-template-v2"
                if resolved_template
                else "adaptive-v1"
            )
            if question_strategy == "adaptive"
            else (
                "fixed-template-v1"
                if resolved_template
                else "fixed-v1"
            )
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "status": session.status,
        "config": session.config,
        "question_strategy": session.question_strategy,
        "policy_version": session.policy_version,
        "learner_subject_id": session.learner_subject_id,
        "template_version_id": session.template_version_id,
        "template_fingerprint": session.template_fingerprint,
    }


@app.post("/api/blueprints/{blueprint_id}/policy-benchmark")
def run_policy_benchmark(
    blueprint_id: str,
    payload: PolicyBenchmarkCreate,
    db: Annotated[Session, Depends(get_db)],
):
    blueprint = db.get(Blueprint, blueprint_id)
    if not blueprint:
        raise HTTPException(404, "Blueprint not found")
    cognitive = CognitiveStateService(db)
    cognitive.ensure_blueprint_graph(blueprint)
    units, question_units = cognitive.graph(blueprint.id)
    try:
        return PolicyBenchmarkService().run(
            questions=blueprint.data.get("questions", []),
            units=units,
            question_units=question_units,
            question_limit=payload.question_limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sessions/{session_id}/start")
def start_session(session_id: str, db: Annotated[Session, Depends(get_db)]):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    blueprint = db.get(Blueprint, session.blueprint_id)
    provider = provider_or_503(session.config.get("profile"))
    orchestrator = ExamOrchestrator(
        db, provider, project_id=session.project_id, session_id=session.id
    )
    try:
        turn = orchestrator.start_session(session, blueprint)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"session_id": session.id, "status": session.status, "turn": serialize_turn(turn)}


@app.post("/api/sessions/{session_id}/answers")
def submit_answer(
    session_id: str,
    payload: AnswerSubmit,
    db: Annotated[Session, Depends(get_db)],
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    blueprint = db.get(Blueprint, session.blueprint_id)
    provider = provider_or_503(session.config.get("profile"))
    orchestrator = ExamOrchestrator(
        db, provider, project_id=session.project_id, session_id=session.id
    )
    try:
        result = orchestrator.submit_answer(session, blueprint, payload.answer)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    retest_item = None
    if result["completed"]:
        retest_item = RetestLifecycleService(db).complete_from_session(
            session, result["user_turn"]
        )
        if retest_item:
            db.commit()
    return {
        "completed": result["completed"],
        "analysis": result["analysis"],
        "evaluation": result["evaluation"],
        "decision": result["decision"],
        "turns": [serialize_turn(result["user_turn"]), serialize_turn(result["assistant_turn"])],
        "retest_item": RetestLifecycleService.serialize_item(retest_item)
        if retest_item
        else None,
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: Annotated[Session, Depends(get_db)]):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "id": session.id,
        "status": session.status,
        "state": session.state,
        "current_question_index": session.current_question_index,
        "asked_question_ids": session.asked_question_ids,
        "question_strategy": session.question_strategy,
        "policy_version": session.policy_version,
        "learner_subject_id": session.learner_subject_id,
        "mastery_state": session.mastery_state,
        "template_version_id": session.template_version_id,
        "template_fingerprint": session.template_fingerprint,
        "turns": [serialize_turn(turn) for turn in session.turns],
    }


@app.get("/api/sessions/{session_id}/template")
def get_session_template(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return SessionTemplateService(db).inspect_session(session)


@app.get("/api/sessions/{session_id}/report")
def get_report(session_id: str, db: Annotated[Session, Depends(get_db)]):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    blueprint = db.get(Blueprint, session.blueprint_id)
    turns = [serialize_turn(turn) for turn in session.turns]
    cognitive = CognitiveStateService(db)
    units, _ = cognitive.graph(blueprint.id)
    evidence_by_unit = cognitive.evidence_for_session(session.id)
    knowledge_states = [
        {
            **state,
            "unit": units.get(unit_id, {}),
            "evidence": evidence_by_unit.get(unit_id, []),
        }
        for unit_id, state in cognitive.states(session.id).items()
    ]
    report = ExamOrchestrator(db, provider_or_503()).reporter.generate(
        blueprint=blueprint.data,
        turns=turns,
        mastery_state=session.mastery_state,
        knowledge_states=knowledge_states,
        mode=session.mode,
        template_snapshot=session.template_snapshot_json,
        language=str(session.config.get("language") or "zh-CN"),
        template_fingerprint=session.template_fingerprint,
    )
    report["session_status"] = session.status
    return report


@app.get("/api/sessions/{session_id}/knowledge-state")
def get_session_knowledge_state(
    session_id: str, db: Annotated[Session, Depends(get_db)]
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    cognitive = CognitiveStateService(db)
    units, question_units = cognitive.graph(session.blueprint_id)
    states = cognitive.states(session.id)
    evidence_by_unit = cognitive.evidence_for_session(session.id)
    evidence_count = db.scalar(
        select(func.count(KnowledgeEvidenceEvent.id)).where(
            KnowledgeEvidenceEvent.session_id == session.id
        )
    )
    return {
        "session_id": session.id,
        "question_strategy": session.question_strategy,
        "policy_version": session.policy_version,
        "learner_subject_id": session.learner_subject_id,
        "units": list(units.values()),
        "question_units": question_units,
        "states": [
            {
                **state,
                "unit": units.get(unit_id, {}),
                "evidence": evidence_by_unit.get(unit_id, []),
            }
            for unit_id, state in states.items()
        ],
        "evidence_event_count": evidence_count or 0,
        "algorithm_version": CognitiveStateService.algorithm_version,
    }


@app.post("/api/sessions/{session_id}/knowledge-state/rebuild")
def rebuild_session_knowledge_state(
    session_id: str, db: Annotated[Session, Depends(get_db)]
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    states = CognitiveStateService(db).rebuild(session)
    db.commit()
    return {"session_id": session.id, "states": states, "rebuilt": True}


@app.get("/api/sessions/{session_id}/adaptive-decisions")
def get_adaptive_decisions(session_id: str, db: Annotated[Session, Depends(get_db)]):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    decisions = db.scalars(
        select(AdaptiveDecision)
        .where(AdaptiveDecision.session_id == session.id)
        .order_by(AdaptiveDecision.created_at, AdaptiveDecision.id)
    ).all()
    return [
        {
            "id": decision.id,
            "strategy": decision.strategy,
            "action": decision.action,
            "selected_question_id": decision.selected_question_id,
            "target_difficulty": decision.target_difficulty,
            "reason_codes": decision.reason_codes,
            "candidate_scores": decision.candidate_scores,
            "policy_config": decision.policy_config,
            "policy_version": decision.policy_version,
            "turn_id": decision.turn_id,
            "created_at": decision.created_at.isoformat(),
        }
        for decision in decisions
    ]


@app.get("/api/subjects/{subject_id}/knowledge-state")
def get_subject_knowledge_state(subject_id: str, db: Annotated[Session, Depends(get_db)]):
    subject = db.get(LearnerSubject, subject_id)
    if not subject:
        raise HTTPException(404, "Learner subject not found")
    return {
        "subject_id": subject.id,
        "subject_key": subject.subject_key,
        "states": CognitiveStateService(db).subject_summary(subject.id),
    }


@app.get("/api/subjects/{subject_id}/learning-history")
def get_subject_learning_history(subject_id: str, db: Annotated[Session, Depends(get_db)]):
    subject = db.get(LearnerSubject, subject_id)
    if not subject:
        raise HTTPException(404, "Learner subject not found")
    units = {
        unit.id: unit
        for unit in db.scalars(select(KnowledgeUnit)).all()
    }
    events = db.scalars(
        select(KnowledgeEvidenceEvent)
        .where(KnowledgeEvidenceEvent.learner_subject_id == subject.id)
        .order_by(KnowledgeEvidenceEvent.created_at.desc())
        .limit(500)
    ).all()
    return {
        "subject_id": subject.id,
        "events": [
            {
                "id": event.id,
                "session_id": event.session_id,
                "turn_id": event.turn_id,
                "question_id": event.question_id,
                "knowledge_unit_id": event.knowledge_unit_id,
                "knowledge_unit_code": units.get(event.knowledge_unit_id).code
                if units.get(event.knowledge_unit_id)
                else None,
                "observation": event.observation,
                "evidence_weight": event.evidence_weight,
                "assistance_level": event.assistance_level,
                "detected_misconceptions": event.detected_misconceptions,
                "source_type": event.source_type,
                "algorithm_version": event.algorithm_version,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
    }


def memory_service(db: Session) -> LearnerMemoryService:
    if not settings.memory_identity_secret:
        raise HTTPException(
            503,
            "Long-term memory is not configured; set MEMORY_IDENTITY_SECRET",
        )
    return LearnerMemoryService(db, settings.memory_identity_secret)


def learner_identity_or_404(db: Session, identity_id: str) -> LearnerIdentity:
    identity = db.get(LearnerIdentity, identity_id)
    if not identity:
        raise HTTPException(404, "Learner identity not found")
    return identity


def serialize_identity(identity: LearnerIdentity, db: Session) -> dict:
    links = db.scalars(
        select(LearnerIdentityLink)
        .where(LearnerIdentityLink.learner_identity_id == identity.id)
        .order_by(LearnerIdentityLink.created_at, LearnerIdentityLink.id)
    ).all()
    return {
        "id": identity.id,
        "display_name": identity.display_name,
        "memory_enabled": identity.memory_enabled,
        "memory_scope": identity.memory_scope,
        "memory_write_blocked": identity.memory_write_blocked,
        "preference_inference_enabled": identity.preference_inference_enabled,
        "retest_planning_enabled": identity.retest_planning_enabled,
        "retention_days": identity.retention_days,
        "policy_version": identity.policy_version,
        "created_at": identity.created_at.isoformat(),
        "disabled_at": identity.disabled_at.isoformat() if identity.disabled_at else None,
        "links": [
            {
                "id": link.id,
                "learner_subject_id": link.learner_subject_id,
                "status": link.status,
                "provenance": link.provenance,
                "created_at": link.created_at.isoformat(),
                "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
            }
            for link in links
        ],
    }


@app.post("/api/learner-identities", status_code=201)
def create_learner_identity(
    payload: LearnerIdentityCreate, db: Annotated[Session, Depends(get_db)]
):
    service = memory_service(db)
    try:
        identity, created = service.create_identity(
            external_subject_ref=payload.external_subject_ref,
            display_name=payload.display_name,
            memory_enabled=payload.memory_enabled,
            memory_scope=payload.memory_scope,
        )
    except MemoryPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(identity)
    return {**serialize_identity(identity, db), "created": created}


@app.get("/api/learner-identities/{identity_id}")
def get_learner_identity(identity_id: str, db: Annotated[Session, Depends(get_db)]):
    return serialize_identity(learner_identity_or_404(db, identity_id), db)


@app.patch("/api/learner-identities/{identity_id}/memory-settings")
def update_memory_settings(
    identity_id: str,
    payload: MemorySettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(400, "At least one memory setting is required")
    service = memory_service(db)
    service.update_settings(identity, values)
    db.commit()
    db.refresh(identity)
    return serialize_identity(identity, db)


@app.post("/api/learner-identities/{identity_id}/links", status_code=201)
def create_identity_link(
    identity_id: str,
    payload: LearnerIdentityLinkCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    subject = db.get(LearnerSubject, payload.learner_subject_id)
    if not subject:
        raise HTTPException(404, "Learner subject not found")
    try:
        link, created = memory_service(db).link_subject(
            identity, subject, provenance=payload.provenance
        )
    except MemoryConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    db.refresh(link)
    return {
        "id": link.id,
        "learner_identity_id": link.learner_identity_id,
        "learner_subject_id": link.learner_subject_id,
        "status": link.status,
        "provenance": link.provenance,
        "created": created,
    }


@app.delete("/api/learner-identities/{identity_id}/links/{link_id}")
def revoke_identity_link(
    identity_id: str, link_id: str, db: Annotated[Session, Depends(get_db)]
):
    identity = learner_identity_or_404(db, identity_id)
    link = db.get(LearnerIdentityLink, link_id)
    if not link:
        raise HTTPException(404, "Learner identity link not found")
    try:
        memory_service(db).revoke_link(identity, link)
    except MemoryConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": link.id, "status": link.status, "revoked": True}


@app.post("/api/concepts", status_code=201)
def create_concept(payload: ConceptCreate, db: Annotated[Session, Depends(get_db)]):
    try:
        concept, created = memory_service(db).create_concept(
            namespace=payload.namespace,
            canonical_key=payload.canonical_key,
            title=payload.title,
            description=payload.description,
            language=payload.language,
        )
    except MemoryPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(concept)
    return {
        "id": concept.id,
        "namespace": concept.namespace,
        "canonical_key": concept.canonical_key,
        "title": concept.title,
        "description": concept.description,
        "language": concept.language,
        "status": concept.status,
        "version": concept.version,
        "created": created,
    }


@app.get("/api/concepts")
def list_concepts(
    db: Annotated[Session, Depends(get_db)],
    namespace: str | None = None,
    q: str | None = Query(default=None, max_length=200),
):
    query = select(Concept).where(Concept.status == "active")
    if namespace:
        try:
            query = query.where(Concept.namespace == canonical_token(namespace))
        except MemoryPolicyError as exc:
            raise HTTPException(400, str(exc)) from exc
    if q:
        query = query.where(Concept.title.ilike(f"%{q.strip()}%"))
    concepts = db.scalars(query.order_by(Concept.namespace, Concept.canonical_key)).all()
    return [
        {
            "id": concept.id,
            "namespace": concept.namespace,
            "canonical_key": concept.canonical_key,
            "title": concept.title,
            "description": concept.description,
            "language": concept.language,
            "version": concept.version,
        }
        for concept in concepts
    ]


@app.post("/api/knowledge-units/{knowledge_unit_id}/concept-mappings", status_code=201)
def create_concept_mapping(
    knowledge_unit_id: str,
    payload: ConceptMappingCreate,
    db: Annotated[Session, Depends(get_db)],
):
    unit = db.get(KnowledgeUnit, knowledge_unit_id)
    concept = db.get(Concept, payload.concept_id)
    if not unit or not concept:
        raise HTTPException(404, "Knowledge unit or concept not found")
    mapping, created = memory_service(db).create_mapping(
        knowledge_unit_id=unit.id,
        concept_id=concept.id,
        relation=payload.relation,
        confidence=payload.confidence,
        source=payload.source,
        evidence=payload.evidence,
        model_profile=payload.model_profile,
        prompt_version=payload.prompt_version,
    )
    db.commit()
    db.refresh(mapping)
    return {
        "id": mapping.id,
        "knowledge_unit_id": mapping.knowledge_unit_id,
        "concept_id": mapping.concept_id,
        "relation": mapping.relation,
        "confidence": mapping.confidence,
        "status": mapping.status,
        "source": mapping.source,
        "created": created,
    }


@app.patch("/api/concept-mappings/{mapping_id}")
def review_concept_mapping(
    mapping_id: str,
    payload: ConceptMappingReview,
    db: Annotated[Session, Depends(get_db)],
):
    mapping = db.get(KnowledgeUnitConceptMap, mapping_id)
    if not mapping:
        raise HTTPException(404, "Concept mapping not found")
    memory_service(db).review_mapping(mapping, payload.status)
    db.commit()
    db.refresh(mapping)
    return {
        "id": mapping.id,
        "status": mapping.status,
        "reviewed_at": mapping.reviewed_at.isoformat() if mapping.reviewed_at else None,
    }


@app.post("/api/learner-identities/{identity_id}/memory/import")
def import_learner_memory(
    identity_id: str,
    payload: MemoryImportCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    try:
        result = memory_service(db).import_evidence(identity, dry_run=payload.dry_run)
    except MemoryConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not payload.dry_run:
        db.commit()
    return {
        "learner_identity_id": identity.id,
        **result,
        "rebuild_required": result["imported"] > 0 and not payload.dry_run,
    }


@app.post("/api/learner-identities/{identity_id}/memory/rebuild")
def rebuild_learner_memory(
    identity_id: str,
    payload: LongitudinalRebuildCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    memory_service(db)
    service = LongitudinalStateService(db)
    try:
        states = service.rebuild(
            identity,
            algorithm_version=payload.algorithm_version,
            dry_run=payload.dry_run,
        )
    except LongitudinalStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not payload.dry_run:
        db.commit()
        states = service.states(identity)
    return {
        "learner_identity_id": identity.id,
        "algorithm_version": payload.algorithm_version,
        "dry_run": payload.dry_run,
        "state_count": len(states),
        "states": states,
    }


@app.get("/api/learner-identities/{identity_id}/concept-states")
def get_learner_concept_states(
    identity_id: str, db: Annotated[Session, Depends(get_db)]
):
    identity = learner_identity_or_404(db, identity_id)
    memory_service(db)
    states = LongitudinalStateService(db).states(identity)
    return {
        "learner_identity_id": identity.id,
        "state_count": len(states),
        "states": states,
    }


@app.get("/api/learner-identities/{identity_id}/growth")
def get_learner_growth(
    identity_id: str,
    db: Annotated[Session, Depends(get_db)],
    concept_id: str | None = None,
    algorithm_version: str = "evidence-half-life-v1",
):
    identity = learner_identity_or_404(db, identity_id)
    memory_service(db)
    try:
        series = LongitudinalStateService(db).growth(
            identity,
            concept_id=concept_id,
            algorithm_version=algorithm_version,
        )
    except LongitudinalStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "learner_identity_id": identity.id,
        "algorithm_version": algorithm_version,
        "series": series,
    }


@app.post("/api/learner-identities/{identity_id}/retest-plans", status_code=201)
def create_retest_plan(
    identity_id: str,
    payload: RetestPlanCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    memory_service(db)
    try:
        plan = LongitudinalStateService(db).create_retest_plan(
            identity,
            horizon_days=payload.horizon_days,
            max_items=payload.max_items,
            mode=payload.mode,
        )
    except LongitudinalStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return plan


@app.get("/api/learner-identities/{identity_id}/retest-plans")
def list_retest_plans(
    identity_id: str, db: Annotated[Session, Depends(get_db)]
):
    identity = learner_identity_or_404(db, identity_id)
    memory_service(db)
    return {
        "learner_identity_id": identity.id,
        "plans": LongitudinalStateService(db).plans(identity),
    }


@app.patch("/api/learner-identities/{identity_id}/retest-items/{item_id}")
def act_on_retest_item(
    identity_id: str,
    item_id: str,
    payload: RetestItemAction,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    service = RetestLifecycleService(db)
    try:
        item = service.item_for_identity(identity, item_id)
        service.act(
            identity,
            item,
            action=payload.action,
            cooldown_days=payload.cooldown_days,
        )
    except RetestLifecycleError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return service.serialize_item(item)


@app.post("/api/learner-identities/{identity_id}/retest-items/{item_id}/start")
def start_retest_session(
    identity_id: str,
    item_id: str,
    payload: RetestSessionCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    blueprint = db.get(Blueprint, payload.blueprint_id)
    if not blueprint:
        raise HTTPException(404, "Blueprint not found")
    fallback = (
        f"{settings.model_provider}:"
        f"{settings.default_model_for(settings.model_provider)}"
    )
    profile = _profiles([payload.profile] if payload.profile else [], fallback)[0]
    provider = provider_or_503(profile)
    service = RetestLifecycleService(db)
    try:
        item = service.item_for_identity(identity, item_id)
        session = service.start_session(
            identity,
            item,
            blueprint=blueprint,
            profile=profile,
        )
        turn = ExamOrchestrator(
            db,
            provider,
            project_id=session.project_id,
            session_id=session.id,
        ).start_session(session, blueprint)
    except (RetestLifecycleError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "retest_item": service.serialize_item(item),
        "turn": serialize_turn(turn),
    }


@app.post("/api/learner-identities/{identity_id}/preferences", status_code=201)
def create_learner_preference(
    identity_id: str,
    payload: PreferenceCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    service = PreferenceService(db)
    try:
        preference = service.create_or_replace(
            identity,
            preference_key=payload.preference_key,
            value=payload.value,
            source=payload.source,
            evidence=payload.evidence,
            expires_in_days=payload.expires_in_days,
        )
    except PreferencePolicyError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return service.serialize(preference)


@app.get("/api/learner-identities/{identity_id}/preferences")
def list_learner_preferences(
    identity_id: str, db: Annotated[Session, Depends(get_db)]
):
    identity = learner_identity_or_404(db, identity_id)
    preferences = PreferenceService(db).list(identity)
    db.commit()
    return {"learner_identity_id": identity.id, "preferences": preferences}


@app.patch("/api/learner-identities/{identity_id}/preferences/{preference_id}")
def act_on_learner_preference(
    identity_id: str,
    preference_id: str,
    payload: PreferenceAction,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    preference = db.get(LearnerPreference, preference_id)
    if not preference:
        raise HTTPException(404, "Preference not found")
    service = PreferenceService(db)
    try:
        service.act(
            identity,
            preference,
            action=payload.action,
            value=payload.value,
        )
    except PreferencePolicyError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return service.serialize(preference)


@app.post("/api/learner-identities/{identity_id}/memory/{event_id}/correct")
def correct_learner_memory(
    identity_id: str,
    event_id: str,
    payload: MemoryCorrectionCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    event = db.get(LearnerMemoryEvent, event_id)
    if not event:
        raise HTTPException(404, "Memory event not found")
    try:
        correction = MemoryControlService(db, settings).correct_event(
            identity,
            event,
            observation=payload.observation,
            reason=payload.reason,
        )
    except MemoryControlError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {
        "id": correction.id,
        "event_type": correction.event_type,
        "supersedes_event_id": correction.supersedes_event_id,
        "payload": correction.payload_json,
    }


@app.post("/api/learner-identities/{identity_id}/memory/export", status_code=202)
def export_learner_memory(
    identity_id: str,
    payload: MemoryExportCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    memory_service(db)
    job = enqueue_job(
        db,
        kind="memory_export",
        project_id=None,
        payload={
            "identity_id": identity.id,
            "include_source_quotes": payload.include_source_quotes,
        },
    )
    return serialize_job(job)


@app.get("/api/memory-exports/{artifact_id}/file", include_in_schema=False)
def download_memory_export(
    artifact_id: str, db: Annotated[Session, Depends(get_db)]
):
    try:
        artifact = MemoryControlService(db, settings).artifact_or_error(artifact_id)
    except MemoryControlError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(
        artifact.storage_path,
        media_type="application/json",
        filename=f"ai-examiner-memory-{artifact.id}.json",
    )


def _memory_deletion_target(payload: MemoryDeletionCreate) -> str | None:
    if payload.scope == "preference":
        return payload.preference_id
    if payload.scope == "concept":
        return payload.concept_id
    if payload.scope == "project_link":
        return payload.learner_subject_id
    return None


@app.delete("/api/learner-identities/{identity_id}/memory", status_code=202)
def delete_learner_memory_scope(
    identity_id: str,
    payload: MemoryDeletionCreate,
    db: Annotated[Session, Depends(get_db)],
):
    identity = learner_identity_or_404(db, identity_id)
    target = _memory_deletion_target(payload)
    if payload.scope in {"preference", "concept", "project_link"} and not target:
        raise HTTPException(400, f"Deletion scope {payload.scope} requires a target")
    try:
        audit = MemoryControlService(db, settings).begin_deletion(
            identity,
            scope=payload.scope,
            target_ref=target,
        )
    except MemoryControlError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    job = enqueue_job(
        db,
        kind="memory_deletion",
        project_id=None,
        payload={"audit_id": audit.id},
    )
    return {"audit_id": audit.id, "job": serialize_job(job)}


@app.get("/api/learner-identities/{identity_id}/memory-deletions")
def list_memory_deletions(
    identity_id: str, db: Annotated[Session, Depends(get_db)]
):
    learner_identity_or_404(db, identity_id)
    audits = db.scalars(
        select(MemoryDeletionAudit)
        .where(MemoryDeletionAudit.learner_identity_id == identity_id)
        .order_by(MemoryDeletionAudit.created_at.desc())
    ).all()
    return {
        "learner_identity_id": identity_id,
        "deletions": [
            {
                "id": audit.id,
                "scope": audit.scope,
                "target_ref": audit.target_ref,
                "status": audit.status,
                "counts": audit.counts_json,
                "error_code": audit.error_code,
                "created_at": audit.created_at.isoformat(),
                "completed_at": audit.completed_at.isoformat()
                if audit.completed_at
                else None,
            }
            for audit in audits
        ],
    }


@app.post("/api/memory-deletions/{audit_id}/retry", status_code=202)
def retry_memory_deletion(
    audit_id: str, db: Annotated[Session, Depends(get_db)]
):
    audit = db.get(MemoryDeletionAudit, audit_id)
    if not audit or not audit.learner_identity_id:
        raise HTTPException(404, "Memory deletion audit not found")
    if audit.status != "failed":
        raise HTTPException(409, "Only failed deletion jobs can be retried")
    identity = learner_identity_or_404(db, audit.learner_identity_id)
    identity.memory_write_blocked = True
    audit.status = "pending"
    audit.error_code = None
    audit.completed_at = None
    db.commit()
    job = enqueue_job(
        db,
        kind="memory_deletion",
        project_id=None,
        payload={"audit_id": audit.id},
    )
    return {"audit_id": audit.id, "job": serialize_job(job)}


@app.get("/api/learner-identities/{identity_id}/memory-center")
def get_memory_center(
    identity_id: str, db: Annotated[Session, Depends(get_db)]
):
    identity = learner_identity_or_404(db, identity_id)
    longitudinal = LongitudinalStateService(db)
    preferences = PreferenceService(db).list(identity)
    db.commit()
    return {
        "identity": serialize_identity(identity, db),
        "concept_states": longitudinal.states(identity),
        "growth": longitudinal.growth(identity),
        "preferences": preferences,
        "retest_plans": longitudinal.plans(identity),
        "labels": {
            "observed": "Direct evidence recorded from an attempt",
            "predicted": "Time-adjusted estimate, not a new observation",
        },
    }


@app.post("/api/evaluations/longitudinal")
def evaluate_longitudinal_engine():
    return LongitudinalEvaluationService().run()


@app.get("/api/learner-identities/{identity_id}/memory")
def get_learner_memory(
    identity_id: str,
    db: Annotated[Session, Depends(get_db)],
    category: str | None = None,
    concept_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    learner_identity_or_404(db, identity_id)
    query = select(LearnerMemoryEvent).where(
        LearnerMemoryEvent.learner_identity_id == identity_id,
        LearnerMemoryEvent.deleted_at.is_(None),
    )
    if category:
        query = query.where(LearnerMemoryEvent.event_type == category)
    if concept_id:
        query = query.where(LearnerMemoryEvent.concept_id == concept_id)
    events = db.scalars(
        query.order_by(LearnerMemoryEvent.occurred_at.desc(), LearnerMemoryEvent.id).limit(
            limit
        )
    ).all()
    concepts = {
        concept.id: concept
        for concept in db.scalars(
            select(Concept).where(
                Concept.id.in_({event.concept_id for event in events if event.concept_id})
            )
        ).all()
    }
    return {
        "learner_identity_id": identity_id,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "learner_subject_id": event.learner_subject_id,
                "concept_id": event.concept_id,
                "concept_title": concepts[event.concept_id].title
                if event.concept_id in concepts
                else None,
                "source_evidence_event_id": event.source_evidence_event_id,
                "payload": event.payload_json,
                "occurred_at": event.occurred_at.isoformat(),
                "recorded_at": event.recorded_at.isoformat(),
                "policy_version": event.policy_version,
                "algorithm_version": event.algorithm_version,
                "supersedes_event_id": event.supersedes_event_id,
            }
            for event in events
        ],
    }


@app.get("/api/metrics")
def metrics(db: Annotated[Session, Depends(get_db)]):
    events = db.scalars(select(UsageEvent).order_by(UsageEvent.created_at.desc()).limit(1000)).all()
    latencies = sorted(event.latency_ms for event in events if event.latency_ms > 0)
    p50 = latencies[(len(latencies) - 1) // 2] if latencies else None
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    return {
        "calls": len(events),
        "input_tokens": sum(event.input_tokens for event in events),
        "output_tokens": sum(event.output_tokens for event in events),
        "estimated_cost_usd": round(sum(event.estimated_cost_usd for event in events), 6),
        "latency_ms": {"samples": len(latencies), "p50": p50, "p95": p95},
        "retries": sum(event.retry_count for event in events),
        "json_repairs": sum(1 for event in events if event.json_repair_used),
        "by_agent": {
            agent: sum(1 for event in events if event.agent == agent)
            for agent in sorted({event.agent for event in events})
        },
        "by_provider": {
            provider: {
                "calls": sum(1 for event in events if event.provider == provider),
                "estimated_cost_usd": round(
                    sum(
                        event.estimated_cost_usd
                        for event in events
                        if event.provider == provider
                    ),
                    6,
                ),
            }
            for provider in sorted({event.provider for event in events})
        },
    }


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, db: Annotated[Session, Depends(get_db)]):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    upload_path = settings.upload_dir / project_id
    affected_identity_ids = set(
        db.scalars(
            select(LearnerIdentityLink.learner_identity_id)
            .join(
                LearnerSubject,
                LearnerSubject.id == LearnerIdentityLink.learner_subject_id,
            )
            .where(LearnerSubject.project_id == project_id)
        ).all()
    )
    for run in db.scalars(
        select(BenchmarkRun).where(BenchmarkRun.project_id == project_id)
    ).all():
        db.delete(run)
    dataset_ids = db.scalars(
        select(GoldenDataset.id).where(GoldenDataset.project_id == project_id)
    ).all()
    if dataset_ids:
        for rating in db.scalars(
            select(ExpertRating).where(ExpertRating.golden_dataset_id.in_(dataset_ids))
        ).all():
            db.delete(rating)
        for dataset in db.scalars(
            select(GoldenDataset).where(GoldenDataset.project_id == project_id)
        ).all():
            db.delete(dataset)
    db.delete(project)
    db.flush()
    longitudinal = LongitudinalStateService(db)
    for identity_id in affected_identity_ids:
        for plan in db.scalars(
            select(RetestPlan).where(RetestPlan.learner_identity_id == identity_id)
        ).all():
            db.delete(plan)
        identity = db.get(LearnerIdentity, identity_id)
        if identity:
            algorithm_version = db.scalar(
                select(LearnerConceptState.algorithm_version).where(
                    LearnerConceptState.learner_identity_id == identity_id
                )
            ) or "evidence-half-life-v1"
            longitudinal.rebuild(
                identity,
                algorithm_version=algorithm_version,
                dry_run=False,
            )
    db.commit()
    if upload_path.exists():
        shutil.rmtree(upload_path, ignore_errors=True)
    return {"deleted": project_id}


def run() -> None:
    import uvicorn

    uvicorn.run("ai_examiner.main:app", host="0.0.0.0", port=8000, reload=False)


@app.get("/api/projects/{project_id}/documents")
def list_documents(project_id: str, db: Annotated[Session, Depends(get_db)]):
    documents = db.scalars(
        select(Document).where(Document.project_id == project_id).order_by(Document.created_at.desc())
    ).all()
    return [
        {
            "id": document.id,
            "filename": document.filename,
            "content_type": document.content_type,
            "char_count": document.char_count,
            "page_count": len(document.page_map or []),
            "warnings": document.parse_warnings,
            "created_at": document.created_at.isoformat(),
        }
        for document in documents
    ]


@app.get("/api/documents/{document_id}/evidence")
def get_document_evidence(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    kind: str | None = None,
    page: int | None = None,
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    query = select(EvidenceAsset).where(EvidenceAsset.document_id == document_id)
    if kind:
        query = query.where(EvidenceAsset.kind == kind)
    if page:
        query = query.where(EvidenceAsset.page_number == page)
    assets = db.scalars(query.order_by(EvidenceAsset.page_number, EvidenceAsset.sequence)).all()
    return {
        "document_id": document.id,
        "filename": document.filename,
        "page_map": document.page_map,
        "assets": [serialize_asset(asset) for asset in assets],
    }


@app.get("/api/evidence/{asset_id}/file", include_in_schema=False)
def get_evidence_file(asset_id: str, db: Annotated[Session, Depends(get_db)]):
    asset = db.get(EvidenceAsset, asset_id)
    if not asset or not asset.storage_path:
        raise HTTPException(404, "Evidence file not found")
    path = Path(asset.storage_path)
    if not path.exists():
        raise HTTPException(404, "Evidence file is missing on disk")
    return FileResponse(path, media_type=asset.mime_type or "application/octet-stream")


@app.get("/api/evidence/{asset_id}/highlight", include_in_schema=False)
def get_evidence_highlight(asset_id: str, db: Annotated[Session, Depends(get_db)]):
    asset = db.get(EvidenceAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Evidence asset not found")
    page_asset = db.scalar(
        select(EvidenceAsset).where(
            EvidenceAsset.document_id == asset.document_id,
            EvidenceAsset.page_number == asset.page_number,
            EvidenceAsset.kind == "page",
        )
    )
    if not page_asset:
        raise HTTPException(404, "Page preview not found")
    try:
        output = create_highlighted_crop(asset, page_asset, settings.evidence_dir / "crops")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(output, media_type="image/png")


@app.post("/api/documents/{document_id}/visual-analyses", status_code=202)
def analyze_document_visuals(
    document_id: str,
    payload: VisualAnalyzeCreate,
    db: Annotated[Session, Depends(get_db)],
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    project = db.get(Project, document.project_id)
    profile = payload.profile or settings.visual_default_profile
    _profiles([profile], settings.visual_default_profile)
    if payload.asynchronous and not settings.celery_always_eager:
        job = enqueue_job(
            db,
            kind="visual_document",
            project_id=project.id,
            payload={
                "project_id": project.id,
                "document_id": document.id,
                "profile": profile,
                "max_pages": payload.max_pages,
            },
        )
        return {"mode": "async", "job": serialize_job(job)}
    analyses = VisualEvidenceService(db, settings, project.id).analyze_document(
        document, profile, project.language, payload.max_pages
    )
    return {
        "mode": "sync",
        "count": len(analyses),
        "analyses": [
            {
                "id": item.id,
                "evidence_asset_id": item.evidence_asset_id,
                "provider": item.provider,
                "model": item.model,
                "data": item.data,
            }
            for item in analyses
        ],
    }


@app.get("/api/documents/{document_id}/visual-analyses")
def list_visual_analyses(document_id: str, db: Annotated[Session, Depends(get_db)]):
    analyses = db.scalars(
        select(VisualAnalysis)
        .where(VisualAnalysis.document_id == document_id)
        .order_by(VisualAnalysis.created_at.desc())
    ).all()
    return [
        {
            "id": item.id,
            "evidence_asset_id": item.evidence_asset_id,
            "provider": item.provider,
            "model": item.model,
            "prompt_version": item.prompt_version,
            "status": item.status,
            "data": item.data,
            "created_at": item.created_at.isoformat(),
        }
        for item in analyses
    ]


@app.post("/api/projects/{project_id}/joint-analyses", status_code=201)
def create_joint_analysis(
    project_id: str,
    payload: JointAnalysisCreate,
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    documents = [db.get(Document, document_id) for document_id in payload.document_ids]
    if any(document is None or document.project_id != project_id for document in documents):
        raise HTTPException(400, "All documents must belong to the project")
    profile = payload.profile or f"{settings.model_provider}:{settings.default_model_for(settings.model_provider)}"
    _profiles([profile], profile)
    try:
        analysis = JointAnalysisService(db, settings, project_id).run(
            documents, profile, project.language
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"Joint analysis failed: {exc}") from exc
    return {
        "id": analysis.id,
        "document_ids": analysis.document_ids,
        "provider": analysis.provider,
        "model": analysis.model,
        "data": analysis.data,
    }


@app.get("/api/projects/{project_id}/joint-analyses")
def list_joint_analyses(project_id: str, db: Annotated[Session, Depends(get_db)]):
    rows = db.scalars(
        select(JointAnalysis)
        .where(JointAnalysis.project_id == project_id)
        .order_by(JointAnalysis.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "document_ids": row.document_ids,
            "provider": row.provider,
            "model": row.model,
            "prompt_version": row.prompt_version,
            "data": row.data,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.patch("/api/golden-datasets/{dataset_id}/status")
def update_dataset_status(
    dataset_id: str,
    payload: DatasetStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    try:
        dataset = set_dataset_status(db, dataset, payload.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return serialize_dataset(dataset, include_data=False)


@app.get("/api/golden-datasets/{left_id}/diff/{right_id}")
def compare_datasets(
    left_id: str,
    right_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    left = db.get(GoldenDataset, left_id)
    right = db.get(GoldenDataset, right_id)
    if not left or not right:
        raise HTTPException(404, "Golden Dataset not found")
    if left.project_id != right.project_id:
        raise HTTPException(400, "Datasets must belong to the same project")
    return dataset_diff(left, right)


@app.get("/api/prompts")
def list_prompts(db: Annotated[Session, Depends(get_db)]):
    prompts = db.scalars(
        select(PromptVersion).order_by(PromptVersion.name, PromptVersion.version.desc())
    ).all()
    return {
        "active_manifest": prompt_manifest(db),
        "versions": [
            {
                "id": prompt.id,
                "name": prompt.name,
                "version": prompt.version,
                "role": prompt.role,
                "status": prompt.status,
                "content": prompt.content,
                "schema_hint": prompt.schema_hint,
                "metadata": prompt.metadata_json,
                "created_at": prompt.created_at.isoformat(),
            }
            for prompt in prompts
        ],
    }


@app.post("/api/prompts", status_code=201)
def add_prompt_version(
    payload: PromptVersionCreate,
    db: Annotated[Session, Depends(get_db)],
):
    prompt = create_prompt_version(
        db,
        name=payload.name,
        role=payload.role,
        content=payload.content,
        schema_hint=payload.schema_hint,
        metadata=payload.metadata,
        activate=payload.activate,
    )
    return {"id": prompt.id, "name": prompt.name, "version": prompt.version, "status": prompt.status}


@app.post("/api/prompts/{prompt_id}/activate")
def activate_prompt_version(prompt_id: str, db: Annotated[Session, Depends(get_db)]):
    prompt = db.get(PromptVersion, prompt_id)
    if not prompt:
        raise HTTPException(404, "Prompt version not found")
    prompt = activate_prompt(db, prompt)
    return {"id": prompt.id, "name": prompt.name, "version": prompt.version, "status": prompt.status}


@app.post("/api/projects/{project_id}/golden-datasets/async", status_code=202)
def generate_golden_dataset_async(
    project_id: str,
    payload: GoldenDatasetCreate,
    db: Annotated[Session, Depends(get_db)],
):
    project = db.get(Project, project_id)
    document = db.get(Document, payload.document_id)
    if not project or not document or document.project_id != project_id:
        raise HTTPException(404, "Project or document not found")
    profiles = _profiles(payload.profiles, settings.golden_default_profiles)
    consensus_profile = payload.consensus_profile or profiles[0]
    if consensus_profile not in profiles:
        profiles.append(consensus_profile)
    job = enqueue_job(
        db,
        kind="golden_dataset",
        project_id=project_id,
        payload={
            "project_id": project_id,
            "document_id": document.id,
            "profiles": profiles,
            "consensus_profile": consensus_profile,
            "question_count": payload.question_count,
        },
    )
    return serialize_job(job)


@app.post("/api/golden-datasets/{dataset_id}/benchmarks/async", status_code=202)
def run_benchmark_async(
    dataset_id: str,
    payload: BenchmarkCreate,
    db: Annotated[Session, Depends(get_db)],
):
    dataset = db.get(GoldenDataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Golden Dataset not found")
    profiles = _profiles(payload.profiles, settings.benchmark_default_profiles)
    job = enqueue_job(
        db,
        kind="benchmark",
        project_id=dataset.project_id,
        payload={
            "dataset_id": dataset.id,
            "profiles": profiles,
            "case_limit": payload.case_limit,
            "run_planner": payload.run_planner,
            "run_analyzer": payload.run_analyzer,
        },
    )
    return serialize_job(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, db: Annotated[Session, Depends(get_db)]):
    job = db.get(BackgroundJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return serialize_job(job)


@app.get("/api/projects/{project_id}/jobs")
def list_jobs(project_id: str, db: Annotated[Session, Depends(get_db)]):
    jobs = db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.project_id == project_id)
        .order_by(BackgroundJob.created_at.desc())
        .limit(100)
    ).all()
    return [serialize_job(job) for job in jobs]


@app.get("/api/provider-health")
def provider_health(db: Annotated[Session, Depends(get_db)]):
    latest = db.scalars(select(UsageEvent).order_by(UsageEvent.created_at.desc()).limit(100)).all()
    result = []
    for entry in CATALOG:
        provider_events = [event for event in latest if event.provider == entry.provider]
        result.append(
            {
                **entry.public_dict(profile_ready(settings, entry.id)),
                "status": "available" if profile_ready(settings, entry.id) else "missing_key",
                "recent_calls": len(provider_events),
                "recent_cost_usd": round(sum(event.estimated_cost_usd for event in provider_events), 6),
                "last_used_at": provider_events[0].created_at.isoformat() if provider_events else None,
            }
        )
    return result


@app.get("/api/costs")
def cost_dashboard(
    db: Annotated[Session, Depends(get_db)],
    project_id: str | None = None,
):
    query = select(UsageEvent)
    if project_id:
        query = query.where(UsageEvent.project_id == project_id)
    events = db.scalars(query.order_by(UsageEvent.created_at.desc()).limit(10000)).all()
    total = sum(event.estimated_cost_usd for event in events)
    by_model: dict[str, dict] = {}
    for event in events:
        key = f"{event.provider}:{event.model}"
        item = by_model.setdefault(
            key,
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "latencies": [],
                "retries": 0,
                "json_repairs": 0,
            },
        )
        item["calls"] += 1
        item["input_tokens"] += event.input_tokens
        item["output_tokens"] += event.output_tokens
        item["cost_usd"] += event.estimated_cost_usd
        if event.latency_ms > 0:
            item["latencies"].append(event.latency_ms)
        item["retries"] += event.retry_count
        item["json_repairs"] += int(event.json_repair_used)
    for item in by_model.values():
        item["cost_usd"] = round(item["cost_usd"], 6)
        latencies = sorted(item.pop("latencies"))
        item["latency_ms"] = {
            "samples": len(latencies),
            "p50": latencies[(len(latencies) - 1) // 2] if latencies else None,
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
            if latencies
            else None,
        }
    budget = settings.project_model_budget_usd if project_id else settings.daily_model_budget_usd
    return {
        "project_id": project_id,
        "estimated_cost_usd": round(total, 6),
        "budget_usd": budget,
        "budget_used_ratio": round(total / budget, 4) if budget else None,
        "over_budget": bool(budget and total >= budget),
        "by_model": by_model,
    }


def serialize_voice_session(voice: VoiceSession, db: Session, *, include_events: bool = False) -> dict:
    exam = db.get(ExamSession, voice.exam_session_id)
    payload = {
        "id": voice.id,
        "project_id": voice.project_id,
        "blueprint_id": voice.blueprint_id,
        "exam_session_id": voice.exam_session_id,
        "provider": voice.provider,
        "model": voice.model,
        "voice": voice.voice,
        "status": voice.status,
        "question_strategy": exam.question_strategy if exam else "fixed",
        "learner_subject_id": exam.learner_subject_id if exam else None,
        "template_version_id": exam.template_version_id if exam else None,
        "template_fingerprint": exam.template_fingerprint if exam else None,
        "config": {key: value for key, value in (voice.config or {}).items() if key != "instructions"},
        "metrics": voice.metrics,
        "started_at": voice.started_at.isoformat() if voice.started_at else None,
        "completed_at": voice.completed_at.isoformat() if voice.completed_at else None,
        "created_at": voice.created_at.isoformat(),
    }
    if include_events:
        rows = db.scalars(
            select(VoiceEvent)
            .where(VoiceEvent.voice_session_id == voice.id)
            .order_by(VoiceEvent.created_at)
        ).all()
        payload["events"] = [
            {
                "id": row.id,
                "event_type": row.event_type,
                "role": row.role,
                "text": row.text,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    return payload


@app.get("/api/voice/config")
def voice_config():
    providers = [
        {
            "id": provider,
            "label": config["label"],
            "ready": voice_provider_ready(provider, settings),
            "model": model_for(provider, settings),
            "default_voice": default_voice_for(provider, settings),
            "voices": list(config["voices"]),
            "supports_ptt": config["supports_ptt"],
            "max_dialog_turns": 8 if provider == "qwen" else None,
        }
        for provider, config in VOICE_PROVIDERS.items()
    ]
    default_provider = next((item for item in providers if item["ready"]), providers[0])
    return {
        "ready": any(item["ready"] for item in providers),
        "provider": default_provider["id"],
        "model": default_provider["model"],
        "default_voice": default_provider["default_voice"],
        "voices": default_provider["voices"],
        "providers": providers,
        "default_vad_eagerness": settings.realtime_vad_eagerness,
        "max_session_minutes": settings.realtime_session_max_minutes,
        "requires_secure_context": True,
    }


@app.post("/api/voice/sessions", status_code=201)
def start_voice_session(
    payload: VoiceSessionCreate,
    db: Annotated[Session, Depends(get_db)],
):
    if not voice_provider_ready(payload.provider, settings):
        raise HTTPException(503, f"{payload.provider} realtime voice is not configured")
    project = db.get(Project, payload.project_id)
    blueprint = db.get(Blueprint, payload.blueprint_id)
    if not project or not blueprint or blueprint.project_id != project.id:
        raise HTTPException(404, "Project or blueprint not found")
    cognitive = CognitiveStateService(db)
    cognitive.ensure_blueprint_graph(blueprint)
    subject = cognitive.get_or_create_subject(project.id, payload.learner_subject_key)
    if payload.analysis_profile:
        _profiles([payload.analysis_profile], payload.analysis_profile)
    question_limit = (
        min(payload.question_limit, 4)
        if payload.provider == "qwen"
        else payload.question_limit
    )
    max_followups = (
        min(payload.max_followups, 1)
        if payload.provider == "qwen"
        else payload.max_followups
    )
    request_overrides: dict[str, object] = {"voice_provider": payload.provider}
    fields = payload.model_fields_set
    if "question_limit" in fields or payload.provider == "qwen":
        request_overrides["question_limit"] = question_limit
    if "max_followups" in fields or payload.provider == "qwen":
        request_overrides["max_followups_per_question"] = max_followups
    if "question_strategy" in fields:
        request_overrides["question_strategy"] = payload.question_strategy
    resolved_template = SessionTemplateService(db).resolve(
        project,
        mode=payload.mode,
        template_version_id=payload.template_version_id,
        template_overrides=payload.template_overrides,
        request_overrides=request_overrides,
    )
    mode = payload.mode
    question_strategy = payload.question_strategy
    if resolved_template:
        legacy = resolved_template.legacy
        mode = resolved_template.effective_mode
        question_limit = legacy["question_limit"]
        max_followups = legacy["max_followups_per_question"]
        question_strategy = legacy["question_strategy"]
    conversation_policy = effective_conversation_policy(
        resolved_template.snapshot if resolved_template else None,
        user_allows_active_interruption=payload.allow_active_interruptions,
        legacy_config={
            "allow_hints": True,
            "allow_corrections": True,
            "max_followups_per_question": max_followups,
        },
    )
    try:
        voice = create_voice_session(
            db,
            project=project,
            blueprint=blueprint,
            settings=settings,
            provider=payload.provider,
            mode=mode,
            language=payload.language,
            voice=payload.voice,
            vad_eagerness=payload.vad_eagerness,
            question_limit=question_limit,
            max_followups=max_followups,
            question_strategy=question_strategy,
            learner_subject_id=subject.id if subject else None,
            analysis_profile=payload.analysis_profile,
            resolved_template=resolved_template,
            conversation_policy=conversation_policy,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = serialize_voice_session(voice, db)
    if voice.provider == "qwen":
        result["client_config"] = qwen_realtime_session_config(voice)
    return result


@app.post("/api/voice/sessions/{voice_session_id}/sdp")
async def create_voice_sdp(
    voice_session_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    voice = db.get(VoiceSession, voice_session_id)
    if not voice:
        raise HTTPException(404, "Voice session not found")
    if voice.provider == "qwen":
        raise HTTPException(400, "Qwen realtime voice uses the WebSocket proxy")
    body = await request.body()
    if not body or len(body) > 200_000:
        raise HTTPException(400, "Invalid SDP payload")
    status_code, text, content_type = await create_realtime_call(
        sdp=body.decode("utf-8", errors="strict"),
        session=voice,
        settings=settings,
    )
    if status_code >= 400:
        raise HTTPException(status_code, text[:2000])
    voice.status = "connected"
    voice.started_at = voice.started_at or datetime.now(UTC)
    exam = db.get(ExamSession, voice.exam_session_id)
    if exam:
        exam.status = "voice_active"
        exam.state = "VOICE_ACTIVE"
        exam.started_at = exam.started_at or voice.started_at
    db.commit()
    return Response(content=text, media_type=content_type)


@app.websocket("/api/voice/sessions/{voice_session_id}/qwen-ws")
async def qwen_voice_websocket(websocket: WebSocket, voice_session_id: str):
    await websocket.accept()
    with SessionLocal() as db:
        voice = db.get(VoiceSession, voice_session_id)
        if not voice or voice.provider != "qwen":
            await websocket.close(code=1008, reason="Qwen voice session not found")
            return
        if not settings.dashscope_api_key:
            await websocket.close(code=1011, reason="Qwen realtime voice is not configured")
            return
        model = voice.model

    upstream_url = f"{settings.qwen_realtime_ws_url}?{urlencode({'model': model})}"
    try:
        async with websockets.connect(
            upstream_url,
            additional_headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            open_timeout=20,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
        ) as upstream:
            with SessionLocal() as db:
                voice = db.get(VoiceSession, voice_session_id)
                if voice:
                    voice.status = "connected"
                    voice.started_at = voice.started_at or datetime.now(UTC)
                    exam = db.get(ExamSession, voice.exam_session_id)
                    if exam:
                        exam.status = "voice_active"
                        exam.state = "VOICE_ACTIVE"
                        exam.started_at = exam.started_at or voice.started_at
                    db.commit()

            async def browser_to_qwen() -> None:
                while True:
                    await upstream.send(await websocket.receive_text())

            async def qwen_to_browser() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")
                    await websocket.send_text(message)

            tasks = {
                asyncio.create_task(browser_to_qwen()),
                asyncio.create_task(qwen_to_browser()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*done)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json(
                {"type": "error", "error": {"message": f"Qwen realtime connection failed: {exc}"}}
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass


@app.post("/api/voice/sessions/{voice_session_id}/events", status_code=201)
def add_voice_event(
    voice_session_id: str,
    payload: VoiceEventCreate,
    db: Annotated[Session, Depends(get_db)],
):
    voice = db.get(VoiceSession, voice_session_id)
    if not voice:
        raise HTTPException(404, "Voice session not found")
    event = record_voice_event(
        db,
        voice,
        event_type=payload.event_type,
        role=payload.role,
        text=payload.text,
        latency_ms=payload.latency_ms,
        raw=payload.raw,
    )
    if payload.text and payload.role in {"user", "assistant"}:
        db.add(
            Turn(
                session_id=voice.exam_session_id,
                role=payload.role,
                kind="voice_transcript",
                content=payload.text,
            )
        )
        db.commit()
    return {"id": event.id, "metrics": voice.metrics}


@app.get("/api/voice/sessions/{voice_session_id}")
def get_voice_session(
    voice_session_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    voice = db.get(VoiceSession, voice_session_id)
    if not voice:
        raise HTTPException(404, "Voice session not found")
    return serialize_voice_session(voice, db, include_events=True)


@app.post("/api/voice/sessions/{voice_session_id}/complete")
def complete_voice_session(
    voice_session_id: str,
    payload: VoiceSessionComplete,
    db: Annotated[Session, Depends(get_db)],
):
    voice = db.get(VoiceSession, voice_session_id)
    if not voice:
        raise HTTPException(404, "Voice session not found")
    now = datetime.now(UTC)
    voice.status = "completed"
    voice.completed_at = now
    metrics = dict(voice.metrics or {})
    metrics["completion_reason"] = payload.reason
    if voice.started_at:
        started_at = voice.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        metrics["duration_seconds"] = max(0, int((now - started_at).total_seconds()))
    exam = db.get(ExamSession, voice.exam_session_id)
    if exam:
        if exam.question_strategy == "adaptive":
            blueprint = db.get(Blueprint, exam.blueprint_id)
            finalized = ExamOrchestrator(
                db,
                provider_or_503(exam.config.get("profile")),
                project_id=exam.project_id,
                session_id=exam.id,
            ).finalize_voice_transcripts(exam, blueprint)
            metrics["cognitive_finalized_turns"] = max(
                int(metrics.get("cognitive_finalized_turns", 0)), len(finalized)
            )
        exam.status = "completed"
        exam.state = "VOICE_COMPLETED"
        exam.completed_at = now
    voice.metrics = metrics
    db.commit()
    return serialize_voice_session(voice, db, include_events=True)
