#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_file "$ENTERPRISE_ENV_PATH"

cd "$ENTERPRISE_ROOT"
PREVIOUS_COMMIT="$(git rev-parse HEAD)"
BACKUP_SET="$("$ENTERPRISE_ROOT/deploy/enterprise/backup-enterprise.sh")"
mkdir -p "$ENTERPRISE_ROOT/data/enterprise-release-state"
printf '%s\n' "$PREVIOUS_COMMIT" \
  >"$ENTERPRISE_ROOT/data/enterprise-release-state/previous-commit"
printf '%s\n' "$BACKUP_SET" \
  >"$ENTERPRISE_ROOT/data/enterprise-release-state/previous-backup"

git fetch --tags --prune origin
git checkout "${DEPLOY_BRANCH:-research/v0.9.0}"
git pull --ff-only origin "${DEPLOY_BRANCH:-research/v0.9.0}"

enterprise_compose build --pull
enterprise_compose stop ai-examiner worker
if [[ "${USE_HTTPS:-false}" == "true" ]]; then
  enterprise_compose stop caddy
fi

enterprise_compose run --rm database-bootstrap
enterprise_compose up -d --remove-orphans
"$ENTERPRISE_ROOT/deploy/enterprise/verify-enterprise.sh"

printf 'Enterprise update completed: %s -> %s\n' \
  "$PREVIOUS_COMMIT" "$(git rev-parse HEAD)"
