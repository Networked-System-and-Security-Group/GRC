# Repository Instructions

This repository is an ns-3.19-based RDMA-over-WAN simulator for GSCC-style WAN congestion control, RDMA transport behavior, and paper-scale experiment sweeps.

## Quick Start

- One-time build: `./waf configure --build-profile=optimized && ./waf`
- Single experiment: `python3 run.py --simul_time 0.05 --cdf WebSearch --intra_load 30 --inter_load_all 60 --wan_cc_mode 1 --tcp_flow ""`
- Batch sweeps: `python3 autorun.py ...` or `python3 autorun_flow_scan.py ...`
- Check or kill running jobs: `python3 check.py state` and `python3 check.py kill "1-5"`
- Long/background batch sweeps from Codex or other managed shells should be launched with `setsid -f` so child `scratch/remote` processes survive after the launcher shell exits, for example:
  `setsid -f python3 expr-gscc-fair/autorun.py --modes gscc,gscc_fair --sleep 1 > expr-gscc-fair/run.log 2>&1`

## Architecture

- Experiment orchestration: `run.py`, `autorun.py`, `autorun_flow_scan.py`, `check.py`
- Simulation bootstrap and config parsing: `scratch/remote.cc`
- Shared settings, raw params, and log files: `src/point-to-point/model/settings.h/.cc`
- DC transport and congestion control: `src/point-to-point/model/rdma-hw.*`, `rdma-queue-pair.*`, `qbb-net-device.*`
- WAN routing and GSCC logic: `src/point-to-point/model/wan-routing.*`
- Post-processing: `analysis/deep_analyse.py` and `analysis/*.py`, using .venv python environment
- When starting a new experiment, create a dedicated `expr-xxx/` folder and keep the run script, notes, and result records there.
- Manage `--msg` deliberately for each run so the experiment folder and `mix/history.txt` stay readable and searchable. Keep msg short and efficient.

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

## Running And Monitoring Experiments

- `run.py` starts `./waf --run 'scratch/remote <config>'` in the background by default, unless `--stdout 1` or `--debug 1` is used.
- In managed shells, ordinary `nohup ... &` or background children may be cleaned up when the shell exits. Use `setsid -f <command> > <log> 2>&1` for long runs that must continue independently.
- To keep a PID record for a detached launcher:
  `setsid -f bash -c 'echo $$ > "$0"; exec python3 expr-xxx/autorun.py ...' expr-xxx/run.pid > expr-xxx/run.log 2>&1`
- `python3 check.py state` shows the latest 5 experiment folders by numeric ID and lists currently running `scratch/remote` processes for this repo.
- `python3 check.py state 10` checks the latest 10 experiment folders.
- `python3 check.py kill "1-5,8,13"` kills running experiments whose output path contains those IDs. ID ranges and comma-separated IDs are supported.
- `python3 check.py monitor [kill_hours] [interval_seconds]` watches current repo experiments until they finish. If `kill_hours` is positive, jobs older than that limit are killed; default polling interval is 2 seconds.

## Important baselines

- GSCC. Run by `python run.py --wan_cc_mode 1`
- Simple DCQCN. Run by `python run.py --wan_cc_mode 0`
- Simple DCQCN with inf buffer. Run by `python run.py --wan_cc_mode 0 --wan 4000 --dci 4000`
- GEMINI. Run by `python run.py --cc gemini --wan_cc_mode 0`

## run.py Options

| Flag | Default | Description |
|---|---|---|
| `--cc` | `dcqcn` | DC congestion control: `dcqcn`, `hpcc`, `timely`, `dctcp`, `gemini` |
| `--simul_time` | `0.05` | Seconds of traffic to simulate (minimum 0.005). Actual ns-3 run time = 2.0 + simul_time. |
| `--inter_load_all` | `60` | Total inter-DC offered load in Gbps (used when auto-generating flow files). |
| `--intra_load` | `30` | Per-host intra-DC offered load in Gbps (used when auto-generating flow files). |
| `--cdf` | `WebSearch` | CDF family used by the traffic generator when a flow file is auto-generated. |
| `--my_flow` | `w-dynamic-100-150` | Flow file stem (or path) to use. Pass `''` to auto-generate from `--cdf`/`--intra_load`/`--inter_load_all`. |
| `--buffer` | `9` | DC switch shared buffer size in MB. |
| `--dci_buffer` | `0` | DCI switch buffer in MB. 0 keeps the C++ default. |
| `--wan_buffer` | `0` | WAN switch buffer in MB. 0 keeps the C++ default. |
| `--topo` | `cernet_topo` | Topology file stem under `config/` (without `.txt`). |
| `--tcp_flow` | `''` | Optional TCP flow file path; enables mixed RDMA+TCP run. Same format as RDMA flow file. |
| `--wan_cc_mode` | `1` | WAN/inter-DC congestion control mode: `1`=GSCC, `0`=none (pure DCQCN). |
| `--enforce_win` | `0` | Force window-based CC even for rate-based modes. |
| `--msg` | `''` | Short label appended to the run ID and written to `mix/history.txt`. |
| `--config` | `''` | Re-use an existing `config.txt` instead of generating a new one. |
| `--extra KEY=VALUE` | — | Passthrough knob injected verbatim into `config.txt`; readable via `Settings::GetRawParam()`. Repeatable. |
| `--debug` | `0` | Launch under GDB instead of running normally. |
| `--stdout` | `0` | Print simulation output to stdout instead of a log file. |

