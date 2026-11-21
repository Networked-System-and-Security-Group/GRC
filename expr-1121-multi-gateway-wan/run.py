import argparse
from collections import deque
import json
from pathlib import Path
import re
import subprocess
import sys


CASES = (
    "ack-local", "ack-half", "ack-cross",
    "rate-one", "rate-two", "rate-two-dc",
    "rate-one-weighted", "rate-two-weighted",
    "path-both", "path-busy", "path-short-warm", "path-long-warm",
)
PILOTS = ("path-short", "path-long")
CONFIG = Path("config")
BASE = CONFIG / "cernet_topo.txt"
EXTRA = 327
MIB = 1024 ** 2


def local_path(site, host, gateway, core):
    allowed = set(site["switches"]) - {link["dst"] for link in site["links"]
                                       if link["src"] == site["dci_switch"]}
    allowed.update((host, gateway, core))
    neighbors = {node: [] for node in allowed}
    for link in site["links"]:
        src, dst = link["src"], link["dst"]
        if src in allowed and dst in allowed:
            neighbors[src].append(dst)
            neighbors[dst].append(src)
    pending = deque([[host]])
    seen = {host}
    while pending:
        path = pending.popleft()
        if path[-1] == gateway:
            return path
        for node in sorted(neighbors[path[-1]]):
            if node not in seen:
                seen.add(node)
                pending.append(path + [node])
    raise ValueError(f"No route from host {host} to gateway {gateway} via {core}")


def make_case(name):
    topo = json.loads(BASE.read_text())
    dc = {site["as_id"]: site for site in topo["as_topologies"]}
    dc[3]["extra_dci_switches"] = [EXTRA]
    dc[3]["links"] += [dict(link, src=EXTRA) for link in dc[3]["links"] if link["src"] == 147]
    topo["wan_links"] += [dict(link, src=EXTRA) for link in topo["wan_links"] if link["src"] == 147]
    topo["wan_link_num"] = len(topo["wan_links"])
    paths = topo["pinned_wan_paths"] = []
    flows = []

    def add(src_site, src_pos, dst_site, dst_pos, forward, backward, src_core, dst_core, size, start):
        src = dc[src_site]["hosts"][src_pos]
        dst = dc[dst_site]["hosts"][dst_pos]
        left = local_path(dc[src_site], src, forward[0], src_core)
        right = local_path(dc[dst_site], dst, forward[-1], dst_core)
        left_ack = local_path(dc[src_site], src, backward[-1], src_core)
        paths.extend([left[:-1] + forward + right[-2::-1], right[:-1] + backward + left_ack[-2::-1]])
        flows.append((src, dst, 3, size, start))

    def capacity(src, dst, rate):
        link, = (link for link in topo["wan_links"] if {link["src"], link["dst"]} == {src, dst})
        link["bw"] = f"{rate}Gbps"

    if name.startswith("ack-"):
        for pos in range(4):
            gateway = 147 if pos < 2 else EXTRA
            other = EXTRA if gateway == 147 else 147
            ack = other if name == "ack-cross" or (name == "ack-half" and pos % 2) else gateway
            add(3, pos * 4, 0, pos * 4, [gateway, 226, 222, 36],
                [36, 222, 226, ack], 143 + pos, 32 + pos, 2 * MIB, 2.0 + pos * 0.0001)
    elif name.startswith("rate-"):
        capacity(226, 222, 200)
        for group in range(2):
            site = 4 if name == "rate-two-dc" and group else 3
            gateway = 184 if site == 4 else EXTRA if group and name.startswith("rate-two") else 147
            for pod in range(4):
                route = [gateway, 226, 222, 36]
                add(site, pod * 4 + group, 0, pod * 4 + group, route, route[::-1],
                    (180 if site == 4 else 143) + group, 32 + group, 384 * MIB, 2.0 + group * 0.015)
    else:
        capacity(222, 224, 100)
        for src, dst in ((222, 223), (223, 224)):
            capacity(src, dst, 100)
        for group in range(2):
            if name.startswith(("path-short", "path-long")):
                path = [36, 222, 223, 224, 110] if group and name.startswith("path-long") else [36, 222, 224, 110]
                add(0, group * 4, 2, group * 4, path, path[::-1], 32 + group, 106 + group,
                    (2 if group or name in PILOTS else 48) * MIB, 2.0 + group * 0.025)
                continue
            path = [36, 222, 224, 110] if group == 0 else [36, 222, 223, 224, 110]
            for pod in range(4):
                add(0, pod * 4 + group, 2, pod * 4 + group, path, path[::-1],
                    32 + group, 106 + group, 256 * MIB, 2.0)
        if name == "path-busy":
            src, dst = topo["wan_hosts"][0], topo["wan_hosts"][40]
            assert (src, dst) == (227, 267)
            paths.extend([[src, 222, 224, dst], [dst, 224, 222, src]])
            flows.append((src, dst, 3, 192 * MIB, 2.025))

    assert len(paths) == 2 * len(flows)
    assert len({(path[0], path[-1]) for path in paths}) == len(paths)
    flows.sort(key=lambda flow: flow[-1])
    return topo, flows


def run(name, seed, inputs_only=False, *, overrides=(), tag=None, inputs=None):
    stem = f"{tag or 'mg1121-' + name}-s{seed}"
    topo, flows = inputs if inputs is not None else make_case(name)
    (CONFIG / f"{stem}-topo.txt").write_text(json.dumps(topo, indent=2) + "\n")
    (CONFIG / f"{stem}-flow.txt").write_text(str(len(flows)) + "\n" + "".join(
        f"{src} {dst} {pg} {size} {start:.9f}\n" for src, dst, pg, size, start in flows))
    if inputs_only:
        return
    args = [sys.executable, "run.py", "--skip-build", "1", "--stdout", "1",
            "--topo", f"{stem}-topo", "--my_flow", f"{stem}-flow", "--tcp_flow", "",
            "--wan_cc_mode", "1", "--cc", "dcqcn", "--lb", "fecmp", "--simul_time", "0.2",
            "--msg", stem, "--extra", f"RANDOM_SEED={seed}",
            "--extra", f"ENABLE_W={'TRUE' if name.endswith('-weighted') else 'FALSE'}"]
    if name.startswith(("ack-", "path-short", "path-long")):
        args += ["--extra", "WAN_TRACE_RTT_MATCH=1"]
    for override in overrides:
        args += ["--extra", override]
    process = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = process.stdout
    match = re.search(r"(/[^\n']+/mix/output/\[\d+\][^\n']+)/config\.txt", output)
    if process.returncode or not match or "Simulator is enforced to be finished" not in output:
        raise RuntimeError(output[-6000:])
    print(f"{name},seed={seed},{match.group(1)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", default=CASES)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--inputs-only", action="store_true")
    args = parser.parse_args()
    for case in args.cases:
        if case not in CASES + PILOTS:
            parser.error(f"unknown case {case!r}")
        run(case, args.seed, args.inputs_only)
