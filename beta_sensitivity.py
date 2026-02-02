#!/usr/bin/env python3
import shlex
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent

TOPO = "cernet_topo"
SIMUL_TIME = 0.1
FLOW_SET = "w"
BACKGROUND_INTER_LOAD = 150
DYNAMICS = [0, 50, 100, 150, 200]
BETAS = [0.5, 0.4, 0.3, 0.2, 0.1, 0]
SLEEP = 1


def run(cmd):
    print("+", shlex.join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main():
    topo_path = ROOT / "config" / f"{TOPO}.txt"
    if not topo_path.exists():
        raise FileNotFoundError(f"Topology not found: config/{TOPO}.txt")

    flows = {}
    for dyn in DYNAMICS:
        flow = f"{FLOW_SET}-dynamic-{BACKGROUND_INTER_LOAD}-{dyn}"
        path = ROOT / "config" / f"{flow}.txt"
        if not path.exists():
            run(
                [
                    "python3",
                    "config/large_traffic_gen.py",
                    "-f",
                    FLOW_SET,
                    "-b",
                    str(BACKGROUND_INTER_LOAD),
                    "-d",
                    str(dyn),
                ]
            )
            if not path.exists():
                raise FileNotFoundError(f"Flow file not created: {path}")
        flows[dyn] = flow

    run_id = 1
    for dyn in DYNAMICS:
        flow = flows[dyn]
        for beta in BETAS:
            msg = f"beta_sens:gscc,flow={flow},dyn={dyn},BETA={beta},No.{run_id}"
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
                "--extra",
                f"BETA={beta}",
                "--msg",
                msg,
            ]
            run(cmd)
            run_id += 1
            if SLEEP:
                time.sleep(SLEEP)


if __name__ == "__main__":
    main()
