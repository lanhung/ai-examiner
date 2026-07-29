#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_file "$ENTERPRISE_ENV_PATH"

STATE_DIR="$ENTERPRISE_ROOT/data/enterprise-release-state"
TARGET_REF="${1:-}"
if [[ -z "$TARGET_REF" && -f "$STATE_DIR/previous-commit" ]]; then
  TARGET_REF="$(cat "$STATE_DIR/previous-commit")"
fi
if [[ -z "$TARGET_REF" ]]; then
  echo "Usage: rollback-enterprise.sh GIT_REF" >&2
  exit 2
fi
if [[ -n "$(git -C "$ENTERPRISE_ROOT" status --porcelain)" ]]; then
  echo "Refusing rollback with a dirty Git worktree" >&2
  exit 3
fi

cd "$ENTERPRISE_ROOT"
CURRENT_COMMIT="$(git rev-parse HEAD)"
git fetch --tags --prune origin
git cat-file -e "$TARGET_REF^{commit}"

enterprise_compose stop ai-examiner worker
if [[ "${USE_HTTPS:-false}" == "true" ]]; then
  enterprise_compose stop caddy
fi
git checkout --detach "$TARGET_REF"
enterprise_compose build
enterprise_compose up -d --remove-orphans
"$ENTERPRISE_ROOT/deploy/enterprise/verify-enterprise.sh"

printf 'Application rollback completed: %s -> %s\n' \
  "$CURRENT_COMMIT" "$(git rev-parse HEAD)"
echo "Database schema was not downgraded; restore a backup only into isolation."
