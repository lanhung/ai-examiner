"""Add the v0.7 long-term learner memory foundation.

Revision ID: 20260721_0003
Revises: 20260720_0002
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260721_0003"
down_revision = "20260720_0002"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "learner_identities",
    "concepts",
    "learner_identity_links",
    "knowledge_unit_concept_maps",
    "learner_memory_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "learner_identities" not in existing:
        op.create_table(
            "learner_identities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("opaque_key_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("display_name", sa.String(200), nullable=True),
            sa.Column("memory_enabled", sa.Boolean(), nullable=False),
            sa.Column("memory_scope", sa.String(30), nullable=False),
            sa.Column("preference_inference_enabled", sa.Boolean(), nullable=False),
            sa.Column("retest_planning_enabled", sa.Boolean(), nullable=False),
            sa.Column("retention_days", sa.Integer(), nullable=False),
            sa.Column("policy_version", sa.String(50), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "concepts" not in existing:
        op.create_table(
            "concepts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("namespace", sa.String(100), nullable=False),
            sa.Column("canonical_key", sa.String(160), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("language", sa.String(20), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "namespace", "canonical_key", name="uq_concept_namespace_key"
            ),
        )
    if "learner_identity_links" not in existing:
        op.create_table(
            "learner_identity_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "learner_subject_id",
                sa.String(36),
                sa.ForeignKey("learner_subjects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("provenance", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("learner_subject_id", name="uq_identity_link_subject"),
        )
    if "knowledge_unit_concept_maps" not in existing:
        op.create_table(
            "knowledge_unit_concept_maps",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "knowledge_unit_id",
                sa.String(36),
                sa.ForeignKey("knowledge_units.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "concept_id",
                sa.String(36),
                sa.ForeignKey("concepts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("relation", sa.String(30), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("source", sa.String(30), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("model_profile", sa.String(160), nullable=True),
            sa.Column("prompt_version", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "knowledge_unit_id",
                "concept_id",
                name="uq_knowledge_unit_concept_map",
            ),
        )
        op.create_index(
            "ix_concept_map_status", "knowledge_unit_concept_maps", ["status"]
        )
    if "learner_memory_events" not in existing:
        op.create_table(
            "learner_memory_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "learner_subject_id",
                sa.String(36),
                sa.ForeignKey("learner_subjects.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "concept_id",
                sa.String(36),
                sa.ForeignKey("concepts.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "source_evidence_event_id",
                sa.String(36),
                sa.ForeignKey("knowledge_evidence_events.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("policy_version", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(50), nullable=False),
            sa.Column(
                "supersedes_event_id",
                sa.String(36),
                sa.ForeignKey("learner_memory_events.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "source_evidence_event_id",
                "concept_id",
                "event_type",
                name="uq_memory_source_concept_type",
            ),
        )
        op.create_index(
            "ix_memory_identity_time",
            "learner_memory_events",
            ["learner_identity_id", "occurred_at"],
        )
        op.create_index(
            "ix_memory_subject_time",
            "learner_memory_events",
            ["learner_subject_id", "occurred_at"],
        )
        op.create_index(
            "ix_memory_concept_time",
            "learner_memory_events",
            ["concept_id", "occurred_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(NEW_TABLES):
        if table_name in existing:
            op.drop_table(table_name)
