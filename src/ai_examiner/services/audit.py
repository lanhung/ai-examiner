from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import SessionLocal
from ..models import AuditEvent, Organization
from .authorization import RoutePolicy
from .tenancy import set_tenant_context

AUDIT_SCHEMA_VERSION = 1
AUDITED_BEHAVIORS = frozenset(
    {"authentication", "administrative", "read_sensitive"}
)
SAFE_METADATA_KEYS = frozenset(
    {
        "audit_class",
        "capability",
        "changed_fields",
        "http_method",
        "job_kind",
        "membership_role",
        "membership_status",
        "recovered_count",
        "route_template",
        "status_code",
        "terminal_status",
    }
)
FORBIDDEN_KEY_FRAGMENTS = (
    "answer",
    "authorization",
    "body",
    "content",
    "cookie",
    "document",
    "header",
    "key",
    "password",
    "prompt",
    "secret",
    "text",
    "token",
    "transcript",
    "url",
)
SECRET_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"AIza[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bcanary[_:-][A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"[?&](?:x-amz-|signature|token|key)[^=\s]*=", re.IGNORECASE),
)
TRACEPARENT_PATTERN = re.compile(
    r"^[\da-fA-F]{2}-([\da-fA-F]{32})-([\da-fA-F]{16})-[\da-fA-F]{2}$"
)
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,160}$")


class AuditWriteError(RuntimeError):
    """Raised when a required audit event cannot be persisted."""


@dataclass(frozen=True)
class AuditFilters:
    actor_id: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: str | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    request_id: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def initialize_request_audit_context(request: Request) -> None:
    request_id = str(uuid4())
    trace_id = request_id.replace("-", "")
    traceparent = request.headers.get("traceparent", "").strip()
    matched = TRACEPARENT_PATTERN.fullmatch(traceparent)
    if matched and matched.group(1) != "0" * 32:
        trace_id = matched.group(1).lower()
    request.state.request_id = request_id
    request.state.trace_id = trace_id
    request.state.audit_actor_type = "anonymous"
    request.state.audit_actor_id = None
    request.state.audit_authentication_method = "unknown"
    request.state.audit_reason_code = ""


def mark_authentication(
    request: Request,
    *,
    principal_id: str | None,
    method: str,
) -> None:
    request.state.audit_actor_type = "principal" if principal_id else "anonymous"
    request.state.audit_actor_id = _safe_identifier(principal_id)
    request.state.audit_authentication_method = _safe_code(method, "unknown")


def mark_authorization_denial(request: Request, reason_code: str) -> None:
    request.state.audit_reason_code = _safe_code(
        reason_code,
        "authorization_denied",
    )


def _safe_code(value: str | None, fallback: str = "") -> str:
    candidate = (value or "").strip()
    if SAFE_IDENTIFIER_PATTERN.fullmatch(candidate):
        return candidate[:160]
    return fallback


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _safe_identifier(value: str | None) -> str | None:
    candidate = (value or "").strip()
    if not candidate or not SAFE_IDENTIFIER_PATTERN.fullmatch(candidate):
        return None
    if _contains_secret(candidate):
        return None
    return candidate[:160]


def _redact_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    candidate = str(value).strip()
    if not candidate or len(candidate) > 160 or _contains_secret(candidate):
        return "[REDACTED]"
    if not SAFE_IDENTIFIER_PATTERN.fullmatch(candidate):
        return "[REDACTED]"
    return candidate


