#!/usr/bin/env bash
# Recorded commands; do not run a second hardware sweep during an active batch.
set -euo pipefail

case "${1:-status}" in
  status)
    ssh pengbo29@192.168.5.112 \
      'python3 ~/p4-identifier-seqhash-20261115/watch_status.py'
    ;;
  analyze)
    cd "$(dirname "$0")/../../.."
    task_plot_python="${P4_PLOT_PYTHON:-/home/micraow/miniconda3/envs/math_modeling/bin/python}"
    "$task_plot_python" expr-p4-identifier-seqhash/plot_results.py \
      expr-p4-identifier-seqhash/results/paper-identifier-repeat-20261115
    "$task_plot_python" expr-p4-identifier-seqhash/report_results.py \
      expr-p4-identifier-seqhash/results/paper-identifier-repeat-20261115
    ;;
  *)
    echo 'Usage: commands.sh [status|analyze]' >&2
    exit 2
    ;;
esac

# The already-running orchestration on 112 was launched inside tmux:
# cd ~/p4-identifier-seqhash-20261115
# python3 -u finish_paper.py > results/finish.log 2>&1
# It invokes:
# python3 scripts/sweep_identifier.py \
#   --cohort paper-identifier-repeat-20261115 \
#   --qualification results/qualification/qualified.json --reps 3
