import argparse
import shlex
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

MIB = 1024 * 1024

# Baselines:
# - wo_gscc: WAN_CC_MODE=0 (no GSCC, WAN ECN off)
# - inf_wo_gscc: like wo_gscc, but huge DCI/WAN buffers
# - gscc_20m: GSCC without W; w=1, so INV_DELTA is 20MiB
# - gscc_20m_fair: gscc_20m with GSCC_FAIR enabled
# - gscc_w_8m: GSCC with W enabled; expected w~=2.5, so INV_DELTA is 8MiB
# - gscc_w_8m_fair: gscc_w_8m with GSCC_FAIR enabled
# - gemini: GEMINI host-side CC without GSCC
# - unocc: UnoCC host-side CC without GSCC
PRESETS = {
    "wo_gscc": {"wan_cc_mode": 0},
    "inf_wo_gscc": {"wan_cc_mode": 0, "wan_buffer": 4000, "dci_buffer": 4000},
    "gscc_20m": {
        "wan_cc_mode": 1,
        "extra": {"ENABLE_W": "FALSE", "INV_DELTA": str(20 * MIB), "GSCC_FAIR": "FALSE"},
    },
    "gscc_20m_fair": {
        "wan_cc_mode": 1,
        "extra": {"ENABLE_W": "FALSE", "INV_DELTA": str(20 * MIB), "GSCC_FAIR": "TRUE"},
    },
    "gscc_w_8m": {
        "wan_cc_mode": 1,
        "extra": {"ENABLE_W": "TRUE", "INV_DELTA": str(8 * MIB), "GSCC_FAIR": "FALSE"},
    },
    "gscc_w_8m_fair": {
        "wan_cc_mode": 1,
        "extra": {"ENABLE_W": "TRUE", "INV_DELTA": str(8 * MIB), "GSCC_FAIR": "TRUE"},
    },
    "gemini": {"wan_cc_mode": 0, "cc": "gemini"},
    "unocc": {"wan_cc_mode": 0, "cc": "unocc"},
}


def run(cmd, *, dry_run=False):
    print("+", shlex.join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, cwd=str(ROOT), check=True)


def append_preset_args(cmd, preset):
    for key, value in preset.items():
        if key == "extra":
            continue
        cmd.append(f"--{key}")
        cmd.append(str(value))
    for key, value in preset.get("extra", {}).items():
        cmd.append("--extra")
        cmd.append(f"{key}={value}")


def main():
    p = argparse.ArgumentParser(description="overall batch runner with UnoCC and GSCC W sweeps")
    p.add_argument("--topo", default="cernet_topo")
    p.add_argument("--simul_time", type=float, default=0.1)
    p.add_argument("--flow_set", choices=["w", "a"], default="w")
    p.add_argument("--background_inter_load", type=int, default=150)
    p.add_argument("--dynamic_list", default="0,60,120,180")
    p.add_argument(
        "--modes",
        default="wo_gscc,inf_wo_gscc,gscc_20m,gscc_20m_fair,gscc_w_8m,gscc_w_8m_fair,gemini,unocc",
    )
    p.add_argument("--inf_buffer_mb", type=int, default=4000)
    p.add_argument("--gscc_invdelta_mib", type=float, default=20.0)
    p.add_argument("--weighted_invdelta_mib", type=float, default=8.0)
    p.add_argument("--weighted_w_max", type=float, default=4.0)
    p.add_argument("--sleep", type=float, default=1)
    p.add_argument("--dry_run", action="store_true")
    args, extra = p.parse_known_args()

    if not (ROOT / "config" / f"{args.topo}.txt").exists():
        raise FileNotFoundError(f"Topology not found: config/{args.topo}.txt")

    presets = {name: dict(value) for name, value in PRESETS.items()}
    presets["inf_wo_gscc"]["wan_buffer"] = args.inf_buffer_mb
    presets["inf_wo_gscc"]["dci_buffer"] = args.inf_buffer_mb
    presets["gscc_20m"]["extra"] = {
        "ENABLE_W": "FALSE",
        "INV_DELTA": str(int(args.gscc_invdelta_mib * MIB)),
        "GSCC_FAIR": "FALSE",
    }
    presets["gscc_20m_fair"]["extra"] = {
        "ENABLE_W": "FALSE",
        "INV_DELTA": str(int(args.gscc_invdelta_mib * MIB)),
        "GSCC_FAIR": "TRUE",
    }
    presets["gscc_w_8m"]["extra"] = {
        "ENABLE_W": "TRUE",
        "INV_DELTA": str(int(args.weighted_invdelta_mib * MIB)),
        "W_MAX": str(args.weighted_w_max),
        "GSCC_FAIR": "FALSE",
    }
    presets["gscc_w_8m_fair"]["extra"] = {
        "ENABLE_W": "TRUE",
        "INV_DELTA": str(int(args.weighted_invdelta_mib * MIB)),
        "W_MAX": str(args.weighted_w_max),
        "GSCC_FAIR": "TRUE",
    }

    dynamics = [int(x) for x in args.dynamic_list.split(",") if x.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = [m for m in modes if m not in presets]
    if unknown:
        raise ValueError(f"Unknown mode(s): {unknown}. Supported: {list(presets.keys())}")

    # 1) Generate flows so run.py won't fall back to wan_traffic_gen.py.
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

    # 2) Launch runs.
    run_id = 1
    for dyn in dynamics:
        flow = flows[dyn]
        for mode in modes:
            preset = presets[mode]

            msg = f"overall:{mode},flow={flow},dyn={dyn},No.{run_id}"
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
            append_preset_args(cmd, preset)
            run(cmd, dry_run=args.dry_run)
            run_id += 1
            if args.sleep:
                time.sleep(args.sleep)


if __name__ == "__main__":
    main()
