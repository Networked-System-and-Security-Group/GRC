# Add DC Congestion Control

Open this document when the task is to add or modify a host-side RDMA congestion control algorithm such as DCQCN, HPCC, TIMELY, or DCTCP.

## First Files To Open

- `src/point-to-point/model/rdma-queue-pair.h`
- `src/point-to-point/model/rdma-hw.h`
- `src/point-to-point/model/rdma-hw.cc`
- `scratch/remote.cc`
- `run.py`

## Current Boundary Of Responsibility

### `rdma-queue-pair.h`

Owns the `CcMode` enum and the per-QP state structs for the existing algorithms.

If a new algorithm needs persistent per-flow state, add it here first.

### `rdma-hw.h/.cc`

Owns the actual control logic:

- ACK handling
- CNP handling
- timeout recovery
- rate or window changes
- per-mode helper functions such as `HandleAckTimely()` or `HandleAckDctcp()`

### `scratch/remote.cc`

Maps `CC_MODE` into runtime behavior such as INT header configuration and other global defaults.

### `run.py`

Maps CLI strings to numeric `CC_MODE` values and materializes the base `config.txt`.

## Recommended Change Order

1. Add the new enum value to `CcMode` in `rdma-queue-pair.h`.
2. Add any new per-QP state fields to `RdmaQueuePair`.
3. Extend `run.py` so the mode can be selected from the CLI.
4. Extend `scratch/remote.cc` if the new mode needs different global setup.
5. Implement the algorithm in `rdma-hw.cc`.
6. Add logging only after the control path works.

## Important Repo-Specific Caveat

`run.py` currently contains CLI names for more algorithms than it fully materializes in the config-generation branch. Right now the Python runner has explicit config-template branches for `dcqcn` and `timely`, so a new user-facing CC mode must be verified end to end instead of assuming the enum map is sufficient.

## When You Also Need Switch-Side Support

Some algorithms need more than host-side ACK logic.

Examples:

- If the mode uses INT or per-hop telemetry, inspect `src/point-to-point/model/int-header.*` and `src/point-to-point/model/switch-node.*`.
- If the mode changes queue behavior or packet scheduling, inspect `src/point-to-point/model/qbb-net-device.*` and `src/point-to-point/model/switch-mmu.*`.

## Logging And Analysis

If the new mode needs per-flow telemetry:

1. register or enable a log file in `src/point-to-point/model/settings.cc`,
2. emit from `rdma-hw.cc` or the owning module,
3. parse in `analysis/deep_analyse.py`.

The repository already has a `qp_rate_log` file handle, but it is not always enabled by default.
