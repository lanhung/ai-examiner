"""Add immutable scenario template snapshots to exam sessions.

Revision ID: 20260723_0007
Revises: 20260723_0006
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260723_0007"
down_revision = "20260723_0006"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    columns = _column_names("exam_sessions")
    with op.batch_alter_table("exam_sessions") as batch:
        if "template_version_id" not in columns:
            batch.add_column(
                sa.Column("template_version_id", sa.String(36), nullable=True)
            )
            batch.create_foreign_key(
                "fk_exam_session_template_version",
                "scenario_template_versions",
                ["template_version_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        if "template_snapshot_json" not in columns:
            batch.add_column(
                sa.Column("template_snapshot_json", sa.JSON(), nullable=True)
            )
        if "template_fingerprint" not in columns:
            batch.add_column(
                sa.Column("template_fingerprint", sa.String(80), nullable=True)
            )
        if "template_compiler_version" not in columns:
            batch.add_column(
                sa.Column(
                    "template_compiler_version",
                    sa.String(80),
                    nullable=True,
                )
            )
        if "template_overrides_json" not in columns:
            batch.add_column(
                sa.Column("template_overrides_json", sa.JSON(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    columns = _column_names("exam_sessions")
    if "template_version_id" in columns:
        bound = int(
            bind.execute(
                sa.text(
                    "SELECT COUNT(*) FROM exam_sessions "
                    "WHERE template_version_id IS NOT NULL"
                )
            ).scalar_one()
        )
        if bound:
            raise RuntimeError(
                "Cannot remove v0.8 session template snapshots while bound "
                "sessions exist"
            )
    with op.batch_alter_table("exam_sessions") as batch:
        for name in (
            "template_overrides_json",
            "template_compiler_version",
            "template_fingerprint",
            "template_snapshot_json",
            "template_version_id",
        ):
            if name in columns:
                batch.drop_column(name)
