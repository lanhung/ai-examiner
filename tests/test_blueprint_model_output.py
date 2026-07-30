from types import SimpleNamespace

import pytest

from ai_examiner.config import Settings
from ai_examiner.providers.base import ModelOutputValidationError
from ai_examiner.services.blueprints import BlueprintGenerationService


def test_blueprint_service_marks_generated_contract_violations_as_model_errors(
    monkeypatch,
):
    class FailingOrchestrator:
        def __init__(self, *_args, **_kwargs):
            pass

        def build_blueprint(self, **_kwargs):
            raise ValueError("Planner produced no questions")

    monkeypatch.setattr(
        "ai_examiner.services.blueprints.SessionTemplateService.resolve",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "ai_examiner.services.blueprints.governed_provider",
        lambda *_args, **_kwargs: SimpleNamespace(name="qwen", model="qwen-plus"),
    )
    monkeypatch.setattr(
        "ai_examiner.services.blueprints.ExamOrchestrator",
        FailingOrchestrator,
    )

    service = BlueprintGenerationService(SimpleNamespace(), Settings())
    project = SimpleNamespace(id="project", language="zh")
    document = SimpleNamespace(content_text="paper", filename="paper.pdf")

    with pytest.raises(ModelOutputValidationError, match="produced no questions"):
        service.prepare(
            project=project,
            document=document,
            profile="qwen:qwen-plus",
            mode="defense",
            template_version_id=None,
            template_overrides={},
        )
