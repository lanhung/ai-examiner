from __future__ import annotations

import json

import yaml


def thesis_versions(client):
    catalog = client.get("/api/templates").json()
    thesis = next(
        item for item in catalog if item["slug"] == "academic.thesis_defense"
    )
    detail = client.get(f"/api/templates/{thesis['id']}").json()
    return {
        item["semantic_version"]: item for item in detail["versions"]
    }


def test_export_and_reimport_always_creates_local_draft(client):
    versions = thesis_versions(client)
    exported = client.get(
        f"/api/template-versions/{versions['1.2.0']['id']}/export?format=json"
    )
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "no-store"
    assert exported.headers["x-template-export-version"] == "template-export-v1"
    assert exported.headers["x-template-fingerprint"].startswith("sha256:")
    source = exported.json()
    assert source["template"]["trust_level"] == "built_in_reviewed"
    serialized = exported.text
    for forbidden in (
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "template_snapshot_json",
        "learner_memory",
        "document_text",
        "system_prompt",
    ):
        assert forbidden not in serialized

    imported = client.post(
        "/api/templates/import",
        headers={"X-AI-Examiner-Actor": "test-operator"},
        json={
            "document": source,
            "target_slug": "local.imported_thesis",
            "semantic_version": "0.1.0",
        },
    )
    assert imported.status_code == 201
    payload = imported.json()
    assert payload["trust_assignment"] == "local_draft"
    assert payload["authorization"] == {
        "scope": "local_template_authoring",
        "enforced": False,
    }
    assert payload["template"]["owner_scope"] == "local"
    assert payload["template"]["slug"] == "local.imported_thesis"
    assert payload["version"]["status"] == "draft"
    assert payload["version"]["source"]["template"]["slug"] == (
        "local.imported_thesis"
    )
    assert payload["version"]["source"]["template"]["version"] == "0.1.0"
    assert payload["version"]["source"]["template"]["trust_level"] == "local_draft"


def test_yaml_export_round_trips_as_safe_source_only(client):
    versions = thesis_versions(client)
    exported = client.get(
        f"/api/template-versions/{versions['1.2.0']['id']}/export?format=yaml"
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/yaml")
    assert "attachment;" in exported.headers["content-disposition"]
    source = yaml.safe_load(exported.text)
    assert source["template"]["slug"] == "academic.thesis_defense"
    assert set(source) == {
        "schema_version",
        "template",
        "capabilities",
        "objectives",
        "question_policy",
        "assistance_policy",
        "conversation_policy",
        "assessment_policy",
        "report_policy",
        "safety_policy",
        "presentation_policy",
        "voice_policy",
        "compatibility",
        "overrides",
    }


def test_import_preserves_parser_safety_error_codes(client):
    alias_document = """
schema_version: "1.0"
template: &template
  slug: local.unsafe
copy: *template
"""
    unsafe = client.post(
        "/api/templates/import",
        json={"document": alias_document},
    )
    assert unsafe.status_code == 422
    assert unsafe.json()["detail"]["code"] == "TEMPLATE_IMPORT_UNSAFE"

    oversized = client.post(
        "/api/templates/import",
        json={"document": "x" * (256 * 1024 + 1)},
    )
    assert oversized.status_code == 422
    assert oversized.json()["detail"]["code"] == "TEMPLATE_IMPORT_TOO_LARGE"


def test_semantic_diff_groups_behavior_changes_and_is_deterministic(client):
    versions = thesis_versions(client)
    left_id = versions["1.0.0"]["id"]
    right_id = versions["1.2.0"]["id"]
    first = client.get(
        f"/api/template-versions/{left_id}/diff/{right_id}"
    )
    second = client.get(
        f"/api/template-versions/{left_id}/diff/{right_id}"
    )
    assert first.status_code == second.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json() == second.json()
    payload = first.json()
    assert payload["diff_version"] == "template-semantic-diff-v1"
    assert payload["summary"]["identical"] is False
    assert payload["summary"]["behavioral_change_count"] > 0
    assert "question_policy" in payload["summary"]["changed_groups"]
    assert all(
        change["path"].startswith(f"/{group['id']}")
        for group in payload["groups"]
        for change in group["changes"]
    )

    identical = client.get(
        f"/api/template-versions/{right_id}/diff/{right_id}"
    ).json()
    assert identical["summary"] == {
        "identical": True,
        "change_count": 0,
        "behavioral_change_count": 0,
        "changed_groups": [],
    }
    assert identical["groups"] == []


def test_preview_applies_bounded_overrides_without_creating_session(client):
    versions = thesis_versions(client)
    preview = client.post(
        f"/api/template-versions/{versions['1.2.0']['id']}/preview",
        json={
            "overrides": {
                "question_limit": 9,
                "question_strategy": "adaptive",
                "hints_allowed": False,
            },
            "fixture": "partial_answer",
        },
    )
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    payload = preview.json()
    assert payload["preview_version"] == "template-preview-v1"
    assert payload["fixture"] == "partial_answer"
    assert payload["effective_settings"]["question_selection"]["question_limit"] == 9
    assert payload["effective_settings"]["question_selection"]["strategy"] == "adaptive"
    assert payload["effective_settings"]["conversation"]["assistance"]["hints"][
        "allowed"
    ] is False
    accepted = {
        item["name"]
        for item in payload["override_audit"]
        if item["status"] == "accepted"
    }
    assert accepted == {"hints_allowed", "question_limit", "question_strategy"}

    invalid = client.post(
        f"/api/template-versions/{versions['1.2.0']['id']}/preview",
        json={"overrides": {"question_limit": 500}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "TEMPLATE_OVERRIDE_INVALID"


def test_transfer_endpoints_return_stable_not_found_and_validation_errors(client):
    missing_export = client.get(
        "/api/template-versions/missing/export?format=json"
    )
    assert missing_export.status_code == 404
    assert missing_export.json()["detail"]["code"] == (
        "TEMPLATE_VERSION_NOT_FOUND"
    )

    missing_diff = client.get(
        "/api/template-versions/missing/diff/also-missing"
    )
    assert missing_diff.status_code == 404
    assert missing_diff.json()["detail"]["code"] == (
        "TEMPLATE_VERSION_NOT_FOUND"
    )

    invalid_format = client.get(
        "/api/template-versions/missing/export?format=toml"
    )
    assert invalid_format.status_code == 422
    body = json.dumps(invalid_format.json())
    assert "format" in body
