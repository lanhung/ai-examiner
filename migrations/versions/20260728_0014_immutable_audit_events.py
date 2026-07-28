"""Add append-only enterprise audit events.

Revision ID: 20260728_0014
Revises: 20260728_0013
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260728_0014"
down_revision = "20260728_0013"
branch_labels = None
depends_on = None


def _table_exists() -> bool:
    return "audit_events" in inspect(op.get_bind()).get_table_names()


def _index_names() -> set[str]:
    if not _table_exists():
        return set()
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_indexes("audit_events")
        if item.get("name")
    }


def _create_table() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=True),
        sa.Column(
            "authentication_method",
            sa.String(30),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column(
            "resource_type",
            sa.String(100),
            nullable=False,
            server_default="none",
        ),
        sa.Column("resource_id", sa.String(160), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(120), nullable=False, server_default=""),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column(
            "source_ip_class",
            sa.String(20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("source_ip_hash", sa.String(64), nullable=True),
        sa.Column(
            "user_agent_family",
            sa.String(40),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("event_digest", sa.String(64), nullable=False),
        sa.Column(
            "retention_class",
            sa.String(30),
            nullable=False,
            server_default="administrative",
        ),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('anonymous', 'principal', 'system', 'worker')",
            name="ck_audit_event_actor_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')",
            name="ck_audit_event_outcome",
        ),
        sa.CheckConstraint(
            "source_ip_class IN "
            "('loopback', 'private', 'public', 'unknown')",
            name="ck_audit_event_source_ip_class",
        ),
        sa.CheckConstraint(
            "retention_class IN "
            "('security', 'administrative', 'sensitive_read')",
            name="ck_audit_event_retention_class",
        ),
    )


def _create_indexes() -> None:
    existing = _index_names()
    for name, columns in (
        (
            "ix_audit_event_organization_occurred",
            ["organization_id", "occurred_at", "id"],
        ),
        ("ix_audit_event_request", ["request_id"]),
        (
            "ix_audit_event_actor",
            ["organization_id", "actor_id", "occurred_at"],
        ),
        (
            "ix_audit_event_resource",
            ["organization_id", "resource_type", "resource_id"],
        ),
    ):
        if name not in existing:
            op.create_index(name, "audit_events", columns)


def _sqlite_immutability() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS audit_events_no_update "
            "BEFORE UPDATE ON audit_events BEGIN "
            "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS audit_events_no_delete "
            "BEFORE DELETE ON audit_events BEGIN "
            "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
        )
    )


def _postgres_security() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles "
            "WHERE rolname = 'ai_examiner_audit_maintenance') THEN "
            "CREATE ROLE ai_examiner_audit_maintenance NOLOGIN NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS; "
            "END IF; END $$"
        )
    )
    bind.execute(sa.text("REVOKE ALL ON TABLE audit_events FROM PUBLIC"))
    bind.execute(
        sa.text(
            "REVOKE UPDATE, DELETE ON TABLE audit_events "
            "FROM ai_examiner_runtime"
        )
    )
    bind.execute(
        sa.text(
            "GRANT SELECT, INSERT ON TABLE audit_events "
            "TO ai_examiner_runtime"
        )
    )
    bind.execute(
        sa.text(
            "GRANT SELECT, DELETE ON TABLE audit_events "
            "TO ai_examiner_audit_maintenance"
        )
    )
    bind.execute(sa.text("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY"))
    for policy in (
        "audit_tenant_select",
        "audit_tenant_insert",
        "audit_maintenance_select",
        "audit_maintenance_delete",
    ):
        bind.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON audit_events"))
    tenant_match = (
        "organization_id = "
        "NULLIF(current_setting('app.organization_id', true), '')"
    )
    bind.execute(
        sa.text(
            "CREATE POLICY audit_tenant_select ON audit_events "
            f"FOR SELECT TO ai_examiner_runtime USING ({tenant_match})"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY audit_tenant_insert ON audit_events "
            "FOR INSERT TO ai_examiner_runtime WITH CHECK "
            f"(organization_id IS NULL OR {tenant_match})"
        )
    )
    maintenance_enabled = (
        "current_setting('app.audit_maintenance', true) = 'on'"
    )
    bind.execute(
        sa.text(
            "CREATE POLICY audit_maintenance_select ON audit_events "
            "FOR SELECT TO ai_examiner_audit_maintenance "
            f"USING ({maintenance_enabled})"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY audit_maintenance_delete ON audit_events "
            "FOR DELETE TO ai_examiner_audit_maintenance "
            f"USING ({maintenance_enabled})"
        )
    )
    bind.execute(
        sa.text(
            "CREATE OR REPLACE FUNCTION reject_audit_event_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF TG_OP = 'DELETE' "
            "AND current_user = 'ai_examiner_audit_maintenance' "
            "AND current_setting('app.audit_maintenance', true) = 'on' THEN "
            "RETURN OLD; "
            "END IF; "
            "RAISE EXCEPTION 'audit_events are append-only'; "
            "END $$"
        )
    )
    bind.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER audit_events_immutable "
            "BEFORE UPDATE OR DELETE ON audit_events "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
        )
    )


def upgrade() -> None:
    if not _table_exists():
        _create_table()
    _create_indexes()
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _sqlite_immutability()
    elif dialect == "postgresql":
        _postgres_security()


def downgrade() -> None:
    if not _table_exists():
        return
    bind = op.get_bind()
    event_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM audit_events")
    ).scalar_one()
    if event_count:
        raise RuntimeError(
            "Audit downgrade refuses to destroy immutable evidence; "
            "export and age records through the privileged process first"
        )
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events"
            )
        )
        bind.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS reject_audit_event_mutation()"
            )
        )
    op.drop_table("audit_events")
