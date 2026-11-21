import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.deep_analyse import get_analyser


def with_time(frame):
    return frame.assign(ms=(frame.timestamp_ns - 2_000_000_000) / 1e6)


def link_rate(links, src, dst, flow_ids=None):
    selected = links[(links.src_id == src) & (links.dst_id == dst)]
    if flow_ids is not None:
        selected = selected[selected.flow_id.isin(flow_ids)]
    return selected.groupby("ms").bytes.sum() * 8 / 500_000


def window_rate(series, start, end):
    return series.reindex(pd.RangeIndex(int(start * 2) + 1, int(end * 2) + 1) / 2, fill_value=0)


def link_queue(queues, src, dst):
    return queues[(queues.switch_id == src) & (queues.next_hop == dst)].set_index("ms").egress_bytes / 2**20


def ack_stats(events):
    slots = {}
    pending = {}
    observed = set()
    accepted = set()
    counts = Counter()
    for event in events.itertuples(index=False):
        key = (event.flow_id, event.seq)
        slot = (event.switch_id, event.slot)
        counts[event.status] += 1
        if event.status in ("write", "refresh", "occupied"):
            observed.add(key)
            if event.status != "occupied":
                if slot in slots:
                    pending.pop(slots[slot], None)
                slots[slot] = key
                pending[key] = slot
                accepted.add(key)
        else:
            owner = pending.get(key)
            if event.status in ("sample", "invalid"):
                assert slots.pop(slot) == key, f"unexpected timestamp match: {event}"
                del pending[key]
            elif owner is not None and owner[0] != event.switch_id:
                counts["cross_with_live_record"] += 1
            elif key not in accepted and key in observed:
                counts["not_written"] += 1
            else:
                counts["other_miss"] += 1
    counts["unconsumed_records"] = len(pending)
    return dict(counts)


def analyse(run_id):
    run = get_analyser(run_id)
    folder = Path(run.dir)
    case = re.search(r"-mg1121-(.+)-s\d+$", folder.name)[1]
    log = (folder / "config.log").read_text()
    completed, expected = map(int, re.search(r"finished so far: RDMA (\d+)/(\d+)", log).groups())
    flows = pd.read_json(folder / "flow_output").set_index("flow_id")
    assert len(flows) == expected
    links = with_time(pd.read_csv(folder / "link_utilization"))
    queues = with_time(pd.read_csv(folder / "buffer_monitor"))
    rates = with_time(pd.read_csv(folder / "rate_monitor"))
    drops = pd.read_csv(folder / "drop_log")
    forward = {(route[0], route[-1]): route for route in run.topo["pinned_wan_paths"]}
    wan = set(run.topo["wan_switches"])
    for flow_id, flow in flows.iterrows():
        route = forward[(flow.src, flow.dst)]
        expected_edges = {(src, dst) for src, dst in zip(route, route[1:])
                          if (src in wan or dst in wan) and src != flow.src and dst != flow.dst}
        seen = links[links.flow_id == flow_id]
        assert set(zip(seen.src_id, seen.dst_id)) == expected_edges, (run_id, flow_id, route)
    result = {"id": run_id, "case": case, "completed": completed, "flows": expected, "logged_drops": len(drops)}
    traces = {}
    if (folder / "rtt_match_log").exists():
        events = with_time(pd.read_csv(folder / "rtt_match_log"))
        local_dcis = {site["dci_switch"] for site in run.topo["as_topologies"]}
        local_dcis.update(gateway for site in run.topo["as_topologies"]
                          for gateway in site.get("extra_dci_switches", []))
        for flow_id, flow in flows.iterrows():
            fw = forward[(flow.src, flow.dst)]
            rev = forward[(flow.dst, flow.src)]
            forward_dci = next(node for node in fw if node in local_dcis)
            return_dci = next(node for node in reversed(rev) if node in local_dcis)
            current = events[events.flow_id == flow_id]
            write = current.status.isin(["write", "occupied", "refresh"])
            assert set(current.loc[write, "switch_id"]) == {forward_dci}, (run_id, flow_id, fw)
            assert set(current.loc[~write, "switch_id"]) == {return_dci}, (run_id, flow_id, rev)
        result.update(ack_stats(events))
        samples = events[events.status == "sample"]
        if not samples.empty:
            result["delay_ms_by_flow"] = (samples.groupby("flow_id").sample_ns.median() / 1e6).to_dict()
    if case.startswith("rate-"):
        link = link_rate(links, 226, 222)
        queue = link_queue(queues, 226, 222)
        traces = {"link": link, "queue": queue}
        result["windows"] = {}
        gateways = rates[(rates.dst_as == 0) & rates.switch_id.isin([147, 184, 327])]
        gateways = gateways[gateways.switch_id.isin(links.loc[links.dst_id == 226, "src_id"])]
        for gateway, group in gateways.groupby("switch_id"):
            traces[f"ref {gateway}"] = group.set_index("ms").ref_rate * 8e-9
            traces[f"send {gateway}"] = link_rate(links, gateway, 226)
        active_until = (flows.finish_time.min() - 2) * 1000
        result["first_finish_ms"] = active_until
        for start, end in ((5, 15), (22, 45), (60, 100)):
            assert active_until > end, (run_id, active_until, end)
            throughput = window_rate(link, start, end)
            q = queue.loc[start:end]
            result["windows"][f"{start}-{end}"] = {
                "throughput_gbps": throughput.mean(), "throughput_p10_gbps": throughput.quantile(.10),
                "queue_mean_mib": q.mean(), "queue_peak_mib": q.max(),
                "by_gateway_gbps": {key: window_rate(value, start, end).mean()
                                     for key, value in traces.items() if key.startswith("send ")},
            }
        result["peak_queue_mib"] = queue.max()
    if case.startswith("path-"):
        traces = {"short RDMA": link_rate(links, 222, 224, flows.index[flows.src < 16]),
                  "long RDMA": link_rate(links, 222, 223),
                  "short queue": link_queue(queues, 222, 224),
                  "long queue": link_queue(queues, 222, 223),
                  "long second hop queue": link_queue(queues, 223, 224),
                  "destination access queue": link_queue(queues, 224, 110),
                  "source access queue": link_queue(queues, 36, 222),
                  "ref 36": rates[(rates.switch_id == 36) & (rates.dst_as == 2)].set_index("ms").ref_rate * 8e-9}
        result["peak_queues_mib"] = {key: value.max() for key, value in traces.items() if "queue" in key}
        result["first_finish_ms"] = (flows.finish_time.min() - 2) * 1000
        if case.endswith("-warm"):
            updates = re.findall(r"^\[(\d+)\]AS0->2,.*?\[Copa .*?queue_delay: ([\d.]+)ms,"
                                 r".*?ref_rate ([\d.]+)->([\d.]+)", log, re.M)
            assert any(int(ns) < 2_025_000_000 for ns, *_ in updates), (run_id, "no warm-up update")
            ns, delay, before, after = next(update for update in updates if int(update[0]) >= 2_025_000_000)
            result["first_probe_update"] = {"time_ms": (int(ns) - 2_000_000_000) / 1e6,
                                            "estimated_queue_ms": float(delay),
                                            "ref_before_gbps": 8 * float(before),
                                            "ref_after_gbps": 8 * float(after)}
        if case in ("path-both", "path-busy"):
            result["windows"] = {}
            bg = link_rate(links, 222, 224, flows.index[flows.src == 227])
            traces["background"] = bg
            cnp = with_time(pd.read_csv(folder / "cnp_log"))
            long_flows = links[(links.src_id == 222) & (links.dst_id == 223)].flow_id.unique()
            long_cnp = cnp[(cnp.switch_id == 36) & cnp.flow_id.isin(long_flows)]
            for start, end in ((10, 25), (30, 42)):
                assert (flows[flows.src < 16].finish_time.min() - 2) * 1000 > end, (run_id, start, end)
                result["windows"][f"{start}-{end}"] = {
                    **{key: window_rate(traces[key], start, end).mean()
                       for key in ("short RDMA", "long RDMA", "background")},
                    **{key: value.loc[start:end].mean() for key, value in traces.items()
                       if "queue" in key or key.startswith("ref ")},
                    "cnp_to_long_path": int(((long_cnp.ms >= start) & (long_cnp.ms < end)).sum()),
                }
    return result, traces


