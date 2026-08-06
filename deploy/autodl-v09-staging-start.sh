#!/usr/bin/env bash
set -euo pipefail

umask 077
ROOT="${AI_EXAMINER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${AI_EXAMINER_STAGING_ENV:-$ROOT/.env.oidc-staging}"
APP_PORT="${APP_PORT:-6006}"
OIDC_PORT="${TEST_OIDC_PORT:-6008}"

cd "$ROOT"
mkdir -p logs

if [[ ! -f "$ENV_FILE" ]]; then
  echo "OIDC staging environment is unavailable: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export TEST_OIDC_ISSUER="${TEST_OIDC_ISSUER:-${OIDC_ISSUER_URL:?OIDC_ISSUER_URL is required}}"
export TEST_OIDC_CLIENT_ID="${TEST_OIDC_CLIENT_ID:-${OIDC_CLIENT_ID:?OIDC_CLIENT_ID is required}}"
export TEST_OIDC_AUDIENCE="${TEST_OIDC_AUDIENCE:-${OIDC_AUDIENCE:?OIDC_AUDIENCE is required}}"
export TEST_OIDC_REDIRECT_URI="${TEST_OIDC_REDIRECT_URI:-${OIDC_REDIRECT_URI:?OIDC_REDIRECT_URI is required}}"
export TEST_OIDC_BIND="${TEST_OIDC_BIND:-0.0.0.0}"
export TEST_OIDC_PORT="$OIDC_PORT"
export APP_PORT

wait_for_url() {
  local url="$1"
  local attempts="${2:-60}"
  for _ in $(seq 1 "$attempts"); do
    curl -fsS --max-time 3 "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

listener_pid() {
  local port="$1"
  ss -ltnp "sport = :$port" 2>/dev/null \
    | sed -nE 's/.*pid=([0-9]+).*/\1/p' \
    | head -1
}

stop_stale_oidc_listener() {
  local pid command_line
  pid="$(listener_pid "$OIDC_PORT")"
  [[ -z "$pid" ]] && return 0
  if curl -fsS --max-time 3 "http://127.0.0.1:$OIDC_PORT/.well-known/openid-configuration" 2>/dev/null \
    | grep -Fq "\"issuer\":\"$TEST_OIDC_ISSUER\""; then
    return 0
  fi
  command_line="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ "$command_line" != *"oidc_test_issuer.py"* && "$command_line" != *"uvicorn ai_examiner.main:app"* ]]; then
    echo "Refusing to stop unexpected process on port $OIDC_PORT: $command_line" >&2
    exit 1
  fi
  kill "$pid"
  for _ in $(seq 1 30); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  echo "Process $pid did not release OIDC port $OIDC_PORT" >&2
  exit 1
}

if ! redis-cli ping 2>/dev/null | grep -qx PONG; then
  redis-server --daemonize yes
fi
if ! redis-cli ping 2>/dev/null | grep -qx PONG; then
  echo "Redis failed to become ready" >&2
  exit 1
fi

stop_stale_oidc_listener
if ! curl -fsS --max-time 3 "http://127.0.0.1:$OIDC_PORT/health" >/dev/null 2>&1; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  log="logs/oidc-test-issuer-$stamp.log"
  nohup .venv/bin/python deploy/testing/oidc_test_issuer.py >"$log" 2>&1 &
  echo $! >logs/oidc-test-issuer.pid
  ln -sfn "$(basename "$log")" logs/oidc-test-issuer.log
fi
if ! wait_for_url "http://127.0.0.1:$OIDC_PORT/.well-known/openid-configuration"; then
  echo "OIDC test issuer failed to become ready; check $ROOT/logs/oidc-test-issuer.log" >&2
  exit 1
fi

AI_EXAMINER_ROOT="$ROOT" APP_PORT="$APP_PORT" "$ROOT/deploy/autodl-start.sh"
if ! wait_for_url "http://127.0.0.1:$APP_PORT/ready"; then
  echo "AI Examiner readiness check failed; check $ROOT/logs/uvicorn-$APP_PORT.log" >&2
  exit 1
fi

echo "AI Examiner v0.9 staging is ready (app=$APP_PORT, oidc=$OIDC_PORT)"
