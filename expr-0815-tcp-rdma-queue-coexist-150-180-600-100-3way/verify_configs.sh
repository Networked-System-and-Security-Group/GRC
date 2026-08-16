#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXPR_DIR="$(cd "$(dirname "$0")" && pwd)"
Q1_BASE="$ROOT_DIR/mix/output/[349]-08-14-03:36:59/config.txt"
Q3_BASE="$ROOT_DIR/mix/output/[350]-08-14-03:36:59/config.txt"
RDMA_HASH="2349e1807c9bf72ca41e8ee7e937d7b1a30ce832f0bcf9c6e806ff686775446b"
TCP_HASH="bfe43ab95595e8bb1e102b81bf697c1b3ecfdf6886a0051f8b89ba5df682a128"

source "$EXPR_DIR/registered.env"

assert_key() {
  local file="$1"
  local key="$2"
  local expected="$3"
  local actual

  actual="$(awk -v key="$key" '$1 == key {$1=""; sub(/^ /, ""); print}' "$file")"
  if [[ "$actual" != "$expected" ]]; then
    echo "$file: expected '$key $expected', got '$actual'" >&2
    exit 1
  fi
}

assert_absent() {
  local file="$1"
  local key="$2"
  if awk -v key="$key" '$1 == key {found=1} END {exit !found}' "$file"; then
    echo "$file: unexpected key '$key'" >&2
    exit 1
  fi
}

strip_authorized_fields() {
  awk '
    $1 == "FLOW_FILE" ||
    $1 == "OUTPUT_DIR_PATH" ||
    $1 == "TCP_QUEUE_INDEX" ||
    $1 == "TCP_FLOW_FILE" ||
    $1 == "WAIT_TCP_COMPLETION" ||
    $1 == "TIME" ||
    $1 == "MSG" { next }
    { print }
  ' "$1"
}

for config in "$Q1_DIR/config.txt" "$Q3_DIR/config.txt" "$NO_TCP_DIR/config.txt"; do
  assert_key "$config" FLOW_FILE config/w-dynamic-150-180.txt
  assert_key "$config" FLOWGEN_START_TIME 2.0
  assert_key "$config" FLOWGEN_STOP_TIME 2.05
  assert_key "$config" WAIT_TCP_COMPLETION 0
  assert_absent "$config" PRINT_LOG
  assert_absent "$config" THEMIS_ENABLE
done

assert_key "$Q1_DIR/config.txt" TCP_QUEUE_INDEX 1
assert_key "$Q1_DIR/config.txt" TCP_FLOW_FILE config/w-tcp-600-100.txt
assert_key "$Q1_DIR/config.txt" MSG rdma150-180-tcp600-100-q1

assert_key "$Q3_DIR/config.txt" TCP_QUEUE_INDEX 3
assert_key "$Q3_DIR/config.txt" TCP_FLOW_FILE config/w-tcp-600-100.txt
assert_key "$Q3_DIR/config.txt" MSG rdma150-180-tcp600-100-q3

assert_key "$NO_TCP_DIR/config.txt" TCP_QUEUE_INDEX 1
assert_absent "$NO_TCP_DIR/config.txt" TCP_FLOW_FILE
assert_key "$NO_TCP_DIR/config.txt" MSG rdma150-180-tcp600-100-no-tcp

diff -u <(strip_authorized_fields "$Q1_BASE") <(strip_authorized_fields "$Q1_DIR/config.txt")
diff -u <(strip_authorized_fields "$Q3_BASE") <(strip_authorized_fields "$Q3_DIR/config.txt")
diff -u <(strip_authorized_fields "$Q1_BASE") <(strip_authorized_fields "$NO_TCP_DIR/config.txt")

printf '%s  %s\n' \
  "$RDMA_HASH" "$ROOT_DIR/config/w-dynamic-150-180.txt" \
  "$TCP_HASH" "$ROOT_DIR/config/w-tcp-600-100.txt" \
  | sha256sum -c -

echo "All three registered configurations match the canonical baseline."
