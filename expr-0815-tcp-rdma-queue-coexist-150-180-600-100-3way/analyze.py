#!/usr/bin/env python3
"""Summarize the completed 600 Gbps TCP/RDMA q1, q3, and no-TCP runs."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REFERENCE = ROOT / "expr-0810-tcp-rdma-queue-coexist-75-90-200/analyze.py"
EXPERIMENTS = {
    "357": ROOT / "mix/output/[357]-0815-1408-rdma150-180-tcp600-100-q1",
    "358": ROOT / "mix/output/[358]-0815-1415-rdma150-180-tcp600-100-q3",
    "359": ROOT / "mix/output/[359]-0815-1415-rdma150-180-tcp600-100-no-tcp",
}


def load_reference_analyzer():
    spec = importlib.util.spec_from_file_location("tcp_rdma_reference_analyze", REFERENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reference analyzer: {REFERENCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tcp_metrics(reference, directory: Path, has_tcp: bool) -> dict[str, object]:
    if has_tcp:
        # TCP applications start at the input absolute time plus 1 ns.
        return reference.tcp_metrics(directory, sender_start_scale=1.0)
    return {
        "total": 0,
        "completed": 0,
        "missing": [],
        "offered_bytes": 0,
        "completed_bytes": 0,
        "uncompleted_bytes": 0,
        "avg_fct_s": 0.0,
        "p50_fct_s": 0.0,
        "p95_fct_s": 0.0,
        "p99_fct_s": 0.0,
        "max_fct_s": 0.0,
        "legacy_avg_fct_s": 0.0,
        "legacy_p50_fct_s": 0.0,
        "legacy_p95_fct_s": 0.0,
        "legacy_p99_fct_s": 0.0,
        "legacy_max_fct_s": 0.0,
    }


def completion_metrics(directory: Path) -> dict[str, int | float]:
    pattern = re.compile(
        r"finished so far: RDMA (\d+)/(\d+), TCP (\d+)/(\d+), Time:\+([0-9.eE+-]+)ns"
    )
    matches = pattern.findall((directory / "config.log").read_text(errors="replace"))
    if not matches:
        raise RuntimeError(f"missing final completion line in {directory / 'config.log'}")
    rdma_done, rdma_total, tcp_done, tcp_total, end_ns = matches[-1]
    return {
        "final_rdma_completed": int(rdma_done),
        "final_rdma_total": int(rdma_total),
        "final_tcp_completed": int(tcp_done),
        "final_tcp_total": int(tcp_total),
        "simulation_end_s": float(end_ns) * 1e-9,
    }


def pfc_metrics(directory: Path) -> dict[str, int]:
    pattern = re.compile(r"PFC summary: pause_triggers=(\d+), resumes=(\d+)")
    matches = pattern.findall((directory / "config.log").read_text(errors="replace"))
    if not matches:
        return {"pfc_pause_triggers": 0, "pfc_resumes": 0}
    pauses, resumes = matches[-1]
    return {"pfc_pause_triggers": int(pauses), "pfc_resumes": int(resumes)}


def drop_metrics(directory: Path) -> dict[str, int]:
    with (directory / "drop_log").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    no_rdma_tag = sum(int(row["flow_id"]) == 0xFFFFFFFF for row in rows)
    return {
        "drop_rows": len(rows),
        "drop_rows_without_rdma_flow_id": no_rdma_tag,
        "drop_rows_with_rdma_flow_id": len(rows) - no_rdma_tag,
    }


def main() -> None:
    reference = load_reference_analyzer()
    topology = json.loads((ROOT / "config/cernet_topo.txt").read_text())
    host_to_as = {
        host: as_topology["as_id"]
        for as_topology in topology["as_topologies"]
        for host in as_topology["hosts"]
    }
    dci_switches = {as_topology["dci_switch"] for as_topology in topology["as_topologies"]}
    wan_switches = set(topology["wan_switches"])

    sys.path.insert(0, str(ROOT))
    from analysis.deep_analyse import get_analyser

    rows: list[dict[str, object]] = []
    for experiment_id, directory in EXPERIMENTS.items():
        if not directory.is_dir():
            raise RuntimeError(f"missing experiment directory: {directory}")
        config = reference.read_config(directory / "config.txt")
        rdma = reference.rdma_metrics(directory, host_to_as)
        tcp = tcp_metrics(reference, directory, "TCP_FLOW_FILE" in config)

        deep_avg, deep_p99 = get_analyser(int(experiment_id)).get_fct()
        if not math.isclose(float(rdma["avg_slowdown"]), deep_avg[0], rel_tol=1e-12):
            raise AssertionError(f"experiment {experiment_id}: average slowdown mismatch")
        if not math.isclose(float(rdma["p99_slowdown"]), deep_p99[0], rel_tol=1e-12):
            raise AssertionError(f"experiment {experiment_id}: P99 slowdown mismatch")

        row: dict[str, object] = {
            "experiment_id": experiment_id,
            "directory": str(directory.relative_to(ROOT)),
            "tcp_queue_index": config.get("TCP_QUEUE_INDEX", ""),
            "message": config.get("MSG", ""),
            "has_tcp": int("TCP_FLOW_FILE" in config),
        }
        row.update(completion_metrics(directory))
        row.update(pfc_metrics(directory))
        row.update({f"rdma_{key}": value for key, value in rdma.items()})
        row.update({f"tcp_{key}": value for key, value in tcp.items() if key != "missing"})
        row["tcp_missing_ids"] = ",".join(map(str, tcp["missing"]))
        row.update(drop_metrics(directory))
        row.update(reference.auxiliary_metrics(directory))
        row.update(reference.buffer_metrics(directory, dci_switches, wan_switches))

        tcp_total = int(row["tcp_total"])
        tcp_completed = int(row["tcp_completed"])
        row["tcp_flow_completion_rate"] = tcp_completed / tcp_total if tcp_total else ""
        row["tcp_payload_completion_rate"] = (
            int(row["tcp_completed_bytes"]) / int(row["tcp_offered_bytes"])
            if int(row["tcp_offered_bytes"])
            else ""
        )
        total_offered = int(row["rdma_offered_bytes"]) + int(row["tcp_offered_bytes"])
        total_completed = int(row["rdma_offered_bytes"]) + int(row["tcp_completed_bytes"])
        row["total_offered_bytes"] = total_offered
        row["total_completed_bytes"] = total_completed
        row["total_payload_completion_rate"] = total_completed / total_offered
        row["rdma_offered_share"] = int(row["rdma_offered_bytes"]) / total_offered
        row["tcp_offered_share"] = int(row["tcp_offered_bytes"]) / total_offered
        rows.append(row)

    output = HERE / "summary.csv"
    keys = sorted({key for row in rows for key in row})
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    for row in rows:
        print(
            f"exp{row['experiment_id']}: queue={row['tcp_queue_index']} "
            f"RDMA={row['rdma_total']}/{row['final_rdma_total']} "
            f"avg-slowdown={float(row['rdma_avg_slowdown']):.6f} "
            f"TCP={row['tcp_completed']}/{row['tcp_total']} "
            f"TCP-avg-FCT={float(row['tcp_avg_fct_s']):.6f}s "
            f"drop-log={row['drop_rows']}"
        )
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
