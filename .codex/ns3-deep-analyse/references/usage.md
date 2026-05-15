# NS-3 Deep Analyse

Use `analysis/deep_analyse.py` when you need to inspect a finished run under `mix/output/`.

## Common Entry Points

- `latest(offset=0)` opens the newest run
- `get_analyser(id)` opens a specific run
- `analyser_iter("1-5,8")` iterates across multiple runs

## Analysis Flow

1. Find the run directory in `mix/output/[id]-MMDD-HHMM[-msg]/`.
2. Read `config.txt` first to confirm the exact knobs.
3. Load logs through `Analyser` and its `__read_*` helpers.
4. Add new metric parsing in `deep_analyse.py` before building plots.

## Notes

- Keep `--msg` short and stable.
- Use the archived output directory, not the shell command, as the source of truth.
