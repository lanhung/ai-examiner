#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
require_file "$ENTERPRISE_ENV_PATH"

enterprise_compose stop
echo "Enterprise containers stopped. Named volumes were preserved."
