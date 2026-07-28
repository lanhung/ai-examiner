# v0.9 OpenTelemetry and Operations

Status: implemented by WP-11 on `research/v0.9.0`.

## Purpose

WP-11 adds operational visibility without turning telemetry into an
authoritative data store or a business-path dependency. The application must
continue to create, assess, export and delete records when an observability
backend is slow or unavailable.

The implementation covers:

- W3C request and worker trace correlation;
- FastAPI, SQLAlchemy, HTTPX and Celery instrumentation;
- explicit low-cardinality HTTP and background-job metrics;
- export-time span redaction;
- an OTLP Collector, Tempo, Prometheus, Grafana and Alertmanager Compose
  overlay;
- provisioned dashboards and alert rules;
- configuration, privacy and outage tests.

## Runtime architecture

```text
Browser / API client
        |
        | traceparent
        v
FastAPI instrumentation
        |
        +-- SQLAlchemy spans
        +-- HTTPX/provider spans
        +-- safe HTTP counters and histograms
        |
        | TaskEnvelope v2
        | request_id + traceparent
        v
Celery worker instrumentation
        |
        +-- worker delivery span
        +-- SQLAlchemy/HTTPX child spans
        +-- safe job counters and histograms
        |
        v
OTLP/HTTP Collector
        |
        +-- traces -> Tempo
        +-- metrics -> Prometheus
        +-- defensive attribute deletion
        |
        v
Grafana dashboards / Prometheus alerts / Alertmanager
```

## Failure boundary

Telemetry is disabled by default. When enabled:

- spans use `BatchSpanProcessor`;
- metric export is periodic;
- exporter timeouts are bounded;
- exporter exceptions become failed telemetry exports and are not raised into
  request or worker business logic;
- no database transaction depends on an OTLP response;
- `TELEMETRY_REQUIRED` affects readiness only, not transaction semantics.

`/health` reports configuration state. `/ready` fails for a required telemetry
configuration that cannot be initialized. A Collector outage after startup is
reported through Collector/Prometheus alerts and does not roll back business
state.

## Trace correlation

`TaskEnvelope` version 2 adds:

```json
{
  "request_id": "request correlation identifier",
  "traceparent": "00-<trace-id>-<span-id>-<flags>"
}
```

Version 1 remains readable so queued jobs created before the upgrade can
finish. New jobs use version 2. Envelope integrity continues to cover all
fields through the existing SHA-256 digest.

Workers extract the W3C parent and create a `CONSUMER` span named
`ai_examiner.job.delivery`. Worker audit events reuse the request ID and trace
ID from the integrity-protected task envelope.

## Privacy contract

Telemetry is not allowed to contain:

- API keys, bearer tokens, cookies or authorization headers;
- request or response bodies;
- prompts, answers, transcripts or uploaded document content;
- full URLs or query strings;
- SQL statements;
- exception messages or stack traces;
- organization, learner or project identifiers as metric labels.

Application span export is allowlist-based. Unsafe attribute keys are dropped
and unsafe values are replaced with `[REDACTED]`. A second Collector processor
deletes common sensitive attributes before traces reach Tempo.

Safe span correlation identifiers may be high-cardinality because traces are
sampled. Metrics use only bounded labels:

- HTTP method;
- route template;
- HTTP status code;
- background-job kind;
- background-job terminal state.

## Metrics and alerts

Application instruments:

```text
ai_examiner.http.server.requests
ai_examiner.http.server.duration
ai_examiner.jobs.deliveries
ai_examiner.jobs.duration
```

The dashboard shows request rate, HTTP 5xx ratio, p95 latency, background-job
outcomes and telemetry export failures. Alert rules detect:

- HTTP 5xx ratio above 5% for 10 minutes;
- p95 request latency above two seconds for 15 minutes;
- background-job failures;
- Collector scrape failure;
- Collector trace export failures.

Alertmanager defaults to a local receiver with no external credentials.
Operators can add email, Slack, PagerDuty or another receiver in a private
deployment override. Credentials must never be committed.

## Configuration

```env
TELEMETRY_ENABLED=true
TELEMETRY_REQUIRED=false
TELEMETRY_SERVICE_NAME=ai-examiner
TELEMETRY_SERVICE_NAMESPACE=ai-examiner
TELEMETRY_OTLP_ENDPOINT=http://otel-collector:4318
TELEMETRY_OTLP_HEADERS=
TELEMETRY_ALLOW_INSECURE_OTLP=true
TELEMETRY_TRACE_SAMPLE_RATIO=0.1
TELEMETRY_EXPORT_TIMEOUT_SECONDS=2
TELEMETRY_METRIC_INTERVAL_SECONDS=30
TELEMETRY_EXCLUDED_URLS=/health,/ready
```

`TELEMETRY_OTLP_HEADERS` is a secret environment value and is never returned
by health endpoints. Production endpoints containing user info, query strings
or fragments are rejected. Plain HTTP requires an explicit opt-in and is
intended only for the private Docker network.

## Docker Compose

Set a Grafana password in `.env`:

```env
GRAFANA_ADMIN_PASSWORD=<long-random-value>
```

Start the application plus observability:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.observability.yml \
  up -d --build --remove-orphans
```

For HTTPS also include `docker-compose.https.yml`.

Prometheus and Grafana bind to loopback:

```text
127.0.0.1:9090
127.0.0.1:3000
```

Use an SSH tunnel for Grafana administration:

```bash
ssh -L 3000:127.0.0.1:3000 root@VULTR_HOST
```

## Operator checks

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.observability.yml \
  ps

curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

WP-11 has no database migration. To disable observability, restart without
`docker-compose.observability.yml` and set `TELEMETRY_ENABLED=false`. Do not
use `docker compose down -v` during normal upgrades.

