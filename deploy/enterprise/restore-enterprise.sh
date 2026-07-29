#!/usr/bin/env bash
set -euo pipefail

BACKUP_SET="${1:-}"
if [[ -z "$BACKUP_SET" ]]; then
  echo "Usage: restore-enterprise.sh BACKUP_DIRECTORY" >&2
  exit 2
fi

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_command docker
require_command sha256sum
require_command realpath
require_file "$ENTERPRISE_ENV_PATH"
require_file "$BACKUP_SET/manifest.sha256"
require_file "$BACKUP_SET/postgres.dump"
require_file "$BACKUP_SET/metadata.json"

BACKUP_SET="$(realpath "$BACKUP_SET")"
BACKUP_ROOT="${ENTERPRISE_BACKUP_ROOT:-$(
  enterprise_env_value ENTERPRISE_BACKUP_ROOT "$ENTERPRISE_ROOT/backups/enterprise"
)}"
if [[ "$BACKUP_ROOT" != /* ]]; then
  BACKUP_ROOT="$ENTERPRISE_ROOT/${BACKUP_ROOT#./}"
fi
BACKUP_ROOT="$(realpath "$BACKUP_ROOT")"
case "$BACKUP_SET/" in
  "$BACKUP_ROOT"/*) ;;
  *)
    echo "Backup must be located under ENTERPRISE_BACKUP_ROOT" >&2
    exit 2
    ;;
esac

(
  cd "$BACKUP_SET"
  sha256sum --check --strict manifest.sha256
)

RESTORE_PROJECT_NAME="${RESTORE_PROJECT_NAME:-}"
safe_project_name "$RESTORE_PROJECT_NAME"
if [[ "$RESTORE_PROJECT_NAME" != ai-examiner-restore-* ]]; then
  echo "RESTORE_PROJECT_NAME must begin with ai-examiner-restore-" >&2
  exit 2
fi
if [[ "${CONFIRM_ISOLATED_RESTORE:-}" != "yes" ]]; then
  echo "Set CONFIRM_ISOLATED_RESTORE=yes to create isolated restore volumes" >&2
  exit 2
fi

if docker volume ls --format '{{.Name}}' | grep -Eq "^${RESTORE_PROJECT_NAME}[_-]"; then
  echo "Restore project already has volumes; refusing non-empty target" >&2
  exit 3
fi

RESTORE_STARTED_EPOCH="$(date -u +%s)"
RESTORE_STAMP="$(basename "$BACKUP_SET")"
export COMPOSE_PROJECT_NAME="$RESTORE_PROJECT_NAME"
export APP_BIND_ADDRESS=127.0.0.1
export APP_PORT="${RESTORE_APP_PORT:-18080}"
export USE_HTTPS=false
export USE_OBSERVABILITY=false
LIVE_HOST_DATA_DIR="${HOST_DATA_DIR:-$(
  enterprise_env_value HOST_DATA_DIR "$ENTERPRISE_ROOT/data"
)}"
RESTORE_HOST_DATA_DIR="${RESTORE_HOST_DATA_DIR:-$(
  printf '%s/backups/restore-data/%s' "$ENTERPRISE_ROOT" "$RESTORE_PROJECT_NAME"
)}"
LIVE_HOST_DATA_DIR="$(realpath -m "$LIVE_HOST_DATA_DIR")"
RESTORE_HOST_DATA_DIR="$(realpath -m "$RESTORE_HOST_DATA_DIR")"
if [[ "$RESTORE_HOST_DATA_DIR" == "$LIVE_HOST_DATA_DIR" ]]; then
  echo "Restore data directory must be isolated from live application data" >&2
  exit 3
fi
mkdir -p "$RESTORE_HOST_DATA_DIR"
export HOST_DATA_DIR="$RESTORE_HOST_DATA_DIR"
enterprise_compose_files

enterprise_compose up -d postgres
enterprise_compose run --rm database-bootstrap \
  python /app/deploy/enterprise/bootstrap_database.py prepare-roles

cat "$BACKUP_SET/postgres.dump" \
  | enterprise_compose exec -T postgres sh -ec \
    'pg_restore --exit-on-error --no-owner \
      --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"'

if [[ "${USE_MINIO:-false}" == "true" ]]; then
  require_file "$BACKUP_SET/objects-complete"
fi

if [[ "${USE_MINIO:-false}" == "true" ]]; then
  enterprise_compose up -d minio
  enterprise_compose run --rm minio-init
  enterprise_compose run --rm --no-deps \
    --env BACKUP_STAMP="$RESTORE_STAMP" \
    object-tool -ec '
      mc alias set storage http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
      mc mirror --overwrite "/backup/$BACKUP_STAMP/objects" "storage/$S3_BUCKET"
    '
fi

enterprise_compose run --rm database-bootstrap
enterprise_compose up -d ai-examiner worker

VERIFY_BASE_URL="http://127.0.0.1:$APP_PORT" \
VERIFY_READY="${VERIFY_READY:-true}" \
  "$ENTERPRISE_ROOT/deploy/enterprise/verify-enterprise.sh"

if [[ "${USE_MINIO:-false}" == "true" ]]; then
  VERIFY_DIRECTORY="$BACKUP_SET/restore-verification"
  rm -rf "$VERIFY_DIRECTORY"
  enterprise_compose run --rm --no-deps \
    --env BACKUP_STAMP="$RESTORE_STAMP" \
    object-tool -ec '
      mc alias set storage http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
      mkdir -p "/backup/$BACKUP_STAMP/restore-verification"
      mc mirror --overwrite "storage/$S3_BUCKET" "/backup/$BACKUP_STAMP/restore-verification"
    '
  diff -u \
    <(cd "$BACKUP_SET/objects" && find . -type f -print0 | sort -z | xargs -0 sha256sum) \
    <(cd "$VERIFY_DIRECTORY" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
  rm -rf "$VERIFY_DIRECTORY"
fi

RESTORE_COMPLETED_EPOCH="$(date -u +%s)"
BACKUP_CREATED_EPOCH="$(
  sed -n 's/.*"created_at_epoch":[[:space:]]*\([0-9][0-9]*\).*/\1/p' \
    "$BACKUP_SET/metadata.json"
)"
if [[ -z "$BACKUP_CREATED_EPOCH" ]]; then
  echo "Backup metadata does not contain created_at_epoch" >&2
  exit 4
fi

RPO_SECONDS="$((RESTORE_STARTED_EPOCH - BACKUP_CREATED_EPOCH))"
RTO_SECONDS="$((RESTORE_COMPLETED_EPOCH - RESTORE_STARTED_EPOCH))"
RPO_HOURS="${ENTERPRISE_RPO_HOURS:-$(enterprise_env_value ENTERPRISE_RPO_HOURS 24)}"
RTO_TARGET_SECONDS="${ENTERPRISE_RTO_SECONDS:-$(
  enterprise_env_value ENTERPRISE_RTO_SECONDS 14400
)}"
RPO_TARGET_SECONDS="$(( RPO_HOURS * 3600 ))"
RPO_STATUS=passed
RTO_STATUS=passed
if (( RPO_SECONDS > RPO_TARGET_SECONDS )); then RPO_STATUS=failed; fi
if (( RTO_SECONDS > RTO_TARGET_SECONDS )); then RTO_STATUS=failed; fi

cat >"$BACKUP_SET/disaster-recovery.json" <<EOF
{
  "format_version": 1,
  "status": "$([[ "$RPO_STATUS" == passed && "$RTO_STATUS" == passed ]] && printf passed || printf failed)",
  "restore_project": "$RESTORE_PROJECT_NAME",
  "backup_manifest_verified": true,
  "database_restore_verified": true,
  "object_restore_verified": ${USE_MINIO:-false},
  "rpo_seconds": $RPO_SECONDS,
  "rpo_target_seconds": $RPO_TARGET_SECONDS,
  "rpo_status": "$RPO_STATUS",
  "rto_seconds": $RTO_SECONDS,
  "rto_target_seconds": $RTO_TARGET_SECONDS,
  "rto_status": "$RTO_STATUS"
}
EOF
chmod 600 "$BACKUP_SET/disaster-recovery.json"
cat "$BACKUP_SET/disaster-recovery.json"

if [[ "$RPO_STATUS" != passed || "$RTO_STATUS" != passed ]]; then
  exit 6
fi
