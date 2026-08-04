from __future__ import annotations

from ai_examiner.release_evidence import SuiteResult, _base, _probe_otlp


def test_suite_result_only_passes_clean_zero_exit():
    assert SuiteResult(3, 0, 0, 0, 0.1, 0, "digest").passed is True
    assert SuiteResult(3, 1, 0, 0, 0.1, 1, "digest").passed is False


def test_release_evidence_base_is_sanitized():
    payload = _base("a" * 40, status="passed")

    assert payload["schema_version"] == "1.0"
    assert payload["source_commit"] == "a" * 40
    assert payload["status"] == "passed"
    assert "secret" not in payload


def test_otlp_probe_exports_redacted_wire_payload():
    result = _probe_otlp()

    assert result["verified"] is True
    assert result["request_count"] >= 1
    assert result["canary_leak_count"] == 0
    assert len(result["wire_sha256"]) == 64
