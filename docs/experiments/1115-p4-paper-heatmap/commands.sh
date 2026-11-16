#!/usr/bin/env bash
# The run branch is the operator handoff. It starts the full hardware matrix.
set -euo pipefail
case "${1:-}" in
  run)
    cd ~/p4-paper-heatmap-20261115
    python3 scripts/heatmap.py check
    python3 -u scripts/heatmap.py run | tee -a results/heatmap-run.log
    ;;
  status)
    cd ~/p4-paper-heatmap-20261115
    cat results/paper-loop-heatmap-20261115/status.json
    ;;
  analyze)
    cd "$(dirname "$0")/../../../expr-p4-paper-loop"
    [[ $# == 2 ]] || { echo 'Usage: commands.sh analyze /absolute/path/to/copied/cohort' >&2; exit 2; }
    cohort=$(realpath "$2")
    [[ "$cohort" == "$(pwd)/results/$(basename "$cohort")" ]] || {
      echo 'Copy the named cohort under expr-p4-paper-loop/results first.' >&2; exit 2;
    }
    python3 scripts/heatmap.py audit --cohort "$(basename "$cohort")"
    PYTHONPATH="$PWD/scripts${PYTHONPATH:+:$PYTHONPATH}" "${P4_PLOT_PYTHON:-python3}" \
      "$cohort/plot_final.py" "$cohort/summary.csv" "$cohort/figures/closed_loop_hit_zh"
    ;;
  *) echo 'Usage: commands.sh {run|status|analyze COHORT}' >&2; exit 2 ;;
esac
