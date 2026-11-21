import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


spec = spec_from_file_location("multi_gateway_runner", Path(__file__).resolve().parents[1]
                               / "expr-1121-multi-gateway-wan/run.py")
base = module_from_spec(spec)
spec.loader.exec_module(base)

# ACK return, mirror enabled, link propagation, timestamp mode, flow size (MiB).
CASES = {
    "same-off": ("local", False, 2, True, 2),
    "same-on": ("local", True, 2, True, 2),
    "half-off": ("half", False, 2, True, 2),
    "half-on": ("half", True, 2, True, 2),
    "cross-off": ("cross", False, 2, True, 2),
    "cross-on": ("cross", True, 2, True, 2),
    "cross-slow": ("cross", True, 1200, True, 2),
    "roundtrip-fast": ("cross", True, 2, False, 2),
    "roundtrip-slow": ("cross", True, 1200, False, 2),
    "long-same": ("local", False, 2, True, 128),
    "long-off": ("cross", False, 2, True, 128),
    "long-on": ("cross", True, 2, True, 128),
    "long-slow": ("cross", True, 1200, True, 128),
}


def run(case, seed):
    return_path, enabled, delay_us, timestamp, size = CASES[case]
    name = f"ack-{return_path}"
    topo, flows = base.make_case(name)
    site = next(site for site in topo["as_topologies"] if site["as_id"] == 3)
    site["links"].append({"src": site["dci_switch"], "dst": base.EXTRA, "bw": "100Gbps",
                          "delay": f"{delay_us}us", "loss": 0.0})
    flows = [(src, dst, pg, size * base.MIB, start) for src, dst, pg, _, start in flows]
    base.run(name, seed, tag=f"am1121-{case}", inputs=(topo, flows), overrides=(
        f"WAN_ACK_MIRROR={int(enabled)}", f"GSCC_ACK_TS={'TRUE' if timestamp else 'FALSE'}",
        "EARLIEST_STOP_SECONDS=2.010" if size == 2 else "EARLIEST_STOP_SECONDS=2.100"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", default=list(CASES))
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    for case in args.cases:
        if case not in CASES:
            parser.error(f"unknown case {case!r}")
        run(case, args.seed)
