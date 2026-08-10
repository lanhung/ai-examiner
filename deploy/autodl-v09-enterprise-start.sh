#!/usr/bin/env bash
set -euo pipefail

umask 077
ROOT="${AI_EXAMINER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TOOLS_ROOT="${AI_EXAMINER_TOOLS_ROOT:-/root/autodl-tmp/ai-examiner-tools}"
PUBLIC_ENV="${AI_EXAMINER_PUBLIC_ENV:-$TOOLS_ROOT/rc1-public.env}"
MINIO_ENV="${AI_EXAMINER_MINIO_ENV:-$TOOLS_ROOT/rc1-enterprise.env}"
APP_PORT="${APP_PORT:-6006}"
OIDC_PORT="${TEST_OIDC_PORT:-6008}"

cd "$ROOT"
mkdir -p logs "$TOOLS_ROOT/logs"
for file in "$PUBLIC_ENV" "$MINIO_ENV"; do
  if [[ ! -f "$file" ]]; then
    echo "Required runtime environment is unavailable: $file" >&2
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$PUBLIC_ENV"
# shellcheck disable=SC1090
source "$MINIO_ENV"
set +a
export APP_PORT OIDC_PORT
export TEST_OIDC_ISSUER="${TEST_OIDC_ISSUER:-${OIDC_ISSUER_URL:?OIDC_ISSUER_URL is required}}"
export TEST_OIDC_CLIENT_ID="${TEST_OIDC_CLIENT_ID:-${OIDC_CLIENT_ID:?OIDC_CLIENT_ID is required}}"
export TEST_OIDC_AUDIENCE="${TEST_OIDC_AUDIENCE:-${OIDC_AUDIENCE:?OIDC_AUDIENCE is required}}"
export TEST_OIDC_REDIRECT_URI="${TEST_OIDC_REDIRECT_URI:-${OIDC_REDIRECT_URI:?OIDC_REDIRECT_URI is required}}"
export TEST_OIDC_BIND="${TEST_OIDC_BIND:-0.0.0.0}"
export TEST_OIDC_PORT="$OIDC_PORT"

wait_for_url() {
  local url="$1" attempts="${2:-90}"
  for _ in $(seq 1 "$attempts"); do
    curl -fsS --max-time 3 "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

wait_for_port() {
  local host="$1" port="$2" attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    (echo >/dev/tcp/"$host"/"$port") >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

stop_pid_file() {
  local pid_file="$1" expected="$2" pid command_line
  [[ -f "$pid_file" ]] || return 0
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || { rm -f "$pid_file"; return 0; }
  kill -0 "$pid" 2>/dev/null || { rm -f "$pid_file"; return 0; }
  command_line="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$command_line" == *"$expected"* ]] || return 0
  kill "$pid"
  for _ in $(seq 1 30); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$pid_file"; return 0; }
    sleep 1
  done
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$pid_file"
}

if command -v pg_isready >/dev/null 2>&1 \
  && ! pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
  pg_ctlcluster 17 main start
fi
if ! wait_for_port 127.0.0.1 5433 60; then
  echo "PostgreSQL did not become ready on port 5433" >&2
  exit 1
fi

seed_global_data() {
  local database_name database_port root_mode migration_url
  database_name="$(.venv/bin/python - <<'PY'
import os
from sqlalchemy.engine import make_url

print(make_url(os.environ["DATABASE_URL"]).database)
PY
)"
  database_port="$(.venv/bin/python - <<'PY'
import os
from sqlalchemy.engine import make_url

