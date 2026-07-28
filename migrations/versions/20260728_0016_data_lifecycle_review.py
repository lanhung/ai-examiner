"""Add retention, export, deletion and human review controls.

Revision ID: 20260728_0016
Revises: 20260728_0015
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from ai_examiner import models  # noqa: F401
from ai_examiner.db import Base

revision = "20260728_0016"
down_revision = "20260728_0015"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "organization_retention_policies",
    "legal_holds",
    "organization_export_artifacts",
    "data_subject_requests",
    "human_review_cases",
    "human_review_events",
)


def _postgres_security() -> None:
    bind = op.get_bind()
    tenant_match = (
        "organization_id = "
        "NULLIF(current_setting('app.organization_id', true), '')"
    )
    for table_name in NEW_TABLES:
        bind.execute(sa.text(f"REVOKE ALL ON TABLE {table_name} FROM PUBLIC"))
        privileges = (
            "SELECT, INSERT"
            if table_name == "human_review_events"
            else "SELECT, INSERT, UPDATE"
        )
        bind.execute(
            sa.text(
                f"GRANT {privileges} ON TABLE {table_name} "
                "TO ai_examiner_runtime"
            )
        )
        bind.execute(
            sa.text(
                f"REVOKE DELETE ON TABLE {table_name} "
                "FROM ai_examiner_runtime"
            )
        )
        bind.execute(
            sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        )
        bind.execute(
            sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        )
        bind.execute(
            sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
        )
        bind.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation ON {table_name} "
                "TO ai_examiner_runtime "
                f"USING ({tenant_match}) WITH CHECK ({tenant_match})"
            )
        )
    bind.execute(
        sa.text(
            "CREATE OR REPLACE FUNCTION "
            "ai_examiner_reject_review_event_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'human_review_events are append-only'; "
            "END; $$"
        )
    )
    bind.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS human_review_events_no_update "
            "ON human_review_events"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER human_review_events_no_update "
            "BEFORE UPDATE ON human_review_events FOR EACH ROW "
            "EXECUTE FUNCTION ai_examiner_reject_review_event_mutation()"
        )
    )
    bind.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS human_review_events_no_delete "
            "ON human_review_events"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER human_review_events_no_delete "
            "BEFORE DELETE ON human_review_events FOR EACH ROW "
            "EXECUTE FUNCTION ai_examiner_reject_review_event_mutation()"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        _postgres_security()


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    protected = (
        "data_subject_requests",
        "human_review_events",
        "organization_export_artifacts",
    )
    for table_name in protected:
        if table_name not in tables:
            continue
        count = int(
            bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()
        )
        if count:
            raise RuntimeError(
                "Data lifecycle downgrade refuses to destroy compliance evidence"
            )
    for table_name in reversed(NEW_TABLES):
        if table_name in tables:
            op.drop_table(table_name)
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS "
                "ai_examiner_reject_review_event_mutation()"
            )
        )
