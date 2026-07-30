import json
import subprocess
from pathlib import Path

from ai_examiner.config import Settings
from ai_examiner.db import _alembic_config_path
from ai_examiner.model_governance_probe import run_probe
from ai_examiner.providers.base import ModelProvider, ProviderResult
from ai_examiner.release_hardening import (
    _evidence_validation_errors,
    ai_regression_check,
    build_release_report,
    dependency_audit,
    migration_head_check,
    route_policy_check,
    scan_tracked_secrets,
    working_tree_clean_check,
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


def test_working_tree_gate_binds_release_evidence_to_committed_source(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.test")
    _git(tmp_path, "config", "user.name", "Release Test")
    source = tmp_path / "tracked.txt"
    source.write_text("committed\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")

    assert working_tree_clean_check(tmp_path).status == "passed"

    source.write_text("uncommitted\n", encoding="utf-8")
    result = working_tree_clean_check(tmp_path)

    assert result.status == "failed"
    assert result.evidence["entry_count"] == 1
    assert result.evidence["status_codes"] == [" M"]
    assert "tracked.txt" not in json.dumps(result.evidence)


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


def test_dependency_audit_does_not_describe_command_failure_as_zero_issues(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        "ai_examiner.release_hardening.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["pip_audit"],
            returncode=1,
            stdout='{"dependencies": []}',
            stderr="temporary audit service failure",
        ),
    )

    result = dependency_audit(tmp_path)

    assert result.status == "failed"
    assert "command failed with status 1" in result.summary
    assert "found 0 issue" not in result.summary
    assert result.evidence["vulnerabilities"] == []
    assert "temporary audit service failure" not in json.dumps(result.evidence)


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


def test_specialized_release_evidence_requires_real_measurements():
    base = {
        "generated_at": "2026-07-29T00:00:00+00:00",
        "source_commit": "a" * 40,
        "status": "passed",
    }

    assert _evidence_validation_errors(
        "quota_model_policy",
        {
            **base,
            "actual_provider": "qwen",
            "actual_model": "qwen-plus",
            "ledger_status": "completed",
            "provider_result_matches_ledger": True,
            "prompt_content_recorded": False,
            "response_content_recorded": False,
            "api_key_recorded": False,
        },
    ) == []
    assert _evidence_validation_errors(
        "staging_observation",
        {
            **base,
            "observation_hours": 2,
            "open_release_blockers": 1,
            "tls_verified": False,
            "oidc_verified": False,
        },
    ) == [
        "observation_period_too_short",
        "open_release_blockers",
        "tls_not_verified",
        "oidc_not_verified",
    ]
    assert _evidence_validation_errors(
        "disaster_recovery",
        {
            **base,
            "rpo_seconds": 90_000,
            "rto_seconds": 15_000,
            "object_restore_verified": False,
            "rollback_success": False,
        },
    ) == [
        "rpo_target_missed",
        "rto_target_missed",
        "object_restore_not_verified",
        "rollback_not_verified",
    ]


def test_wheel_runtime_finds_repository_alembic_config(monkeypatch, tmp_path):
    config = tmp_path / "alembic.ini"
    config.write_text("[alembic]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _alembic_config_path() == config
