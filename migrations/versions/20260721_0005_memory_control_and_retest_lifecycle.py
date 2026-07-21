"""Add v0.7 preference, export, deletion and retest lifecycle controls.

Revision ID: 20260721_0005
Revises: 20260721_0004
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260721_0005"
down_revision = "20260721_0004"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    if "memory_write_blocked" not in _column_names("learner_identities"):
        with op.batch_alter_table("learner_identities") as batch:
            batch.add_column(
                sa.Column(
                    "memory_write_blocked",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    retest_columns = _column_names("retest_items")
    with op.batch_alter_table("retest_items") as batch:
        if "exam_session_id" not in retest_columns:
            batch.add_column(sa.Column("exam_session_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_retest_item_exam_session",
                "exam_sessions",
                ["exam_session_id"],
                ["id"],
                ondelete="SET NULL",
            )
        for name in (
            "dismissed_until",
            "accepted_at",
            "started_at",
            "completed_at",
        ):
            if name not in retest_columns:
                batch.add_column(
                    sa.Column(name, sa.DateTime(timezone=True), nullable=True)
                )

    if "learner_preferences" not in existing:
        op.create_table(
            "learner_preferences",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("preference_key", sa.String(80), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(30), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("confirmation_count", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "learner_identity_id",
                "preference_key",
                name="uq_identity_preference_key",
            ),
        )
        op.create_index(
            "ix_preference_identity_status",
            "learner_preferences",
            ["learner_identity_id", "status"],
        )

    if "memory_export_artifacts" not in existing:
        op.create_table(
            "memory_export_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("storage_path", sa.String(500), nullable=False),
            sa.Column("scope_json", sa.JSON(), nullable=False),
            sa.Column("record_counts", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_memory_export_identity_created",
            "memory_export_artifacts",
            ["learner_identity_id", "created_at"],
        )

    if "memory_deletion_audits" not in existing:
        op.create_table(
            "memory_deletion_audits",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("scope", sa.String(50), nullable=False),
            sa.Column("target_ref", sa.String(160), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("counts_json", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_memory_deletion_identity_created",
            "memory_deletion_audits",
            ["learner_identity_id", "created_at"],
        )


def downgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    for table_name in (
        "memory_deletion_audits",
        "memory_export_artifacts",
        "learner_preferences",
    ):
        if table_name in existing:
            op.drop_table(table_name)

    retest_columns = _column_names("retest_items")
    with op.batch_alter_table("retest_items") as batch:
        for name in (
            "completed_at",
            "started_at",
            "accepted_at",
            "dismissed_until",
            "exam_session_id",
        ):
            if name in retest_columns:
                batch.drop_column(name)

    if "memory_write_blocked" in _column_names("learner_identities"):
        with op.batch_alter_table("learner_identities") as batch:
            batch.drop_column("memory_write_blocked")
