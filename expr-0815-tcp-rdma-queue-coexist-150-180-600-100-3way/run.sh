#!/usr/bin/env bash
set -euo pipefail

EXPR_DIR="$(cd "$(dirname "$0")" && pwd)"

"$EXPR_DIR/register.sh"
"$EXPR_DIR/launch_registered.sh"
