#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXPR_DIR="$(cd "$(dirname "$0")" && pwd)"

source "$EXPR_DIR/registered.env"

cd "$ROOT_DIR"
"$EXPR_DIR/verify_configs.sh"

launch_one() {
  local label="$1"
  local output_dir="$2"
  local pid_file="$EXPR_DIR/$label-waf.pid"
  local old_pid

  if [[ -s "$pid_file" ]]; then
    old_pid="$(<"$pid_file")"
    if kill -0 "$old_pid" 2>/dev/null; then
      echo "$label is already running as PID $old_pid" >&2
      exit 1
    fi
  fi

  setsid -f bash -c \
    'echo "$$" > "$1"; exec "$2" --run "scratch/remote $3"' \
    "$label" "$pid_file" "$ROOT_DIR/waf" "$output_dir/config.txt" \
    > "$output_dir/config.log" 2>&1

  for _ in 1 2 3 4 5; do
    [[ -s "$pid_file" ]] && break
    sleep 1
  done
  if [[ ! -s "$pid_file" ]]; then
    echo "No PID file was created for $label" >&2
    exit 1
  fi
  echo "Launched $label as PID $(<"$pid_file")"
}

launch_one q1 "$Q1_DIR"
launch_one q3 "$Q3_DIR"
launch_one no-tcp "$NO_TCP_DIR"
