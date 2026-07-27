"""Add the v0.9 organization and principal foundation.

Revision ID: 20260727_0008
Revises: 20260723_0007
Create Date: 2026-07-27
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260727_0008"
down_revision = "20260723_0007"
branch_labels = None
depends_on = None

LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    existing = _table_names()
    if "organizations" not in existing:
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("slug", sa.String(100), nullable=False, unique=True),
            sa.Column("display_name", sa.String(200), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('active', 'suspended', 'disabled')",
                name="ck_organization_status",
            ),
        )

    organizations = sa.table(
        "organizations",
        sa.column("id", sa.String(36)),
        sa.column("slug", sa.String(100)),
        sa.column("display_name", sa.String(200)),
        sa.column("status", sa.String(30)),
        sa.column("version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    legacy_exists = op.get_bind().scalar(
        sa.select(sa.func.count())
        .select_from(organizations)
        .where(organizations.c.id == LEGACY_ORGANIZATION_ID)
    )
    if not legacy_exists:
        now = datetime.now(UTC)
        op.bulk_insert(
            organizations,
            [
                {
                    "id": LEGACY_ORGANIZATION_ID,
                    "slug": "legacy",
                    "display_name": "Legacy workspace",
                    "status": "active",
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    existing = _table_names()
    if "principals" not in existing:
        op.create_table(
            "principals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("issuer", sa.String(500), nullable=False),
            sa.Column("subject", sa.String(500), nullable=False),
            sa.Column("display_name", sa.String(200), nullable=True),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "issuer",
                "subject",
                name="uq_principal_issuer_subject",
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'active', 'suspended', 'disabled')",
                name="ck_principal_status",
            ),
        )
        op.create_index("ix_principal_status", "principals", ["status"])

    if "organization_memberships" not in existing:
        op.create_table(
            "organization_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "principal_id",
                sa.String(36),
                sa.ForeignKey("principals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "organization_id",
                "principal_id",
                name="uq_organization_membership_principal",
            ),
            sa.CheckConstraint(
                "role IN ('owner', 'admin', 'examiner', 'template_author', "
                "'reviewer', 'learner', 'auditor')",
                name="ck_organization_membership_role",
            ),
            sa.CheckConstraint(
                "status IN ('invited', 'active', 'suspended', 'revoked')",
                name="ck_organization_membership_status",
            ),
        )
        op.create_index(
            "ix_organization_membership_status",
            "organization_memberships",
            ["organization_id", "status"],
        )

    project_columns = _column_names("projects")
    if "organization_id" not in project_columns:
        with op.batch_alter_table("projects") as batch:
            batch.add_column(
                sa.Column(
                    "organization_id",
                    sa.String(36),
                    nullable=True,
                    server_default=LEGACY_ORGANIZATION_ID,
                )
            )
            batch.create_foreign_key(
                "fk_project_organization",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        op.execute(
            sa.text(
                "UPDATE projects SET organization_id = :organization_id "
                "WHERE organization_id IS NULL"
            ).bindparams(organization_id=LEGACY_ORGANIZATION_ID)
        )
        with op.batch_alter_table("projects") as batch:
            batch.alter_column(
                "organization_id",
                existing_type=sa.String(36),
                nullable=False,
                server_default=LEGACY_ORGANIZATION_ID,
            )
        op.create_index(
            "ix_project_organization_created",
            "projects",
            ["organization_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _table_names()
    if "principals" in existing:
        principal_count = int(
            bind.scalar(sa.text("SELECT COUNT(*) FROM principals")) or 0
        )
        if principal_count:
            raise RuntimeError(
                "Cannot remove the v0.9 identity foundation while principals exist"
            )

    if "organization_id" in _column_names("projects"):
        project_indexes = {
            item["name"] for item in inspect(bind).get_indexes("projects")
        }
        if "ix_project_organization_created" in project_indexes:
            op.drop_index("ix_project_organization_created", table_name="projects")
        with op.batch_alter_table("projects") as batch:
            batch.drop_column("organization_id")

    for table_name in (
        "organization_memberships",
        "principals",
        "organizations",
    ):
        if table_name in existing:
            op.drop_table(table_name)
