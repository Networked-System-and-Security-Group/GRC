# Config inputs (topology + flows)

This doc describes **experiment inputs** and **generators** consumed by the harness (`run.py`).

## Topology files (JSON disguised as .txt)
- `run.py` writes `TOPOLOGY_FILE config/<topo>.txt` into `mix/output/.../config.txt`.
- The simulator reads it in `scratch/remote.cc` via `topof >> topo_json`.
- Despite the `.txt` extension, the content is **JSON**.

Typical entrypoint:
- `config/wan_topo_json.txt` (default in `run.py --topo wan_topo_json`)

Minimum fields expected by `scratch/remote.cc` (high-level):
- `num_as`
- `as_topologies`: list of AS objects, each containing at least:
  - `as_id`
  - `dci_switch`
  - `hosts`: list of host node ids
  - `switches`: list of switch node ids
  - `links`: list of link objects (`src`, `dst`, `bw`, `delay`, `loss`)
- `wan_switches`: list of WAN switch node ids
- `wan_links`: list of WAN link objects (`src`, `dst`, `bw`, `delay`, `loss`)

If you change the JSON schema, update the corresponding parsing/initialization in `scratch/remote.cc` (topology init paths).

## Flow files (plain text)
- `run.py` writes `FLOW_FILE config/<flow>.txt` into `mix/output/.../config.txt`.
- Parsed by `scratch/remote.cc::ReadFlowInput()`.

Optional (TCP/RDMA mixed-run):
- `run.py --tcp_flow <path>` writes `TCP_FLOW_FILE <path>` into `mix/output/.../config.txt`.
- Parsed by `scratch/remote.cc::ReadTcpFlowInput()` and scheduled by `ScheduleTcpFlowInputs()`.

Format:
- Line 1: integer number of flows `N`
- Each subsequent line:

```
<src> <dst> <pg> <size_bytes> <start_time_seconds>
```

Notes:
- `start_time_seconds` is a float (seconds).
- `pg` is typically `3` in WAN generators.
- For TCP flows, `pg` is currently treated as an input field for compatibility; recommended value is `1`.
- If you change this format, update `ReadFlowInput()`.

## Generators (under `config/`)
- `config/wan_traffic_gen.py`: default WAN traffic generator invoked by `run.py` when the flow file is missing.
  - Called like: `python3 config/wan_traffic_gen.py --duration <sec> --inter_load_all <Gbps> --intra_load <Gbps> --cdf <name> --output <file>.txt`
  - Uses CDF files under `traffic_gen/`.
- `config/wan_topo_gen.py`: generates WAN+DC topologies; prefer this over hand-editing large JSON.
- `config/large_traffic_gen.py`, `config/motivation_traffic_gen.py`: optional scenario-specific generators.

## Common gotchas
- The “.txt topology” is JSON; don’t treat it as an ns-3 text topology.
- Flow naming matters: `run.py` ultimately looks for `config/<stem>.txt`.
  - For `--my_flow`, supported forms are: `stem`, `stem.txt`, or `config/stem.txt` (it will normalize to `stem`).
  - The generator is only invoked if `config/<stem>.txt` is missing.
