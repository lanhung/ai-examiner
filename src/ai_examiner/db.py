from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings
from .enterprise_constants import LEGACY_ORGANIZATION_ID
from .services.tenancy import (
    TENANT_ORGANIZATION_KEY,
    TENANT_PRINCIPAL_KEY,
    apply_tenant_context_to_connection,
)


class Base(DeclarativeBase):
    pass


settings = get_settings()
is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
audit_engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
AuditSessionLocal = sessionmaker(
    bind=audit_engine,
    autoflush=False,
    expire_on_commit=False,
)


@event.listens_for(Session, "after_begin")
def _apply_transaction_tenant_context(
    session: Session,
    transaction,
    connection,
) -> None:
    if transaction.nested:
        return
    apply_tenant_context_to_connection(
        connection,
        organization_id=session.info.get(TENANT_ORGANIZATION_KEY),
        principal_id=session.info.get(TENANT_PRINCIPAL_KEY),
    )


@event.listens_for(Session, "before_flush")
def _default_required_tenant_ownership(
    session: Session,
    _flush_context,
    _instances,
) -> None:
    organization_id = (
        session.info.get(TENANT_ORGANIZATION_KEY) or LEGACY_ORGANIZATION_ID
    )
    for instance in session.new:
        if not hasattr(instance, "organization_id"):
            continue
        column = instance.__table__.c.get("organization_id")
        if column is None or column.nullable:
            continue
        if getattr(instance, "organization_id", None) is None:
            instance.organization_id = organization_id


if is_sqlite:

    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _set_sqlite_pragmas)
    event.listen(audit_engine, "connect", _set_sqlite_pragmas)


def init_db() -> None:
    if settings.database_schema_management == "external":
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return

    from . import models  # noqa: F401

    config_path = _alembic_config_path()
    if config_path.exists():
        from alembic import command
        from alembic.config import Config

        alembic_config = Config(str(config_path))
        alembic_config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
        command.upgrade(alembic_config, "head")
    Base.metadata.create_all(bind=engine)
    from .services.enterprise_identity import ensure_legacy_organization
    from .services.prompts import seed_prompt_registry
    from .services.templates import seed_builtin_templates

    with SessionLocal() as db:
        ensure_legacy_organization(db)
        db.commit()
        seed_prompt_registry(db, settings.prompt_dir)
        seed_builtin_templates(db)


def _alembic_config_path() -> Path:
    candidates = (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    )
    return next((path for path in candidates if path.is_file()), candidates[-1])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    if settings.auth_mode == "disabled":
        db.info[TENANT_ORGANIZATION_KEY] = LEGACY_ORGANIZATION_ID
    try:
        yield db
    finally:
        db.close()
