#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_command curl
require_file "$ENTERPRISE_ENV_PATH"

APP_PORT="${APP_PORT:-8000}"
BASE_URL="${VERIFY_BASE_URL:-http://127.0.0.1:$APP_PORT}"
wait_for_url "$BASE_URL/health" "${VERIFY_ATTEMPTS:-60}"

HEALTH="$(curl -fsS "$BASE_URL/health")"
READY_STATUS="$(curl -sS -o /tmp/ai-examiner-ready.json -w '%{http_code}' "$BASE_URL/ready")"
if [[ "${VERIFY_READY:-true}" == "true" && "$READY_STATUS" != "200" ]]; then
  cat /tmp/ai-examiner-ready.json >&2
  echo "Enterprise readiness check failed with HTTP $READY_STATUS" >&2
  exit 4
fi

ALEMBIC_VERSION="$(
  enterprise_compose exec -T postgres sh -ec \
    'psql --no-psqlrc --tuples-only --no-align \
      --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      --command "SELECT version_num FROM alembic_version"'
)"

ROLE_RESULT="$(
  printf '%s\n' \
    "SELECT rolcanlogin::text || chr(44) || rolsuper::text || chr(44) ||" \
    "rolbypassrls::text FROM pg_roles WHERE rolname = :'app_user';" |
    enterprise_compose exec -T postgres sh -ec '
      psql --no-psqlrc --tuples-only --no-align \
        --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        --set app_user="$POSTGRES_APP_USER"
    '
)"
if [[ "$ROLE_RESULT" != "true,false,false" ]]; then
  echo "Runtime database login does not satisfy least-privilege checks" >&2
  exit 5
fi

AUDIT_ROLE_RESULT="$(
  enterprise_compose exec -T postgres sh -ec \
    'psql --no-psqlrc --tuples-only --no-align \
      --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      --command "SELECT rolcanlogin::text || chr(44) || rolsuper::text ||
        chr(44) || rolbypassrls::text FROM pg_roles
        WHERE rolname = '\''ai_examiner_audit_maintenance'\''"'
)"
if [[ "$AUDIT_ROLE_RESULT" != "false,false,false" ]]; then
  echo "Audit maintenance role does not satisfy least-privilege checks" >&2
  exit 5
fi

RLS_RESULT="$(
  enterprise_compose run --rm --no-deps database-bootstrap \
    python /app/deploy/verify-v09-rls.py
)"

printf '%s\n' "$HEALTH"
printf '{"status":"passed","alembic_version":"%s","runtime_role":"least_privilege"}\n' \
  "$ALEMBIC_VERSION"
printf '%s\n' "$RLS_RESULT"
