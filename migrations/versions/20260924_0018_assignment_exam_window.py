"""Add assignments and learner attempts for the exam window.

Revision ID: 20260924_0018
Revises: 20260810_0017
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from ai_examiner import models  # noqa: F401
from ai_examiner.db import Base

revision = "20260924_0018"
down_revision = "20260810_0017"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "assignments",
    "assignment_attempts",
)


def _postgres_security() -> None:
    bind = op.get_bind()
    tenant_match = (
        "organization_id = "
        "NULLIF(current_setting('app.organization_id', true), '')"
    )
    for table_name in NEW_TABLES:
        bind.execute(sa.text(f"REVOKE ALL ON TABLE {table_name} FROM PUBLIC"))
        bind.execute(
            sa.text(
                f"GRANT SELECT, INSERT, UPDATE ON TABLE {table_name} "
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


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        _postgres_security()


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "assignment_attempts" in tables:
        count = int(
            bind.execute(
                sa.text("SELECT COUNT(*) FROM assignment_attempts")
            ).scalar_one()
        )
        if count:
            raise RuntimeError(
                "Assignment downgrade refuses to destroy learner attempt evidence"
            )
    for table_name in reversed(NEW_TABLES):
        if table_name in tables:
            op.drop_table(table_name)
