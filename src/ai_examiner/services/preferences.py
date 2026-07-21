from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LearnerIdentity, LearnerMemoryEvent, LearnerPreference

PREFERENCE_REGISTRY = {
    "explanation_style": {"concise", "step_by_step", "example_first"},
    "response_pace": {"fast", "balanced", "deliberate"},
    "interruption_style": {"minimal", "balanced", "strict"},
    "hint_style": {"none", "progressive", "direct"},
    "interface_language": {"zh-CN", "en"},
}


class PreferencePolicyError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class PreferenceService:
    policy_version = "preference-policy-v1"

    def __init__(self, db: Session):
        self.db = db

    def create_or_replace(
        self,
        identity: LearnerIdentity,
        *,
        preference_key: str,
        value: Any,
        source: str,
        evidence: list[dict],
        expires_in_days: int | None,
    ) -> LearnerPreference:
        self._assert_writable(identity)
        normalized_value = self._validate(preference_key, value)
        if source == "inferred":
            if not identity.preference_inference_enabled:
                raise PreferencePolicyError("Preference inference is disabled")
            if len(evidence) < 2:
                raise PreferencePolicyError(
                    "Inferred preferences require at least two evidence records"
                )
            status = "proposed"
        elif source == "explicit":
            status = "active"
        else:
            raise PreferencePolicyError("Unsupported preference source")
        preference = self.db.scalar(
            select(LearnerPreference).where(
                LearnerPreference.learner_identity_id == identity.id,
                LearnerPreference.preference_key == preference_key,
            )
        )
        now = utcnow()
        if not preference:
            preference = LearnerPreference(
                learner_identity_id=identity.id,
                preference_key=preference_key,
            )
            self.db.add(preference)
        preference.value_json = {"value": normalized_value}
        preference.source = source
        preference.status = status
        preference.evidence_json = self._safe_evidence(evidence)
        preference.confirmation_count = 1 if source == "explicit" else 0
        preference.expires_at = (
            now + timedelta(days=expires_in_days) if expires_in_days else None
        )
        preference.updated_at = now
        preference.reviewed_at = now if source == "explicit" else None
        self._record_event(identity, preference, "explicit_preference")
        self.db.flush()
        return preference

    def act(
        self,
        identity: LearnerIdentity,
        preference: LearnerPreference,
        *,
        action: str,
        value: Any | None,
    ) -> LearnerPreference:
        self._assert_writable(identity)
        if preference.learner_identity_id != identity.id:
            raise PreferencePolicyError("Preference does not belong to this identity")
        now = utcnow()
        if action == "confirm":
            preference.status = "active"
            preference.confirmation_count += 1
            preference.reviewed_at = now
            self._record_event(identity, preference, "confirmed_preference")
        elif action == "reject":
            preference.status = "rejected"
            preference.reviewed_at = now
        elif action == "expire":
            preference.status = "expired"
            preference.expires_at = now
            preference.reviewed_at = now
        elif action == "edit":
            if value is None:
                raise PreferencePolicyError("Edited preference requires a value")
            preference.value_json = {
                "value": self._validate(preference.preference_key, value)
            }
            preference.source = "explicit"
            preference.status = "active"
            preference.confirmation_count += 1
            preference.reviewed_at = now
            self._record_event(identity, preference, "confirmed_preference")
        else:
            raise PreferencePolicyError("Unsupported preference action")
        preference.updated_at = now
        self.db.flush()
        return preference

    def list(self, identity: LearnerIdentity) -> list[dict]:
        now = utcnow()
        preferences = self.db.scalars(
            select(LearnerPreference)
            .where(LearnerPreference.learner_identity_id == identity.id)
            .order_by(LearnerPreference.preference_key)
        ).all()
        for preference in preferences:
            if (
                preference.status == "active"
                and preference.expires_at
                and self._ensure_utc(preference.expires_at) <= now
            ):
                preference.status = "expired"
                preference.updated_at = now
        self.db.flush()
        return [self.serialize(item) for item in preferences]

    @staticmethod
    def serialize(preference: LearnerPreference) -> dict:
        return {
            "id": preference.id,
            "preference_key": preference.preference_key,
            "value": (preference.value_json or {}).get("value"),
            "source": preference.source,
            "status": preference.status,
            "evidence": preference.evidence_json,
            "confirmation_count": preference.confirmation_count,
            "expires_at": preference.expires_at.isoformat()
            if preference.expires_at
            else None,
            "created_at": preference.created_at.isoformat(),
            "updated_at": preference.updated_at.isoformat(),
            "reviewed_at": preference.reviewed_at.isoformat()
            if preference.reviewed_at
            else None,
        }

    def _record_event(
        self,
        identity: LearnerIdentity,
        preference: LearnerPreference,
        event_type: str,
    ) -> None:
        self.db.add(
            LearnerMemoryEvent(
                learner_identity_id=identity.id,
                event_type=event_type,
                payload_json={
                    "preference_key": preference.preference_key,
                    "value": (preference.value_json or {}).get("value"),
                    "source": preference.source,
                    "preference_policy_version": self.policy_version,
                },
                occurred_at=utcnow(),
                policy_version=self.policy_version,
                algorithm_version="preference-ledger-v1",
            )
        )

    @staticmethod
    def _safe_evidence(evidence: list[dict]) -> list[dict]:
        return [
            {
                "source": str(item.get("source") or "behavior")[:80],
                "reference_id": str(item.get("reference_id") or "")[:160],
                "observation": str(item.get("observation") or "")[:240],
            }
            for item in evidence[:20]
        ]

    @staticmethod
    def _validate(preference_key: str, value: Any) -> str:
        allowed = PREFERENCE_REGISTRY.get(preference_key)
        if not allowed:
            raise PreferencePolicyError(
                f"Preference key is not allowed: {preference_key}"
            )
        normalized = str(value).strip()
        if normalized not in allowed:
            raise PreferencePolicyError(
                f"Preference value is not allowed for {preference_key}"
            )
        return normalized

    @staticmethod
    def _assert_writable(identity: LearnerIdentity) -> None:
        if not identity.memory_enabled:
            raise PreferencePolicyError("Long-term memory is disabled")
        if identity.memory_write_blocked:
            raise PreferencePolicyError("Memory writes are blocked by a deletion job")

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
