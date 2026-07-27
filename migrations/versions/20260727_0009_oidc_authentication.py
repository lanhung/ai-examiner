"""Add OIDC login transactions and browser sessions.

Revision ID: 20260727_0009
Revises: 20260727_0008
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260727_0009"
down_revision = "20260727_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    if "oidc_login_transactions" not in existing:
        op.create_table(
            "oidc_login_transactions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
            sa.Column("nonce_hash", sa.String(64), nullable=False),
            sa.Column("redirect_uri", sa.String(1000), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_oidc_login_expires",
            "oidc_login_transactions",
            ["expires_at"],
        )

    if "browser_auth_sessions" not in existing:
        op.create_table(
            "browser_auth_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "principal_id",
                sa.String(36),
                sa.ForeignKey("principals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("session_token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("scopes_json", sa.JSON(), nullable=False),
            sa.Column("auth_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_browser_auth_session_expires",
            "browser_auth_sessions",
            ["expires_at"],
        )
        op.create_index(
            "ix_browser_auth_session_principal",
            "browser_auth_sessions",
            ["principal_id", "revoked_at"],
        )


def downgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    for table_name in (
        "browser_auth_sessions",
        "oidc_login_transactions",
    ):
        if table_name in existing:
            op.drop_table(table_name)
