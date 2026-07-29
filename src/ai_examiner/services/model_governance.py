from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db import SessionLocal
from ..model_catalog import CATALOG, estimate_cost
from ..models import (
    ModelUsageLedger,
    OrganizationModelPolicy,
    Project,
)
from ..providers.base import ModelProvider, ProviderResult
from ..providers.factory import build_provider, parse_profile
from .audit import append_audit_event
from .tenancy import current_tenant_context, set_tenant_context

CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}
EXTERNAL_PROVIDERS = frozenset({"openai", "anthropic", "gemini", "qwen"})


class ModelGovernanceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 403,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class RateLimitLease:
    reservation_id: str
    concurrent_key: str


@dataclass(frozen=True)
class UsageReservation:
    ledger_id: str
    lease: RateLimitLease
    profile: str
    organization_id: str
    principal_id: str | None


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_allowed_profiles() -> list[dict[str, Any]]:
    profiles = [
        {
            "provider": entry.provider,
            "model_pattern": entry.model,
            "tasks": ["*"],
        }
        for entry in CATALOG
    ]
    profiles.extend(
        [
            {
                "provider": "openai",
                "model_pattern": "gpt-realtime-*",
                "tasks": ["voice"],
            },
            {
                "provider": "qwen",
                "model_pattern": "qwen*-realtime",
                "tasks": ["voice"],
            },
        ]
    )
    return profiles


def policy_snapshot(policy: OrganizationModelPolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "organization_id": policy.organization_id,
        "version": policy.version,
        "allowed_profiles": policy.allowed_profiles_json,
        "fallback_profiles": policy.fallback_profiles_json,
        "external_provider_max_classification": (
            policy.external_provider_max_classification
        ),
        "fallback_mode": policy.fallback_mode,
        "provider_retention_allowed": policy.provider_retention_allowed,
        "quota_mode": policy.quota_mode,
        "monthly_budget_usd": policy.monthly_budget_usd,
        "per_session_budget_usd": policy.per_session_budget_usd,
        "per_request_budget_usd": policy.per_request_budget_usd,
        "soft_limit_ratio": policy.soft_limit_ratio,
        "organization_requests_per_minute": (
            policy.organization_requests_per_minute
        ),
        "principal_requests_per_minute": policy.principal_requests_per_minute,
        "organization_tokens_per_minute": policy.organization_tokens_per_minute,
        "max_concurrent_calls": policy.max_concurrent_calls,
        "policy_digest": policy.policy_digest,
        "updated_at": policy.updated_at.isoformat(),
    }


def _effective_policy_digest(policy: OrganizationModelPolicy) -> str:
    payload = policy_snapshot(policy)
    payload.pop("policy_digest", None)
    payload.pop("updated_at", None)
    return _canonical_digest(payload)


def ensure_model_policy(
    db: Session,
    organization_id: str,
    *,
    principal_id: str | None = None,
) -> OrganizationModelPolicy:
    policy = db.scalar(
        select(OrganizationModelPolicy).where(
            OrganizationModelPolicy.organization_id == organization_id
        )
    )
    if policy is not None:
        return policy
    allowed = _default_allowed_profiles()
    policy = OrganizationModelPolicy(
        organization_id=organization_id,
        allowed_profiles_json=allowed,
        fallback_profiles_json=[],
        policy_digest="0" * 64,
        updated_by_principal_id=principal_id,
    )
    try:
        with db.begin_nested():
            db.add(policy)
            db.flush()
            policy.policy_digest = _effective_policy_digest(policy)
            db.flush()
    except IntegrityError:
        policy = db.scalar(
            select(OrganizationModelPolicy).where(
                OrganizationModelPolicy.organization_id == organization_id
            )
        )
        if policy is None:
            raise
    return policy


def update_model_policy(
    db: Session,
    policy: OrganizationModelPolicy,
    *,
    values: dict[str, Any],
    principal_id: str | None,
) -> OrganizationModelPolicy:
    for field, value in values.items():
        setattr(policy, field, value)
    policy.version += 1
    policy.updated_by_principal_id = principal_id
    policy.updated_at = datetime.now(UTC)
    policy.policy_digest = _effective_policy_digest(policy)
    db.flush()
    return policy


class MemoryModelRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int, int]] = {}
        self._leases: dict[str, dict[str, float]] = {}

    def acquire(
        self,
        *,
        organization_id: str,
        principal_id: str | None,
        reservation_id: str,
        token_units: int,
        organization_limit: int,
        principal_limit: int,
        token_limit: int,
        concurrent_limit: int,
        window_seconds: int,
        lease_seconds: int,
    ) -> RateLimitLease:
        now = int(time.time())
        window = now // window_seconds
        org_key = f"org:{organization_id}:{window}"
        principal_key = f"principal:{organization_id}:{principal_id or 'anonymous'}:{window}"
        concurrent_key = f"concurrent:{organization_id}"
        with self._lock:
            org_count, org_tokens, _ = self._windows.get(org_key, (0, 0, window))
            principal_count, _, _ = self._windows.get(
                principal_key,
                (0, 0, window),
            )
            leases = self._leases.setdefault(concurrent_key, {})
            leases = {
                key: expiry
                for key, expiry in leases.items()
                if expiry > time.time()
            }
            self._leases[concurrent_key] = leases
            retry_after = window_seconds - (now % window_seconds)
            if org_count >= organization_limit:
                raise ModelGovernanceError(
                    "organization_rate_limited",
                    "Organization model request rate limit reached",
                    status_code=429,
                    retry_after=retry_after,
                )
            if principal_count >= principal_limit:
                raise ModelGovernanceError(
                    "principal_rate_limited",
                    "Principal model request rate limit reached",
                    status_code=429,
                    retry_after=retry_after,
                )
            if org_tokens + token_units > token_limit:
                raise ModelGovernanceError(
                    "organization_token_rate_limited",
                    "Organization model token rate limit reached",
                    status_code=429,
                    retry_after=retry_after,
                )
            if len(leases) >= concurrent_limit:
                raise ModelGovernanceError(
                    "organization_concurrency_limited",
                    "Organization concurrent model-call limit reached",
                    status_code=429,
                    retry_after=1,
                )
            self._windows[org_key] = (
                org_count + 1,
                org_tokens + token_units,
                window,
            )
            self._windows[principal_key] = (
                principal_count + 1,
                0,
                window,
            )
            leases[reservation_id] = time.time() + lease_seconds
        return RateLimitLease(reservation_id, concurrent_key)

    def release(self, lease: RateLimitLease) -> None:
        with self._lock:
            self._leases.get(lease.concurrent_key, {}).pop(
                lease.reservation_id,
                None,
            )

    def check_ready(self) -> None:
        return None


class RedisModelRateLimiter:
    _ACQUIRE_SCRIPT = """
local org_count = tonumber(redis.call('GET', KEYS[1]) or '0')
local principal_count = tonumber(redis.call('GET', KEYS[2]) or '0')
local token_count = tonumber(redis.call('GET', KEYS[3]) or '0')
redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', ARGV[1])
local concurrent_count = tonumber(redis.call('ZCARD', KEYS[4]) or '0')
if org_count >= tonumber(ARGV[3]) then return {0, 1} end
if principal_count >= tonumber(ARGV[4]) then return {0, 2} end
if token_count + tonumber(ARGV[2]) > tonumber(ARGV[5]) then return {0, 3} end
if concurrent_count >= tonumber(ARGV[6]) then return {0, 4} end
local org_value = redis.call('INCR', KEYS[1])
local principal_value = redis.call('INCR', KEYS[2])
redis.call('INCRBY', KEYS[3], ARGV[2])
if org_value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[7]) end
if principal_value == 1 then redis.call('EXPIRE', KEYS[2], ARGV[7]) end
if token_count == 0 then redis.call('EXPIRE', KEYS[3], ARGV[7]) end
redis.call('ZADD', KEYS[4], tonumber(ARGV[1]) + tonumber(ARGV[8]), ARGV[9])
redis.call('EXPIRE', KEYS[4], ARGV[8])
return {1, 0}
"""

    def __init__(self, redis_url: str) -> None:
        from redis import Redis

        self.redis = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def acquire(
        self,
        *,
        organization_id: str,
        principal_id: str | None,
        reservation_id: str,
        token_units: int,
        organization_limit: int,
        principal_limit: int,
        token_limit: int,
        concurrent_limit: int,
        window_seconds: int,
        lease_seconds: int,
    ) -> RateLimitLease:
        now = int(time.time())
        window = now // window_seconds
        prefix = "ai-examiner:model"
        keys = [
            f"{prefix}:org:{organization_id}:{window}",
            f"{prefix}:principal:{organization_id}:{principal_id or 'anonymous'}:{window}",
            f"{prefix}:tokens:{organization_id}:{window}",
            f"{prefix}:concurrent:{organization_id}",
        ]
        result = self.redis.eval(
            self._ACQUIRE_SCRIPT,
            len(keys),
            *keys,
            now,
            token_units,
            organization_limit,
            principal_limit,
            token_limit,
            concurrent_limit,
            window_seconds + 5,
            lease_seconds,
            reservation_id,
        )
        allowed, reason = int(result[0]), int(result[1])
        if allowed:
            return RateLimitLease(reservation_id, keys[3])
        retry_after = (
            1
            if reason == 4
            else max(1, window_seconds - (now % window_seconds))
        )
        codes = {
            1: "organization_rate_limited",
            2: "principal_rate_limited",
            3: "organization_token_rate_limited",
            4: "organization_concurrency_limited",
        }
        raise ModelGovernanceError(
            codes.get(reason, "model_rate_limited"),
            "Model rate limit reached",
            status_code=429,
            retry_after=retry_after,
        )

    def release(self, lease: RateLimitLease) -> None:
        self.redis.zrem(lease.concurrent_key, lease.reservation_id)

    def check_ready(self) -> None:
        self.redis.ping()


