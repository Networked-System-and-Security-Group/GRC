#!/usr/bin/env python3
"""Run 2-layer-hash ablation on a single flow file.

This runs two experiments (independent, not a sweep product):
- ENABLE_2LAYER_HASH=TRUE
- ENABLE_2LAYER_HASH=FALSE

Example:
  python3 two_layer_hash_ablation.py --my_flow w-2layerhash-websearch-case --simul_time 0.1
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], *, dry_run: bool) -> None:
    print("+", shlex.join(cmd), flush=True)
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main() -> None:
    p = argparse.ArgumentParser(description="2-layer hash ablation runner")
    p.add_argument("--topo", default="cernet_topo")
    p.add_argument("--my_flow", default="w-2layerhash-websearch-case")
    p.add_argument("--wan_cc_mode", type=int, default=1)
    p.add_argument("--simul_time", type=float, default=None, help="override simulation time; default uses run.py default")
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--dry_run", action="store_true")
    args = p.parse_args()

    # Best-effort check that the flow file exists.
    flow = args.my_flow.strip()
    if flow.startswith("config/"):
        flow = flow[len("config/"):]
    if flow.endswith(".txt"):
        flow = flow[:-4]

    flow_path = ROOT / "config" / f"{flow}.txt"
    if not flow_path.exists():
        raise FileNotFoundError(
            f"Flow file not found: {flow_path}. "
            f"Generate it via: python3 config/gen_2layerhash_websearch_case.py --output {flow}"
        )

    values = ["TRUE", "FALSE"]
    total = len(values)
    for i, v in enumerate(values, start=1):
        msg = (
            "2layerhash_ablation:"
            f"topo={args.topo},"
            f"flow={flow},"
            f"WAN_CC_MODE={args.wan_cc_mode},"
            f"ENABLE_2LAYER_HASH={v},"
            f"No.{i}/{total}"
        )

        cmd = [
            "python3",
            "run.py",
            "--topo",
            args.topo,
            "--my_flow",
            flow,
            "--wan_cc_mode",
            str(args.wan_cc_mode),
            "--extra",
            f"ENABLE_2LAYER_HASH={v}",
            "--msg",
            msg,
        ]
        if args.simul_time is not None:
            cmd.extend(["--simul_time", str(args.simul_time)])

        print(f"[{i}/{total}] ENABLE_2LAYER_HASH={v}")
        run(cmd, dry_run=args.dry_run)
        if args.sleep and i < total:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
