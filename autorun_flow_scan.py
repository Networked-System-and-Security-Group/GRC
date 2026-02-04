#!/usr/bin/env python3
import argparse
import shlex
import subprocess
import time
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Baselines:
# - wo_gscc: WAN_CC_MODE=0 (no GSCC, WAN ECN off)
# - inf_wo_gscc: like wo_gscc, but huge DCI/WAN buffers
# - gscc: WAN_CC_MODE=1
PRESETS = {
    "wo_gscc": {"wan_cc_mode": 0, "dci": 0, "wan": 0},
    "inf_wo_gscc": {"wan_cc_mode": 0},
    "gscc": {"wan_cc_mode": 1, "dci": 0, "wan": 0},
}

def run(cmd, *, dry_run=False):
    print("+", shlex.join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, cwd=str(ROOT), check=True)

def main():
    p = argparse.ArgumentParser(description="Scan flow sets with variations")
    p.add_argument("--topo", default="cernet_topo")
    p.add_argument("--simul_time", type=float, default=0.1)
    p.add_argument("--flow_set", choices=["w", "a"], default="w")
    p.add_argument("--background_inter_load", type=int, default=150)
    p.add_argument("--dynamic_list", default="60,120,180")
    p.add_argument("--variations", type=int, default=2)
    p.add_argument("--modes", default="wo_gscc,inf_wo_gscc,gscc")
    p.add_argument("--inf_buffer_mb", type=int, default=4000)
    p.add_argument("--sleep", type=float, default=1)
    p.add_argument("--dry_run", action="store_true")
    args = p.parse_args()

    dynamics = [int(x) for x in args.dynamic_list.split(",") if x.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    
    # Validate modes
    unknown = [m for m in modes if m not in PRESETS]
    if unknown:
        raise ValueError(f"Unknown mode(s): {unknown}. Supported: {list(PRESETS.keys())}")

    # 1. Generate flows
    # We want 'variations' count of random flows for each dynamic load.
    generated_flows = {} # key: (dyn, variation_index) -> value: flow_name
    
    for dyn in dynamics:
        # The filename that large_traffic_gen.py produces by default
        base_flow_name = f"{args.flow_set}-dynamic-{args.background_inter_load}-{dyn}"
        base_path = ROOT / "config" / f"{base_flow_name}.txt"
        
        for v in range(args.variations):
            # Target flow name with variation suffix
            target_flow_name = f"{base_flow_name}-v{v}"
            target_path = ROOT / "config" / f"{target_flow_name}.txt"
            
            if target_path.exists():
                print(f"Flow file already exists, skipping generation: {target_path}")
            else:
                print(f"Generating variation {v} for dynamic load {dyn}...")
                # Run generator
                # large_traffic_gen.py logic ensures random flows on each run
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
                
                # Move/Rename file to save this specific variation
                if not args.dry_run:
                    if base_path.exists():
                        shutil.move(str(base_path), str(target_path))
                        print(f"Renamed {base_path} to {target_path}")
                    else:
                        raise FileNotFoundError(f"Expected generated file not found: {base_path}")
            
            generated_flows[(dyn, v)] = target_flow_name

    # 2. Run Experiments
    run_id = 1
    # Order: For each load -> For each variation -> For each mode
    # Total 3 * 2 * 3 = 18 experiments (with default args)
    
    for dyn in dynamics:
        for v in range(args.variations):
            flow = generated_flows[(dyn, v)]
            for mode in modes:
                preset = PRESETS[mode]
                wan_cc_mode = preset["wan_cc_mode"]
                if mode == "inf_wo_gscc":
                    dci_mb = wan_mb = args.inf_buffer_mb
                else:
                    dci_mb = preset["dci"]
                    wan_mb = preset["wan"]

                msg = f"paper_scan:{mode},flow={flow},dyn={dyn},var={v},No.{run_id}"
                cmd = [
                    "python3",
                    "run.py",
                    "--topo",
                    args.topo,
                    "--simul_time",
                    str(args.simul_time),
                    "--my_flow",
                    flow,
                    "--wan_cc_mode",
                    str(wan_cc_mode),
                    "--dci_buffer",
                    str(dci_mb),
                    "--wan_buffer",
                    str(wan_mb),
                    "--msg",
                    msg,
                ]
                run(cmd, dry_run=args.dry_run)
                run_id += 1
                if args.sleep:
                    time.sleep(args.sleep)

if __name__ == "__main__":
    main()
