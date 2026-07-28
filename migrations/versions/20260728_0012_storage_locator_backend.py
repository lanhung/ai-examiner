"""Add tenant object locators for local and S3-compatible storage.

Revision ID: 20260728_0012
Revises: 20260728_0011
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260728_0012"
down_revision = "20260728_0011"
branch_labels = None
depends_on = None

RESOURCE_TABLES = (
    "documents",
    "evidence_assets",
    "memory_export_artifacts",
)


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_columns(table_name)
    }


def _constraint_names(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {
        item["name"]
        for item in (
            inspector.get_unique_constraints(table_name)
            + inspector.get_foreign_keys(table_name)
        )
        if item.get("name")
    }


def _index_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def _has_foreign_key(
    table_name: str,
    constrained_columns: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> bool:
    return any(
        tuple(item.get("constrained_columns") or ()) == constrained_columns
        and item.get("referred_table") == referred_table
        and tuple(item.get("referred_columns") or ()) == referred_columns
        for item in inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables()
    if "stored_objects" not in existing:
        op.create_table(
            "stored_objects",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("resource_type", sa.String(50), nullable=False),
            sa.Column("resource_id", sa.String(36), nullable=False),
            sa.Column("purpose", sa.String(50), nullable=False),
            sa.Column("backend", sa.String(20), nullable=False),
            sa.Column("bucket", sa.String(255), nullable=False, server_default=""),
            sa.Column("object_key", sa.String(900), nullable=False),
            sa.Column("content_type", sa.String(150), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "backend",
                "bucket",
                "object_key",
                name="uq_stored_object_locator",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'missing', 'deleted')",
                name="ck_stored_object_status",
            ),
        )
        op.create_index(
            "ix_stored_object_resource",
            "stored_objects",
            ["organization_id", "resource_type", "resource_id"],
        )

    for table_name in RESOURCE_TABLES:
        if "storage_object_id" not in _columns(table_name):
            op.add_column(
                table_name,
                sa.Column("storage_object_id", sa.String(36), nullable=True),
            )
        index_name = f"ix_{table_name}_storage_object"
        if index_name not in _index_names(table_name):
            op.create_index(
                index_name,
                table_name,
                ["storage_object_id"],
            )
        needs_storage_fk = not _has_foreign_key(
            table_name,
            ("storage_object_id",),
            "stored_objects",
            ("id",),
        )
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "storage_path",
                existing_type=sa.String(500),
                nullable=True,
            )
            if needs_storage_fk:
                batch.create_foreign_key(
                    f"fk_{table_name}_storage_object",
                    "stored_objects",
                    ["storage_object_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    if bind.dialect.name != "postgresql":
        return

    names = _constraint_names("stored_objects")
    if "uq_stored_objects_organization_id" not in names:
        op.create_unique_constraint(
            "uq_stored_objects_organization_id",
            "stored_objects",
            ["organization_id", "id"],
        )

    for table_name in RESOURCE_TABLES:
        composite_name = f"fk_tenant_{table_name}_storage_object"
        if composite_name not in _constraint_names(table_name):
            op.create_foreign_key(
                composite_name,
                table_name,
                "stored_objects",
                ["organization_id", "storage_object_id"],
                ["organization_id", "id"],
            )

    bind.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            "stored_objects TO ai_examiner_runtime"
        )
    )
    bind.execute(
        sa.text("ALTER TABLE stored_objects ENABLE ROW LEVEL SECURITY")
    )
    bind.execute(
        sa.text("ALTER TABLE stored_objects FORCE ROW LEVEL SECURITY")
    )
    bind.execute(
        sa.text(
            "DROP POLICY IF EXISTS tenant_isolation ON stored_objects"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY tenant_isolation ON stored_objects "
            "FOR ALL TO ai_examiner_runtime "
            "USING (organization_id = "
            "NULLIF(current_setting('app.organization_id', true), '')) "
            "WITH CHECK (organization_id = "
            "NULLIF(current_setting('app.organization_id', true), ''))"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "stored_objects" not in _tables():
        return
    unsafe_resources = {
        table_name: bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table_name} "
                "WHERE storage_object_id IS NOT NULL OR storage_path IS NULL"
            )
        ).scalar_one()
        for table_name in RESOURCE_TABLES
        if "storage_object_id" in _columns(table_name)
    }
    unsafe_resources = {
        table_name: count
        for table_name, count in unsafe_resources.items()
        if count
    }
    if unsafe_resources:
        raise RuntimeError(
            "Storage locator downgrade would orphan migrated objects. "
            "Restore verified legacy paths before downgrading: "
            + ", ".join(
                f"{table_name}={count}"
                for table_name, count in sorted(unsafe_resources.items())
            )
        )
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "DROP POLICY IF EXISTS tenant_isolation ON stored_objects"
            )
        )
        bind.execute(
            sa.text(
                "ALTER TABLE stored_objects NO FORCE ROW LEVEL SECURITY"
            )
        )
        bind.execute(
            sa.text("ALTER TABLE stored_objects DISABLE ROW LEVEL SECURITY")
        )
        for table_name in reversed(RESOURCE_TABLES):
            for name in (
                f"fk_tenant_{table_name}_storage_object",
                f"fk_{table_name}_storage_object",
            ):
                if name in _constraint_names(table_name):
                    op.drop_constraint(name, table_name, type_="foreignkey")

    for table_name in reversed(RESOURCE_TABLES):
        if "storage_object_id" not in _columns(table_name):
            continue
        indexes = {
            item["name"]
            for item in inspect(bind).get_indexes(table_name)
            if item.get("name")
        }
        index_name = f"ix_{table_name}_storage_object"
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("storage_object_id")
            batch.alter_column(
                "storage_path",
                existing_type=sa.String(500),
                nullable=False,
            )
    op.drop_table("stored_objects")
