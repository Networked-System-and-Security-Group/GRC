#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./waf -j "${GRC_BUILD_JOBS:-8}"
exec python3 expr-1121-multi-gateway-wan/run.py "$@"
