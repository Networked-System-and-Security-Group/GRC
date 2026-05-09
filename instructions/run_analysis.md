# Running analysis scripts

This repo writes experiment outputs under `mix/output/[id]-<timestamp>/` and analyzes them primarily via `analysis/deep_analyse.py`.

Detailed per-script guide:
- `docs/analysis-scripts-guide.md`

## Prereqs
From the top-level repo directory:
- Python packages (typical):

```bash
python3 -m pip install numpy pandas matplotlib cycler
```

## How analysis finds experiment data
- Each run creates a new output dir: `mix/output/[id]-.../`
- `analysis/deep_analyse.py` locates an experiment by searching for `[{id}]` in directory names.

## Quick usage (no Jupyter)
Run from repo root:

- Summarize basic FCT metrics for a range:

```bash
python3 -c "from analysis.deep_analyse import get_basic_result; print(get_basic_result('1-5'))"
```

- Print average/p99 FCT per experiment:

```bash
python3 -c "from analysis.deep_analyse import show_fct; show_fct('1-5')"
```

- Get the latest experiment as an `Analyser` object:

```bash
python3 -c "from analysis.deep_analyse import latest; a = latest(); print(a.id, a.dir)"
```

## Jupyter workflow (recommended)
- Start Jupyter in repo root, then import helpers:

```python
from analysis.deep_analyse import get_analyser, get_basic_result, latest

a = latest()              # newest experiment
# a.plot_as_rate(0, 1)     # example: plots are methods on Analyser
```

There are also interactive notebooks/scripts under `show/` (useful for quick visualization).

## Important logging caveat (affects analysis)
Some CSV logs are **disabled by default** (redirected to `/dev/null`) in `src/point-to-point/model/settings.cc::logfile::initialize_log()`:
- `qp_rate_log`, `pfc_file`, `cnp_log`, `accumulated_bytes_log`

If you call plots that read these files (e.g., `Analyser.plot_qp_rate()` reads `qp_rate_log`) you must switch those files from `OPEN_EMPTY_FILE(...)` to `OPEN_FILE(...)` and keep the CSV headers stable.

## Where metrics come from
- Core result is `flow_output` (JSON) written by `scratch/remote.cc::output_flow_info()`.
- Most other logs are CSV created in `src/point-to-point/model/settings.cc` and written throughout:
  - Drops/buffers: `src/point-to-point/model/switch-node.cc`, `src/point-to-point/model/switch-mmu.h`
  - WAN control-plane: `src/point-to-point/model/wan-routing.cc`

For deeper “what is this column?” details, see `run_sim/code/05-logging-index.md`.
