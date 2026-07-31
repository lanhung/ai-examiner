from pathlib import Path


def test_alembic_keeps_application_loggers_enabled():
    source = (Path(__file__).parents[1] / "migrations" / "env.py").read_text(
        encoding="utf-8"
    )

    assert "fileConfig(config.config_file_name, disable_existing_loggers=False)" in source
