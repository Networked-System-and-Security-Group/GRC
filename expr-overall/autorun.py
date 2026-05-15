import argparse
import shlex
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# Baselines:
# - wo_gscc: WAN_CC_MODE=0 (no GSCC, WAN ECN off)
# - inf_wo_gscc: like wo_gscc, but huge DCI/WAN buffers
# - gscc: WAN_CC_MODE=1
# - dcqcn_ecn: WAN_CC_MODE=2 (WAN ECN on, no GSCC)
PRESETS = {
    "wo_gscc": {"wan_cc_mode": 0},
    "inf_wo_gscc": {"wan_cc_mode": 0, "wan_buffer":4000, "dci_buffer":4000},
    "gscc": {"wan_cc_mode": 1},
    "gemini": {"wan_cc_mode": 0, "cc": "gemini"},
}


def run(cmd, *, dry_run=False):
    print("+", shlex.join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, cwd=str(ROOT), check=True)


def main():
    p = argparse.ArgumentParser(description="paper batch runner")
    p.add_argument("--topo", default="cernet_topo")
    p.add_argument("--simul_time", type=float, default=0.1)
    p.add_argument("--flow_set", choices=["w", "a"], default="w")
    p.add_argument("--background_inter_load", type=int, default=150)
    p.add_argument("--dynamic_list", default="0,60,120,180")
    p.add_argument("--modes", default="wo_gscc,inf_wo_gscc,gscc,gemini")
    p.add_argument("--inf_buffer_mb", type=int, default=4000)
    p.add_argument("--sleep", type=float, default=1)
    p.add_argument("--dry_run", action="store_true")
    args, extra = p.parse_known_args()


    if not (ROOT / "config" / f"{args.topo}.txt").exists():
        raise FileNotFoundError(f"Topology not found: config/{args.topo}.txt")

    dynamics = [int(x) for x in args.dynamic_list.split(",") if x.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = [m for m in modes if m not in PRESETS]
    if unknown:
        raise ValueError(f"Unknown mode(s): {unknown}. Supported: {list(PRESETS.keys())}")

    # 1) Generate flows (so run.py won't fall back to wan_traffic_gen.py)
    flows = {}
    for dyn in dynamics:
        flow = f"{args.flow_set}-dynamic-{args.background_inter_load}-{dyn}"
        path = ROOT / "config" / f"{flow}.txt"
        if not path.exists():
            run(
                [
                    "python3",
                    "config/large_traffic_gen.py",
                    "-f",
                    args.flow_set,
                    "-b",
                    str(args.background_inter_load),
                    "-d",
                    str(dyn),
                ],
                dry_run=args.dry_run,
            )
            if not args.dry_run and not path.exists():
                raise FileNotFoundError(f"Flow file not created: {path}")
        flows[dyn] = flow

    # 2) Launch runs
    run_id = 1
    for dyn in dynamics:
        flow = flows[dyn]
        for mode in modes:
            preset = PRESETS[mode]

            msg = f"paper:{mode},flow={flow},dyn={dyn},No.{run_id}"
            cmd = [
                "python3",
                "run.py",
                "--topo",
                args.topo,
                "--simul_time",
                str(args.simul_time),
                "--my_flow",
                flow,
                "--msg",
                msg,
            ] + extra
            for key, value in preset.items():
                cmd.append(f"--{key}")
                cmd.append(str(value))
            run(cmd, dry_run=args.dry_run)
            run_id += 1
            if args.sleep:
                time.sleep(args.sleep)


if __name__ == "__main__":
    main()