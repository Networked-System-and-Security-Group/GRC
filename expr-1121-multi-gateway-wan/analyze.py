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


def save_svg(fig, path):
    fig.savefig(path, metadata={"Date": None})
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")
    plt.close(fig)


def plot(runs, output):
    plt.rcParams.update({"font.family": ["Source Han Sans CN", "DejaVu Sans"], "svg.hashsalt": "cernet1121"})
    colors = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#49348E")
    styles = ("-", "-", "--", ":", "-.")
    scenarios = {
        "rate-one": "同一 DC · 1 个网关",
        "rate-two": "同一 DC · 2 个网关",
        "rate-two-dc": "两个 DC · 各 1 个网关",
        "rate-one-weighted": "同一 DC · 1 个网关（自适应权重）",
        "rate-two-weighted": "同一 DC · 2 个网关（自适应权重）",
    }
    grouped = {result["case"]: (result, traces) for result, traces in runs}
    if grouped.keys() & scenarios.keys():
        fig, axes = plt.subplots(3, 1, figsize=(9.1, 8.9), sharex=True)
        fig.subplots_adjust(left=.13, right=.97, top=.79, bottom=.10, hspace=.43)
        fig.suptitle("多个网关共用一条 WAN 瓶颈链路", x=.13, ha="left", y=.984, fontsize=18)
        fig.text(.13, .933, "CERNET 呼和浩特 → 北京  |  名义容量 200 Gb/s  |  两批流量各 4 条长流", fontsize=11)
        for i, (case, label) in enumerate(scenarios.items()):
            if case not in grouped:
                continue
            _, traces = grouped[case]
            style = dict(color=colors[i], ls=styles[i], lw=1.65)
            axes[0].plot(traces["link"], label=label, **style)
            axes[1].plot(traces["queue"], **style)
            if case == "rate-one":
                axes[2].plot(traces["ref 147"], label="单网关组：唯一网关", **style)
            if case == "rate-two":
                axes[2].plot(traces["ref 147"], label="双网关组：第一网关", **style)
                axes[2].plot(traces["ref 327"], color=colors[i], ls="--", lw=1.65,
                             label="双网关组：第二网关")
        fig.legend(*axes[0].get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(.12, .91),
                   ncol=2, frameon=False, fontsize=10)
        for axis, title, unit in zip(axes, ("链路实际发出了多少数据", "链路发送前积压了多少数据",
                                           "网关给自己负责的流量设定的参考速率（固定权重组）"),
                                    ("吞吐（Gb/s）", "积压（MiB）", "参考速率（Gb/s）")):
            axis.set(xlim=(0, 115), ylim=(0, None), ylabel=unit)
            axis.set_title(title, loc="left", fontsize=11)
            axis.grid(axis="y", alpha=.19)
            axis.axvline(15, color="#777777", ls="--", lw=.9)
        axes[0].axhline(200, color="#555555", lw=.7, alpha=.5)
        axes[0].text(15.6, 17, "第二批流开始", fontsize=9, color="#555555")
        axes[2].legend(loc="upper right", fontsize=9, frameon=False)
        axes[2].set_xlabel("从第一批流开始算起的时间（ms）")
        fig.text(.13, .025, "未注明的组固定权重为 1。发送时间取整使饱和吞吐读数略高于名义容量。", fontsize=9)
        save_svg(fig, output / "shared-bottleneck.svg")
    if {"path-both", "path-busy"} <= grouped.keys():
        fig, axes = plt.subplots(3, 1, figsize=(9.1, 8.0), sharex=True)
        fig.subplots_adjust(left=.13, right=.97, top=.81, bottom=.10, hspace=.43)
        fig.suptitle("去同一目的地的两条路共用一个参考速率", x=.13, ha="left", y=.984, fontsize=18)
        fig.text(.13, .927, "CERNET 北京 → 石家庄  |  只给直达路加背景流量", fontsize=11)
        for case, label, ls in (("path-both", "无背景流量", "--"), ("path-busy", "有背景流量", "-")):
            _, traces = grouped[case]
            for key, route, color in (("short RDMA", "直达", colors[0]), ("long RDMA", "经天津", colors[1])):
                axes[0].plot(traces[key], color=color, ls=ls, lw=1.7, label=f"{route} · {label}")
            if case == "path-busy":
                axes[1].plot(traces["short queue"], color=colors[0], lw=1.7, label="直达链路")
                detour = traces["long queue"].combine(traces["long second hop queue"], max)
                axes[1].plot(detour, color=colors[1], ls="--", lw=1.7, label="经天津两段中积压较大的一段")
            axes[2].plot(traces["ref 36"], color=colors[4], ls=ls, lw=1.7, label=label)
        fig.legend(*axes[0].get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(.12, .903),
                   ncol=2, frameon=False, fontsize=10)
        for axis, title, unit in zip(axes, ("两条路上的实验流吞吐", "加入背景流后的骨干出端口积压",
                                           "北京网关为去石家庄的所有实验流设定的参考速率"),
                                    ("吞吐（Gb/s）", "积压（MiB）", "参考速率（Gb/s）")):
            axis.set(xlim=(0, 50), ylim=(0, None), ylabel=unit)
            axis.set_title(title, loc="left", fontsize=11)
            axis.grid(axis="y", alpha=.19)
            axis.axvline(25, color="#777777", ls="--", lw=.9)
        axes[0].text(25.5, 6, "直达路加入背景流", fontsize=9, color="#555555")
        axes[1].legend(loc="upper left", fontsize=9, frameon=False)
        axes[2].legend(loc="upper left", fontsize=9, frameon=False)
        axes[2].set_xlabel("从实验流开始算起的时间（ms）")
        save_svg(fig, output / "two-paths.svg")


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