def redact_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for raw_key, raw_value in (metadata or {}).items():
        key = str(raw_key).strip().lower()
        if (
            key not in SAFE_METADATA_KEYS
            or any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS)
        ):
            continue
        if key == "changed_fields":
            if not isinstance(raw_value, (list, tuple, set)):
                continue
            values = [
                value
                for item in raw_value
                if (value := _safe_identifier(str(item))) is not None
            ]
            sanitized[key] = sorted(set(values))[:32]
            continue
        if key == "route_template":
            candidate = str(raw_value).strip()
            if (
                len(candidate) <= 240
                and candidate.startswith("/api/v1/")
                and re.fullmatch(r"/[A-Za-z0-9_/{}/.-]+", candidate)
            ):
                sanitized[key] = candidate
            continue
        sanitized[key] = _redact_scalar(raw_value)
    return sanitized


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _event_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _source_ip_details(
    request: Request,
    settings: Settings,
) -> tuple[str, str | None]:
    raw = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return "unknown", None
    if address.is_loopback:
        classification = "loopback"
    elif address.is_private:
        classification = "private"
    else:
        classification = "public"
    secret = settings.audit_ip_hash_key
    if secret is None:
        if settings.app_env == "production":
            return classification, None
        key = b"ai-examiner-development-audit-key"
    else:
        key = secret.get_secret_value().encode("utf-8")
    digest = hmac.new(key, address.compressed.encode("ascii"), hashlib.sha256)
    return classification, digest.hexdigest()


def _user_agent_family(request: Request) -> str:
    user_agent = request.headers.get("User-Agent", "").lower()
    for marker, family in (
        ("edg/", "edge"),
        ("chrome/", "chrome"),
        ("firefox/", "firefox"),
        ("safari/", "safari"),
        ("curl/", "curl"),
        ("python-httpx/", "python-httpx"),
        ("postmanruntime/", "postman"),
    ):
        if marker in user_agent:
            return family
    return "other" if user_agent else "unknown"


def append_audit_event(
    db: Session,
    *,
    organization_id: str | None,
    actor_type: str,
    actor_id: str | None,
    authentication_method: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    reason_code: str,
    request_id: str,
    trace_id: str,
    source_ip_class: str = "unknown",
    source_ip_hash: str | None = None,
    user_agent_family: str = "unknown",
    metadata: dict[str, Any] | None = None,
    retention_class: str = "administrative",
    settings: Settings | None = None,
) -> AuditEvent:
    selected_settings = settings or get_settings()
    occurred_at = utcnow()
    event_id = str(uuid4())
    safe_metadata = redact_audit_metadata(metadata)
    payload = {
        "id": event_id,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "organization_id": organization_id,
        "actor_type": actor_type,
        "actor_id": _safe_identifier(actor_id),
        "authentication_method": _safe_code(authentication_method, "unknown"),
        "action": _safe_code(action, "unknown"),
        "resource_type": _safe_code(resource_type, "none"),
        "resource_id": _safe_identifier(resource_id),
        "outcome": outcome,
        "reason_code": _safe_code(reason_code),
        "request_id": _safe_code(request_id, str(uuid4())),
        "trace_id": _safe_code(trace_id, uuid4().hex),
        "source_ip_class": source_ip_class,
        "source_ip_hash": source_ip_hash,
        "user_agent_family": _safe_code(user_agent_family, "unknown"),
        "metadata_json": safe_metadata,
        "retention_class": retention_class,
        "retention_until": (
            occurred_at + timedelta(days=selected_settings.audit_retention_days)
        ).isoformat(),
        "occurred_at": occurred_at.isoformat(),
    }
    event = AuditEvent(
        id=event_id,
        schema_version=AUDIT_SCHEMA_VERSION,
        organization_id=organization_id,
        actor_type=actor_type,
        actor_id=payload["actor_id"],
        authentication_method=payload["authentication_method"],
        action=payload["action"],
        resource_type=payload["resource_type"],
        resource_id=payload["resource_id"],
        outcome=outcome,
        reason_code=payload["reason_code"],
        request_id=payload["request_id"],
        trace_id=payload["trace_id"],
        source_ip_class=source_ip_class,
        source_ip_hash=source_ip_hash,
        user_agent_family=payload["user_agent_family"],
        metadata_json=safe_metadata,
        event_digest=_event_digest(payload),
        retention_class=retention_class,
        retention_until=occurred_at
        + timedelta(days=selected_settings.audit_retention_days),
        occurred_at=occurred_at,
    )
    db.add(event)
    db.flush()
    return event


