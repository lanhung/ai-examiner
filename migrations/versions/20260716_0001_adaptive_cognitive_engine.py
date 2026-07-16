"""Add v0.5 adaptive cognitive engine tables.

Revision ID: 20260716_0001
Revises: None
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from ai_examiner import models  # noqa: F401
from ai_examiner.db import Base

revision = "20260716_0001"
down_revision = None
branch_labels = None
depends_on = None

NEW_TABLES = (
    "knowledge_units",
    "question_knowledge_units",
    "learner_subjects",
    "knowledge_states",
    "knowledge_evidence_events",
    "adaptive_decisions",
)


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "projects" not in tables:
        Base.metadata.create_all(bind=bind)
        return

    session_columns = _columns("exam_sessions")
    additions = {
        "learner_subject_id": "VARCHAR(36)",
        "question_strategy": "VARCHAR(30) NOT NULL DEFAULT 'fixed'",
        "policy_version": "VARCHAR(50) NOT NULL DEFAULT 'fixed-v1'",
        "asked_question_ids": "JSON NOT NULL DEFAULT '[]'",
    }
    for name, definition in additions.items():
        if name not in session_columns:
            op.execute(f"ALTER TABLE exam_sessions ADD COLUMN {name} {definition}")

    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name in reversed(NEW_TABLES):
        if table_name in tables:
            op.drop_table(table_name)

    if "exam_sessions" not in tables:
        return
    columns = _columns("exam_sessions")
    with op.batch_alter_table("exam_sessions") as batch:
        for name in ("asked_question_ids", "policy_version", "question_strategy", "learner_subject_id"):
            if name in columns:
                batch.drop_column(name)
