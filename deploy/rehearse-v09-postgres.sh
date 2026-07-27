#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_NAME="${V09_POSTGRES_PROJECT_NAME:-ai-examiner-v09-postgres-parity}"
COMPOSE_FILE="$ROOT/docker-compose.postgres-test.yml"

cleanup() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --file "$COMPOSE_FILE" \
    down --remove-orphans -v
}
trap cleanup EXIT

cleanup
docker compose \
  --project-name "$PROJECT_NAME" \
  --file "$COMPOSE_FILE" \
  up \
  --build \
  --abort-on-container-exit \
  --exit-code-from postgres-tests