def route_audit_action(method: str, route_template: str) -> str:
    path = route_template.removeprefix("/api/v1/").strip("/")
    normalized = re.sub(r"[{}]", "", path).replace("/", ".").replace("-", "_")
    operation = {
        "GET": "read",
        "POST": "create",
        "PUT": "replace",
        "PATCH": "update",
        "DELETE": "delete",
    }.get(method.upper(), method.lower())
    return _safe_code(f"api.{normalized}.{operation}", "api.request")


def _resource_id_for_request(request: Request, resolver: str) -> str | None:
    parameter = {
        "organization": "organization_id",
        "organization_membership": "membership_id",
        "document": "document_id",
        "evidence_asset": "asset_id",
        "memory_export_artifact": "artifact_id",
        "background_job": "job_id",
    }.get(resolver)
    if parameter is None:
        return None
    return _safe_identifier(request.path_params.get(parameter))


def _request_outcome(request: Request, status_code: int) -> tuple[str, str]:
    reason = getattr(request.state, "audit_reason_code", "")
    if reason or status_code in {401, 403}:
        return "denied", reason or f"http_{status_code}"
    if status_code >= 400:
        return "failed", f"http_{status_code}"
    return "succeeded", ""


def should_audit_request(
    request: Request,
    policy: RoutePolicy | None,
    status_code: int,
) -> bool:
    if policy is None:
        return False
    if policy.audit in AUDITED_BEHAVIORS:
        return True
    return bool(
        getattr(request.state, "audit_reason_code", "")
        or (policy.authentication == "required" and status_code in {401, 403})
    )


def write_request_audit(
    request: Request,
    policy: RoutePolicy,
    status_code: int,
    *,
    route_template: str,
) -> AuditEvent:
    claimed_organization_id = request.path_params.get(
        "organization_id"
    ) or request.headers.get("X-AI-Examiner-Organization")
    with SessionLocal() as db:
        organization_id = _safe_identifier(claimed_organization_id)
        if organization_id:
            set_tenant_context(
                db,
                organization_id=organization_id,
                principal_id=getattr(request.state, "audit_actor_id", None),
            )
            if db.get(Organization, organization_id) is None:
                organization_id = None
        event = append_request_audit_event(
            db,
            request=request,
            policy=policy,
            status_code=status_code,
            route_template=route_template,
            organization_id=organization_id,
        )
        db.commit()
        return event


