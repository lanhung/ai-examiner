"""Add assessment provider telemetry.

Revision ID: 20260720_0002
Revises: 20260716_0001
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "20260720_0002"
down_revision = "20260716_0001"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "usage_events" not in tables:
        return
    columns = _columns("usage_events")
    additions = {
        "latency_ms": "INTEGER NOT NULL DEFAULT 0",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "json_repair_used": "BOOLEAN NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in columns:
            op.execute(f"ALTER TABLE usage_events ADD COLUMN {name} {definition}")


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "usage_events" not in tables:
        return
    columns = _columns("usage_events")
    with op.batch_alter_table("usage_events") as batch:
        for name in ("json_repair_used", "retry_count", "latency_ms"):
            if name in columns:
                batch.drop_column(name)