print(make_url(os.environ["DATABASE_URL"]).port or 5432)
PY
)"
  if [[ ! "$database_name" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Unsafe PostgreSQL database name in DATABASE_URL" >&2
    return 1
  fi
  if [[ ! "$database_port" =~ ^[0-9]+$ ]]; then
    echo "Unsafe PostgreSQL port in DATABASE_URL" >&2
    return 1
  fi
  migration_url="postgresql+psycopg://postgres@/$database_name?host=/var/run/postgresql&port=$database_port"
  root_mode="$(stat -c %a /root)"
  chmod 711 /root
  if ! runuser -u postgres -- env \
    DATABASE_URL="$migration_url" \
    PROMPT_DIR="$ROOT/prompts" \
    sh -c 'cd /tmp && exec "$@"' sh \
    "$ROOT/.venv/bin/python" \
    "$ROOT/deploy/enterprise/bootstrap_database.py" seed-global-data; then
    chmod "$root_mode" /root
    return 1
  fi
  chmod "$root_mode" /root
}

seed_global_data

if ! redis-cli ping 2>/dev/null | grep -qx PONG; then
  redis-server --daemonize yes
fi
redis-cli ping 2>/dev/null | grep -qx PONG

if ! wait_for_port 127.0.0.1 9000 1; then
  nohup "$TOOLS_ROOT/bin/minio" server "$TOOLS_ROOT/minio-data" \
    --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 \
    >"$TOOLS_ROOT/logs/minio.log" 2>&1 &
  echo $! >"$TOOLS_ROOT/logs/minio.pid"
fi
if ! wait_for_port 127.0.0.1 9000 60; then
  echo "MinIO did not become ready" >&2
  exit 1
fi

if ! wait_for_port 127.0.0.1 4317 1; then
  nohup "$TOOLS_ROOT/bin/otelcol-contrib" --config="$TOOLS_ROOT/otel-native.yml" \
    >"$TOOLS_ROOT/logs/otelcol.log" 2>&1 &
  echo $! >"$TOOLS_ROOT/logs/otelcol.pid"
fi
if ! wait_for_port 127.0.0.1 4317 60; then
  echo "OpenTelemetry Collector did not become ready" >&2
  exit 1
fi

if ! wait_for_url "http://127.0.0.1:$OIDC_PORT/health" 1; then
  nohup .venv/bin/python deploy/testing/oidc_test_issuer.py \
    >"$TOOLS_ROOT/logs/oidc-test-issuer.log" 2>&1 &
  echo $! >"$TOOLS_ROOT/logs/oidc-test-issuer.pid"
fi
if ! wait_for_url "http://127.0.0.1:$OIDC_PORT/.well-known/openid-configuration" 60; then
  echo "OIDC test issuer did not become ready" >&2
  exit 1
fi

if [[ "${CELERY_ALWAYS_EAGER:-false}" != "true" ]]; then
  worker_pid_file="$TOOLS_ROOT/logs/celery-worker.pid"
  worker_pid="$(cat "$worker_pid_file" 2>/dev/null || true)"
  if [[ ! "$worker_pid" =~ ^[0-9]+$ ]] || ! kill -0 "$worker_pid" 2>/dev/null; then
    nohup .venv/bin/celery -A ai_examiner.jobs.celery_app worker \
      --loglevel=INFO --concurrency=1 \
      >"$TOOLS_ROOT/logs/celery-worker.log" 2>&1 &
    echo $! >"$worker_pid_file"
  fi
fi

if ! wait_for_url "http://127.0.0.1:$APP_PORT/health" 1; then
  stop_pid_file "$ROOT/logs/uvicorn.pid" "uvicorn ai_examiner.main:app"
  stamp="$(date +%Y%m%d-%H%M%S)"
  log="logs/uvicorn-$APP_PORT-$stamp.log"
  nohup .venv/bin/uvicorn ai_examiner.main:app --host 0.0.0.0 --port "$APP_PORT" \
    >"$log" 2>&1 &
  echo $! >logs/uvicorn.pid
  ln -sfn "$(basename "$log")" "logs/uvicorn-$APP_PORT.log"
fi
if ! wait_for_url "http://127.0.0.1:$APP_PORT/ready" 90; then
  echo "AI Examiner enterprise runtime failed readiness" >&2
  exit 1
fi

echo "AI Examiner v0.9 enterprise runtime is ready (app=$APP_PORT, oidc=$OIDC_PORT)"
