#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_file "$ENTERPRISE_ENV_PATH"
require_command docker
require_command curl

enterprise_compose config --quiet
enterprise_compose up -d --build --remove-orphans

if [[ "${USE_HTTPS:-false}" == "true" ]]; then
  SITE_ADDRESS="${SITE_ADDRESS:-$(enterprise_env_value SITE_ADDRESS)}"
  if [[ -z "$SITE_ADDRESS" ]]; then
    echo "SITE_ADDRESS is required for HTTPS verification" >&2
    exit 2
  fi
  export VERIFY_BASE_URL="https://$SITE_ADDRESS"
fi
"$ENTERPRISE_ROOT/deploy/enterprise/verify-enterprise.sh"
enterprise_compose ps
