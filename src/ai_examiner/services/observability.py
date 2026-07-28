from __future__ import annotations

import atexit
import re
import secrets
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Link, SpanKind, Status, StatusCode

from .. import __version__
from ..config import Settings

_REQUEST_ID: ContextVar[str] = ContextVar("telemetry_request_id", default="")
_AUDIT_TRACE_ID: ContextVar[str] = ContextVar(
    "telemetry_audit_trace_id",
    default="",
)
_LOCK = threading.Lock()
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_./:{} @-]{1,200}$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_./:{} @-]{1,240}$")
_TRACEPARENT = re.compile(
    r"^00-([\da-f]{32})-([\da-f]{16})-([\da-f]{2})$",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"AIza[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bcanary[_:-][A-Za-z0-9_-]+", re.IGNORECASE),
)
_FORBIDDEN_ATTRIBUTE_FRAGMENTS = (
    "authorization",
    "body",
    "content",
    "cookie",
    "document",
    "header",
    "password",
    "prompt",
    "query",
    "secret",
    "statement",
    "text",
    "token",
    "transcript",
    "url",
)
_SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "ai_examiner.job.id",
        "ai_examiner.job.kind",
        "ai_examiner.request.id",
        "celery.action",
        "celery.state",
        "celery.task_name",
        "db.namespace",
        "db.operation.name",
        "db.system",
        "db.system.name",
        "error.type",
        "http.method",
        "http.request.method",
        "http.response.status_code",
        "http.route",
        "http.status_code",
        "messaging.destination.name",
        "messaging.operation",
        "messaging.operation.type",
        "messaging.system",
        "network.protocol.name",
        "network.protocol.version",
        "otel.kind",
        "request.id",
        "rpc.method",
        "rpc.service",
        "rpc.system",
        "server.port",
        "service.name",
        "service.namespace",
        "service.version",
    }
)


@dataclass
class TelemetryRuntime:
    configured: bool = False
    enabled: bool = False
    exporter_ready: bool = False
    failure_code: str = ""
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    http_requests: Any = None
    http_duration: Any = None
    job_deliveries: Any = None
    job_duration: Any = None


_RUNTIME = TelemetryRuntime()
_FASTAPI_APPS: set[int] = set()
_SQL_ENGINES: set[int] = set()
_HTTPX_INSTRUMENTED = False
_CELERY_INSTRUMENTED = False


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def _safe_string(value: object) -> str:
    candidate = str(value).strip()
    if (
        not candidate
        or len(candidate) > 240
        or _contains_secret(candidate)
        or not _SAFE_VALUE.fullmatch(candidate)
    ):
        return "[REDACTED]"
    return candidate


def _safe_attribute_value(value: object) -> object:
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray, str),
    ):
        return tuple(_safe_attribute_value(item) for item in value[:32])
    return "[REDACTED]"


def redact_telemetry_attributes(
    attributes: Mapping[str, object] | None,
) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for raw_key, value in (attributes or {}).items():
        key = str(raw_key).strip().lower()
        if (
            key not in _SAFE_ATTRIBUTE_KEYS
            or any(fragment in key for fragment in _FORBIDDEN_ATTRIBUTE_FRAGMENTS)
        ):
            continue
        sanitized[key] = _safe_attribute_value(value)
    return sanitized


def _safe_span_name(name: str) -> str:
    candidate = (name or "").strip()
    if (
        not candidate
        or len(candidate) > 200
        or _contains_secret(candidate)
        or not _SAFE_NAME.fullmatch(candidate)
    ):
        return "ai_examiner.operation"
    return candidate