def append_request_audit_event(
    db: Session,
    *,
    request: Request,
    policy: RoutePolicy,
    status_code: int,
    route_template: str,
    organization_id: str | None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    settings = get_settings()
    source_ip_class, source_ip_hash = _source_ip_details(request, settings)
    outcome, reason_code = _request_outcome(request, status_code)
    try:
        event = append_audit_event(
            db,
            organization_id=organization_id,
            actor_type=getattr(request.state, "audit_actor_type", "anonymous"),
            actor_id=getattr(request.state, "audit_actor_id", None),
            authentication_method=getattr(
                request.state,
                "audit_authentication_method",
                "unknown",
            ),
            action=route_audit_action(request.method, route_template),
            resource_type=policy.resource_resolver,
            resource_id=resource_id
            or _resource_id_for_request(request, policy.resource_resolver),
            outcome=outcome,
            reason_code=reason_code,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
            source_ip_class=source_ip_class,
            source_ip_hash=source_ip_hash,
            user_agent_family=_user_agent_family(request),
            metadata={
                "audit_class": policy.audit,
                "capability": policy.capability,
                "http_method": request.method,
                "route_template": route_template,
                "status_code": status_code,
                **(metadata or {}),
            },
            retention_class=(
                "security"
                if outcome in {"denied", "failed"}
                or policy.audit == "authentication"
                else (
                    "sensitive_read"
                    if policy.audit == "read_sensitive"
                    else "administrative"
                )
            ),
            settings=settings,
        )
    except Exception as exc:
        db.rollback()
        raise AuditWriteError(
            "Required audit event could not be persisted"
        ) from exc
    request.state.audit_recorded = True
    return event


def serialize_audit_event(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "schema_version": event.schema_version,
        "organization_id": event.organization_id,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "authentication_method": event.authentication_method,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "outcome": event.outcome,
        "reason_code": event.reason_code,
        "request_id": event.request_id,
        "trace_id": event.trace_id,
        "source_ip_class": event.source_ip_class,
        "source_ip_hash": event.source_ip_hash,
        "user_agent_family": event.user_agent_family,
        "metadata": redact_audit_metadata(event.metadata_json),
        "event_digest": event.event_digest,
        "retention_class": event.retention_class,
        "retention_until": event.retention_until.isoformat(),
        "occurred_at": event.occurred_at.isoformat(),
    }


def audit_event_query(
    organization_id: str,
    filters: AuditFilters,
):
    query = select(AuditEvent).where(AuditEvent.organization_id == organization_id)
    for column, value in (
        (AuditEvent.actor_id, filters.actor_id),
        (AuditEvent.action, filters.action),
        (AuditEvent.resource_type, filters.resource_type),
        (AuditEvent.resource_id, filters.resource_id),
        (AuditEvent.outcome, filters.outcome),
        (AuditEvent.request_id, filters.request_id),
    ):
        if value:
            query = query.where(column == value)
    if filters.occurred_after:
        query = query.where(AuditEvent.occurred_at >= filters.occurred_after)
    if filters.occurred_before:
        query = query.where(AuditEvent.occurred_at < filters.occurred_before)
    return query


def list_audit_events(
    db: Session,
    *,
    organization_id: str,
    filters: AuditFilters,
    cursor: str | None,
    limit: int,
) -> tuple[list[AuditEvent], str | None]:
    query = audit_event_query(organization_id, filters)
    if cursor:
        cursor_event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.id == cursor,
            )
        )
        if cursor_event is not None:
            query = query.where(
                or_(
                    AuditEvent.occurred_at < cursor_event.occurred_at,
                    and_(
                        AuditEvent.occurred_at == cursor_event.occurred_at,
                        AuditEvent.id < cursor_event.id,
                    ),
                )
            )
    events = list(
        db.scalars(
            query.order_by(
                AuditEvent.occurred_at.desc(),
                AuditEvent.id.desc(),
            ).limit(limit + 1)
        ).all()
    )
    has_more = len(events) > limit
    events = events[:limit]
    return events, events[-1].id if has_more and events else None


def export_audit_events(
    db: Session,
    *,
    organization_id: str,
    filters: AuditFilters,
    max_rows: int,
) -> tuple[str, int, bool]:
    events = list(
        db.scalars(
            audit_event_query(organization_id, filters)
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
            .limit(max_rows + 1)
        ).all()
    )
    truncated = len(events) > max_rows
    events = events[:max_rows]
    lines = [
        json.dumps(
            {
                "type": "manifest",
                "schema_version": AUDIT_SCHEMA_VERSION,
                "organization_id": organization_id,
                "record_count": len(events),
                "truncated": truncated,
                "generated_at": utcnow().isoformat(),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    ]
    lines.extend(
        json.dumps(serialize_audit_event(event), ensure_ascii=True, sort_keys=True)
        for event in events
    )
    return "\n".join(lines) + "\n", len(events), truncated


def encode_audit_cursor(event_id: str) -> str:
    return base64.urlsafe_b64encode(event_id.encode("ascii")).decode("ascii")


def decode_audit_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
    except (ValueError, UnicodeError):
        return None
    return _safe_identifier(decoded)
