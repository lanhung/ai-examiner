#!/usr/bin/env bash
set -euo pipefail

ENTERPRISE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ENV_FILE="${APP_ENV_FILE:-.env.enterprise}"
if [[ "$APP_ENV_FILE" = /* ]]; then
  ENTERPRISE_ENV_PATH="$APP_ENV_FILE"
else
  ENTERPRISE_ENV_PATH="$ENTERPRISE_ROOT/$APP_ENV_FILE"
fi
APP_ENV_FILE="$ENTERPRISE_ENV_PATH"
export APP_ENV_FILE

enterprise_compose_files() {
  ENTERPRISE_COMPOSE_FILES=(
    -f "$ENTERPRISE_ROOT/docker-compose.yml"
    -f "$ENTERPRISE_ROOT/docker-compose.prod.yml"
    -f "$ENTERPRISE_ROOT/docker-compose.enterprise.yml"
  )
  if [[ "${USE_MINIO:-false}" == "true" ]]; then
    ENTERPRISE_COMPOSE_FILES+=(-f "$ENTERPRISE_ROOT/docker-compose.minio.yml")
  fi
  if [[ "${USE_OBSERVABILITY:-false}" == "true" ]]; then
    ENTERPRISE_COMPOSE_FILES+=(-f "$ENTERPRISE_ROOT/docker-compose.observability.yml")
  fi
  if [[ "${USE_HTTPS:-false}" == "true" ]]; then
    ENTERPRISE_COMPOSE_FILES+=(-f "$ENTERPRISE_ROOT/docker-compose.https.yml")
  fi
}

enterprise_compose() {
  docker compose \
    --env-file "$ENTERPRISE_ENV_PATH" \
    "${ENTERPRISE_COMPOSE_FILES[@]}" \
    "$@"
}

enterprise_env_value() {
  local key="$1"
  local fallback="${2:-}"
  local value
  value="$(
    sed -n "s/^${key}=//p" "$ENTERPRISE_ENV_PATH" \
      | tail -n 1
  )"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value:-$fallback}"
}

require_file() {
  if [[ ! -f "$1" ]]; then
    printf 'Required file not found: %s\n' "$1" >&2
    exit 2
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$1" >&2
    exit 2
  fi
}

wait_for_url() {
  local url="$1"
  local attempts="${2:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  printf 'Timed out waiting for %s\n' "$url" >&2
  return 1
}

safe_project_name() {
  if [[ ! "$1" =~ ^[a-z0-9][a-z0-9_-]{2,62}$ ]]; then
    printf 'Unsafe Compose project name: %s\n' "$1" >&2
    exit 2
  fi
}

enterprise_compose_files