_MEMORY_RATE_LIMITER = MemoryModelRateLimiter()
_QUOTA_LOCK_REGISTRY_GUARD = threading.Lock()
_QUOTA_LOCKS: dict[str, threading.RLock] = {}


def _organization_quota_lock(organization_id: str) -> threading.RLock:
    with _QUOTA_LOCK_REGISTRY_GUARD:
        return _QUOTA_LOCKS.setdefault(organization_id, threading.RLock())


def build_model_rate_limiter(settings: Settings):
    if settings.app_env == "test":
        return MemoryModelRateLimiter()
    if settings.model_rate_limit_backend == "memory":
        return _MEMORY_RATE_LIMITER
    try:
        return RedisModelRateLimiter(settings.redis_url)
    except Exception as exc:
        if settings.model_rate_limit_required:
            raise ModelGovernanceError(
                "rate_limiter_unavailable",
                "Model admission control is unavailable",
                status_code=503,
            ) from exc
        return _MEMORY_RATE_LIMITER


def _profile_allowed(
    policy: OrganizationModelPolicy,
    profile: str,
    task_type: str,
    classification: str,
) -> bool:
    provider, model = parse_profile(profile)
    if (
        provider in EXTERNAL_PROVIDERS
        and CLASSIFICATION_ORDER[classification]
        > CLASSIFICATION_ORDER[policy.external_provider_max_classification]
    ):
        return False
    for rule in policy.allowed_profiles_json:
        tasks = rule.get("tasks") or ["*"]
        if (
            rule.get("provider") == provider
            and fnmatchcase(model, str(rule.get("model_pattern") or ""))
            and ("*" in tasks or task_type in tasks)
        ):
            return True
    return False


