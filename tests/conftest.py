import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url


def _test_database_url() -> str:
    candidate = os.environ.get(
        "AI_EXAMINER_TEST_DATABASE_URL",
        "sqlite:///./data/test_ai_examiner.db",
    )
    url = make_url(candidate)
    if url.drivername.startswith("sqlite"):
        return candidate
    database = (url.database or "").lower()
    if database != "test" and not (
        database.startswith("test_") or database.endswith("_test")
    ):
        raise RuntimeError(
            "AI_EXAMINER_TEST_DATABASE_URL must name an explicit test database"
        )
    return candidate

os.environ["MODEL_PROVIDER"] = "mock"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "disabled"
os.environ["GOLDEN_DEFAULT_PROFILES"] = "mock:heuristic-v2"
os.environ["BENCHMARK_DEFAULT_PROFILES"] = "mock:heuristic-v2"
os.environ["VISUAL_DEFAULT_PROFILE"] = "mock:heuristic-v2"
os.environ["MODEL_RATE_LIMIT_BACKEND"] = "redis"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["DASHSCOPE_API_KEY"] = "test-dashscope-key"
os.environ["DATABASE_URL"] = _test_database_url()
os.environ["UPLOAD_DIR"] = "./data/test_uploads"
os.environ["EVIDENCE_DIR"] = "./data/test_evidence"
os.environ["EXPORT_DIR"] = "./data/test_exports"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_ROOT"] = "./data/test_objects"
os.environ["PROMPT_DIR"] = "./prompts"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["MEMORY_IDENTITY_SECRET"] = "test-only-memory-identity-secret"

from ai_examiner.db import Base, SessionLocal, engine  # noqa: E402
from ai_examiner.main import app  # noqa: E402
from ai_examiner.services.enterprise_identity import ensure_legacy_organization  # noqa: E402


def _drop_test_tables():
    if engine.dialect.name == "postgresql":
        # Drop the known test tables as a group: RLS policies can reference
        # another table without appearing in SQLAlchemy's foreign-key ordering.
        # Keep RESTRICT; an external dependency must not be silently removed.
        tables = ", ".join(
            engine.dialect.identifier_preparer.format_table(table)
            for table in Base.metadata.sorted_tables
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS " + tables + " RESTRICT")
    else:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_database():
    _drop_test_tables()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_legacy_organization(db)
        db.commit()
    yield
    _drop_test_tables()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
