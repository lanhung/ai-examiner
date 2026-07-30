from __future__ import annotations

import tomllib
from pathlib import Path

from ai_examiner import __version__


def test_v09_research_version_is_consistent_across_package_and_ui(client):
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    page = client.get("/")
    health = client.get("/health")

    assert project["project"]["version"] == "0.9.0.dev0"
    assert __version__ == "0.9.0.dev0"
    assert health.json()["version"] == "0.9.0.dev0"
    assert "AI Examiner v0.9.0 Research" in page.text
    assert "AI Examiner v0.9 研究开发版" in page.text
    assert "v0.8 开发版" not in page.text
