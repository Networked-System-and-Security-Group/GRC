# Add WAN Control

Open this document when the task is to modify GSCC logic, add a new WAN-side control mode, tune WAN raw parameters, or change DCI-switch forwarding behavior.

## First Files To Open

- `src/point-to-point/model/wan-routing.cc`
- `src/point-to-point/model/wan-routing.h`
- `scratch/remote.cc`
- `src/point-to-point/model/settings.h`
- `src/point-to-point/model/settings.cc`

## Control Path

The WAN path is usually:

1. `run.py` writes `WAN_CC_MODE`, buffer sizes, and optional raw params into `config.txt`.
2. `scratch/remote.cc` parses those values, stores `Settings::wan_cc_mode`, and builds `Settings::wan_routing` from the topology JSON.
3. `wan-routing.cc` runs at DCI switches, handles inter-DC UDP and ACK packets, tracks RTT state, and triggers WAN-side feedback.
4. `settings.cc` owns the WAN-facing logs such as `wan_log`, `rtt_log`, `drop_log`, `buffer_monitor`, `rate_monitor`, and `cnp_log`.

## Existing Raw Parameters In `wan-routing.cc`

These already use `Settings::GetRawParam()` and are therefore easy to tune through `--extra`:

- `WAN_EPOCH_US`
- `ENABLE_2LAYER_HASH`
- `ENABLE_W`
- `W_MAX`
- `W_K`
- `INV_DELTA`
- `BETA`
- `ENABLE_V`

This makes `wan-routing.cc` the best first target for exploratory WAN algorithm changes.

## Recommended Change Order For A New WAN Mode

1. Decide whether the change is only a tuning variant or a real new mode.
2. For tuning variants, start with `--extra KEY=VALUE` and raw params.
3. For real modes, extend `Settings::WanCCMode` in `settings.h`.
4. Extend `run.py` if the mode should be user-facing.
5. Parse the mode in `scratch/remote.cc` and ensure switch setup reflects it.
6. Implement the behavior in `wan-routing.cc`.
7. Add or update logs and analysis only after the forwarding and control behavior is stable.

## Where Routing Tables Come From

`wan-routing.cc` does not invent the WAN route map on its own. The route data is constructed in `scratch/remote.cc` from the topology JSON and stored in `Settings::wan_routing`.

If a task changes path selection, topology interpretation, or DCI/WAN connectivity, inspect `scratch/remote.cc` before touching `wan-routing.cc`.

## When To Touch Other Modules

- If the change is really about queue thresholds or drop behavior, inspect `src/point-to-point/model/switch-mmu.*`.
- If the task changes what is counted as a packet source or sink, inspect `src/point-to-point/model/qbb-net-device.*`.
- If the task needs new experiment knobs, follow [config-pipeline.md](config-pipeline.md).

## Logging Notes

WAN experiments are usually debugged through the output files opened in `settings.cc`.

If you add a new log:

1. open the file in `initialize_log()`,
2. keep the header stable,
3. add a parser in `analysis/deep_analyse.py` if the metric matters after the run.
