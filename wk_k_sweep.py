#!/usr/bin/env python3
"""Sweep W_K around a target value with fixed INV_DELTA.

Base command:
  python3 run.py --topo cernet_topo --my_flow w-dynamic-150-180-v1 --wan_cc_mode 1

This experiment:
- Enables weight w/k: ENABLE_W=TRUE
- Keeps W_MAX at default (do not pass W_MAX)
- Fixes INV_DELTA to 10MB (i.e., 10 * 1024 * 1024 = 10485760)
- Sweeps W_K near 1.75e-9

All params are passed through run.py via repeated --extra KEY=VALUE.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import time


INV_DELTA = 8 * 1024 * 1024 


def run(cmd: list[str], *, dry_run: bool) -> None:
    printable = "+ " + " ".join(shlex.quote(c) for c in cmd)
    print(printable)
    if dry_run:
        return
    subprocess.check_call(cmd)


def main() -> None:
    p = argparse.ArgumentParser(description="Sweep W_K values (ENABLE_W=TRUE, INV_DELTA fixed)")
    p.add_argument("--topo", default="cernet_topo")
    p.add_argument("--my_flow", default="w-dynamic-150-180-v1")
    p.add_argument("--wan_cc_mode", type=int, default=1)
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--dry_run", action="store_true")
    p.add_argument("--simul_time", type=float, default=None, help="Override --simul_time; default uses run.py default")
    args = p.parse_args()

    flow_cfg = os.path.join("config", f"{args.my_flow}.txt")
    if not os.path.exists(flow_cfg):
        raise FileNotFoundError(f"Missing flow config: {flow_cfg}")

    # Values near 1.75e-9 (try a few around it).
    k_values = [
        1.0e-9,
        1.2e-9,
        1.4e-9,
        1.6e-9,
        1.75e-9,
        1.9e-9,
        2.1e-9,
        2.3e-9,
        2.5e-9,
        2.7e-9,
        3.0e-9,
    ]

    total = len(k_values)
    for idx, k in enumerate(k_values, start=1):
        msg = (
            "wk_k_sweep:"
            f"topo={args.topo},"
            f"flow={args.my_flow},"
            f"WAN_CC_MODE={args.wan_cc_mode},"
            f"ENABLE_W=TRUE,"
            f"INV_DELTA={INV_DELTA},"
            f"W_K={k:.6e},"
            f"No.{idx}/{total}"
        )

        cmd = [
            "python3",
            "run.py",
            "--topo",
            args.topo,
            "--my_flow",
            args.my_flow,
            "--wan_cc_mode",
            str(args.wan_cc_mode),
            "--extra",
            "ENABLE_W=TRUE",
            "--extra",
            f"INV_DELTA={INV_DELTA}",
            "--extra",
            f"W_K={k:.12e}",
            "--msg",
            msg,
        ]
        if args.simul_time is not None:
            cmd.extend(["--simul_time", str(args.simul_time)])

        print(f"[{idx}/{total}] W_K={k:.12e}")
        run(cmd, dry_run=args.dry_run)

        if args.sleep and idx < total:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
