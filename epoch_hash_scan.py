#!/usr/bin/env python3
"""Run two independent sweeps for WAN knobs.

Base configs:
- python3 run.py --topo cernet_topo --my_flow w-dynamic-150-180-v0 --wan_cc_mode 1
- python3 run.py --topo cernet_topo --my_flow w-dynamic-150-120-v0 --wan_cc_mode 1

Independent experiments (NOT Cartesian product):
1) Hash sweep: ENABLE_2LAYER_HASH in {TRUE, FALSE}
2) Epoch sweep: WAN_EPOCH_US in {1000, 2000, 3000, 4000, 5000} (i.e., 1..5ms)

We pass raw params through run.py using repeated --extra KEY=VALUE.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class BaseCase:
    topo: str
    my_flow: str
    wan_cc_mode: int


def run(cmd: list[str], *, dry_run: bool) -> None:
    print("+", shlex.join(cmd), flush=True)
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Sweep ENABLE_2LAYER_HASH and WAN_EPOCH_US")
    p.add_argument("--topo", default="cernet_topo")
    p.add_argument("--simul_time", type=float, default=None, help="Override --simul_time; default uses run.py default")
    p.add_argument(
        "--experiment",
        choices=["hash", "epoch", "all"],
        default="all",
        help="Which experiment batch to run (default: all)",
    )
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--dry_run", action="store_true")
    args = p.parse_args()

    flows = [
        "w-dynamic-150-180-v1",
        "w-dynamic-150-120-v1",
    ]

    enable_2layer_hash_values = ["TRUE", "FALSE"]
    epoch_ms_values = [1, 2, 3, 4, 5]

    # Best-effort check that the flow files exist.
    for flow in flows:
        flow_path = ROOT / "config" / f"{flow}.txt"
        if not flow_path.exists():
            raise FileNotFoundError(f"Flow file not found: {flow_path}")

    base_cases = [BaseCase(topo=args.topo, my_flow=flow, wan_cc_mode=1) for flow in flows]

    def _run_one(*, base: BaseCase, extras: list[str], msg: str) -> None:
        cmd = [
            "python3",
            "run.py",
            "--topo",
            base.topo,
            "--my_flow",
            base.my_flow,
            "--wan_cc_mode",
            str(base.wan_cc_mode),
        ]
        for extra in extras:
            cmd.extend(["--extra", extra])
        cmd.extend(["--msg", msg])
        if args.simul_time is not None:
            cmd.extend(["--simul_time", str(args.simul_time)])
        run(cmd, dry_run=args.dry_run)

    def _hash_sweep() -> None:
        total = len(base_cases) * len(enable_2layer_hash_values)
        run_id = 1
        for base in base_cases:
            for enable_2layer_hash in enable_2layer_hash_values:
                msg = (
                    "hash_sweep:"
                    f"topo={base.topo},"
                    f"flow={base.my_flow},"
                    f"WAN_CC_MODE={base.wan_cc_mode},"
                    f"ENABLE_2LAYER_HASH={enable_2layer_hash},"
                    f"No.{run_id}/{total}"
                )
                print(f"[{run_id}/{total}] Hash sweep {base.my_flow}, ENABLE_2LAYER_HASH={enable_2layer_hash}")
                _run_one(base=base, extras=[f"ENABLE_2LAYER_HASH={enable_2layer_hash}"], msg=msg)
                run_id += 1
                if args.sleep and run_id <= total:
                    time.sleep(args.sleep)

    def _epoch_sweep() -> None:
        total = len(base_cases) * len(epoch_ms_values)
        run_id = 1
        for base in base_cases:
            for epoch_ms in epoch_ms_values:
                epoch_us = epoch_ms * 1000
                msg = (
                    "epoch_sweep:"
                    f"topo={base.topo},"
                    f"flow={base.my_flow},"
                    f"WAN_CC_MODE={base.wan_cc_mode},"
                    f"WAN_EPOCH_US={epoch_us},"
                    f"No.{run_id}/{total}"
                )
                print(f"[{run_id}/{total}] Epoch sweep {base.my_flow}, WAN_EPOCH_US={epoch_us}")
                _run_one(base=base, extras=[f"WAN_EPOCH_US={epoch_us}"], msg=msg)
                run_id += 1
                if args.sleep and run_id <= total:
                    time.sleep(args.sleep)

    # if args.experiment in ("hash", "all"):
        # _hash_sweep()
    if args.experiment in ("epoch", "all"):
        _epoch_sweep()


if __name__ == "__main__":
    main()
