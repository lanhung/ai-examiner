"""Allow authenticated principals to discover their active organizations.

Revision ID: 20260810_0017
Revises: 20260728_0016
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260810_0017"
down_revision = "20260728_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    no_selected_organization = (
        "NULLIF(current_setting('app.organization_id', true), '') IS NULL"
    )
    current_principal = (
        "NULLIF(current_setting('app.principal_id', true), '')"
    )

    bind.execute(
        sa.text(
            "DROP POLICY IF EXISTS membership_self_discovery "
            "ON organization_memberships"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY membership_self_discovery "
            "ON organization_memberships FOR SELECT TO ai_examiner_runtime "
            f"USING ({no_selected_organization} "
            f"AND principal_id = {current_principal} "
            "AND status = 'active')"
        )
    )

    bind.execute(
        sa.text(
            "DROP POLICY IF EXISTS organization_self_discovery "
            "ON organizations"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY organization_self_discovery "
            "ON organizations FOR SELECT TO ai_examiner_runtime "
            f"USING ({no_selected_organization} AND EXISTS ("
            "SELECT 1 FROM organization_memberships membership "
            "WHERE membership.organization_id = organizations.id "
            f"AND membership.principal_id = {current_principal} "
            "AND membership.status = 'active'))"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        sa.text(
            "DROP POLICY IF EXISTS organization_self_discovery "
            "ON organizations"
        )
    )
    bind.execute(
        sa.text(
            "DROP POLICY IF EXISTS membership_self_discovery "
            "ON organization_memberships"
        )
    )
