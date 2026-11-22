"""Summarize ACK mirror behavior at the two DC3 gateways."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
from statistics import median, quantiles


GATEWAYS = {147, 327}
CORE_ROUTER = 226
START = 2_000_000_000
BIN = 500_000
EPOCH = 1_000_000
ORIGINAL = {"sample", "miss", "invalid"}


def analyze(folder):
    case = folder.name.split("-am1121-scale-")[-1]
    run_id = int(re.match(r"\[(\d+)\]", folder.name)[1])
    log = (folder / "config.log").read_text()
    assert "Simulator is enforced to be finished" in log, f"Run {run_id} is incomplete"
    config = dict(line.split(maxsplit=1) for line in (folder / "config.txt").read_text().splitlines()
                  if len(line.split()) > 1)
    topology = json.loads(Path(config["TOPOLOGY_FILE"]).read_text())
    hosts = {h: site["as_id"] for site in topology["as_topologies"] for h in site["hosts"]}
    flows = {f["flow_id"]: f for f in json.loads((folder / "flow_output").read_text())}
    dcis = {site["dci_switch"] for site in topology["as_topologies"]} | GATEWAYS
    pinned = {(path[0], path[-1]): tuple(g for g in path if g in dcis)
              for path in topology["pinned_wan_paths"]}
    events, mirror_bins, active_epochs, sampled_epochs = Counter(), Counter(), set(), set()
    original_bytes = mirror_bytes = 0
    delays = []
    crossed_epoch = 0
    with (folder / "rtt_match_log").open() as stream:
        reader = csv.reader(stream)
        next(reader)
        for t, gw, fid, _, _, event, sample, size, arrival, stamp in reader:
            gw = int(gw)
            if gw not in GATEWAYS:
                continue
            flow = flows[int(fid)]
            src, dst = flow["src"], flow["dst"]
            assert hosts[src] == 3 and hosts[dst] != 3
            events[event] += 1
            t, size, arrival = int(t), int(size), int(arrival)
            if event in ORIGINAL | {"mirror_send"}:
                assert gw == pinned[dst, src][-1] and t == arrival
            elif event.startswith("mirror_"):
                assert gw != pinned[dst, src][-1]
                if event == "mirror_sample":
                    assert gw == pinned[src, dst][0]
            else:
                assert gw == pinned[src, dst][0]
            if event in ORIGINAL:
                original_bytes += size
            if event == "mirror_send":
                mirror_bytes += size
                mirror_bins[gw, (t - START) // BIN] += size
            if event in {"sample", "mirror_sample"}:
                sampled_epochs.add((gw, hosts[dst], (t - START) // EPOCH))
            if event == "mirror_sample":
                delays.append(t - arrival)
                crossed_epoch += t // EPOCH != arrival // EPOCH
    wan_tx = Counter()
    with (folder / "link_utilization").open() as stream:
        reader = csv.reader(stream)
        next(reader)
        for t, src, dst, fid, size in reader:
            t, src, dst, fid, size = map(int, (t, src, dst, fid, size))
            if src in GATEWAYS and dst == CORE_ROUTER:
                wan_tx[src] += size
                destination = hosts[flows[fid]["dst"]]
                # Link monitor logs the right edge of the elapsed 0.5 ms bin.
                active_epochs.add((src, destination, (t - START - 1) // EPOCH))
    originals = sum(events[event] for event in ORIGINAL)
    delivered = sum(events[event] for event in {"mirror_sample", "mirror_miss", "mirror_invalid"})
    assert delivered <= events["mirror_send"] and len(wan_tx) == 2
    local_fct = [1000 * (f["finish_time"] - f["start_time"]) for f in flows.values()
                 if hosts[f["src"]] == 3 and hosts[f["dst"]] != 3]
    return {
        "id": run_id, "case": case, "flows": len(flows), "unfinished": log.count("Not Finish!"),
        "dc3_wan_flows": len(local_fct), "events": dict(sorted(events.items())),
        "original_acks": originals, "original_ack_bytes": original_bytes,
        "sample_pct_of_ack": 100 * (events["sample"] + events["mirror_sample"]) / originals,
        "mirror_link_unreceived_copies": events["mirror_send"] - delivered,
        "mirror_bytes": mirror_bytes, "dc3_wan_data_bytes_by_gateway": dict(wan_tx),
        "mirror_pct_of_dc3_wan_data_bytes": 100 * mirror_bytes / sum(wan_tx.values()),
        "mirror_peak_mbps_0p5ms_by_sending_gateway": {
            g: 8 * max((v for (gw, _), v in mirror_bins.items() if gw == g), default=0) / 500
            for g in sorted(GATEWAYS)},
        "mirror_extra_delay_median_us": median(delays) / 1000 if delays else None,
        "mirror_extra_delay_max_us": max(delays) / 1000 if delays else None,
        "mirror_samples_crossing_epoch": crossed_epoch,
        "active_gateway_destination_epochs": len(active_epochs),
        "active_gateway_destination_epochs_with_samples": len(active_epochs & sampled_epochs),
        "dc3_wan_fct_p50_ms": median(local_fct),
        "dc3_wan_fct_p99_ms": quantiles(local_fct, n=100, method="inclusive")[98],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps([analyze(folder) for folder in args.folders], indent=2))