def _input_token_estimate(
    instructions: str,
    payload: dict[str, Any],
) -> int:
    size = len(instructions) + len(
        json.dumps(payload, ensure_ascii=False, default=str)
    )
    return max(1, (size + 3) // 4)


class ModelGovernanceService:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: sessionmaker = SessionLocal,
        rate_limiter=None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.rate_limiter = rate_limiter or build_model_rate_limiter(settings)

    def candidates(
        self,
        *,
        organization_id: str,
        principal_id: str | None,
        requested_profile: str,
        task_type: str,
        classification: str,
    ) -> list[str]:
        with self.session_factory() as db:
            set_tenant_context(
                db,
                organization_id=organization_id,
                principal_id=principal_id,
            )
            policy = ensure_model_policy(
                db,
                organization_id,
                principal_id=principal_id,
            )
            db.commit()
            candidates = [requested_profile]
            if policy.fallback_mode == "ordered":
                candidates.extend(policy.fallback_profiles_json)
            allowed = [
                profile
                for profile in dict.fromkeys(candidates)
                if _profile_allowed(
                    policy,
                    profile,
                    task_type,
                    classification,
                )
            ]
            if not allowed or allowed[0] != requested_profile:
                self._record_denial(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    requested_profile=requested_profile,
                    task_type=task_type,
                    classification=classification,
                    reason="model_policy_denied",
                )
                raise ModelGovernanceError(
                    "model_policy_denied",
                    "The requested model is not allowed by organization policy",
                )
            return allowed

    def reserve(
        self,
        *,
        organization_id: str,
        principal_id: str | None,
        project_id: str | None,
        session_id: str | None,
        requested_profile: str,
        candidate_profile: str,
        fallback_from_profile: str | None,
        task_type: str,
        classification: str,
        token_units: int,
        request_id: str,
    ) -> UsageReservation:
        with _organization_quota_lock(organization_id):
            return self._reserve_locked(
                organization_id=organization_id,
                principal_id=principal_id,
                project_id=project_id,
                session_id=session_id,
                requested_profile=requested_profile,
                candidate_profile=candidate_profile,
                fallback_from_profile=fallback_from_profile,
                task_type=task_type,
                classification=classification,
                token_units=token_units,
                request_id=request_id,
            )

    def _reserve_locked(
        self,
        *,
        organization_id: str,
        principal_id: str | None,
        project_id: str | None,
        session_id: str | None,
        requested_profile: str,
        candidate_profile: str,
        fallback_from_profile: str | None,
        task_type: str,
        classification: str,
        token_units: int,
        request_id: str,
    ) -> UsageReservation:
        now = datetime.now(UTC)
        provider, model = parse_profile(candidate_profile)
        reservation_cost = max(
            estimate_cost(
                provider,
                model,
                token_units,
                self.settings.model_reserved_output_tokens,
            ),
            0.000001,
        )
        with self.session_factory() as db:
            set_tenant_context(
                db,
                organization_id=organization_id,
                principal_id=principal_id,
            )
            policy = db.scalar(
                select(OrganizationModelPolicy)
                .where(
                    OrganizationModelPolicy.organization_id == organization_id
                )
                .with_for_update()
            )
            if policy is None:
                policy = ensure_model_policy(
                    db,
                    organization_id,
                    principal_id=principal_id,
                )
            if not _profile_allowed(
                policy,
                candidate_profile,
                task_type,
                classification,
            ):
                db.rollback()
                raise ModelGovernanceError(
                    "model_policy_changed",
                    "Organization model policy changed before execution",
                )
            period_start = _month_start(now)
            completed_cost = float(
                db.scalar(
                    select(
                        func.coalesce(
                            func.sum(ModelUsageLedger.estimated_cost_usd),
                            0.0,
                        )
                    ).where(
                        ModelUsageLedger.organization_id == organization_id,
                        ModelUsageLedger.status.in_(("completed", "failed")),
                        ModelUsageLedger.created_at >= period_start,
                    )
                )
                or 0.0
            )
            reserved_cost = float(
                db.scalar(
                    select(
                        func.coalesce(
                            func.sum(ModelUsageLedger.reservation_cost_usd),
                            0.0,
                        )
                    ).where(
                        ModelUsageLedger.organization_id == organization_id,
                        ModelUsageLedger.status == "reserved",
                        ModelUsageLedger.created_at >= period_start,
                    )
                )
                or 0.0
            )
            session_cost = 0.0
            if session_id:
                completed_session_cost = float(
                    db.scalar(
                        select(
                            func.coalesce(
                                func.sum(ModelUsageLedger.estimated_cost_usd),
                                0.0,
                            )
                        ).where(
                            ModelUsageLedger.organization_id == organization_id,
                            ModelUsageLedger.session_id == session_id,
                            ModelUsageLedger.status.in_(("completed", "failed")),
                        )
                    )
                    or 0.0
                )
                reserved_session_cost = float(
                    db.scalar(
                        select(
                            func.coalesce(
                                func.sum(
                                    ModelUsageLedger.reservation_cost_usd
                                ),
                                0.0,
                            )
                        ).where(
                            ModelUsageLedger.organization_id == organization_id,
                            ModelUsageLedger.session_id == session_id,
                            ModelUsageLedger.status == "reserved",
                        )
                    )
                    or 0.0
                )
                session_cost = completed_session_cost + reserved_session_cost
            reason = ""
            if (
                policy.per_request_budget_usd
                and reservation_cost > policy.per_request_budget_usd
            ):
                reason = "per_request_quota_exceeded"
            elif (
                policy.monthly_budget_usd
                and completed_cost + reserved_cost + reservation_cost
                > policy.monthly_budget_usd
            ):
                reason = "monthly_quota_exceeded"
            elif (
                session_id
                and policy.per_session_budget_usd
                and session_cost + reservation_cost
                > policy.per_session_budget_usd
            ):
                reason = "session_quota_exceeded"
            projected_ratio = (
                (completed_cost + reserved_cost + reservation_cost)
                / policy.monthly_budget_usd
                if policy.monthly_budget_usd
                else 0.0
            )
            soft_exceeded = projected_ratio >= policy.soft_limit_ratio
            if reason and policy.quota_mode == "hard":
                ledger = self._new_ledger(
                    policy=policy,
                    requested_profile=requested_profile,
                    candidate_profile=candidate_profile,
                    fallback_from_profile=fallback_from_profile,
                    task_type=task_type,
                    classification=classification,
                    organization_id=organization_id,
                    principal_id=principal_id,
                    project_id=project_id,
                    session_id=session_id,
                    request_id=request_id,
                    reservation_cost=reservation_cost,
                    status="denied",
                    denial_reason=reason,
                    soft_exceeded=True,
                    now=now,
                )
                db.add(ledger)
                self._append_denial_audit(db, ledger, reason)
                db.commit()
                raise ModelGovernanceError(
                    reason,
                    "Organization model quota has been reached",
                    status_code=429,
                )
            ledger = self._new_ledger(
                policy=policy,
                requested_profile=requested_profile,
                candidate_profile=candidate_profile,
                fallback_from_profile=fallback_from_profile,
                task_type=task_type,
                classification=classification,
                organization_id=organization_id,
                principal_id=principal_id,
                project_id=project_id,
                session_id=session_id,
                request_id=request_id,
                reservation_cost=reservation_cost,
                status="reserved",
                denial_reason=reason if policy.quota_mode == "soft" else "",
                soft_exceeded=soft_exceeded or bool(reason),
                now=now,
            )
            db.add(ledger)
            db.commit()
            ledger_id = ledger.id
            rate_values = {
                "organization_limit": policy.organization_requests_per_minute,
                "principal_limit": (
                    policy.principal_requests_per_minute
                    if principal_id
                    else policy.organization_requests_per_minute
                ),
                "token_limit": policy.organization_tokens_per_minute,
                "concurrent_limit": policy.max_concurrent_calls,
            }
        try:
            lease = self.rate_limiter.acquire(
                organization_id=organization_id,
                principal_id=principal_id,
                reservation_id=ledger_id,
                token_units=token_units,
                window_seconds=self.settings.model_rate_limit_window_seconds,
                lease_seconds=self.settings.model_concurrency_lease_seconds,
                **rate_values,
            )
        except ModelGovernanceError as exc:
            self.deny_reserved(
                ledger_id,
                organization_id,
                principal_id,
                exc.code,
            )
            raise
        except Exception as exc:
            if self.settings.model_rate_limit_required:
                self.deny_reserved(
                    ledger_id,
                    organization_id,
                    principal_id,
                    "rate_limiter_unavailable",
                )
                raise ModelGovernanceError(
                    "rate_limiter_unavailable",
                    "Model admission control is unavailable",
                    status_code=503,
                ) from exc
            lease = _MEMORY_RATE_LIMITER.acquire(
                organization_id=organization_id,
                principal_id=principal_id,
                reservation_id=ledger_id,
                token_units=token_units,
                window_seconds=self.settings.model_rate_limit_window_seconds,
                lease_seconds=self.settings.model_concurrency_lease_seconds,
                **rate_values,
            )
        return UsageReservation(
            ledger_id,
            lease,
            candidate_profile,
            organization_id,
            principal_id,
        )

    @staticmethod
    def _new_ledger(
        *,
        policy: OrganizationModelPolicy,
        requested_profile: str,
        candidate_profile: str,
        fallback_from_profile: str | None,
        task_type: str,
        classification: str,
        organization_id: str,
        principal_id: str | None,
        project_id: str | None,
        session_id: str | None,
        request_id: str,
        reservation_cost: float,
        status: str,
        denial_reason: str,
        soft_exceeded: bool,
        now: datetime,
    ) -> ModelUsageLedger:
        provider, model = parse_profile(candidate_profile)
        return ModelUsageLedger(
            organization_id=organization_id,
            policy_id=policy.id,
            policy_version=policy.version,
            policy_snapshot_digest=policy.policy_digest,
            project_id=project_id,
            session_id=session_id,
            actor_principal_id=principal_id,
            request_id=request_id,
            task_type=task_type,
            data_classification=classification,
            requested_profile=requested_profile,
            actual_provider=provider if status != "denied" else None,
            actual_model=model if status != "denied" else None,
            fallback_from_profile=fallback_from_profile,
            status=status,
            reservation_cost_usd=reservation_cost,
            denial_reason=denial_reason,
            soft_limit_exceeded=soft_exceeded,
            created_at=now,
            completed_at=now if status == "denied" else None,
        )

    def _record_denial(
        self,
        *,
        organization_id: str,
        principal_id: str | None,
        requested_profile: str,
        task_type: str,
        classification: str,
        reason: str,
    ) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            set_tenant_context(
                db,
                organization_id=organization_id,
                principal_id=principal_id,
            )
            policy = ensure_model_policy(
                db,
                organization_id,
                principal_id=principal_id,
            )
            ledger = ModelUsageLedger(
                organization_id=organization_id,
                policy_id=policy.id,
                policy_version=policy.version,
                policy_snapshot_digest=policy.policy_digest,
                actor_principal_id=principal_id,
                request_id=uuid4().hex,
                task_type=task_type,
                data_classification=classification,
                requested_profile=requested_profile,
                status="denied",
                denial_reason=reason,
                created_at=now,
                completed_at=now,
            )
            db.add(ledger)
            db.flush()
            self._append_denial_audit(db, ledger, reason)
            db.commit()

    @staticmethod
    def _append_denial_audit(
        db: Session,
        ledger: ModelUsageLedger,
        reason: str,
    ) -> None:
        append_audit_event(
            db,
            organization_id=ledger.organization_id,
            actor_type=(
                "principal" if ledger.actor_principal_id else "system"
            ),
            actor_id=ledger.actor_principal_id,
            authentication_method=(
                "membership" if ledger.actor_principal_id else "system"
            ),
            action="model.call",
            resource_type="model_usage",
            resource_id=ledger.id,
            outcome="denied",
            reason_code=reason,
            request_id=ledger.request_id,
            trace_id=ledger.request_id,
            metadata={
                "task_type": ledger.task_type,
                "requested_profile": ledger.requested_profile,
                "policy_version": ledger.policy_version,
                "data_classification": ledger.data_classification,
            },
            retention_class="security",
        )

    def deny_reserved(
        self,
        ledger_id: str,
        organization_id: str,
        principal_id: str | None,
        reason: str,
    ) -> None:
        with self.session_factory() as db:
            set_tenant_context(
                db,
                organization_id=organization_id,
                principal_id=principal_id,
            )
            ledger = db.get(ModelUsageLedger, ledger_id)
            if ledger is None:
                return
            ledger.status = "denied"
            ledger.denial_reason = reason
            ledger.rate_limit_scope = {
                "organization_rate_limited": "organization_requests",
                "principal_rate_limited": "principal_requests",
                "organization_token_rate_limited": "organization_tokens",
                "organization_concurrency_limited": "organization_concurrency",
                "rate_limiter_unavailable": "admission_backend",
            }.get(reason, ledger.rate_limit_scope)
            ledger.completed_at = datetime.now(UTC)
            self._append_denial_audit(db, ledger, reason)
            db.commit()

    def settle(
        self,
        reservation: UsageReservation,
        result: ProviderResult,
    ) -> None:
        try:
            with self.session_factory() as db:
                set_tenant_context(
                    db,
                    organization_id=reservation.organization_id,
                    principal_id=reservation.principal_id,
                )
                ledger = db.get(ModelUsageLedger, reservation.ledger_id)
                if ledger is None:
                    raise RuntimeError("Model usage reservation disappeared")
                ledger.actual_provider = result.provider
                ledger.actual_model = result.model
                ledger.status = "completed"
                ledger.estimated_cost_usd = estimate_cost(
                    result.provider,
                    result.model,
                    result.input_tokens,
                    result.output_tokens,
                )
                ledger.input_tokens = result.input_tokens
                ledger.output_tokens = result.output_tokens
                ledger.latency_ms = result.latency_ms
                ledger.retry_count = result.retry_count
                ledger.completed_at = datetime.now(UTC)
                db.commit()
        finally:
            self.rate_limiter.release(reservation.lease)

    def fail(self, reservation: UsageReservation) -> None:
        try:
            with self.session_factory() as db:
                set_tenant_context(
                    db,
                    organization_id=reservation.organization_id,
                    principal_id=reservation.principal_id,
                )
                ledger = db.get(ModelUsageLedger, reservation.ledger_id)
                if ledger is not None:
                    ledger.status = "failed"
                    ledger.denial_reason = "provider_failure"
                    ledger.estimated_cost_usd = max(
                        ledger.estimated_cost_usd,
                        ledger.reservation_cost_usd,
                    )
                    ledger.completed_at = datetime.now(UTC)
                    db.commit()
        finally:
            self.rate_limiter.release(reservation.lease)


class GovernedModelProvider(ModelProvider):
    def __init__(
        self,
        *,
        settings: Settings,
        organization_id: str,
        principal_id: str | None,
        project_id: str | None,
        session_id: str | None,
        classification: str,
        requested_profile: str,
        session_factory: sessionmaker = SessionLocal,
        rate_limiter=None,
    ) -> None:
        self.settings = settings
        self.organization_id = organization_id
        self.principal_id = principal_id
        self.project_id = project_id
        self.session_id = session_id
        self.classification = classification
        self.requested_profile = requested_profile
        self.governance = ModelGovernanceService(
            settings,
            session_factory=session_factory,
            rate_limiter=rate_limiter,
        )
        self.name, self.model = parse_profile(requested_profile)
        self._image_model = self.model

    @property
    def image_model(self) -> str:
        return self._image_model

    def _call(
        self,
        method: str,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        **kwargs,
    ) -> ProviderResult:
        candidates = self.governance.candidates(
            organization_id=self.organization_id,
            principal_id=self.principal_id,
            requested_profile=self.requested_profile,
            task_type=agent,
            classification=self.classification,
        )
        token_units = _input_token_estimate(instructions, payload)
        request_id = uuid4().hex
        last_error: Exception | None = None
        for index, profile in enumerate(candidates):
            reservation = self.governance.reserve(
                organization_id=self.organization_id,
                principal_id=self.principal_id,
                project_id=self.project_id,
                session_id=self.session_id,
                requested_profile=self.requested_profile,
                candidate_profile=profile,
                fallback_from_profile=(
                    self.requested_profile if index else None
                ),
                task_type=agent,
                classification=self.classification,
                token_units=token_units,
                request_id=request_id,
            )
            try:
                provider = build_provider(self.settings, profile)
                started = time.perf_counter()
                result = getattr(provider, method)(
                    agent=agent,
                    instructions=instructions,
                    payload=payload,
                    **kwargs,
                )
                if result.latency_ms <= 0:
                    result.latency_ms = max(
                        1,
                        int((time.perf_counter() - started) * 1000),
                    )
            except Exception as exc:
                self.governance.fail(reservation)
                last_error = exc
                continue
            self.name = result.provider
            self.model = result.model
            self._image_model = provider.image_model
            self.governance.settle(reservation, result)
            return result
        if last_error is not None:
            raise last_error
        raise ModelGovernanceError(
            "model_policy_denied",
            "No model candidate is allowed",
        )

    def complete_json(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        return self._call(
            "complete_json",
            agent=agent,
            instructions=instructions,
            payload=payload,
            schema_hint=schema_hint,
        )

    def complete_json_with_images(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        image_paths: list[Path],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        return self._call(
            "complete_json_with_images",
            agent=agent,
            instructions=instructions,
            payload=payload,
            image_paths=image_paths,
            schema_hint=schema_hint,
        )

    def complete_text(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
    ) -> ProviderResult:
        return self._call(
            "complete_text",
            agent=agent,
            instructions=instructions,
            payload=payload,
        )


def governed_provider(
    db: Session,
    settings: Settings,
    profile: str | None = None,
    *,
    project_id: str | None = None,
    session_id: str | None = None,
) -> ModelProvider:
    if not settings.model_governance_enabled:
        return build_provider(settings, profile)
    resolved_profile = profile or (
        f"{settings.model_provider}:"
        f"{settings.default_model_for(settings.model_provider)}"
    )
    context = current_tenant_context(db)
    organization_id = context.organization_id
    classification = "internal"
    if project_id:
        project = db.get(Project, project_id)
        if project is None:
            raise ModelGovernanceError(
                "project_not_found",
                "Project not found for model governance",
                status_code=404,
            )
        organization_id = project.organization_id
        classification = project.data_classification
    if organization_id is None:
        raise ModelGovernanceError(
            "organization_context_required",
            "Organization context is required for model execution",
        )
    return GovernedModelProvider(
        settings=settings,
        organization_id=organization_id,
        principal_id=context.principal_id,
        project_id=project_id,
        session_id=session_id,
        classification=classification,
        requested_profile=resolved_profile,
    )


def usage_summary(
    db: Session,
    *,
    organization_id: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    policy = ensure_model_policy(db, organization_id)
    period_start = _month_start(datetime.now(UTC))
    query = select(ModelUsageLedger).where(
        ModelUsageLedger.organization_id == organization_id,
        ModelUsageLedger.created_at >= period_start,
    )
    if project_id:
        query = query.where(ModelUsageLedger.project_id == project_id)
    entries = db.scalars(query.order_by(ModelUsageLedger.created_at.desc())).all()
    completed = [entry for entry in entries if entry.status == "completed"]
    failed = [entry for entry in entries if entry.status == "failed"]
    accounted = completed + failed
    reserved = [entry for entry in entries if entry.status == "reserved"]
    denied = [entry for entry in entries if entry.status == "denied"]
    cost = sum(entry.estimated_cost_usd for entry in accounted)
    reserved_cost = sum(entry.reservation_cost_usd for entry in reserved)
    by_profile: dict[str, dict[str, float | int]] = {}
    by_project: dict[str, dict[str, float | int]] = {}
    by_task: dict[str, dict[str, float | int]] = {}
    for entry in accounted:
        tokens = entry.input_tokens + entry.output_tokens
        dimensions = (
            (
                by_profile,
                f"{entry.actual_provider}:{entry.actual_model}",
            ),
            (by_project, entry.project_id or "unassigned"),
            (by_task, entry.task_type),
        )
        for buckets, key in dimensions:
            bucket = buckets.setdefault(
                key,
                {"calls": 0, "tokens": 0, "cost_usd": 0.0},
            )
            bucket["calls"] += 1
            bucket["tokens"] += tokens
            bucket["cost_usd"] += entry.estimated_cost_usd

    def rounded_buckets(
        buckets: dict[str, dict[str, float | int]],
    ) -> dict[str, dict[str, float | int]]:
        return {
            key: {
                **value,
                "cost_usd": round(float(value["cost_usd"]), 8),
            }
            for key, value in sorted(buckets.items())
        }

    return {
        "period_start": period_start.isoformat(),
        "organization_id": organization_id,
        "project_id": project_id,
        "quota_mode": policy.quota_mode,
        "monthly_budget_usd": policy.monthly_budget_usd,
        "committed_cost_usd": round(cost, 8),
        "reserved_cost_usd": round(reserved_cost, 8),
        "remaining_budget_usd": (
            round(
                max(0.0, policy.monthly_budget_usd - cost - reserved_cost),
                8,
            )
            if policy.monthly_budget_usd
            else None
        ),
        "completed_calls": len(completed),
        "failed_calls": len(failed),
        "reserved_calls": len(reserved),
        "denied_calls": len(denied),
        "input_tokens": sum(entry.input_tokens for entry in completed),
        "output_tokens": sum(entry.output_tokens for entry in completed),
        "by_profile": rounded_buckets(by_profile),
        "by_project": rounded_buckets(by_project),
        "by_task": rounded_buckets(by_task),
        "policy_version": policy.version,
        "policy_digest": policy.policy_digest,
    }
