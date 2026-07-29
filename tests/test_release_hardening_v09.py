import json
import subprocess
from pathlib import Path

from ai_examiner.config import Settings
from ai_examiner.model_governance_probe import run_probe
from ai_examiner.providers.base import ModelProvider, ProviderResult
from ai_examiner.release_hardening import (
    ai_regression_check,
    build_release_report,
    migration_head_check,
    route_policy_check,
    scan_tracked_secrets,
)
from ai_examiner.services import model_governance


class _ProbeProvider(ModelProvider):
    name = "qwen"
    model = "qwen-plus"

    def complete_json(self, **_kwargs) -> ProviderResult:
        return ProviderResult(
            data={"status": "ok"},
            provider=self.name,
            model=self.model,
            input_tokens=12,
            output_tokens=4,
        )

    def complete_text(self, **_kwargs) -> ProviderResult:
        return ProviderResult(
            data="ok",
            provider=self.name,
            model=self.model,
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_secret_scan_reports_rule_and_path_without_secret_value(tmp_path):
    _git(tmp_path, "init")
    source = tmp_path / "settings.txt"
    secret = "sk-proj-" + ("A" * 32)
    source.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    _git(tmp_path, "add", "settings.txt")

    result = scan_tracked_secrets(tmp_path)

    assert result.status == "failed"
    assert result.evidence["findings"] == [
        {"path": "settings.txt", "rule_id": "openai_api_key"}
    ]
    assert secret not in json.dumps(result.evidence)


def test_release_static_gates_are_machine_readable(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]

    migration = migration_head_check(repo_root)
    routes = route_policy_check()
    ai = ai_regression_check(repo_root)
    report = build_release_report(
        repo_root,
        execute_commands=False,
        evidence_dir=tmp_path,
    )

    assert migration.status == "passed"
    assert len(migration.evidence["heads"]) == 1
    assert routes.status == "passed"
    assert routes.evidence["missing_metadata"] == []
    assert ai.status == "passed"
    assert report["status"] == "failed"
    assert report["release_ready"] is False
    assert report["security"] == {
        "contains_secret_values": False,
        "contains_model_content": False,
    }
    assert any(
        item["category"] == "staging_evidence"
        and item["status"] == "blocked"
        for item in report["checks"]
    )


def test_real_provider_probe_records_governed_ledger_without_content(monkeypatch):
    monkeypatch.setattr(
        model_governance,
        "build_provider",
        lambda _settings, _profile: _ProbeProvider(),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        model_provider="qwen",
        dashscope_api_key="configured-for-test",
        model_rate_limit_backend="memory",
        model_reserved_output_tokens=128,
    )

    report = run_probe(settings, profile="qwen:qwen-plus")

    assert report["status"] == "passed"
    assert report["requested_profile"] == "qwen:qwen-plus"
    assert report["actual_provider"] == "qwen"
    assert report["actual_model"] == "qwen-plus"
    assert report["ledger_status"] == "completed"
    assert report["provider_result_matches_ledger"] is True
    assert report["latency_ms"] >= 1
    assert report["prompt_content_recorded"] is False
    assert report["response_content_recorded"] is False
    assert report["api_key_recorded"] is False
