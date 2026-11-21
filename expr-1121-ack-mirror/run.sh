#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./waf -j "${GRC_BUILD_JOBS:-12}"
exec python3 expr-1121-ack-mirror/run.py "$@"
