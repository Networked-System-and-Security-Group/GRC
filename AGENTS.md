# Repository Instructions

This repository is an ns-3.19-based RDMA-over-WAN simulator for GSCC-style WAN congestion control, RDMA transport behavior, and paper-scale experiment sweeps.

## Quick Start

- One-time build: `./waf configure --build-profile=optimized && ./waf`
- Single experiment: `python3 run.py --simul_time 0.05 --cdf WebSearch --intra_load 30 --inter_load_all 60 --wan_cc_mode 1 --tcp_flow ""`
- Batch sweeps: `python3 autorun.py ...` or `python3 autorun_flow_scan.py ...`
- Check or kill running jobs: `python3 check.py state` and `python3 check.py kill "1-5"`

## Architecture

- Experiment orchestration: `run.py`, `autorun.py`, `autorun_flow_scan.py`, `check.py`
- Simulation bootstrap and config parsing: `scratch/remote.cc`
- Shared settings, raw params, and log files: `src/point-to-point/model/settings.h/.cc`
- DC transport and congestion control: `src/point-to-point/model/rdma-hw.*`, `rdma-queue-pair.*`, `qbb-net-device.*`
- WAN routing and GSCC logic: `src/point-to-point/model/wan-routing.*`
- Post-processing: `analysis/deep_analyse.py` and `analysis/*.py`

## Canonical Docs

Canonical repo docs live in `docs/`. Treat `instructions/` as legacy.

- Start here: `docs/README.md`
- Experiment execution: `docs/experiment-workflows.md`
- Config plumbing: `docs/config-pipeline.md`
- DC congestion control changes: `docs/add-dc-congestion-control.md`
- WAN or GSCC changes: `docs/add-wan-control.md`
- Topology and traffic inputs: `docs/inputs.md`
- Logs and result analysis: `docs/analysis.md`

## Repo-Specific Notes

- The main runtime path is `run.py -> mix/output/[id]-*/config.txt -> scratch/remote.cc -> src/point-to-point/model/*`.
- Prefer `--extra KEY=VALUE` plus `Settings::GetRawParam()` for fast WAN tuning before adding permanent CLI flags.
- Be explicit about `--my_flow` and `--tcp_flow` when reproducing experiments; current runner defaults are not empty.
- `run.py` currently materializes config templates for `dcqcn` and `timely`; if you expose another `--cc` mode, verify the Python runner before assuming it is wired end to end.