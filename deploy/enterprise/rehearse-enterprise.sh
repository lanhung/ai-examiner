#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_file "$ENTERPRISE_ENV_PATH"

BACKUP_SET="$("$ENTERPRISE_ROOT/deploy/enterprise/backup-enterprise.sh")"
RESTORE_PROJECT_NAME="${RESTORE_PROJECT_NAME:-ai-examiner-restore-$(date -u +%Y%m%d%H%M%S)}"
safe_project_name "$RESTORE_PROJECT_NAME"

export RESTORE_PROJECT_NAME
export CONFIRM_ISOLATED_RESTORE=yes
"$ENTERPRISE_ROOT/deploy/enterprise/restore-enterprise.sh" "$BACKUP_SET"

printf 'Rehearsal evidence: %s/disaster-recovery.json\n' "$BACKUP_SET"
printf 'Restored project retained for inspection: %s\n' "$RESTORE_PROJECT_NAME"
printf 'Remove only after review with:\n'
printf 'COMPOSE_PROJECT_NAME=%q docker compose ' "$RESTORE_PROJECT_NAME"
printf '%q ' "${ENTERPRISE_COMPOSE_FILES[@]}"
printf 'down --remove-orphans -v\n'
