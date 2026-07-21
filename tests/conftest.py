import os

import pytest
from fastapi.testclient import TestClient

os.environ["MODEL_PROVIDER"] = "mock"
os.environ["GOLDEN_DEFAULT_PROFILES"] = "mock:heuristic-v2"
os.environ["BENCHMARK_DEFAULT_PROFILES"] = "mock:heuristic-v2"
os.environ["VISUAL_DEFAULT_PROFILE"] = "mock:heuristic-v2"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["DASHSCOPE_API_KEY"] = "test-dashscope-key"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_ai_examiner.db"
os.environ["UPLOAD_DIR"] = "./data/test_uploads"
os.environ["EVIDENCE_DIR"] = "./data/test_evidence"
os.environ["EXPORT_DIR"] = "./data/test_exports"
os.environ["PROMPT_DIR"] = "./prompts"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["MEMORY_IDENTITY_SECRET"] = "test-only-memory-identity-secret"

from ai_examiner.db import Base, engine  # noqa: E402
from ai_examiner.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
