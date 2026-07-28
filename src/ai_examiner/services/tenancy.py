from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..enterprise_constants import LEGACY_ORGANIZATION_ID

TENANT_ORGANIZATION_KEY = "ai_examiner.organization_id"
TENANT_PRINCIPAL_KEY = "ai_examiner.principal_id"


@dataclass(frozen=True)
class TenantTransactionContext:
    organization_id: str | None
    principal_id: str | None


def _set_postgres_local(
    connection: Connection,
    *,
    organization_id: str | None,
    principal_id: str | None,
) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        select(
            func.set_config(
                "app.organization_id",
                organization_id or "",
                True,
            )
        )
    )
    connection.execute(
        select(
            func.set_config(
                "app.principal_id",
                principal_id or "",
                True,
            )
        )
    )


def apply_tenant_context_to_connection(
    connection: Connection,
    *,
    organization_id: str | None,
    principal_id: str | None,
) -> None:
    _set_postgres_local(
        connection,
        organization_id=organization_id,
        principal_id=principal_id,
    )


def current_tenant_context(db: Session) -> TenantTransactionContext:
    return TenantTransactionContext(
        organization_id=db.info.get(TENANT_ORGANIZATION_KEY),
        principal_id=db.info.get(TENANT_PRINCIPAL_KEY),
    )


def set_tenant_context(
    db: Session,
    *,
    organization_id: str | None,
    principal_id: str | None,
) -> TenantTransactionContext:
    db.info[TENANT_ORGANIZATION_KEY] = organization_id
    db.info[TENANT_PRINCIPAL_KEY] = principal_id
    if db.in_transaction():
        _set_postgres_local(
            db.connection(),
            organization_id=organization_id,
            principal_id=principal_id,
        )
    return current_tenant_context(db)


def clear_tenant_context(db: Session) -> None:
    set_tenant_context(db, organization_id=None, principal_id=None)


@contextmanager
def tenant_context(
    db: Session,
    *,
    organization_id: str | None,
    principal_id: str | None,
) -> Iterator[TenantTransactionContext]:
    previous = current_tenant_context(db)
    current = set_tenant_context(
        db,
        organization_id=organization_id,
        principal_id=principal_id,
    )
    try:
        yield current
    finally:
        set_tenant_context(
            db,
            organization_id=previous.organization_id,
            principal_id=previous.principal_id,
        )


def require_tenant_organization(db: Session) -> str:
    organization_id = current_tenant_context(db).organization_id
    if not organization_id:
        raise RuntimeError("Tenant organization context is required")
    return organization_id


def tenant_organization_or_legacy(db: Session) -> str:
    return (
        current_tenant_context(db).organization_id
        or LEGACY_ORGANIZATION_ID
    )
