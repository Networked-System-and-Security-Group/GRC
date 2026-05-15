---
name: ns3-deep-analyse
description: Use when working with analysis/deep_analyse.py, parsed experiment outputs, or new post-processing metrics for this repository.
---

# Ns3 Deep Analyse

## Use This Skill

Open this skill when the task is to inspect `mix/output/[id]-*/` results, extend `analysis/deep_analyse.py`, or wire a new log into the analysis layer.

## Core Entry Points

- `latest(offset=0)` for the newest run
- `get_analyser(id)` for one run
- `analyser_iter("1-5,8")` for a range of runs
- `Analyser.read_config()` and the `__read_*` helpers for log loading
- `plot_*` methods for plotting or sanity-checking a metric

## Adding A New Metric

Use the repository analysis chain:

1. register or enable the log in `src/point-to-point/model/settings.cc`,
2. emit the data in the owning C++ module,
3. add a parser in `analysis/deep_analyse.py`,
4. add a plot or batch helper in `analysis/*.py` only if needed.

## Practical Rules

- Prefer `mix/output/[id]-MMDD-HHMM[-msg]/` as the canonical run directory format.
- Keep `--msg` short and stable so it doubles as a searchable experiment tag.
