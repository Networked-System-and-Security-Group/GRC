#!/usr/bin/env python3
"""Generate a *special* flow set for 2-layer hash ablation.

Requirements (as requested):
- Topology: cernet_topo (read from config/cernet_topo.txt)
- Only inter-DC traffic among DC0, DC1, DC2
- Background: DC1 -> DC0, average total 100 Gbps
- Two elephants (simultaneous):
    - one host in DC1 -> one host in DC0, size 1G (bytes)
    - one host in DC2 -> the same host in DC0, size 1G (bytes)
- Flow size distribution: WebSearch CDF (traffic_gen/WebSearch.txt)

Output format: same as existing flow files:
- first line: number of flows
- each line: "src dst 3 size start_time" (start_time in seconds)

Example:
    python3 config/gen_2layerhash_websearch_case.py --output w-2layerhash-websearch-case
"""

from __future__ import annotations

import argparse
import json
import os.path as op
from pathlib import Path

# Reuse existing generation logic.
from large_traffic_gen import Flow, CustomRand, poisson, translate_bandwidth  # type: ignore


ROOT = Path(__file__).resolve().parent


def parse_size_bytes(s: str) -> int:
    s = s.strip()
    if not s:
        raise ValueError("empty size")
    units = {"K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}
    last = s[-1].upper()
    if last.isdigit():
        return int(float(s))
    if last not in units:
        raise ValueError(f"invalid size suffix in {s!r}; use K/M/G/T")
    return int(float(s[:-1]) * units[last])


def generate_flows_websearch(
    *,
    src_hosts: list[int],
    dst_hosts: list[int],
    total_rate_gbps: float,
    duration_s: float,
    base_time_s: float,
    seed: int,
) -> list[Flow]:
    """Generate flows so that aggregate offered load ~ total_rate_gbps.

    We model each src host as generating traffic at rate = total_rate / |src_hosts|,
    selecting random dst among dst_hosts.
    """

    if not src_hosts:
        raise ValueError("src_hosts is empty")
    if not dst_hosts:
        raise ValueError("dst_hosts is empty")

    import random

    random.seed(seed)

    cdf_path = op.join(op.dirname(__file__), "../traffic_gen", "WebSearch.txt")
    custom_rand = CustomRand(cdf_path)

    # Per-source rate in bits/s
    rate_total_bps = total_rate_gbps * 1e9
    rate_per_src_bps = rate_total_bps / len(src_hosts)

    # avg_interval (seconds) between flows per src
    avg_size = custom_rand.get_avg()  # bytes
    avg_interval_s = 1 / (rate_per_src_bps / 8 / avg_size)

    flows: list[Flow] = []
    for src in src_hosts:
        cur_time = base_time_s + poisson(avg_interval_s * 1e9) / 1e9
        while cur_time < base_time_s + duration_s:
            # allow dst==src? not possible across DCs; keep guard anyway
            candidates = [h for h in dst_hosts if h != src]
            dst = random.choice(candidates) if candidates else dst_hosts[0]
            size = int(custom_rand.rand())
            flows.append(Flow(src, dst, size, cur_time))
            cur_time += poisson(avg_interval_s * 1e9) / 1e9

    flows.sort(key=lambda f: f.t)
    return flows


def main() -> None:
    p = argparse.ArgumentParser(description="Generate special flow set for 2-layer hash ablation")
    p.add_argument("--topo", default="cernet_topo", help="topology file stem under config/ (default: cernet_topo)")
    p.add_argument("--output", default="w-2layerhash-websearch-case", help="output flow file stem under config/")
    p.add_argument("--duration", type=float, default=0.1, help="traffic duration in seconds (default: 0.1)")
    p.add_argument("--base_time", type=float, default=2.0, help="flow start base time in seconds (default: 2.0)")
    p.add_argument("--bg_total_gbps", type=float, default=100.0, help="DC1->DC0 total background rate (Gbps) (default: 100)")
    p.add_argument("--elephant_size", default="1G", help="elephant size in bytes, supports K/M/G/T (default: 1G)")
    p.add_argument("--elephant_offset", type=float, default=0.005, help="elephant start offset from base_time (s)")
    p.add_argument("--dc0_elephant_host_index", type=int, default=0, help="which host in DC0 receives both elephants (default: 0)")
    p.add_argument("--dc1_elephant_host_index", type=int, default=0, help="which host in DC1 sends an elephant (default: 0)")
    p.add_argument("--dc2_elephant_host_index", type=int, default=0, help="which host in DC2 sends an elephant (default: 0)")
    p.add_argument("--seed", type=int, default=1, help="random seed (default: 1)")
    args = p.parse_args()

    topo_path = ROOT / f"{args.topo}.txt"
    if not topo_path.exists():
        raise FileNotFoundError(f"topology file not found: {topo_path}")

    topo = json.loads(topo_path.read_text())
    as_topos = topo["as_topologies"]

    # Only use DC0, DC1, DC2
    dc0_hosts: list[int] = as_topos[0]["hosts"]
    dc1_hosts: list[int] = as_topos[1]["hosts"]
    dc2_hosts: list[int] = as_topos[2]["hosts"]

    # Background traffic: DC1 -> DC0
    bg_flows = generate_flows_websearch(
        src_hosts=dc1_hosts,
        dst_hosts=dc0_hosts,
        total_rate_gbps=float(args.bg_total_gbps),
        duration_s=float(args.duration),
        base_time_s=float(args.base_time),
        seed=int(args.seed),
    )

    # Elephants (simultaneous): DC1 host + DC2 host -> same DC0 host
    if not (0 <= int(args.dc0_elephant_host_index) < len(dc0_hosts)):
        raise ValueError(f"dc0_elephant_host_index out of range: {args.dc0_elephant_host_index}")
    if not (0 <= int(args.dc1_elephant_host_index) < len(dc1_hosts)):
        raise ValueError(f"dc1_elephant_host_index out of range: {args.dc1_elephant_host_index}")
    if not (0 <= int(args.dc2_elephant_host_index) < len(dc2_hosts)):
        raise ValueError(f"dc2_elephant_host_index out of range: {args.dc2_elephant_host_index}")

    elephant_dst = dc0_hosts[int(args.dc0_elephant_host_index)]
    elephant_size_bytes = parse_size_bytes(args.elephant_size)
    elephant_start = float(args.base_time) + float(args.elephant_offset)

    elephant1 = Flow(dc1_hosts[int(args.dc1_elephant_host_index)], elephant_dst, elephant_size_bytes, elephant_start)
    elephant2 = Flow(dc2_hosts[int(args.dc2_elephant_host_index)], elephant_dst, elephant_size_bytes, elephant_start)

    flows = list(bg_flows)
    flows.append(elephant1)
    flows.append(elephant2)
    flows.sort(key=lambda f: f.t)

    out_path = ROOT / f"{args.output}.txt"
    out_path.write_text("".join([f"{len(flows)}\n"] + [str(f) + "\n" for f in flows]))

    # Print a tiny summary.
    # Approx offered load for background only (bits/s): sum(sizes)/duration*8
    bg_bytes = sum(f.size for f in bg_flows)
    bg_rate_gbps = (bg_bytes / float(args.duration) * 8) / 1e9 if args.duration > 0 else 0.0
    print(f"Wrote: {out_path}")
    print(f"Background flows: {len(bg_flows)}; approx offered load: {bg_rate_gbps:.2f} Gbps (target {args.bg_total_gbps} Gbps)")
    print(f"Elephant1 (DC1->DC0): {elephant1.src}->{elephant1.dst}, size={elephant_size_bytes} bytes, t={elephant_start:.6f}s")
    print(f"Elephant2 (DC2->DC0): {elephant2.src}->{elephant2.dst}, size={elephant_size_bytes} bytes, t={elephant_start:.6f}s")


if __name__ == "__main__":
    main()
