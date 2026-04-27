# Experiment Workflows

Open this document when the task is about running simulations, launching sweeps, checking status, or understanding what `run.py` actually does.

## One-Time Build

Build ns-3 once before the first run:

```bash
./waf configure --build-profile=optimized
./waf
```

`run.py` still calls `./waf` on every launch, so the one-time configure step is the only manual build step you should need in normal use.

## Single Experiment

Minimal pure-RDMA run:

```bash
python3 run.py \
  --simul_time 0.05 \
  --cdf WebSearch \
  --intra_load 30 \
  --inter_load_all 60 \
  --wan_cc_mode 1 \
  --tcp_flow ""
```

Important details:

- `run.py` creates `mix/output/[id]-<timestamp>/` for every launch.
- It writes the exact runtime config to `mix/output/[id]-.../config.txt`.
- It launches `./waf --run 'scratch/remote <config>'` in the background unless `--stdout 1` or `--debug 1` is used.
- If the target flow file does not exist, it auto-generates one with `config/wan_traffic_gen.py`.

## Batch Sweeps

Use these scripts first before creating a new sweep runner:

- `autorun.py`: paper-style mode and load sweeps using predefined presets such as `wo_gscc` and `gscc`
- `autorun_flow_scan.py`: generate multiple randomized flow-set variations and run each mode against each variation
- Other top-level Python sweep scripts such as `beta_sensitivity.py` or `two_layer_hash_ablation.py`: one-off experiment drivers, best treated as examples rather than the core orchestration layer

The usual pattern is:

1. generate or select flow files in `config/`,
2. call `run.py` repeatedly with different `--wan_cc_mode`, buffer, or raw-param settings,
3. record a human-readable tag through `--msg`.

## Monitoring And Cleanup

Useful commands:

```bash
python3 check.py state
python3 check.py state 10
python3 check.py kill "1-5"
```

Relevant files:

- `mix/index.txt`: next experiment id
- `mix/history.txt`: optional run messages written by `--msg`
- `mix/output/[id]-.../config.log`: stdout and stderr from `scratch/remote`

`check.py` identifies `scratch/remote` processes for this repository only, then maps them back to `config.txt` paths under `mix/output/`.

## What `run.py` Owns

`run.py` is the canonical entrypoint for a single simulation launch. It owns:

- CLI defaults and argument validation
- config-template generation
- optional flow auto-generation
- output-folder creation
- launch mode selection (`stdout`, background, or `gdb`)
- `--extra KEY=VALUE` passthrough for rapid experimentation

If the task changes how an experiment is launched, `run.py` is the first file to open.

## Common Pitfalls

- Be explicit about `--tcp_flow`. The current default is not empty, so omitting it can accidentally enable TCP+RDMA mixed runs.
- Be explicit about `--my_flow`. The current default is also not empty, so omitting it does not necessarily regenerate a flow file from the load parameters.
- `run.py` currently materializes config blocks only for `dcqcn` and `timely`. The enum map contains more names than the config-generation branch actually supports.
- When reproducing a past run, the most trustworthy source is the archived `mix/output/[id]-.../config.txt`, not the shell command you think was used.
