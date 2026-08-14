# GEMINI Implementation Notes

This note archives the GEMINI baseline work in this repository. It records what was implemented, which assumptions were made, what bugs were found during debugging, and what future experiments must remember.

## Scope

The implemented baseline is host-side GEMINI congestion control for RDMA flows. The code intentionally avoids using topology-derived cross-DC base RTT as a GEMINI control prior. GEMINI learns `RTT_base` online from ACK timestamp samples.

UNO load balancing is not part of this implementation. Erasure coding was discussed as a shared mechanism for future baselines, but was not implemented in this GEMINI pass.

## Code Paths

- `run.py` maps `--cc gemini` to `CC_MODE 9`.
- `scratch/remote.cc` sets `IntHeader::mode = 1` for GEMINI, so ACKs carry timestamp feedback.
- `src/point-to-point/model/rdma-queue-pair.h/.cc` adds explicit byte-window state and per-flow GEMINI state.
- `src/point-to-point/model/rdma-hw.h/.cc` implements GEMINI ACK handling, cwnd update, RTT tracking, ECN accounting, and per-flow pacing.
- `src/point-to-point/model/settings.h/.cc` adds `flow_debug_log` for targeted debugging.
- `config/gen_single_dc_traffic.py` generates single-DC traffic by importing `large_traffic_gen.py`, instead of modifying that generator directly.

## Current Algorithm Behavior

GEMINI uses an explicit congestion window in bytes via `m_useExplicitWin` and `m_ccWin`. `RdmaQueuePair::GetWin()` returns this explicit window when enabled, so existing RDMA scheduling and in-flight checks still apply.

The initial GEMINI window is `GeminiInitCwnd = 125000` bytes, corresponding to `10 us * 100 Gbps`. This default is kept inside `RdmaHw` attributes rather than exposed through `run.py`.

GEMINI starts in slow start. During slow start, non-ECN ACKed bytes increase cwnd directly. The first congestion signal exits slow start and moves the flow into GEMINI congestion avoidance.

`RTT_base` is the minimum RTT observed by the flow. `RTT_min` for congestion detection is implemented as `m_rttMinThisRtt`, the minimum RTT sample collected during the current ACK epoch. It resets at the epoch boundary.

The current epoch boundary follows the HPCC/DCTCP style used in this codebase: `m_lastUpdateSeq` stores the send frontier at the previous boundary, and a new epoch is detected when `ackSeq > m_lastUpdateSeq`.

ECN accounting is byte based. Each ACK contributes `ackedBytes`; if the ACK carries CNP/ECE, those bytes are counted as ECN-marked. At epoch boundary, `alpha` is updated as an EWMA of `ecnBytes / ackedBytes` using the existing `EWMA_GAIN` config value.

For DC congestion, the reduction factor is:

```text
f_dcn = alpha * 4K / (C * RTT_base + K)
```

For WAN congestion, the reduction factor is:

```text
f_wan = beta
```

When both signals fire, the implementation applies `max(f_dcn, f_wan)` rather than summing them.

The additive increase step uses:

```text
h = H * C * RTT_base
delta_cwnd = h * ackedBytes / cwnd
```

All quantities are represented in bytes where applicable. Since `DataRate` is in bits/s and RTT is in seconds, the implementation divides by 8 when converting BDP-like quantities to bytes. The current clamp for `h` is `[100, 50000]` bytes.

The cwnd upper bound is `C * RTT_base / 8`, where `RTT_base` is the online minimum observed RTT. Before `RTT_base` is valid, only the minimum cwnd bound applies.

Per-flow pacing is derived from cwnd:

```text
rate = cwnd * 8 / RTT_base
```

Before `RTT_base` is learned, GEMINI leaves the flow at line rate. The rate is clipped to `[MinRate, line_rate]`.

## Parameter Settings

The current repository defaults for GEMINI are:

```text
GeminiH = 0.001
GeminiBeta = 0.2
GeminiT = 1000000 ns
GeminiK = 409600 bytes
GeminiInitCwnd = 125000 bytes
```

When `--cc gemini` is used, `run.py` also forces:

```text
KMIN = KMAX = 400 KB
PMAX = 1.0
L2_ACK_INTERVAL = 1
EWMA_GAIN = 0.0625
HAS_WIN = 1
VAR_WIN = 1
```

`KMIN/KMAX` values in `run.py` are passed to `SwitchMmu::ConfigEcn()` in KB-like units and are multiplied by 1000 inside `switch-mmu.cc`. `GeminiK` in `RdmaHw` is a byte value used by the host-side reduction formula.

The paper recommends `T = 5 ms`, `beta = 0.2`, and `K = 50 packets/Gbps`. For the current topology and experiments we used a more aggressive `T = 1 ms` and `K = 400 KB` to match the simulator's DC queueing scale and the desired shallow ECN threshold. `H = 0.001` is much larger than the paper's raw constant because our implementation counts bytes and uses the simulator's ACK/cwnd dynamics directly.

## ACK and ECN Lessons

The simulator's original ACK generation is driven by `AckReq` and `L2_ACK_INTERVAL`. A tail packet always requests ACK. With large `L2_ACK_INTERVAL`, a small window can fail to put an AckReq packet in flight for a long time, which caused retransmission timeouts during GEMINI debugging.

The current pragmatic fix is to force `L2_ACK_INTERVAL = 1` for GEMINI in `run.py`. This makes every data packet carry AckReq and avoids GEMINI ACK starvation.

We discussed DCTCP-style CE-state boundary ACKs, where the receiver sends an ACK when CE state changes so each ACK covers a CE-homogeneous byte range. That full state-machine is not currently implemented. Because GEMINI currently ACKs every packet, ECN feedback is sufficiently fine grained for the experiments we ran. If `L2_ACK_INTERVAL` is relaxed later, CE-boundary ACK state must be implemented explicitly.

