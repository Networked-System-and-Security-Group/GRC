# Docs Index

`docs/` is the canonical documentation set for this repository. Prefer it over the legacy `instructions/` directory.

## Start Here

The main execution chain is:

`run.py -> mix/output/[id]-*/config.txt -> scratch/remote.cc -> src/point-to-point/model/*`

If you only remember one thing, remember that most repository changes are either:

1. a Python-side experiment orchestration change,
2. a `config.txt` plumbing change, or
3. a C++ transport or WAN-control change inside `src/point-to-point/model/`.

## Open By Task

| Task | Open first | Why |
| --- | --- | --- |
| Run one experiment or a batch sweep | [experiment-workflows.md](experiment-workflows.md) | Commands, output layout, and process management |
| Find the owner of a feature quickly | [code-map.md](code-map.md) | Task-to-file routing map |
| Add a new experiment parameter | [config-pipeline.md](config-pipeline.md) | `run.py -> config.txt -> remote.cc -> module` path |
| Add or change a DC-side congestion control algorithm | [add-dc-congestion-control.md](add-dc-congestion-control.md) | Host-side RDMA transport and CC extension points |
| Inspect or change current IRN retransmission behavior | [irn-retransmission-state-machine.md](irn-retransmission-state-machine.md) | Current sender/receiver IRN state machine and long-tail recovery risks |
| Add or change WAN-side GSCC or routing logic | [add-wan-control.md](add-wan-control.md) | DCI/WAN path, raw params, and WAN logs |
| Change topology or traffic inputs | [inputs.md](inputs.md) | Topology JSON schema, flow file format, generators |
| Parse outputs or add a new metric | [analysis.md](analysis.md) | Log owners, analyser entry points, and plotting |

## Fast Rules

- Do not start from `build/`, `bindings/`, or generated outputs unless the task is explicitly about them.
- For quick WAN tuning, prefer `python3 run.py --extra KEY=VALUE` over adding permanent flags immediately.
- For permanent experiment knobs, keep `run.py`, `scratch/remote.cc`, and the target C++ module in sync.
- For new metrics, the usual chain is `settings.cc` log registration -> C++ emit point -> `analysis/deep_analyse.py` parser.
