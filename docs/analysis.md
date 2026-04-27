# Analysis

Open this document when the task is to inspect outputs, parse a finished run, add a new metric, or understand which log file comes from which module.

## Output Directory Layout

Each run creates a directory under `mix/output/`:

```text
mix/output/[id]-timestamp/
```

Common files inside:

- `config.txt`: exact runtime configuration used for this run
- `config.log`: stdout and stderr from `scratch/remote`
- `flow_output`
- `wan_log`
- `rtt_log`
- `drop_log`
- `link_utilization`
- `buffer_monitor`
- `rate_monitor`
- `cnp_log`
- `cnp_trigger_prob_log`
- `accumulated_bytes_log`

The file handles are registered in `src/point-to-point/model/settings.cc::logfile::initialize_log()`.

## Main Analysis Entry Point

The core parser is `analysis/deep_analyse.py`.

Useful entry points:

- `latest(offset=0)`: open the newest experiment directory
- `get_analyser(id)`: build an `Analyser` for a specific experiment id
- `analyser_iter("1-5,8")`: iterate across multiple experiment ids

`Analyser` loads `config.txt`, finds the matching output directory, reads the topology JSON referenced by `TOPOLOGY_FILE`, and lazily loads the various CSV-like outputs into pandas data frames.

## What The Other `analysis/*.py` Files Are

Most of the other scripts under `analysis/` are thin plotting or paper-figure wrappers built on top of `deep_analyse.py`.

Use them as examples for figure generation, but treat `deep_analyse.py` as the canonical parsing layer.

## Adding A New Metric

The usual path is:

1. open or enable a log file in `src/point-to-point/model/settings.cc`,
2. emit rows from the owning C++ module,
3. add a parser or accessor in `analysis/deep_analyse.py`,
4. optionally add a plotting wrapper in `analysis/*.py`.

If the parser expects a CSV header, keep the header stable across runs.

## Log Availability Notes

Not every registered file is enabled by default. Some logs are intentionally redirected to `/dev/null` in `initialize_log()` to keep runs fast.

When debugging:

1. enable only the log you need,
2. keep the column order stable,
3. turn it back off if it is high-frequency and not needed anymore.

## First Places To Look During Postmortem

- `config.txt`: what parameters actually ran
- `config.log`: whether the simulator parsed the config and finished cleanly
- `rtt_log`, `drop_log`, `buffer_monitor`, `rate_monitor`: WAN-control debugging
- `flow_output` and `qp_rate_log`: transport and flow-completion debugging
