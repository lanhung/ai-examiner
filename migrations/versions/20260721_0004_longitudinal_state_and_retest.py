"""Add replayable longitudinal states and shadow retest plans.

Revision ID: 20260721_0004
Revises: 20260721_0003
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260721_0004"
down_revision = "20260721_0003"
branch_labels = None
depends_on = None

NEW_TABLES = ("learner_concept_states", "retest_plans", "retest_items")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "learner_concept_states" not in existing:
        op.create_table(
            "learner_concept_states",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "concept_id",
                sa.String(36),
                sa.ForeignKey("concepts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("observed_mastery", sa.Float(), nullable=False),
            sa.Column("observed_confidence", sa.Float(), nullable=False),
            sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("predicted_retention", sa.Float(), nullable=False),
            sa.Column("prediction_confidence", sa.Float(), nullable=False),
            sa.Column("stability_days", sa.Float(), nullable=False),
            sa.Column("difficulty_estimate", sa.Float(), nullable=False),
            sa.Column("evidence_count", sa.Integer(), nullable=False),
            sa.Column("independent_evidence_count", sa.Integer(), nullable=False),
            sa.Column("assisted_evidence_count", sa.Integer(), nullable=False),
            sa.Column("active_misconceptions", sa.JSON(), nullable=False),
            sa.Column("next_retest_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("algorithm_version", sa.String(50), nullable=False),
            sa.Column("rebuilt_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "learner_identity_id", "concept_id", name="uq_learner_concept_state"
            ),
        )
        op.create_index(
            "ix_concept_state_retest",
            "learner_concept_states",
            ["learner_identity_id", "next_retest_at"],
        )
    if "retest_plans" not in existing:
        op.create_table(
            "retest_plans",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "learner_identity_id",
                sa.String(36),
                sa.ForeignKey("learner_identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("horizon_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("policy_version", sa.String(50), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_retest_plan_identity_created",
            "retest_plans",
            ["learner_identity_id", "created_at"],
        )
    if "retest_items" not in existing:
        op.create_table(
            "retest_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "retest_plan_id",
                sa.String(36),
                sa.ForeignKey("retest_plans.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "concept_id",
                sa.String(36),
                sa.ForeignKey("concepts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("priority", sa.Float(), nullable=False),
            sa.Column("reason_code", sa.String(50), nullable=False),
            sa.Column("predicted_retention", sa.Float(), nullable=False),
            sa.Column("uncertainty", sa.Float(), nullable=False),
            sa.Column("source_state_version", sa.String(50), nullable=False),
            sa.Column("selected_question_id", sa.String(80), nullable=True),
            sa.Column(
                "outcome_event_id",
                sa.String(36),
                sa.ForeignKey("learner_memory_events.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "retest_plan_id", "concept_id", name="uq_retest_plan_concept"
            ),
        )
        op.create_index(
            "ix_retest_item_due", "retest_items", ["retest_plan_id", "due_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(NEW_TABLES):
        if table_name in existing:
            op.drop_table(table_name)
