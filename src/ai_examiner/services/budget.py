from __future__ import annotations

from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import UsageEvent


def budget_snapshot(db: Session, settings: Settings, project_id: str | None = None) -> dict:
    start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    daily = float(
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0)).where(
                UsageEvent.created_at >= start
            )
        )
        or 0.0
    )
    project = 0.0
    if project_id:
        project = float(
            db.scalar(
                select(func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0)).where(
                    UsageEvent.project_id == project_id
                )
            )
            or 0.0
        )
    return {
        "daily_cost_usd": round(daily, 6),
        "daily_budget_usd": settings.daily_model_budget_usd,
        "project_cost_usd": round(project, 6),
        "project_budget_usd": settings.project_model_budget_usd,
    }


def assert_budget(db: Session, settings: Settings, project_id: str | None = None) -> None:
    if settings.model_governance_enabled:
        # WP-09 performs authoritative organization-scoped reservation and
        # settlement immediately before each provider call.
        return
    snapshot = budget_snapshot(db, settings, project_id)
    if settings.daily_model_budget_usd and snapshot["daily_cost_usd"] >= settings.daily_model_budget_usd:
        raise RuntimeError("Daily model budget has been reached")
    if (
        project_id
        and settings.project_model_budget_usd
        and snapshot["project_cost_usd"] >= settings.project_model_budget_usd
    ):
        raise RuntimeError("Project model budget has been reached")
