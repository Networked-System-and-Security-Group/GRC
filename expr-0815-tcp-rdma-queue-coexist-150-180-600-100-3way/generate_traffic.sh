#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR"
python3 config/large_traffic_gen.py \
  --wan-rate 600G \
  --wan-duration-ms 100 \
  --wan-base-time 2.0 \
  --wan-output w-tcp-600-100.txt \
  --wan-only
