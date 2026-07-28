"""Add organization model governance, quota and usage ledger.

Revision ID: 20260728_0015
Revises: 20260728_0014
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from ai_examiner import models  # noqa: F401
from ai_examiner.db import Base

revision = "20260728_0015"
down_revision = "20260728_0014"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "organization_model_policies",
    "model_usage_ledger",
)


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in inspect(op.get_bind()).get_columns(table_name)
    }


def _constraint_names(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {
        item["name"]
        for item in (
            inspector.get_check_constraints(table_name)
            + inspector.get_unique_constraints(table_name)
        )
        if item.get("name")
    }


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
            sa.text(
                f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation ON {table_name} "
                "TO ai_examiner_runtime "
                f"USING ({tenant_match}) WITH CHECK ({tenant_match})"
            )
        )


def upgrade() -> None:
    if "data_classification" not in _columns("projects"):
        op.add_column(
            "projects",
            sa.Column(
                "data_classification",
                sa.String(30),
                nullable=False,
                server_default="confidential",
            ),
        )
    if "ck_project_data_classification" not in _constraint_names("projects"):
        with op.batch_alter_table("projects") as batch:
            batch.create_check_constraint(
                "ck_project_data_classification",
                "data_classification IN "
                "('public', 'internal', 'confidential', 'restricted')",
            )

    bind = op.get_bind()
    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        _postgres_security()


def downgrade() -> None:
    bind = op.get_bind()
    if "model_usage_ledger" in inspect(bind).get_table_names():
        count = int(
            bind.execute(
                sa.text("SELECT COUNT(*) FROM model_usage_ledger")
            ).scalar_one()
        )
        if count:
            raise RuntimeError(
                "Model governance downgrade refuses to destroy usage evidence"
            )
    for table_name in reversed(NEW_TABLES):
        if table_name in inspect(bind).get_table_names():
            op.drop_table(table_name)
    if "data_classification" in _columns("projects"):
        with op.batch_alter_table("projects") as batch:
            if (
                "ck_project_data_classification"
                in _constraint_names("projects")
            ):
                batch.drop_constraint(
                    "ck_project_data_classification",
                    type_="check",
                )
            batch.drop_column("data_classification")
