#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXPR_DIR="$(cd "$(dirname "$0")" && pwd)"
Q1_BASE="$ROOT_DIR/mix/output/[349]-08-14-03:36:59/config.txt"
Q3_BASE="$ROOT_DIR/mix/output/[350]-08-14-03:36:59/config.txt"
ENV_FILE="$EXPR_DIR/registered.env"

RDMA_FLOW="config/w-dynamic-150-180.txt"
TCP_FLOW="config/w-tcp-600-100.txt"
Q1_TAG="rdma150-180-tcp600-100-q1"
Q3_TAG="rdma150-180-tcp600-100-q3"
NO_TCP_TAG="rdma150-180-tcp600-100-no-tcp"
RESUME_Q1_ID=""

if [[ "${1:-}" == "--resume-q1" && $# == 2 && "${2:-}" =~ ^[0-9]+$ ]]; then
  RESUME_Q1_ID="$2"
elif [[ $# != 0 ]]; then
  echo "Usage: $0 [--resume-q1 ID]" >&2
  exit 2
fi

cd "$ROOT_DIR"

if [[ -e "$ENV_FILE" ]]; then
  echo "Refusing to register twice: $ENV_FILE already exists" >&2
  exit 1
fi

for required in "$Q1_BASE" "$Q3_BASE" "$ROOT_DIR/$RDMA_FLOW" "$ROOT_DIR/$TCP_FLOW"; do
  if [[ ! -f "$required" ]]; then
    echo "Required file is missing: $required" >&2
    exit 1
  fi
done

for tag in "$Q1_TAG" "$Q3_TAG" "$NO_TCP_TAG"; do
  collision="$(find "$ROOT_DIR/mix/output" -mindepth 1 -maxdepth 1 -type d -name "*-$tag" -print -quit)"
  if [[ -n "$collision" ]]; then
    if [[ "$tag" == "$Q1_TAG" && -n "$RESUME_Q1_ID" &&
          "$(basename "$collision")" == "[$RESUME_Q1_ID]-"* ]]; then
      continue
    fi
    echo "Output tag collision: $collision" >&2
    exit 1
  fi
done

terminate_registration_run() {
  local id="$1"
  local register_log="$2"

  # run.py has no registration-only mode. Stop only the temporary process
  # associated with this just-reserved numeric ID before normalizing its config.
  for _ in 1 2 3 4; do
    python3 check.py kill "$id" >> "$register_log" 2>&1
    sleep 1
  done

  if python3 check.py state 20 | rg -q "Experiment: .*\\[$id\\]"; then
    echo "Registration process for experiment $id is still running" >&2
    exit 1
  fi
}

archive_registration_output() {
  local label="$1"
  local output_dir="$2"
  local archive_dir="$EXPR_DIR/registration-attempts/$label"

  mkdir -p "$archive_dir"
  find "$output_dir" -mindepth 1 -maxdepth 1 ! -name config.txt \
    -exec mv -t "$archive_dir" -- {} +
}

normalize_config() {
  local baseline="$1"
  local config_path="$2"
  local queue="$3"
  local include_tcp="$4"
  local tag="$5"
  local generated_time output_name output_path tmp_path

  generated_time="$(awk '$1 == "TIME" {$1=""; sub(/^ /, ""); print; exit}' "$config_path")"
  output_name="$(basename "$(dirname "$config_path")")"
  output_path="mix/output/$output_name"
  tmp_path="$config_path.normalized.$$"

  awk \
    -v output_path="$output_path" \
    -v rdma_flow="$RDMA_FLOW" \
    -v tcp_flow="$TCP_FLOW" \
    -v queue="$queue" \
    -v generated_time="$generated_time" \
    -v tag="$tag" \
    -v include_tcp="$include_tcp" '
      $1 == "FLOW_FILE"       { print "FLOW_FILE " rdma_flow; next }
      $1 == "OUTPUT_DIR_PATH" { print "OUTPUT_DIR_PATH " output_path; next }
      $1 == "TCP_QUEUE_INDEX" { print "TCP_QUEUE_INDEX " queue; next }
      $1 == "WAIT_TCP_COMPLETION" { next }
      $1 == "TIME"            { print "TIME " generated_time; next }
      $1 == "MSG"             { print "MSG " tag; next }
      $1 == "TCP_FLOW_FILE" {
        if (include_tcp == 1) {
          print "TCP_FLOW_FILE " tcp_flow
          emitted_tcp = 1
        }
        next
      }
      { print }
      END {
        if (include_tcp == 1 && emitted_tcp != 1)
          print "TCP_FLOW_FILE " tcp_flow
        print "WAIT_TCP_COMPLETION 0"
      }
    ' "$baseline" > "$tmp_path"

  mv "$tmp_path" "$config_path"
}

register_one() {
  local label="$1"
  local baseline="$2"
  local queue="$3"
  local include_tcp="$4"
  local tag="$5"
  local tcp_arg register_log config_path output_dir output_name id

  register_log="$EXPR_DIR/register-$label.log"
  if [[ "$include_tcp" == "1" ]]; then
    tcp_arg="$TCP_FLOW"
  else
    tcp_arg=""
  fi

  python3 run.py \
    --config "$baseline" \
    --topo cernet_topo \
    --my_flow w-dynamic-150-180 \
    --tcp_flow "$tcp_arg" \
    --tcp_queue_index "$queue" \
    --msg "$tag" \
    --stdout 0 \
    --skip-build 1 \
    --extra "FLOW_FILE=$RDMA_FLOW" \
    --extra "MSG=$tag" \
    > "$register_log" 2>&1

  config_path="$(awk -F 'Config filename:' 'NF == 2 {print $2; exit}' "$register_log")"
  output_dir="$(dirname "$config_path")"
  output_name="$(basename "$output_dir")"
  if [[ ! -f "$config_path" ]]; then
    echo "Could not validate registered config path: $config_path" >&2
    exit 1
  fi
  case "$output_dir" in
    "$ROOT_DIR"/mix/output/\[*\]-*) ;;
    *)
      echo "Could not validate registered output directory: $output_dir" >&2
      exit 1
      ;;
  esac
  id="${output_name#\[}"
  id="${id%%\]-*}"
  if [[ ! "$id" =~ ^[0-9]+$ ]]; then
    echo "Could not extract experiment ID from: $output_name" >&2
    exit 1
  fi

  terminate_registration_run "$id" "$register_log"
  archive_registration_output "$label" "$output_dir"
  normalize_config "$baseline" "$config_path" "$queue" "$include_tcp" "$tag"

  REGISTERED_ID="$id"
  REGISTERED_DIR="$output_dir"
  echo "Registered $label as experiment $id: $output_dir"
}

resume_one() {
  local label="$1"
  local baseline="$2"
  local queue="$3"
  local include_tcp="$4"
  local tag="$5"
  local id="$6"
  local output_dir config_path

  output_dir="$(find "$ROOT_DIR/mix/output" -mindepth 1 -maxdepth 1 -type d \
    -name "[[]$id[]]-*-$tag" -print -quit)"
  config_path="$output_dir/config.txt"
  if [[ -z "$output_dir" || ! -f "$config_path" ]]; then
    echo "Could not find resumable $label registration for ID $id" >&2
    exit 1
  fi

  archive_registration_output "$label" "$output_dir"
  normalize_config "$baseline" "$config_path" "$queue" "$include_tcp" "$tag"
  REGISTERED_ID="$id"
  REGISTERED_DIR="$output_dir"
  echo "Resumed $label as experiment $id: $output_dir"
}

if [[ -n "$RESUME_Q1_ID" ]]; then
  resume_one q1 "$Q1_BASE" 1 1 "$Q1_TAG" "$RESUME_Q1_ID"
else
  register_one q1 "$Q1_BASE" 1 1 "$Q1_TAG"
fi
q1_id="$REGISTERED_ID"
q1_dir="$REGISTERED_DIR"

register_one q3 "$Q3_BASE" 3 1 "$Q3_TAG"
q3_id="$REGISTERED_ID"
q3_dir="$REGISTERED_DIR"

register_one no-tcp "$Q1_BASE" 1 0 "$NO_TCP_TAG"
no_tcp_id="$REGISTERED_ID"
no_tcp_dir="$REGISTERED_DIR"

env_tmp="$ENV_FILE.tmp.$$"
{
  printf 'Q1_ID=%q\n' "$q1_id"
  printf 'Q1_DIR=%q\n' "$q1_dir"
  printf 'Q3_ID=%q\n' "$q3_id"
  printf 'Q3_DIR=%q\n' "$q3_dir"
  printf 'NO_TCP_ID=%q\n' "$no_tcp_id"
  printf 'NO_TCP_DIR=%q\n' "$no_tcp_dir"
} > "$env_tmp"
mv "$env_tmp" "$ENV_FILE"

"$EXPR_DIR/verify_configs.sh"
