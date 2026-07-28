from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from ai_examiner.config import Settings
from ai_examiner.services.job_control import TaskEnvelope
from ai_examiner.services.observability import (
    RedactingSpanExporter,
    current_correlation,
    redact_telemetry_attributes,
    request_correlation,
    trace_id_from_traceparent,
)


class FailingExporter(SpanExporter):
    def export(self, _spans):
        raise RuntimeError("collector unavailable with canary-secret")

    def shutdown(self):
        return None


def _envelope() -> TaskEnvelope:
    return TaskEnvelope.create(
        job_id="job-observe",
        organization_id="organization-observe",
        actor_principal_id=None,
        kind="benchmark",
        required_capability="benchmark.run",
        authorization_mode="legacy_local",
        idempotency_key="observe-once",
        payload={"dataset_id": "dataset-observe"},
    )


def test_telemetry_configuration_requires_safe_explicit_endpoint():
    assert Settings(
        telemetry_enabled=True,
    ).telemetry_configuration_issues() == [
        "missing_telemetry_otlp_endpoint"
    ]
    assert Settings(
        telemetry_enabled=True,
        telemetry_otlp_endpoint="http://collector:4318",
    ).telemetry_configuration_issues() == [
        "telemetry_insecure_otlp_not_allowed"
    ]
    assert Settings(
        telemetry_enabled=True,
        telemetry_otlp_endpoint="http://collector:4318",
        telemetry_allow_insecure_otlp=True,
    ).telemetry_configuration_issues() == []
    assert Settings(
        telemetry_enabled=True,
        telemetry_otlp_endpoint="https://user:pass@collector/path?token=x",
    ).telemetry_configuration_issues() == [
        "invalid_telemetry_otlp_endpoint"
    ]


def test_telemetry_attribute_redaction_is_allowlist_based():
    sanitized = redact_telemetry_attributes(
        {
            "http.request.method": "POST",
            "http.route": "/api/v1/projects/{project_id}",
            "http.request.header.authorization": "Bearer canary-secret",
            "url.full": "https://example.test/?token=canary-secret",
            "db.statement": "SELECT 'private content'",
            "ai_examiner.request.id": "sk-proj-secret-canary",
            "untrusted.attribute": "private content",
        }
    )
    assert sanitized == {
        "http.request.method": "POST",
        "http.route": "/api/v1/projects/{project_id}",
        "ai_examiner.request.id": "[REDACTED]",
    }
    assert "canary-secret" not in repr(sanitized)
    assert "private content" not in repr(sanitized)


def test_span_exporter_removes_content_secrets_and_exception_details():
    delegate = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(RedactingSpanExporter(delegate))
    )
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span(
        "POST /api/projects",
        attributes={
            "http.request.method": "POST",
            "http.route": "/api/projects",
            "url.full": "https://example.test/?key=canary-secret",
            "db.statement": "INSERT private answer",
        },
    ) as span:
        span.add_event(
            "exception",
            {
                "exception.type": "RuntimeError",
                "exception.message": "canary-secret private answer",
                "exception.stacktrace": "private stack",
            },
        )
    provider.shutdown()

    exported = delegate.get_finished_spans()
    assert len(exported) == 1
    serialized = repr(exported[0].attributes) + repr(exported[0].events)
    assert exported[0].attributes["http.route"] == "/api/projects"
    assert exported[0].events[0].attributes == {}
    assert "canary-secret" not in serialized
    assert "private answer" not in serialized
    assert "private stack" not in serialized


def test_exporter_outage_is_failure_isolated_from_business_state():
    exporter = RedactingSpanExporter(FailingExporter())
    business_state = {"committed": False}
    business_state["committed"] = True
    result = exporter.export(())
    exporter.shutdown()
    assert result is SpanExportResult.FAILURE
    assert business_state == {"committed": True}


def test_request_context_propagates_to_v2_worker_envelope_and_v1_still_parses():
    trace_id = "1" * 32
    with request_correlation("request-observe", trace_id):
        request_id, traceparent = current_correlation()
        envelope = _envelope()

    assert request_id == "request-observe"
    assert trace_id_from_traceparent(traceparent) == trace_id
    assert envelope.version == 2
    assert envelope.request_id == "request-observe"
    assert trace_id_from_traceparent(envelope.traceparent) == trace_id
    assert TaskEnvelope.from_dict(envelope.as_dict()) == envelope

    legacy = envelope.as_dict()
    legacy["version"] = 1
    legacy.pop("request_id")
    legacy.pop("traceparent")
    parsed = TaskEnvelope.from_dict(legacy)
    assert parsed.version == 1
    assert parsed.request_id == ""
    assert parsed.traceparent == ""
    assert parsed.as_dict() == legacy


def test_health_reports_telemetry_without_endpoint_or_credentials(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    telemetry = response.json()["telemetry"]
    assert telemetry == {
        "enabled": False,
        "required": False,
        "exporter_ready": False,
        "failure_code": "",
    }
    assert "endpoint" not in telemetry
    assert "header" not in telemetry


def test_observability_compose_and_provisioning_contracts_are_parseable():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load(
        (root / "docker-compose.observability.yml").read_text("utf-8")
    )
    services = compose["services"]
    assert {
        "otel-collector",
        "tempo",
        "prometheus",
        "alertmanager",
        "grafana",
    }.issubset(services)
    assert services["prometheus"]["ports"][0].startswith("127.0.0.1:")
    assert services["grafana"]["ports"][0].startswith("127.0.0.1:")

    observability = root / "deploy" / "observability"
    for relative in (
        "otel-collector.yml",
        "tempo.yml",
        "prometheus.yml",
        "alerts.yml",
        "alertmanager.yml",
        "grafana/provisioning/datasources/datasources.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
    ):
        assert yaml.safe_load((observability / relative).read_text("utf-8"))
    dashboard = json.loads(
        (
            observability
            / "grafana"
            / "dashboards"
            / "ai-examiner-operations.json"
        ).read_text("utf-8")
    )
    assert dashboard["uid"] == "ai-examiner-operations"
    assert len(dashboard["panels"]) >= 5


def test_unreachable_collector_does_not_block_business_commit(tmp_path):
    database = tmp_path / "telemetry-outage.db"
    script = """
from fastapi.testclient import TestClient
from ai_examiner.main import app

with TestClient(app) as client:
    response = client.post(
        "/api/projects",
        json={
            "name": "Collector outage proof",
            "domain": "operations",
            "language": "en",
            "data_classification": "internal",
        },
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert project_id in {item["id"] for item in projects.json()}
"""
    env = {
        **os.environ,
        "APP_ENV": "test",
        "AUTH_MODE": "disabled",
        "MODEL_PROVIDER": "mock",
        "AUDIT_REQUIRED": "false",
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "TELEMETRY_ENABLED": "true",
        "TELEMETRY_OTLP_ENDPOINT": "http://127.0.0.1:1",
        "TELEMETRY_ALLOW_INSECURE_OTLP": "true",
        "TELEMETRY_EXPORT_TIMEOUT_SECONDS": "0.1",
        "TELEMETRY_METRIC_INTERVAL_SECONDS": "5",
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
