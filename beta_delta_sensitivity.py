#!/usr/bin/env python3
import shlex
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent

TOPO = "cernet_topo"
SIMUL_TIME = 0.1

# Parameter Ranges
BETAS = [0, 0.15, 0.3, 0.45, 0.6]
# Default is 10485760. Testing range from ~0.25x to ~4x
INV_DELTAS = [2.5 * 1024 * 1024, 
              5 * 1024 * 1024, 
              10 * 1024 * 1024, 
              20 * 1024 * 1024, 
              40 * 1024 * 1024]

# Other Flags
SLEEP = 1
ENABLE_V = 'TRUE'
# Based on previous conversation, you might want to enable W with the found K.
# Setting them here for easy modification.
ENABLE_W = 'FALSE'
W_K = '2.0566e-09'

def run(cmd):
    print("+", shlex.join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main():
    topo_path = ROOT / "config" / f"{TOPO}.txt"
    if not topo_path.exists():
        raise FileNotFoundError(f"Topology not found: config/{TOPO}.txt")

    # Ensure flow file exists
    flow = f"w-dynamic-150-180-v1"

    run_id = 1
    total_runs = len(BETAS) * len(INV_DELTAS)
    
    print(f"Starting Beta-Delta Sensitivity Experiment with {total_runs} runs...")
    
    for inv_delta in INV_DELTAS:
        for beta in BETAS:
            msg = f"beta_delta_sens:gscc,flow={flow},ENABLE_V={ENABLE_V},BETA={beta},INV_DELTA={inv_delta},No.{run_id}"
            cmd = [
                "python3",
                "run.py",
                "--topo",
                TOPO,
                "--simul_time",
                str(SIMUL_TIME),
                "--my_flow",
                flow,
                "--wan_cc_mode",
                "1",
                "--dci_buffer",
                "0",
                "--wan_buffer",
                "0",
                "--extra", f"BETA={beta}",
                "--extra", f"INV_DELTA={inv_delta}",
                "--extra", f"ENABLE_V={ENABLE_V}",
                "--extra", f"ENABLE_W={ENABLE_W}",
                "--extra", f"W_K={W_K}",
                "--msg",
                msg,
            ]
            
            print(f"[{run_id}/{total_runs}] Running BETA={beta}, INV_DELTA={inv_delta}...")
            run(cmd)
            run_id += 1
            if SLEEP:
                time.sleep(SLEEP)


if __name__ == "__main__":
    main()
