"""Add v0.8 scenario template persistence and lifecycle tables.

Revision ID: 20260723_0006
Revises: 20260721_0005
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260723_0006"
down_revision = "20260721_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    if "scenario_templates" not in existing:
        op.create_table(
            "scenario_templates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("slug", sa.String(160), nullable=False, unique=True),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("owner_scope", sa.String(30), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "scenario_template_versions" not in existing:
        op.create_table(
            "scenario_template_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "template_id",
                sa.String(36),
                sa.ForeignKey("scenario_templates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("semantic_version", sa.String(80), nullable=False),
            sa.Column("schema_version", sa.String(20), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("source_json", sa.JSON(), nullable=False),
            sa.Column("compiled_json", sa.JSON(), nullable=True),
            sa.Column("compiler_version", sa.String(80), nullable=True),
            sa.Column("fingerprint", sa.String(80), nullable=True),
            sa.Column("evaluation_summary_json", sa.JSON(), nullable=False),
            sa.Column(
                "created_from_version_id",
                sa.String(36),
                sa.ForeignKey(
                    "scenario_template_versions.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "template_id",
                "semantic_version",
                name="uq_scenario_template_semantic_version",
            ),
        )
        op.create_index(
            "ix_template_version_status",
            "scenario_template_versions",
            ["template_id", "status"],
        )
    if "template_validation_runs" not in existing:
        op.create_table(
            "template_validation_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "template_version_id",
                sa.String(36),
                sa.ForeignKey(
                    "scenario_template_versions.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("validator_version", sa.String(80), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("issues_json", sa.JSON(), nullable=False),
            sa.Column("capability_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_template_validation_version_created",
            "template_validation_runs",
            ["template_version_id", "created_at"],
        )
    if "project_template_bindings" not in existing:
        op.create_table(
            "project_template_bindings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "template_version_id",
                sa.String(36),
                sa.ForeignKey(
                    "scenario_template_versions.id",
                    ondelete="RESTRICT",
                ),
                nullable=False,
            ),
            sa.Column("default_overrides_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_project_template_binding_active",
            "project_template_bindings",
            ["project_id", "superseded_at"],
        )


def _bound_v08_sessions() -> int:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "exam_sessions" not in inspector.get_table_names():
        return 0
    columns = {item["name"] for item in inspector.get_columns("exam_sessions")}
    if "template_version_id" not in columns:
        return 0
    return int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM exam_sessions "
                "WHERE template_version_id IS NOT NULL"
            )
        ).scalar_one()
    )


def downgrade() -> None:
    if _bound_v08_sessions():
        raise RuntimeError(
            "Cannot downgrade v0.8 template persistence while bound sessions exist"
        )
    existing = set(inspect(op.get_bind()).get_table_names())
    for table_name in (
        "project_template_bindings",
        "template_validation_runs",
        "scenario_template_versions",
        "scenario_templates",
    ):
        if table_name in existing:
            op.drop_table(table_name)
