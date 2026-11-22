"""Run the paper's WebSearch trace with controlled ACK return at DC3."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zlib

from run import base


TRACE = "w-dynamic-150-0"
CASES = {
    # (cross_return, mirror, split_data_across_two_gateways)
    "single-off": (False, 0, False),
    "two-same-off": (False, 0, True),
    "two-cross-off": (True, 0, True),
    "same-on": (False, 1, True),
    "cross-off": (True, 0, True),
    "cross-on": (True, 1, True),
}


def make_topology(cross, split):
    topo, _ = base.make_case("ack-local")
    sites = {site["as_id"]: site for site in topo["as_topologies"]}
    dc3 = sites[3]
    gateways = (dc3["dci_switch"], base.EXTRA)
    dc3["links"].append({"src": gateways[0], "dst": gateways[1], "bw": "100Gbps",
                          "delay": "2us", "loss": 0.0})
    access = {link["src"]: link["dst"] for link in topo["wan_links"]
              if link["src"] in {site["dci_switch"] for site in sites.values()} | {base.EXTRA}}
    core_nodes = set(topo["wan_switches"])
    backbone = [link for link in topo["wan_links"] if {link["src"], link["dst"]} <= core_nodes]
    cores = {site: sorted(link["dst"] for link in spec["links"]
                          if link["src"] == spec["dci_switch"] and link["dst"] in spec["switches"]) for site, spec in sites.items()}
    backbone_paths = {site: base.local_path({"switches": core_nodes, "links": backbone, "dci_switch": -1},
                                           access[gateways[0]], access[spec["dci_switch"]],
                                           access[spec["dci_switch"]])
                      for site, spec in sites.items() if site != 3}
    paths = topo["pinned_wan_paths"] = []
    for site, spec in sites.items():
        if site == 3:
            continue
        remote_gw = spec["dci_switch"]
        for local in dc3["hosts"]:
            for remote in spec["hosts"]:
                choice = zlib.crc32(f"{local}:{remote}".encode())
                local_core = cores[3][(choice >> 1) % len(cores[3])]
                remote_core = cores[site][(choice >> 3) % len(cores[site])]
                forward_gw = gateways[choice & 1] if split else gateways[0]
                return_gw = gateways[((choice & 1) ^ cross)] if split else gateways[0]
                left = base.local_path(dc3, local, forward_gw, local_core)
                right = base.local_path(spec, remote, remote_gw, remote_core)
                return_left = base.local_path(dc3, local, return_gw, local_core)
                backbone_path = backbone_paths[site]
                paths.extend([left + backbone_path + right[::-1],
                              right + backbone_path[::-1] + return_left[::-1]])
    return topo


def run(case, bottleneck_gbps=400):
    cross, mirror, split = CASES[case]
    suffix = "" if bottleneck_gbps == 400 else f"-{bottleneck_gbps}g"
    tag = f"am1121-scale-{case}{suffix}"
    topology = make_topology(cross, split)
    if bottleneck_gbps != 400:
        link, = (link for link in topology["wan_links"] if {link["src"], link["dst"]} == {226, 222})
        link["bw"] = f"{bottleneck_gbps}Gbps"
    Path(f"config/{tag}.txt").write_text(json.dumps(topology, indent=2) + "\n")
    overrides = {
        "RANDOM_SEED": 1, "WAN_ACK_MIRROR": mirror, "WAN_TRACE_RTT_MATCH": 1,
        "GSCC_ACK_TS": "TRUE", "ENABLE_W": "TRUE", "INV_DELTA": 6291456,
        "W_MAX": 4, "BETA": 0.3, "GUARANTEED_RATE_FACTOR": 0.25,
        "WAN_EPOCH_US": 1000, "GSCC_FAIR": "TRUE", "ENABLE_V": "TRUE",
    }
    # Use the paper-scale command's run length; short mirror pilots still need to drain late copies.
    if TRACE.endswith("150-0"):
        overrides["EARLIEST_STOP_SECONDS"] = 2.1
    trace_time = "0.1" if TRACE == "w-dynamic-150-0" else "0.2"
    args = [sys.executable, "-u", "run.py", "--skip-build", "1", "--stdout", "1",
            "--topo", tag, "--my_flow", TRACE, "--tcp_flow", "", "--simul_time", trace_time,
            "--wan_cc_mode", "1", "--cc", "dcqcn", "--lb", "fecmp", "--msg", tag]
    for key, value in overrides.items():
        args.extend(["--extra", f"{key}={value}"])
    subprocess.run(args, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=CASES)
    parser.add_argument("--bottleneck-gbps", type=int, choices=(200, 400), default=400)
    args = parser.parse_args()
    run(args.case, args.bottleneck_gbps)
