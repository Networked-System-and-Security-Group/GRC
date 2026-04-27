# Code Map

Open this document when you need to locate the owning files for a feature before making code changes.

## Task To File Routing

| If the task is... | Open these files first | Why |
| --- | --- | --- |
| Change how experiments are launched | `run.py`, `autorun.py`, `autorun_flow_scan.py`, `check.py` | Python orchestration layer |
| Add a permanent runtime parameter | `run.py`, `scratch/remote.cc`, `src/point-to-point/model/settings.h` | Config plumbing path |
| Tune WAN behavior quickly without full plumbing | `run.py`, `src/point-to-point/model/wan-routing.cc` | `--extra` plus raw-param path |
| Add or modify host-side RDMA congestion control | `src/point-to-point/model/rdma-queue-pair.h`, `src/point-to-point/model/rdma-hw.h`, `src/point-to-point/model/rdma-hw.cc` | Per-QP state and ACK/CNP handling |
| Add or modify WAN-side control or GSCC logic | `src/point-to-point/model/wan-routing.cc`, `scratch/remote.cc`, `src/point-to-point/model/settings.h` | DCI routing, WAN mode, raw params |
| Change queueing, device send or receive path | `src/point-to-point/model/qbb-net-device.cc`, `src/point-to-point/model/switch-node.cc`, `src/point-to-point/model/switch-mmu.cc` | Data-plane path and queue behavior |
| Change topology parsing or routing table construction | `scratch/remote.cc`, `config/*.txt` | Topology JSON load and route initialization |
| Change flow generation | `config/wan_traffic_gen.py`, `config/large_traffic_gen.py`, `traffic_gen/*.txt` | Flow file producers and CDF inputs |
| Add a new output metric or parser | `src/point-to-point/model/settings.cc`, emit point in C++, `analysis/deep_analyse.py` | Log registration, writing, and parsing |

## Ownership By Layer

### 1. Python orchestration

- `run.py`: single-run entrypoint, config generation, output directory management, process launch
- `autorun.py` and `autorun_flow_scan.py`: reusable batch runners
- `check.py`: monitor and kill experiments scoped to this repository

### 2. C++ bootstrap

- `scratch/remote.cc`: reads `config.txt`, loads topology JSON, creates nodes and devices, schedules RDMA and optional TCP flows, and starts the simulation

This file is the bridge between Python-side experiment definitions and C++ runtime behavior.

### 3. Shared settings and logs

- `src/point-to-point/model/settings.h/.cc`: global registries such as topology-derived maps, `Settings::wan_cc_mode`, raw params, and file handles under `logfile::`

If a new knob must be visible across multiple modules, it often lands here.

### 4. DC transport and host-side congestion control

- `src/point-to-point/model/rdma-queue-pair.h/.cc`: per-flow transport state and CC mode enum
- `src/point-to-point/model/rdma-hw.h/.cc`: ACK, CNP, timeout, and rate or window update logic
- `src/point-to-point/model/rdma-driver.*`: host-side RDMA object wiring

If the task mentions DCQCN, HPCC, TIMELY, DCTCP, ACK handling, or per-flow rate updates, start here.

### 5. Device and switch pipeline

- `src/point-to-point/model/qbb-net-device.h/.cc`: device send and receive path, queue dispatch, TCP and RDMA coexistence
- `src/point-to-point/model/switch-node.*`: switch behavior and routing integration points
- `src/point-to-point/model/switch-mmu.*`: queue and buffer management

### 6. WAN and GSCC path

- `src/point-to-point/model/wan-routing.h/.cc`: DCI-switch packet handling, RTT tracking, per-destination WAN control, and CNP generation
- `scratch/remote.cc`: construction of `Settings::wan_routing` from topology JSON

### 7. Inputs and outputs

- `config/*.txt`: topology JSON and pre-generated flow files
- `config/*.py`: traffic generators
- `mix/output/[id]-.../`: archived configs, logs, and CSV-like outputs
- `analysis/deep_analyse.py`: main parser and analysis API

## Files Usually Not Worth Opening First

- `build/`: generated artifacts
- `bindings/`: ns-3 bindings, not the main research logic
- `instructions/`: older documentation set kept for reference only
