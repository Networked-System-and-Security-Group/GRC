# GRC closed-loop experiments on Tofino2

This experiment runs a matched P4 program and C controller. The switch maps a
Write and its returning ACK to the same sender QPN, hashes the connection to
select a bucket, and hashes the PSN to select a slot. A packet identifier covers
the connection and PSN. An unexpired record is protected against a different
identifier, and a matching ACK consumes the record. The controller uses the
accepted RTT samples to update the byte budget; the switch sends CNPs to the
actual sender QP. There is no PSN window in this experiment. The
[window baseline](../) uses a separate program and controller.

The runner covers one destination group on a two-port RoCEv2 testbed. It checks
ACK and Write counts, RTT samples consumed by the controller, and CNPs processed
by the NIC. This measures sample availability and closed-loop operation on the
testbed; it does not measure RTT error against a reference or WAN fairness.

## Testbed setup

Use a dedicated Tofino2 ASIC (T2NA SDE, originally 9.7.1), two 100 Gb/s RS-FEC
switch ports in the same pipe, and one Linux traffic host with two ConnectX
RoCEv2 interfaces connected through the switch. The host needs `ib_write_bw`
with QP timeout and duration options, GCC, libibverbs development headers,
`ethtool`, `ip`, and the mlx5 counters used by the runner. Use Python 3.10+ on
the orchestrator and traffic host. BFRT on the switch uses the SDK's Python.

Copy `testbed.example.json` to `testbed.local.json`. Fill in the SSH aliases or
`user@host` for the switch and traffic host, dedicated writable absolute work
directories, SDK paths, the board's switchd JSON configuration, BFRT Python and
module paths, and both endpoints' device names, interface names, IPv4 addresses,
and **Tofino device port numbers**. The board configuration must contain one
program and pipeline on device 0 covering the chosen pipe. The build script
uses the endpoint configuration to generate its P4 topology header. Set up SSH
host verification before running. Use a distinct switch work directory for this
experiment, and stop any unrelated switch controller before running it.

## Run a trial or reproduce the sweep

Run these commands from this directory. The plan command works without a
configured testbed. Compilation does not load the switch program; each traffic
trial cold-starts the managed controller, reads back both hardware QP maps
before releasing traffic, and archives its own evidence.

```sh
python3 scripts/sweep.py plan
for slots in 16 32 64; do
    python3 scripts/build.py --buckets 256 --slots "$slots" --tag "paper-loop-hm-s$slots" || exit
done
python3 scripts/run.py --config paper-loop-hm-s16 --flows 1 --iters 40000
```

The sweep runs the same 42 conditions three times each: 256 buckets, 16/32/64
slots, 1/2/4/8/16/32/64 QPs, and 40,000 or 400,000 Writes per QP. Start it in a
terminal multiplexer after verifying the single trial on your testbed.

```sh
python3 -u scripts/sweep.py run
```

Each batch gets a fresh directory under `results/` with its plan, trial CSV,
and raw evidence. Each condition is retried up to twice on failure; the batch
stops if all attempts fail. Use rows with `integrity_ok=True`. The
`identity_match_pct` column is identifier hits divided by positive ACKs;
`match_pct` counts only ACKs whose RTT sample also passed the filter.

The checked-in files contain source and the experiment plan. `testbed.local.json`,
compilation products, logs, and measurements stay local and are ignored by Git.