def _sanitized_span(span: ReadableSpan) -> ReadableSpan:
    events = tuple(
        Event(
            _safe_span_name(event.name),
            redact_telemetry_attributes(event.attributes),
            event.timestamp,
        )
        for event in span.events
    )
    links = tuple(
        Link(
            link.context,
            redact_telemetry_attributes(link.attributes),
        )
        for link in span.links
    )
    resource = Resource.create(
        redact_telemetry_attributes(span.resource.attributes)
    )
    return ReadableSpan(
        name=_safe_span_name(span.name),
        context=span.context,
        parent=span.parent,
        resource=resource,
        attributes=redact_telemetry_attributes(span.attributes),
        events=events,
        links=links,
        kind=span.kind,
        instrumentation_info=span.instrumentation_info,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanExporter(SpanExporter):
    def __init__(self, delegate: SpanExporter):
        self.delegate = delegate

    def export(
        self,
        spans: Sequence[ReadableSpan],
    ) -> SpanExportResult:
        try:
            return self.delegate.export(
                tuple(_sanitized_span(span) for span in spans)
            )
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        try:
            self.delegate.shutdown()
        except Exception:
            return

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            force_flush = getattr(self.delegate, "force_flush", None)
            if force_flush is None:
                return True
            return bool(force_flush(timeout_millis))
        except Exception:
            return False


def _parse_headers(raw: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in (raw or "").split(","):
        key, separator, value = item.partition("=")
        key = key.strip()
        value = value.strip()
        if (
            not separator
            or not key
            or not value
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key)
        ):
            continue
        headers[key] = value
    return headers


def _signal_endpoint(base: str, signal: str) -> str:
    return f"{base.rstrip('/')}/v1/{signal}"


def configure_telemetry(settings: Settings) -> TelemetryRuntime:
    global _RUNTIME
    with _LOCK:
        if _RUNTIME.configured:
            return _RUNTIME
        _RUNTIME.configured = True
        if not settings.telemetry_enabled:
            return _RUNTIME
        issues = settings.telemetry_configuration_issues()
        if issues:
            _RUNTIME.failure_code = issues[0]
            return _RUNTIME
        try:
            headers = _parse_headers(
                settings.telemetry_otlp_headers.get_secret_value()
                if settings.telemetry_otlp_headers
                else None
            )
            resource = Resource.create(
                {
                    "service.name": settings.telemetry_service_name,
                    "service.namespace": settings.telemetry_service_namespace,
                    "service.version": __version__,
                }
            )
            tracer_provider = TracerProvider(
                resource=resource,
                sampler=ParentBased(
                    TraceIdRatioBased(settings.telemetry_trace_sample_ratio)
                ),
            )
            span_exporter = RedactingSpanExporter(
                OTLPSpanExporter(
                    endpoint=_signal_endpoint(
                        settings.telemetry_otlp_endpoint or "",
                        "traces",
                    ),
                    headers=headers,
                    timeout=settings.telemetry_export_timeout_seconds,
                )
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(span_exporter)
            )
            metric_exporter = OTLPMetricExporter(
                endpoint=_signal_endpoint(
                    settings.telemetry_otlp_endpoint or "",
                    "metrics",
                ),
                headers=headers,
                timeout=settings.telemetry_export_timeout_seconds,
            )
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=(
                    settings.telemetry_metric_interval_seconds * 1000
                ),
                export_timeout_millis=int(
                    settings.telemetry_export_timeout_seconds * 1000
                ),
            )
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )
            trace.set_tracer_provider(tracer_provider)
            metrics.set_meter_provider(meter_provider)
            meter = meter_provider.get_meter("ai_examiner.operations")
            _RUNTIME = TelemetryRuntime(
                configured=True,
                enabled=True,
                exporter_ready=True,
                tracer_provider=tracer_provider,
                meter_provider=meter_provider,
                http_requests=meter.create_counter(
                    "ai_examiner.http.server.requests",
                    unit="{request}",
                ),
                http_duration=meter.create_histogram(
                    "ai_examiner.http.server.duration",
                    unit="s",
                ),
                job_deliveries=meter.create_counter(
                    "ai_examiner.jobs.deliveries",
                    unit="{delivery}",
                ),
                job_duration=meter.create_histogram(
                    "ai_examiner.jobs.duration",
                    unit="s",
                ),
            )
            atexit.register(shutdown_telemetry)
        except Exception:
            _RUNTIME = TelemetryRuntime(
                configured=True,
                failure_code="telemetry_bootstrap_failed",
            )
        return _RUNTIME


def telemetry_status(settings: Settings) -> dict[str, object]:
    runtime = configure_telemetry(settings)
    return {
        "enabled": runtime.enabled,
        "required": settings.telemetry_required,
        "exporter_ready": runtime.exporter_ready,
        "failure_code": runtime.failure_code,
    }


def shutdown_telemetry() -> None:
    runtime = _RUNTIME
    try:
        if runtime.meter_provider is not None:
            runtime.meter_provider.shutdown()
    except Exception:
        pass
    try:
        if runtime.tracer_provider is not None:
            runtime.tracer_provider.shutdown()
    except Exception:
        pass


