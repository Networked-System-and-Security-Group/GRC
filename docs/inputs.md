# Inputs

Open this document when the task is to change topology files, traffic generators, flow formats, or TCP and RDMA input datasets.

## Topology Files

Topology files live under `config/` and use a JSON schema even though the filenames end with `.txt`.

Canonical example: `config/cernet_topo.txt`

`scratch/remote.cc` loads them with:

```cpp
ifstream topof(topology_file);
topof >> topo_json;
```

So the file must be valid JSON.

### Fields You Will See Often

- `num_as`
- `as_topologies`
- per-AS fields such as `as_id`, `dci_switch`, `hosts`, `switches`, and `links`
- WAN-facing structures such as `wan_links` and related connectivity data

When you need a new topology, the fastest path is usually to copy an existing `config/*.txt` topology file and edit the JSON rather than generating one from scratch.

## Flow File Format

RDMA and TCP flow files use the same format.

Line 1:

- number of flows, `N`

Each following line:

- `src dst pg size_bytes start_time_seconds`

The generators in this repository write lines such as:

```text
0 37 3 4096 2.015000000
```

`scratch/remote.cc` reads RDMA flows from `FLOW_FILE` and optional TCP flows from `TCP_FLOW_FILE`.

## Flow Generators

Core generators:

- `config/wan_traffic_gen.py`: simple per-load WAN traffic generator used by `run.py` when a requested flow file does not already exist
- `config/large_traffic_gen.py`: richer generator used by paper-style sweep scripts
- `traffic_gen/*.txt`: flow-size CDF inputs such as `WebSearch`

## Common Tasks

### Change the default traffic family used by `run.py`

Open `run.py` and `config/wan_traffic_gen.py`.

### Generate many randomized flow variations

Open `autorun_flow_scan.py` and `config/large_traffic_gen.py`.

### Mix TCP with RDMA

Use `--tcp_flow <path>`.

The TCP flow file format is intentionally identical to the RDMA flow file format, so you can generate both with the same style of tooling.

### Use a hand-authored flow file

Put it under `config/` and pass `--my_flow <stem>` or a full-ish name that `run.py` can normalize.

## Pitfalls

- `run.py` normalizes `--my_flow`, so it accepts `name`, `name.txt`, or `config/name.txt` and converts them to `config/<stem>.txt`.
- The current `run.py` defaults already point at a non-empty `--my_flow` and `--tcp_flow`. Be explicit when you want generator-driven or pure-RDMA behavior.
- If a topology change breaks routing, the bug may be in the JSON itself or in `scratch/remote.cc`'s route-construction logic, not in `wan-routing.cc`.