Notes:
- Each run allocates `mix/output/[index]-MMDD-HHMM[-msg]/` and increments `mix/index.txt`.
- `--my_flow` accepts `name`, `name.txt`, or `config/name.txt`; run.py normalises all three.
- GEMINI (`--cc gemini`) forces `has_win=1`, `var_win=1`, and uses shallow ECN thresholds (all kmin=kmax=400).
- `simul_time`, `inter_load_all`, `intra_load`, `cdf` is used to automatically generate traffic files, if `my_flow` is empty.

## Key Source Files

### `scratch/remote.cc`
Simulation entry point. Reads `config.txt`, parses the JSON topology, builds the ns-3 node/link graph, assigns IP addresses, installs routing tables, configures CC and LB on every node, opens the flow file(s), schedules `ScheduleFlowInputs()` callbacks, and hands off to `Simulator::Run()`. All global simulation variables (buffer sizes, CC parameters, timing) live here as file-scope globals that are filled from `config.txt`.

### `src/point-to-point/model/rdma-hw.*`
RDMA NIC abstraction installed on every host. Owns the map of active TX (`RdmaQueuePair`) and RX (`RdmaRxQueuePair`) queue pairs. Implements all DC congestion control algorithms — DCQCN (mode 1), HPCC (mode 3), TIMELY (mode 7), DCTCP (mode 8), GEMINI (mode 9) — as methods on this class. Handles packet transmission scheduling, ACK/NACK processing, ECN feedback, rate updates, and window management. The per-QP state machines (timers, rate, window) live in `rdma-queue-pair.*`; `RdmaHw` orchestrates them.

### `src/point-to-point/model/switch-node.*`
Switch node that replaces ns-3's generic `Node`. Receives packets, looks up the egress port via `m_rtTable` (ECMP), then delegates to the active load-balancer method (`DoLbFlowECMP`, `DoLbDrill`, `DoLbConga`, `DoLbLetflow`, `DoLbConWeave`, `DoLbCaver`, `DoLbHula`, …). After port selection calls `DoSwitchSend` which forwards to `SwitchMmu` for admission/PFC/ECN decisions. DCI switches (`isDCI=true`) also call into `WanRouting::RouteInput`.

### `src/point-to-point/model/switch-mmu.*`
Models a Broadcom-style shared-buffer MMU. Tracks per-port, per-queue ingress and egress byte counts. Implements dynamic-threshold PFC (`CheckIngressAdmission` / `CheckEgressAdmission`), headroom management, and probabilistic ECN marking (`ShouldSendCN` with per-port kmin/kmax/pmax). Hosts instances of all routing modules (WanRouting, CongaRouting, ConWeaveRouting, etc.) and is the single place where buffer-size config is applied.

### `src/point-to-point/model/wan-routing.*`
WAN congestion control (GSCC) running on DCI switches. For each destination DC, maintains a `DstDCHandler` that: measures RTT via a small per-flow probe table, tracks send-byte rate with EWMA, and runs an epoch-based (default 1 ms) rate-limiter using parameters `beta`, `delta`, `w`, and `wK`. Each epoch it decides a new `ref_rate` for that destination DC and injects CNP packets to throttle RDMA senders. Key tunable raw-params: `ENABLE_W`, `W_MAX`, `W_K`, `INV_DELTA`, `BETA`, `WAN_EPOCH_US`, `ENABLE_2LAYER_HASH`.

## Flow File Format

Both RDMA and TCP flow files use the same plain-text format.

**Line 1:** number of flows `N`

**Each subsequent line:** `src  dst  pg  size_bytes  start_time_seconds`

- `src` / `dst` — global node indices (hosts only; validated against topology)
- `pg` — priority group (typically `3`)
- `size_bytes` — flow size in bytes (clamped to minimum 1)
- `start_time_seconds` — absolute simulation time when the flow starts (e.g. `2.015000000`)

Example:
```
1312
52 49 3 146143 2.000004201
6  4  3 299510 2.000009517
```

Generators: `config/wan_traffic_gen.py` (used by `run.py`), `config/large_traffic_gen.py` (paper sweeps). CDF inputs live in `traffic_gen/*.txt`.

## Topology File Format

Topology files live in `config/` with a `.txt` extension but contain valid JSON. Load with `--topo <stem>`.

Top-level fields:

| Field | Description |
|---|---|
| `num_as` | Number of datacenter sites (autonomous systems) |
| `as_topologies` | Array of per-DC descriptors (see below) |
| `wan_switch_num` | Number of WAN core routers |
| `wan_switches` | Array of global node IDs for WAN routers |
| `wan_links` | Array of link objects spanning DCI↔WAN and WAN↔WAN (same schema as intra-DC links) |

Each entry in `as_topologies`:

| Field | Description |
|---|---|
| `as_id` | DC index (0-based) |
| `dci_switch` | Node ID of the DCI (border) switch connecting this DC to the WAN |
| `num_switches` / `num_hosts` | Counts |
| `switches` / `hosts` | Arrays of global node IDs |
| `links` | Array of `{"src", "dst", "bw", "delay", "loss"}` objects for intra-DC links |

Each link object:
```json
{"src": 16, "dst": 0, "bw": "100Gbps", "delay": "1000ns", "loss": 0.0}
```
Links are directed; add both directions if bidirectional. `delay` is one-way propagation delay; `bw` uses ns-3 DataRate strings. `loss` is per-link error rate (0.0 = lossless).

WAN links follow the same schema. DCI-to-WAN-router links are listed in `wan_links` (not in the per-AS `links`).

Canonical example: `config/cernet_topo.txt` — 6 DCs, 1 DCI switch per DC, 5 WAN routers.