The receiver-side `send_cnp` rate limit is bypassed for GEMINI. GEMINI uses ACK-carried CNP/ECE as an ECN echo, while DCQCN's separate CNP rate limit remains relevant only to DCQCN.

NACK and timeout logic still follows the existing RDMA/IRN paths. GEMINI ignores `ch.l3Prot == 0xFD` in `HandleAckGemini`, so NACKs can advance recovery state but do not directly update GEMINI cwnd.

## Debugging History

The first two-flow intra-DC 100 MB incast experiment exposed ACK starvation. With the old large ACK interval, some flows timed out. After forcing `L2_ACK_INTERVAL = 1`, the same two-flow intra-DC setup completed with balanced FCTs around 17.5 ms, close to the expected two-way sharing behavior.

A single-DC WebSearch workload was generated through `config/gen_single_dc_traffic.py`. In the 30 ms, 50 Gbps/load experiment, GEMINI and DCQCN were close:

```text
GEMINI: Avg_FCT ~= 2.636756, P99_FCT ~= 10.079729
DCQCN:  Avg_FCT ~= 2.796631, P99_FCT ~= 9.840606
```

For cross-DC 100 MB flows, pure GEMINI must be run with `--wan_cc_mode 0`. With `--wan_cc_mode 1`, GSCC/WAN optimization is enabled and confounds the host-side GEMINI result.

Two cross-DC flows from different sources to the same remote destination initially had poor FCTs around 129 ms and 134 ms with `wan_cc_mode=0`. A single cross-DC 100 MB flow completed around 26.8 ms. Window logs showed GEMINI learned an RTT base around 2.3 ms, exited slow start early, and then increased cwnd too slowly.

The root cause was missing per-flow packet pacing. Without pacing, the two senders emitted window-sized bursts; their bursts collided at the shared path, produced heavy ECN marking, and over-suppressed the GEMINI window. After adding per-flow pacing derived from `cwnd / RTT_base`, the same two-source cross-DC incast recovered to normal behavior. In run `[467]-05-13-16:40:24`, both 404857600-byte flows completed in about 88 ms:

```text
flow 0: finish_time=2.088364655, FCT ~= 88.365 ms
flow 1: finish_time=2.088912740, FCT ~= 88.903 ms
```

That run had no packet drops, no CNP log entries, and no retransmission timeouts. The remaining difference from the earlier "100 MB" label is that `config/gemini-two-interdc-incast-100MB.txt` currently contains 404857600-byte flows.

## Logging

Use `--extra FLOW_DEBUG_ID=<flow_id>` to enable per-flow logs in `flow_debug_log`. The log format is natural-language and grep-friendly:

```text
[time_ns] FlowId:<id>, Sender sends ...
[time_ns] FlowId:<id>, Receiver got ...
[time_ns] FlowId:<id>, Sender received ...
[time_ns] FlowId:<id>, GEMINI ...
```

Useful filters:

```bash
grep 'FlowId:423,' flow_debug_log
grep 'FlowId:423, Receiver got data' flow_debug_log
grep 'FlowId:0, GEMINI' flow_debug_log
```

The current sender-side data log prints every GEMINI data packet for the selected debug flow. This is useful for short targeted debugging, but can be large for long workloads.

## Experiment Commands

Two-flow intra-DC incast:

```bash
python3 run.py --cc gemini --wan_cc_mode 0 --my_flow gemini-two-incast-100MB --tcp_flow "" --simul_time 0.05 --stdout 1
```

Two-flow cross-DC incast:

```bash
python3 run.py --cc gemini --wan_cc_mode 0 --my_flow gemini-two-interdc-incast-100MB --tcp_flow "" --simul_time 0.2 --stdout 1 --extra FLOW_DEBUG_ID=0
```

Single-DC traffic generation:

```bash
python3 config/gen_single_dc_traffic.py --as-id 0 --duration 0.03 --intra-load 50 --cdf WebSearch --output dc0-ws-50G-30ms.txt
```

For analysis scripts, use the repository virtual environment:

```bash
.venv/bin/python analysis/deep_analyse.py ...
```

## Known Risks and Cleanup Items

`RdmaHw::AddQueuePair()` currently asserts `flow_id >= 0`. This is compatible with normal `rdma-client` flow creation, but it changes the meaning of the overloads that pass `-1`. If any future RDMA flow is created without a flow id, this assert will abort.

`run.py` has duplicated config-formatting branches for DCQCN, TIMELY, and GEMINI. This is not a correctness issue, but it makes future parameter changes easy to miss in one branch.

The debug log is always opened, even when no flow is selected. It is mostly harmless, but it creates an extra file in every output directory.

Untracked `package.json`, `package-lock.json`, and `.codex` are unrelated to GEMINI and should not be included in a GEMINI commit unless there is a separate reason.

`config/large_traffic_gen.py` only has a newline-at-EOF diff. That is not logically related to GEMINI.

The current GEMINI receiver does not implement a persistent CE-state ACK-boundary machine. Do not lower ACK frequency for GEMINI without revisiting ECN feedback fidelity.

The current pacing rate uses `cwnd / RTT_base`. This matches the intended per-flow pacing direction, but RTT-base jitter or an early too-small RTT sample can affect the pacing cap. We intentionally left smoothing for later.

The earlier cross-DC slowdown was fixed by per-flow pacing. If this symptom reappears, first check whether GEMINI pacing is active and whether the flow is being paced by `cwnd / RTT_base`; only then revisit ECN thresholds or same-destination versus different-destination path effects.
