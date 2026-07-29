#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_command docker
require_command sha256sum
require_file "$ENTERPRISE_ENV_PATH"

BACKUP_ROOT="${ENTERPRISE_BACKUP_ROOT:-$(
  enterprise_env_value ENTERPRISE_BACKUP_ROOT "$ENTERPRISE_ROOT/data/enterprise-backups"
)}"
if [[ "$BACKUP_ROOT" != /* ]]; then
  BACKUP_ROOT="$ENTERPRISE_ROOT/${BACKUP_ROOT#./}"
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_SET="$BACKUP_ROOT/$STAMP"
LOCK_DIR="$BACKUP_ROOT/.backup.lock"

mkdir -p "$BACKUP_ROOT"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another enterprise backup is running" >&2
  exit 3
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

umask 077
mkdir -p "$BACKUP_SET"

enterprise_compose exec -T postgres sh -ec \
  'pg_dump --format=custom --compress=6 --no-owner \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
  >"$BACKUP_SET/postgres.dump"

enterprise_compose exec -T postgres sh -ec \
  'psql --no-psqlrc --tuples-only --no-align \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --command "SELECT version_num FROM alembic_version"' \
  >"$BACKUP_SET/alembic-version.txt"

if [[ "${USE_MINIO:-false}" == "true" ]]; then
  enterprise_compose run --rm --no-deps \
    --env BACKUP_STAMP="$STAMP" \
    object-tool -ec '
    mc alias set storage http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mkdir -p "/backup/$BACKUP_STAMP/objects"
    mc mirror --overwrite "storage/$S3_BUCKET" "/backup/$BACKUP_STAMP/objects" >/dev/null
  ' >&2
  touch "$BACKUP_SET/objects-complete"
fi

GIT_COMMIT="$(git -C "$ENTERPRISE_ROOT" rev-parse HEAD 2>/dev/null || printf unknown)"
CREATED_EPOCH="$(date -u +%s)"
cat >"$BACKUP_SET/metadata.json" <<EOF
{
  "format_version": 1,
  "created_at": "$STAMP",
  "created_at_epoch": $CREATED_EPOCH,
  "git_commit": "$GIT_COMMIT",
  "database_format": "postgresql_custom",
  "objects_included": ${USE_MINIO:-false},
  "redis_authoritative": false
}
EOF

(
  cd "$BACKUP_SET"
  find . -type f ! -name manifest.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum >manifest.sha256
)
chmod -R go-rwx "$BACKUP_SET"
printf '%s\n' "$BACKUP_SET"
