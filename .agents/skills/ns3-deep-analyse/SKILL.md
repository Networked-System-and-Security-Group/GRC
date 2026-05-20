---
name: ns3-deep-analyse
description: USE THIS SKILL WHENEVER YOU TRY TO ANALYSE EXPERIMENT RESULTS OF NS3 SIMULATOR. This skill illustrate how to use analysis/deep_analyse.py, parsed experiment outputs, or new post-processing metrics for this repository.
---

# Ns3 Deep Analyse

## Use This Skill

Open this skill when the task is to inspect `mix/output/[id]-*/` results, extend `analysis/deep_analyse.py`, or wire a new log into the analysis layer.

---

## 1. Getting an Analyser Object

All analysis starts by obtaining an `Analyser` instance for a specific experiment run.

```python
from analysis.deep_analyse import get_analyser, latest, analyser_iter

# Most recent run
ana = latest()          # latest(offset=1) for the second-latest, etc.

# A specific run by numeric ID
ana = get_analyser(42)  # returns a cached Analyser for run [42]

# Iterate over a range/set of runs
for ana in analyser_iter("1-5,8,13"):
    ...
```

`get_analyser` caches instances, so calling it twice with the same ID returns the same object.

---

## 2. Batch Summary: `get_basic_result`

The most common first step when comparing multiple runs.

```python
from analysis.deep_analyse import get_basic_result

df = get_basic_result("10-15,20")
display(df)
```

Returns a `pd.DataFrame` with one row per run and columns:
`ID`, `MSG`, `Avg_FCT`, `Avg_Intra_FCT`, `Avg_Inter_FCT`, `P99_FCT`, `P99_Intra_FCT`, `P99_Inter_FCT`.

All FCT values are **slowdown** (actual/ideal), not raw latency.

---

## 3. FCT Metrics on a Single Run: `get_fct` and Friends

```python
ana = get_analyser(42)

# Combined convenience wrapper — returns two 3-tuples
(avg_all, avg_intra, avg_inter), (p99_all, p99_intra, p99_inter) = ana.get_fct()

# Individual accessors
avg_all, avg_intra, avg_inter = ana.get_avg_fct()
p99_all, p99_intra, p99_inter = ana.get_p99_fct()

# Split by flow size
mean_all, mean_inter, p99_inter, mean_intra = ana.get_large_flow_fct()   # fsize >= 5 MB
mean_all, mean_inter, p99_inter, mean_intra = ana.get_small_flow_fct()   # fsize < 1 MB
```

Underlying data is loaded lazily from `flow_output` on first access.

---

## 4. Flow DataFrame Helpers

The raw flow records are exposed as `pd.DataFrame` via these helpers:

```python
df_all   = ana.flow_df           # all flows (loaded after any fct call)
df_intra = ana.get_intra_df()    # flows where src_as == dst_as
df_inter = ana.get_inter_df()    # flows where src_as != dst_as
df_large = ana.get_large_flow_df()   # fsize >= 5 MB
df_small = ana.get_small_flow_df()   # fsize < 1 MB
```

Key columns in `flow_df`:
`flow_id`, `src`, `dst`, `fsize`, `start_time`, `finish_time`, `std_fct`, `fct_slowdown`, `src_as`, `dst_as`.

---

## 5. Plot Methods

All `plot_*` methods display inline (Jupyter) and auto-save a PDF to `analysis/figures/`.

| Method | What it shows |
|---|---|
| `plot_fct_cdf()` | CDF of FCT slowdown — overall, intra, inter |
| `plot_as_rate(src_as, dst_as)` | GSCC `real_rate` vs `ref_rate` over time |
| `plot_as_w(src_as, dst_as)` | GSCC `w` parameter over time |
| `plot_as_k(src_as, dst_as)` | GSCC `k` parameter over time |
| `plot_rtt(src_as, dst_as)` | RTT measured by DCI switch toward `dst_as` |
| `plot_qp_rate(flow_ids)` | Per-QP transmission rate for selected flows |
| `plot_buffer(switch_id, egress=True)` | Per-port queue depth on a switch |
| `plot_wan_path_buffer(src_as, dst_as)` | Per-hop WAN queue depth along shortest path |
| `plot_link_utilization(src_id, dst_id)` | Throughput on a directed link |
| `plot_cnp_timestamps(flow_id, ...)` | CNP injection frequency for a flow |
| `plot_cnp_trigger_prob(src_as, dst_as)` | Epoch-level CNP trigger probability |
| `plot_accumulated_bytes(src_as, dst_as)` | Cumulative bytes on a DCI-to-DC pair |
| `plot_drop(switch_id, src_as, dst_as)` | Drop event scatter for a path |
| `plot_pfc(node)` | PFC pause-frame timeline for a node |

---

## 6. Other Useful Methods

| Method | Purpose |
|---|---|
| `ana.read_config()` | Reload `config.txt` into `ana.config` dict |
| `ana.get_drop_number()` | Total packet drops logged |
| `ana.get_drop_rate()` | Drop rate = drops / total estimated packets |
| `ana.show_drop()` | Print drop counts grouped by path |
| `ana.get_wan_buffer_stats()` | Returns `(mean_MB, p99_MB)` for WAN switch queues |
| `ana.get_buffer_information()` | Mean egress bytes in a fixed early window |
| `ana.get_wan_base_rtt_ms(src_as, dst_as)` | Propagation-only RTT from topology |
| `ana.get_wan_key_path(src_as, dst_as)` | Node-id list of shortest WAN path |
| `ana.rtt_queue_linearity(...)` | Correlate measured RTT vs predicted queue delay |
| `ana.wan_high_buffer_intervals(...)` | Find time intervals of high WAN buffer occupancy |
| `ana.diagnose_slow_flow(threshold=99)` | Print/plot the slowest inter-DC flows |
| `ana.analyze_cnp_k(w_max, ...)` | Find optimal GSCC `k` from CNP probability data |
| `ana.get_avg_abs_rtt_diff(...)` | Mean |rtt1 - measured_rtt| for a switch/path |
| `show_fct(ids_str)` | Print avg+p99 FCT for each run in a range |
| `batch_operation(ids_str, fn, *args)` | Call any `Analyser` method for a batch of runs |

---

## 7. Adding A New Metric

1. Register or enable the log in `src/point-to-point/model/settings.cc`.
2. Emit the data in the owning C++ module.
3. Add a `__read_*` loader and expose it via a method or property in `analysis/deep_analyse.py`.
4. Add a `plot_*` or batch helper in `analysis/*.py` only if needed.

---

## Practical Rules

- Prefer `mix/output/[id]-MMDD-HHMM[-msg]/` as the canonical run directory format.
- Keep `--msg` short and stable so it doubles as a searchable experiment tag.
- Always work inside the `.venv` python environment when running analysis scripts.
