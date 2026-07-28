"""Add durable job delivery, leasing and recovery state.

Revision ID: 20260728_0013
Revises: 20260728_0012
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260728_0013"
down_revision = "20260728_0012"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_columns("background_jobs")
    }


def _constraint_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return {
        item["name"]
        for item in (
            inspector.get_unique_constraints("background_jobs")
            + inspector.get_check_constraints("background_jobs")
        )
        if item.get("name")
    }


def _index_names() -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_indexes("background_jobs")
        if item.get("name")
    }


def upgrade() -> None:
    columns = _columns()
    additions = (
        ("idempotency_key", sa.String(160), None),
        ("envelope_version", sa.Integer(), "1"),
        ("envelope_json", sa.JSON(), "'{}'"),
        ("envelope_digest", sa.String(64), "''"),
        ("required_capability", sa.String(100), "''"),
        ("authorization_mode", sa.String(30), "'legacy_local'"),
        ("attempt_count", sa.Integer(), "0"),
        ("max_attempts", sa.Integer(), "3"),
        ("retry_class", sa.String(30), "''"),
        ("next_attempt_at", sa.DateTime(timezone=True), None),
        ("lease_owner", sa.String(160), None),
        ("lease_token", sa.String(64), None),
        ("lease_expires_at", sa.DateTime(timezone=True), None),
        ("heartbeat_at", sa.DateTime(timezone=True), None),
        ("cancel_requested_at", sa.DateTime(timezone=True), None),
        ("cancel_requested_by", sa.String(36), None),
        ("dead_lettered_at", sa.DateTime(timezone=True), None),
        ("terminal_reason", sa.String(120), "''"),
        ("updated_at", sa.DateTime(timezone=True), None),
    )
    for name, type_, default in additions:
        if name in columns:
            continue
        op.add_column(
            "background_jobs",
            sa.Column(
                name,
                type_,
                nullable=True,
                server_default=sa.text(default) if default is not None else None,
            ),
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE background_jobs SET "
            "idempotency_key = COALESCE(idempotency_key, id), "
            "required_capability = CASE kind "
            "WHEN 'golden_dataset' THEN 'dataset.manage' "
            "WHEN 'visual_document' THEN 'document.read' "
            "WHEN 'benchmark' THEN 'benchmark.run' "
            "WHEN 'memory_export' THEN 'learner_memory.admin' "
            "WHEN 'memory_deletion' THEN 'learner_memory.admin' "
            "ELSE '' END, "
            "authorization_mode = CASE "
            "WHEN actor_principal_id IS NULL THEN 'legacy_local' "
            "ELSE 'membership' END, "
            "updated_at = COALESCE(updated_at, created_at), "
            "status = CASE WHEN status IN ('queued', 'running') "
            "THEN 'failed' ELSE status END, "
            "terminal_reason = CASE WHEN status IN ('queued', 'running') "
            "THEN 'upgrade_requires_manual_retry' "
            "ELSE COALESCE(terminal_reason, '') END, "
            "error = CASE WHEN status IN ('queued', 'running') "
            "THEN 'legacy_delivery_invalidated' ELSE error END"
        )
    )

    constraint_names = _constraint_names()
    with op.batch_alter_table("background_jobs") as batch:
        for name, type_ in (
            ("idempotency_key", sa.String(160)),
            ("envelope_version", sa.Integer()),
            ("envelope_json", sa.JSON()),
            ("envelope_digest", sa.String(64)),
            ("required_capability", sa.String(100)),
            ("authorization_mode", sa.String(30)),
            ("attempt_count", sa.Integer()),
            ("max_attempts", sa.Integer()),
            ("retry_class", sa.String(30)),
            ("terminal_reason", sa.String(120)),
            ("updated_at", sa.DateTime(timezone=True)),
        ):
            batch.alter_column(
                name,
                existing_type=type_,
                nullable=False,
            )
        if "uq_background_job_idempotency" not in constraint_names:
            batch.create_unique_constraint(
                "uq_background_job_idempotency",
                ["organization_id", "kind", "idempotency_key"],
            )
        if "ck_background_job_status" not in constraint_names:
            batch.create_check_constraint(
                "ck_background_job_status",
                "status IN ("
                "'queued', 'running', 'retry_scheduled', 'cancelling', "
                "'completed', 'failed', 'cancelled', 'dead_letter'"
                ")",
            )
        if "ck_background_job_authorization_mode" not in constraint_names:
            batch.create_check_constraint(
                "ck_background_job_authorization_mode",
                "authorization_mode IN ('membership', 'legacy_local')",
            )

    if "ix_background_job_lease" not in _index_names():
        op.create_index(
            "ix_background_job_lease",
            "background_jobs",
            ["organization_id", "status", "lease_expires_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    active = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM background_jobs "
            "WHERE status IN ('running', 'retry_scheduled', 'cancelling')"
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            "Job hardening downgrade requires all active jobs to reach a "
            "terminal state"
        )
    if "ix_background_job_lease" in _index_names():
        op.drop_index("ix_background_job_lease", table_name="background_jobs")
    constraint_names = _constraint_names()
    with op.batch_alter_table("background_jobs") as batch:
        for name, kind in (
            ("uq_background_job_idempotency", "unique"),
            ("ck_background_job_status", "check"),
            ("ck_background_job_authorization_mode", "check"),
        ):
            if name in constraint_names:
                batch.drop_constraint(name, type_=kind)
        for name in reversed(
            (
                "idempotency_key",
                "envelope_version",
                "envelope_json",
                "envelope_digest",
                "required_capability",
                "authorization_mode",
                "attempt_count",
                "max_attempts",
                "retry_class",
                "next_attempt_at",
                "lease_owner",
                "lease_token",
                "lease_expires_at",
                "heartbeat_at",
                "cancel_requested_at",
                "cancel_requested_by",
                "dead_lettered_at",
                "terminal_reason",
                "updated_at",
            )
        ):
            if name in _columns():
                batch.drop_column(name)
