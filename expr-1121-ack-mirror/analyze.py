import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
from statistics import mean, median


EPOCH_NS = 1_000_000
START_NS = 2_000_000_000
GATEWAYS = (147, 327)
WRITES = {"write", "refresh", "occupied"}
ARRIVALS = {"sample", "miss", "invalid"}
COPIES = {"mirror_sample", "mirror_miss", "mirror_invalid"}


def rows(folder, name):
    with (folder / name).open() as source:
        yield from csv.DictReader(source)


def analyze(folder):
    run_id, case = re.fullmatch(r"\[(\d+)\].*-am1121-(.+)-s\d+", folder.name).groups()
    config = dict(line.split(maxsplit=1) for line in (folder / "config.txt").read_text().splitlines()
                  if len(line.split()) > 1)
    timestamp_mode = config["GSCC_ACK_TS"] == "TRUE"
    topo = json.loads(Path(config["TOPOLOGY_FILE"]).read_text())
    dci = {147, 327, 36}
    paths = topo["pinned_wan_paths"]
    forward = {i: next(node for node in paths[2*i] if node in dci) for i in range(4)}
    returning = {i: next(node for node in reversed(paths[2*i+1]) if node in dci) for i in range(4)}
    originals, copies, slots = {}, Counter(), {}
    counts = Counter()
    sample_values, mirror_delays, late_epochs = [], [], Counter()
    mirror_errors, mirror_natural, first_sample = [], [], {}
    bytes_sent = 0
    delivered_bins = Counter()
    tested = set()
    for row in rows(folder, "rtt_match_log"):
        event = row.pop("status")
        t, gw, flow, seq, slot, sample, size, arrival, stamp = map(int, row.values())
        key = (flow, seq)
        counts[event] += 1
        if event in WRITES:
            assert gw == forward[flow], (run_id, event, flow, gw)
            if event != "occupied":
                slots[gw, slot] = (key, t)
                tested.add(key)
        elif event in ARRIVALS:
            assert gw == returning[flow] and arrival == t
            originals[flow, seq, t] = (gw, stamp, size)
        elif event == "mirror_send":
            assert originals[flow, seq, arrival] == (gw, stamp, size)
            copies[flow, seq, arrival] += 1
            bytes_sent += size
        elif event in COPIES:
            original_gw, original_stamp, original_size = originals[flow, seq, arrival]
            assert gw != original_gw and original_stamp == stamp and original_size == size
            copies[flow, seq, arrival] -= 1
            assert copies[flow, seq, arrival] == 0
            delivered_bins[original_gw, arrival // 500_000] += size
        else:
            raise ValueError(event)
        if event.endswith("sample") or event in ("invalid", "mirror_invalid"):
            matched, written = slots.pop((gw, slot))
            assert matched == key, (run_id, key, matched, event)
            if event.endswith("sample"):
                expected = (stamp if timestamp_mode else arrival) - written
                assert sample == expected, (run_id, sample, expected)
                sample_values.append(sample)
                first_sample.setdefault(gw, (t - START_NS) / 1e6)
                if event == "mirror_sample":
                    mirror_delays.append(t - arrival)
                    late_epochs[(t // EPOCH_NS) - (arrival // EPOCH_NS)] += 1
                    mirror_errors.append(sample - expected)
                    mirror_natural.append(t - written - (arrival - written))
    unfinished = sum(copies.values())
    assert unfinished == 0, (run_id, unfinished)
    flows = json.loads((folder / "flow_output").read_text())
    assert len(flows) == 4
    fct = [(flow["finish_time"] - flow["start_time"]) * 1000 for flow in flows]
    last_end = min((flow["finish_time"] - 2) * 1000 for flow in flows)
    rtt_rows = [r for r in rows(folder, "rtt_log") if int(r["switch_id"]) in GATEWAYS
                and int(r["dst_as"]) == 0 and START_NS + 8*EPOCH_NS <= int(r["timestamp_ns"]) < START_NS + 20*EPOCH_NS]
    ref_rows = [float(r["ref_rate"]) * 8e-9 for r in rows(folder, "rate_monitor")
                if int(r["switch_id"]) in GATEWAYS and int(r["dst_as"]) == 0
                and START_NS + 8*EPOCH_NS <= int(r["timestamp_ns"]) < START_NS + 20*EPOCH_NS]
    if case.startswith("long-"):
        assert last_end > 20 and len(rtt_rows) == len(ref_rows) == 24, (run_id, last_end)
    return {
        "id": int(run_id), "case": case, "finished": len(flows), "logged_drops": sum(1 for _ in rows(folder, "drop_log")),
        "events": dict(counts), "unique_written": len(tested), "mirror_bytes": bytes_sent,
        "mirror_pct_rdma_payload": 100 * bytes_sent / sum(flow["fsize"] for flow in flows),
        "peak_mirror_direction_mbps_0p5ms": max(delivered_bins.values(), default=0) * 8 / 500,
        "sample_median_ms": median(sample_values)/1e6 if sample_values else None,
        "mirror_delay_median_us": median(mirror_delays)/1e3 if mirror_delays else None,
        "mirror_delay_max_us": max(mirror_delays)/1e3 if mirror_delays else None,
        "mirror_sample_error_max_ns": max(map(abs, mirror_errors)) if mirror_errors else None,
        "legacy_without_arrival_stamp_extra_us": median(mirror_natural)/1e3 if mirror_natural else None,
        "epochs_late": dict(late_epochs), "first_sample_ms": first_sample,
        "fct_ms_mean": mean(fct), "fct_ms_max": max(fct), "first_finish_ms": last_end,
        "fct_ms_by_flow": fct,
        "active_epochs_with_samples_8_20ms": sum(r["measured_rtt_ms"].lower() != "nan" for r in rtt_rows),
        "gateway_epochs_8_20ms": len(rtt_rows), "mean_ref_gbps_per_gateway_8_20ms": mean(ref_rows) if ref_rows else None,
        "cnp": sum(1 for r in rows(folder, "cnp_log") if int(r["switch_id"]) in GATEWAYS),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", type=int, nargs="+")
    args = parser.parse_args()
    output = Path("mix/output")
    folders = [next(path for path in output.glob(f"[[]{i}]-*am1121*")) for i in args.ids]
    summary = [analyze(folder) for folder in folders]
    by_case = {row["case"]: row for row in summary}
    for prefix in ("same", "half", "cross"):
        if {f"{prefix}-off", f"{prefix}-on"} <= by_case.keys():
            off, on = (by_case[f"{prefix}-{suffix}"] for suffix in ("off", "on"))
            assert off["fct_ms_by_flow"] == on["fct_ms_by_flow"]
            recovered = on["events"].get("mirror_sample", 0)
            assert recovered + off["events"].get("sample", 0) == off["unique_written"], prefix
    print(json.dumps(summary, indent=2, allow_nan=False))
