#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-${POSTGRES_TEST_ENV_FILE:-}}"
PYTHON_BIN="${PYTHON_BIN:-python}"
RESET_TEST_DATABASE="${RESET_TEST_DATABASE:-false}"
RUN_FULL_SUITE="${RUN_FULL_SUITE:-false}"

if [[ -z "$ENV_FILE" || ! -f "$ENV_FILE" ]]; then
  printf 'Usage: %s /absolute/path/to/postgres-test.env\n' "$0" >&2
  exit 2
fi
if [[ "$ENV_FILE" != /* ]]; then
  printf 'The PostgreSQL test environment file must use an absolute path.\n' >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required=(
  PG_TEST_DB PG_PORT PG_MIGRATION_USER PG_MIGRATION_PASSWORD
  POSTGRES_APP_USER POSTGRES_APP_PASSWORD
)
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    printf 'Required setting is empty: %s\n' "$key" >&2
    exit 2
  fi
done
if [[ ! "$PG_TEST_DB" =~ ^[a-zA-Z0-9_]+_test$ ]]; then
  printf 'Refusing to operate on non-test database: %s\n' "$PG_TEST_DB" >&2
  exit 2
fi
if [[ ! "$PG_PORT" =~ ^[0-9]+$ ]]; then
  printf 'Invalid PostgreSQL port: %s\n' "$PG_PORT" >&2
  exit 2
fi

for command in pg_isready runuser dropdb createdb "$PYTHON_BIN"; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 2
  fi
done
pg_isready -h 127.0.0.1 -p "$PG_PORT"

if [[ "$RESET_TEST_DATABASE" == "true" ]]; then
  if [[ "$(id -u)" != "0" ]]; then
    printf 'RESET_TEST_DATABASE=true requires root for the postgres OS role.\n' >&2
    exit 2
  fi
  runuser -u postgres -- dropdb --if-exists --force -p "$PG_PORT" "$PG_TEST_DB"
  runuser -u postgres -- createdb \
    -p "$PG_PORT" -O "$PG_MIGRATION_USER" -E UTF8 \
    --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0 \
    "$PG_TEST_DB"
fi

DATABASE_URL="$($PYTHON_BIN - <<'PY'
import os
from urllib.parse import quote

user = quote(os.environ["PG_MIGRATION_USER"], safe="")
password = quote(os.environ["PG_MIGRATION_PASSWORD"], safe="")
print(
    f"postgresql+psycopg://{user}:{password}@127.0.0.1:"
    f"{os.environ['PG_PORT']}/{os.environ['PG_TEST_DB']}"
)
PY
)"
export DATABASE_URL AI_EXAMINER_TEST_DATABASE_URL="$DATABASE_URL"

cd "$ROOT"
"$PYTHON_BIN" deploy/enterprise/bootstrap_database.py prepare-roles
"$PYTHON_BIN" -m alembic upgrade head
"$PYTHON_BIN" -m alembic current
"$PYTHON_BIN" deploy/verify-v09-rls.py
"$PYTHON_BIN" deploy/verify-v09-runtime-login.py

if [[ "$RUN_FULL_SUITE" == "true" ]]; then
  MODEL_PROVIDER=mock CELERY_ALWAYS_EAGER=true "$PYTHON_BIN" -m pytest
fi
