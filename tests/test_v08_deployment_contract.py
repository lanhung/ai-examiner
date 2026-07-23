from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_supports_isolated_environment_and_data_for_rehearsal():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose.count("${APP_ENV_FILE:-.env}") == 2
    assert compose.count("${HOST_DATA_DIR:-./data}:/app/data") == 2
    assert "down -v" not in compose


def test_v08_rehearsal_is_scoped_and_does_not_use_real_model_credentials():
    script = (
        ROOT / "deploy" / "rehearse-v08-compose.sh"
    ).read_text(encoding="utf-8")

    assert "MODEL_PROVIDER=mock" in script
    assert "ai-examiner-v08-rehearsal" in script
    assert "mktemp -d" in script
    assert "alembic upgrade head" in script
    assert "/api/templates/health" in script
    assert "ai-examiner-evaluate-templates" in script
    assert "ai-examiner-backup" in script
    assert "trap cleanup EXIT" in script
    assert "down --remove-orphans -v" in script
    assert "OPENAI_API_KEY=" not in script
    assert "DASHSCOPE_API_KEY=" not in script
