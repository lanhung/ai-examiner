# v0.9 WP-11 Observability Evaluation

Status: deterministic implementation gates completed locally. SQLite and
PostgreSQL GitHub Actions are the authoritative branch acceptance gates.

## Local result

- `pytest`: 282 passed;
- coverage: 85%;
- Ruff: passed;
- Python compile check: passed;
- browser JavaScript syntax check: passed;
- Alembic head remains `20260728_0016`;
- no new database migration is required.

Docker is not installed in the local Windows environment. GitHub Actions
therefore validates the merged Docker Compose configuration, while WP-12 owns
the process-level Vultr rehearsal with real containers.

## Evaluated behaviors

- configuration rejects missing, credential-bearing and unsafe endpoints;
- span export uses an attribute allowlist;
- headers, URLs, SQL statements, content and exception details are absent;
- exporter exceptions return telemetry failure without changing business
  state;
- a real FastAPI request commits data while the Collector is unreachable;
- request IDs and W3C trace context enter a version 2 worker envelope;
- version 1 worker envelopes remain readable;
- health output contains status only, not endpoints or header values;
- Compose, Collector, Tempo, Prometheus, Alertmanager and Grafana files parse;
- existing job hardening, tenancy and security tests remain passing.

## Acceptance mapping

| Requirement | Evidence |
|---|---|
| Request-to-worker trace correlation | Task-envelope v2 test and worker delivery span |
| No raw content or secrets | Canary API key, SQL, URL and exception tests |
| Backend outage does not corrupt state | Isolated subprocess commits and reloads a project |
| FastAPI instrumentation | Application bootstrap and safe request metrics |
| SQLAlchemy instrumentation | API and worker engine instrumentation |
| HTTPX instrumentation | Process-level client instrumentation with URL removal |
| Celery instrumentation | Worker bootstrap and explicit parent extraction |
| Operational dashboards | Provisioned Grafana dashboard and Prometheus source |
| Alerting | Five Prometheus rules and local Alertmanager receiver |

## Residual operational validation

WP-12 will perform the Vultr process-level rehearsal:

- start PostgreSQL, Redis, API, worker, Caddy and observability;
- inspect a request-to-worker trace in Tempo;
- trigger and resolve a synthetic alert;
- restart Collector during API and worker activity;
- verify application state and recovery objectives.
