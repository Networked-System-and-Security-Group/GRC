# Config Pipeline

Open this document when the task is to add a runtime parameter, wire a new CLI flag, or quickly tune an existing algorithm.

## Two Paths: Permanent vs Temporary

Use the permanent path when the knob should become part of the public experiment interface.

Use the temporary path when you are still iterating on an idea and want to avoid touching the parser in multiple places.

## Fast Path: Temporary Knobs With `--extra`

`run.py` supports repeated `--extra KEY=VALUE` arguments.

Example:

```bash
python3 run.py \
  --wan_cc_mode 1 \
  --tcp_flow "" \
  --extra WAN_EPOCH_US=500 \
  --extra BETA=0.2
```

What happens:

1. `run.py` appends `KEY VALUE` lines to the generated `config.txt`.
2. `scratch/remote.cc` stores unknown keys in `Settings::raw_params`.
3. C++ modules read them with `Settings::GetRawParam("KEY", defaultValue)`.

This is the preferred path for fast WAN tuning because `wan-routing.cc` already uses raw params heavily.

`WAIT_TCP_COMPLETION` is a recognized `remote.cc` config key that can also be injected with
`--extra`. It defaults to `0`, so the simulator may stop as soon as all RDMA flows finish even if
TCP flows remain. Set it to `1` to wait for both RDMA and TCP, subject to the existing fallback
time limit:

```bash
python3 run.py \
  --tcp_flow config/w-tcp-100.txt \
  --extra WAIT_TCP_COMPLETION=1
```

## Permanent Path: Add A Real Parameter

The standard path is:

1. Add the CLI flag to `run.py`.
2. Write it into `config_template` or the reused-config upsert path.
3. Parse the new key in `scratch/remote.cc`.
4. Store it in either:
   - a local C++ runtime variable,
   - `Settings`, or
   - the target module's own state.
5. Consume it in the target implementation.

If a future user should see the knob in `python3 run.py --help`, it belongs on this path.

## Where Different Kinds Of Values Live

| Value kind | Typical location |
| --- | --- |
| Python-only launch behavior | `run.py` |
| Shared experiment mode or enum | `scratch/remote.cc` plus `Settings` |
| WAN tuneables under active iteration | `Settings::raw_params` via `--extra` |
| Topology or flow file paths | `config.txt`, then parsed in `scratch/remote.cc` |
| Output-file registration | `src/point-to-point/model/settings.cc` |

## Reusing Old Configs

`run.py --config <path>` loads an existing `config.txt`, rewrites `OUTPUT_DIR_PATH` and `TIME`, then upserts selected authoritative values such as buffers and extra keys.

Use this when the task is "rerun an archived experiment with one or two modifications".

## Existing Examples In This Repo

- `WAN_CC_MODE`: written by `run.py`, parsed in `scratch/remote.cc`, stored in `Settings::wan_cc_mode`
- `DCI_BUFFER_SIZE` and `WAN_BUFFER_SIZE`: written by `run.py`, parsed in `scratch/remote.cc`, then used during switch setup
- `WAN_EPOCH_US`, `BETA`, `ENABLE_V`: passed through `--extra` and consumed inside `wan-routing.cc`

## If The New Knob Also Needs Analysis

The usual chain is:

1. open or enable a log file in `src/point-to-point/model/settings.cc`,
2. emit the metric from the owning C++ module,
3. parse it in `analysis/deep_analyse.py`,
4. optionally add a thin plotting wrapper in `analysis/*.py`.