def instrument_fastapi_app(app, settings: Settings) -> None:
    runtime = configure_telemetry(settings)
    if not runtime.enabled or id(app) in _FASTAPI_APPS:
        return
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=runtime.tracer_provider,
        meter_provider=NoOpMeterProvider(),
        excluded_urls=settings.telemetry_excluded_urls,
        exclude_spans=["receive", "send"],
    )
    _FASTAPI_APPS.add(id(app))


def instrument_sqlalchemy_engine(engine, settings: Settings) -> None:
    runtime = configure_telemetry(settings)
    if not runtime.enabled or id(engine) in _SQL_ENGINES:
        return
    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        tracer_provider=runtime.tracer_provider,
        enable_commenter=False,
    )
    _SQL_ENGINES.add(id(engine))


def instrument_httpx(settings: Settings) -> None:
    global _HTTPX_INSTRUMENTED
    runtime = configure_telemetry(settings)
    if not runtime.enabled or _HTTPX_INSTRUMENTED:
        return
    HTTPXClientInstrumentor().instrument(
        tracer_provider=runtime.tracer_provider,
        meter_provider=NoOpMeterProvider(),
    )
    _HTTPX_INSTRUMENTED = True


def instrument_celery(settings: Settings) -> None:
    global _CELERY_INSTRUMENTED
    runtime = configure_telemetry(settings)
    if not runtime.enabled or _CELERY_INSTRUMENTED:
        return
    CeleryInstrumentor().instrument(
        tracer_provider=runtime.tracer_provider,
    )
    _CELERY_INSTRUMENTED = True


@contextmanager
def request_correlation(
    request_id: str,
    audit_trace_id: str,
) -> Iterator[None]:
    request_token = _REQUEST_ID.set(request_id)
    trace_token = _AUDIT_TRACE_ID.set(audit_trace_id)
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("ai_examiner.request.id", request_id)
        yield
    finally:
        _AUDIT_TRACE_ID.reset(trace_token)
        _REQUEST_ID.reset(request_token)


def current_correlation() -> tuple[str, str]:
    request_id = _REQUEST_ID.get()
    carrier: dict[str, str] = {}
    try:
        propagate.inject(carrier)
    except Exception:
        carrier = {}
    traceparent = carrier.get("traceparent", "")
    if _TRACEPARENT.fullmatch(traceparent):
        return request_id, traceparent.lower()
    audit_trace_id = _AUDIT_TRACE_ID.get().lower()
    if re.fullmatch(r"[\da-f]{32}", audit_trace_id):
        return (
            request_id,
            f"00-{audit_trace_id}-{secrets.token_hex(8)}-01",
        )
    return request_id, ""


def trace_id_from_traceparent(traceparent: str) -> str:
    matched = _TRACEPARENT.fullmatch((traceparent or "").strip())
    return matched.group(1).lower() if matched else ""


@contextmanager
def worker_delivery_span(envelope) -> Iterator[Any]:
    carrier = {"traceparent": getattr(envelope, "traceparent", "")}
    parent_context = (
        propagate.extract(carrier)
        if _TRACEPARENT.fullmatch(carrier["traceparent"])
        else otel_context.Context()
    )
    tracer = trace.get_tracer("ai_examiner.jobs")
    started = monotonic()
    status = "completed"
    with tracer.start_as_current_span(
        "ai_examiner.job.delivery",
        context=parent_context,
        kind=SpanKind.CONSUMER,
        attributes={
            "ai_examiner.job.id": envelope.job_id,
            "ai_examiner.job.kind": envelope.kind,
            "ai_examiner.request.id": getattr(envelope, "request_id", ""),
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            status = "failed"
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", type(exc).__name__)
            raise
        finally:
            record_job_delivery(
                envelope.kind,
                status,
                monotonic() - started,
            )


def record_http_request(
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    runtime = _RUNTIME
    if not runtime.enabled:
        return
    attributes = {
        "http.request.method": _safe_string(method.upper()),
        "http.route": _safe_string(route or "unmatched"),
        "http.response.status_code": int(status_code),
    }
    try:
        runtime.http_requests.add(1, attributes)
        runtime.http_duration.record(max(0.0, duration_seconds), attributes)
    except Exception:
        return


def record_job_delivery(
    kind: str,
    status: str,
    duration_seconds: float,
) -> None:
    runtime = _RUNTIME
    if not runtime.enabled:
        return
    attributes = {
        "ai_examiner.job.kind": _safe_string(kind),
        "celery.state": _safe_string(status),
    }
    try:
        runtime.job_deliveries.add(1, attributes)
        runtime.job_duration.record(max(0.0, duration_seconds), attributes)
    except Exception:
        return
