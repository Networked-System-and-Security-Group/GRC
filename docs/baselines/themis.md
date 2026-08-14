# Themis baseline

Themis is a switch-side long-haul RDMA baseline. In this repository it is
selected with `--cc themis` and uses DCQCN at the hosts plus Themis PNP/TRP at
every topology-defined DCI switch. The baseline forces `WAN_CC_MODE 0` so it
does not combine Themis with GSCC.

```bash
python3 run.py \
  --cc themis \
  --my_flow <flow-stem> \
  --tcp_flow "" \
  --simul_time 0.05 \
  --msg themis
```

The switch-side module is `ThemisRouting`, owned by `SwitchMmu` in the same
style as `WanRouting`. `SwitchNode` only dispatches DCI packets and forwards
dequeue notifications to the module.

## PNP

When a DCI egress queue marks an inter-DC RDMA data packet with ECN, Themis
clears the mark and emits a high-priority CNP toward the packet source. CNPs
are rate-limited per flow (5 microseconds by default) and delayed by 2
microseconds before injection.

The direct CNP path uses the existing `CnHeader` and the normal high-priority
switch routing callback. This avoids a second receiver-generated CNP for the
same ECN mark while keeping packet construction in `ThemisRouting`.

## TRP

At each DCI, a CNP originating in that DCI's local DC arms TRP for the matching
flow. Subsequent copies of that inter-DC data flow entering the local DC are
temporarily delayed before normal routing. The delay is the simulator
equivalent of upstream Themis's self-loop recirculation:

```text
delay = queue_wait + packet_bits * loop_num / recirc_rate
        + THEMIS_TRP_DELAY_NS * loop_num
```

The loop count grows with repeated CNPs and is bounded by
`THEMIS_TRP_MAX_LOOPS`; `recirc_rate` defaults to 1600 Gbps and is shared by
TRP packets at one DCI. State expires after `THEMIS_TRP_TIMEOUT_US` without a
new CNP. No self-loop port or switch ID is hard-coded; all DCI switches are
identified from the topology parser.

## Tuning knobs

These are optional raw config parameters and can be passed with `--extra`:

```text
THEMIS_PNP_DELAY_US       # default 2
THEMIS_PNP_INTERVAL_US    # default 5
THEMIS_TRP_TIMEOUT_US     # default 500
THEMIS_TRP_DELAY_NS       # default 100
THEMIS_TRP_MAX_LOOPS      # default 64
THEMIS_TRP_RECIRC_GBPS    # default 1600
```

`THEMIS_ENABLE` is materialized by `run.py`; it defaults to `0` for all other
baselines. Existing baselines do not enter `ThemisRouting` when the flag is
disabled.

## Provenance

The implementation was adapted from the NS-3 portions of
[Networked-System-and-Security-Group/Themis](https://github.com/Networked-System-and-Security-Group/Themis),
main branch at commit `d941dc101038286d3f5f63ba59824d7145af3dfc`. The upstream
P4/eBPF testbed is intentionally not included here.