def plot(runs, output):
    rate_runs = [(result, traces) for result, traces in runs if result["case"].startswith("rate-")]
    if rate_runs:
        figure, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True, layout="constrained")
        for result, traces in rate_runs:
            tag = result["case"]
            axes[0].plot(traces["link"], label=tag)
            axes[1].plot(traces["queue"], label=tag)
            for key, value in traces.items():
                if key.startswith("ref ") and tag in ("rate-one", "rate-two"):
                    axes[2].plot(value, label=f"{tag} / {key}")
        for axis, label in zip(axes, ("Link throughput (Gb/s)", "WAN queue (MiB)", "Reference rate (Gb/s)")):
            axis.set(ylabel=label, xlim=(0, 115))
            axis.axvline(15, color="grey", ls="--", lw=0.8)
            axis.legend(fontsize=8, ncols=2)
        axes[-1].set_xlabel("Time since first flow start (ms)")
        figure.savefig(output / "shared-bottleneck.svg")
        plt.close(figure)
    path_runs = [(result, traces) for result, traces in runs if result["case"] in ("path-both", "path-busy")]
    if path_runs:
        figure, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True, layout="constrained")
        for result, traces in path_runs:
            tag = result["case"]
            for key in ("short RDMA", "long RDMA", "background"):
                if not traces[key].empty:
                    axes[0].plot(traces[key], label=f"{tag} / {key}")
            for key in ("short queue", "long queue", "long second hop queue", "destination access queue", "source access queue"):
                axes[1].plot(traces[key], label=f"{tag} / {key}")
            axes[2].plot(traces["ref 36"], label=tag)
        for axis, label in zip(axes, ("Path throughput (Gb/s)", "Egress queue (MiB)", "Reference rate (Gb/s)")):
            axis.set(ylabel=label, xlim=(0, 50))
            axis.axvline(25, color="grey", ls="--", lw=0.8)
            axis.legend(fontsize=8, ncols=2)
        axes[-1].set_xlabel("Time since first flow start (ms)")
        figure.savefig(output / "two-paths.svg")
        plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", type=int)
    parser.add_argument("--output", type=Path, default=Path("docs/experiments/1121-multi-gateway-wan"))
    args = parser.parse_args()
    runs = [analyse(run_id) for run_id in args.ids]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps([result for result, _ in runs], indent=2,
                                                          allow_nan=False) + "\n")
    plot(runs, args.output)
