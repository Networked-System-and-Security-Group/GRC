from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "mix" / "output"
REPORT_ROOT = ROOT / "analysis" / "reports"


def _parse_csv_numbers(raw: str, cast):
    values = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        values.append(cast(item))
    if not values:
        raise ValueError(f"empty value list: {raw}")
    return values


def _list_output_dirs():
    if not OUTPUT_ROOT.exists():
        return set()
    return {p.name for p in OUTPUT_ROOT.iterdir() if p.is_dir()}


def _load_flow_metrics(flow_output: Path):
    data = json.loads(flow_output.read_text())
    completed = [x for x in data if x.get("finish_time", 0) > x.get("start_time", 0)]
    fcts = [x["finish_time"] - x["start_time"] for x in completed]
    total = len(data)
    done = len(completed)
    return {
        "total_flows": total,
        "completed_flows": done,
        "completion_rate": done / total if total else 0.0,
        "avg_fct": mean(fcts) if fcts else 0.0,
        "p99_fct": sorted(fcts)[max(int(len(fcts) * 0.99) - 1, 0)] if fcts else 0.0,
    }


@dataclass
class Experiment:
    label: str
    phase: str
    fec_n: int
    red_enable: bool
    red_kmin: int
    red_kmax: int
    red_pmax: float
    red_wq: float
    output_dir: str = ""
    flow_output: str = ""
    total_flows: int = 0
    completed_flows: int = 0
    completion_rate: float = 0.0
    avg_fct: float = 0.0
    p99_fct: float = 0.0
    avg_ratio_vs_baseline: float = 0.0
    p99_ratio_vs_baseline: float = 0.0


def _run_one(exp: Experiment, args, skip_build: bool):
    before = _list_output_dirs()
    cmd = [
        sys.executable,
        "run.py",
        "--topo",
        args.topo,
        "--my_flow",
        args.flow,
        "--tcp_flow",
        "",
        "--simul_time",
        str(args.simul_time),
        "--wan_cc_mode",
        str(args.wan_cc_mode),
        "--fec-n",
        str(exp.fec_n),
        "--stdout",
        "1",
        "--msg",
        exp.label,
    ]
    if skip_build:
        cmd += ["--skip-build", "1"]
    if exp.red_enable:
        cmd += [
            "--extra",
            "WAN_RED_ENABLE=TRUE",
            "--extra",
            f"WAN_RED_KMIN={exp.red_kmin}",
            "--extra",
            f"WAN_RED_KMAX={exp.red_kmax}",
            "--extra",
            f"WAN_RED_PMAX={exp.red_pmax}",
            "--extra",
            f"WAN_RED_WQ={exp.red_wq}",
        ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    after = _list_output_dirs()
    new_dirs = sorted(after - before)
    if len(new_dirs) != 1:
        raise RuntimeError(f"expected exactly one new output dir, got {new_dirs}")

    out_dir = OUTPUT_ROOT / new_dirs[0]
    flow_output = out_dir / "flow_output"
    if not flow_output.exists():
        raise FileNotFoundError(flow_output)

    metrics = _load_flow_metrics(flow_output)
    exp.output_dir = str(out_dir)
    exp.flow_output = str(flow_output)
    exp.total_flows = metrics["total_flows"]
    exp.completed_flows = metrics["completed_flows"]
    exp.completion_rate = metrics["completion_rate"]
    exp.avg_fct = metrics["avg_fct"]
    exp.p99_fct = metrics["p99_fct"]


def _write_reports(report_dir: Path, experiments: list[Experiment], baseline: Experiment):
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / "results.csv"
    md_path = report_dir / "results.md"
    json_path = report_dir / "results.json"

    rows = []
    for exp in experiments:
        row = asdict(exp)
        row["avg_ratio_vs_baseline"] = exp.avg_fct / baseline.avg_fct if baseline.avg_fct else 0.0
        row["p99_ratio_vs_baseline"] = exp.p99_fct / baseline.p99_fct if baseline.p99_fct else 0.0
        rows.append(row)

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    ranked = sorted(
        experiments[1:],
        key=lambda e: (e.avg_fct, e.p99_fct, -e.completion_rate),
    )
    best = ranked[0] if ranked else baseline

    lines = []
    lines.append("# WAN RED/FEC sensitivity sweep")
    lines.append("")
    lines.append(f"- baseline avg FCT: {baseline.avg_fct:.6f}s")
    lines.append(f"- baseline p99 FCT: {baseline.p99_fct:.6f}s")
    lines.append(f"- best observed: {best.label}")
    lines.append("")
    lines.append("| label | phase | fec | red_kmin | red_kmax | red_pmax | red_wq | completion | avg_fct | p99_fct | avg_ratio | p99_ratio |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for exp in sorted(experiments, key=lambda e: (e.phase, e.avg_fct, e.p99_fct)):
        avg_ratio = exp.avg_fct / baseline.avg_fct if baseline.avg_fct else 0.0
        p99_ratio = exp.p99_fct / baseline.p99_fct if baseline.p99_fct else 0.0
        lines.append(
            "| {label} | {phase} | {fec_n} | {red_kmin} | {red_kmax} | {red_pmax:.4f} | {red_wq:.6f} | {completion_rate:.2%} | {avg_fct:.6f} | {p99_fct:.6f} | {avg_ratio:.4f} | {p99_ratio:.4f} |".format(
                **asdict(exp),
                avg_ratio=avg_ratio,
                p99_ratio=p99_ratio,
            )
        )
    md_path.write_text("\n".join(lines) + "\n")

    print(f"wrote: {csv_path}")
    print(f"wrote: {md_path}")
    print(f"wrote: {json_path}")
    print(f"best: {best.label} avg={best.avg_fct:.6f}s p99={best.p99_fct:.6f}s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow", default="w-dynamic-150-200-5000")
    parser.add_argument("--simul_time", type=float, default=0.02)
    parser.add_argument("--topo", default="cernet_topo")
    parser.add_argument("--wan_cc_mode", type=int, default=1)
    parser.add_argument("--report-name", default="")
    parser.add_argument("--red-kmin", default="131072,262144,524288")
    parser.add_argument("--red-kmax", default="1048576,2097152,4194304")
    parser.add_argument("--red-pmax", default="0.02,0.05,0.1")
    parser.add_argument("--red-wq", default="0.001,0.002,0.005")
    parser.add_argument("--fec-n", default="0,2,4,8,10")
    parser.add_argument("--skip-build", type=int, default=1)
    args = parser.parse_args()

    kmin_values = _parse_csv_numbers(args.red_kmin, int)
    kmax_values = _parse_csv_numbers(args.red_kmax, int)
    pmax_values = _parse_csv_numbers(args.red_pmax, float)
    wq_values = _parse_csv_numbers(args.red_wq, float)
    fec_values = _parse_csv_numbers(args.fec_n, int)

    if not bool(args.skip_build):
        subprocess.run(["./waf"], cwd=ROOT, check=True)

    ts = args.report_name or datetime.now().strftime("wan-red-fec-sweep-%Y%m%d-%H%M%S")
    report_dir = REPORT_ROOT / ts
    report_dir.mkdir(parents=True, exist_ok=True)

    experiments: list[Experiment] = []

    baseline = Experiment(
        label="baseline",
        phase="baseline",
        fec_n=0,
        red_enable=False,
        red_kmin=0,
        red_kmax=0,
        red_pmax=0.0,
        red_wq=0.0,
    )
    print("[1] baseline")
    _run_one(baseline, args, skip_build=bool(args.skip_build))
    experiments.append(baseline)

    red_default = {
        "kmin": 131072,
        "kmax": 1048576,
        "pmax": 0.1,
        "wq": 0.002,
    }
    red_sweeps = [
        ("kmin", kmin_values),
        ("kmax", kmax_values),
        ("pmax", pmax_values),
        ("wq", wq_values),
    ]

    idx = 2
    best_red = None
    for key, values in red_sweeps:
        for value in values:
            cfg = dict(red_default)
            cfg[key] = value
            exp = Experiment(
                label=f"red-{key}-{value}",
                phase=f"red-{key}",
                fec_n=0,
                red_enable=True,
                red_kmin=int(cfg["kmin"]),
                red_kmax=int(cfg["kmax"]),
                red_pmax=float(cfg["pmax"]),
                red_wq=float(cfg["wq"]),
            )
            print(f"[{idx}] {exp.label}")
            idx += 1
            _run_one(exp, args, skip_build=bool(args.skip_build))
            experiments.append(exp)
            if (
                best_red is None
                or (exp.avg_fct, exp.p99_fct, -exp.completion_rate)
                < (best_red.avg_fct, best_red.p99_fct, -best_red.completion_rate)
            ):
                best_red = exp

    if best_red is None:
        best_red = baseline

    for fec_n in fec_values:
        exp = Experiment(
            label=f"fec-{fec_n}",
            phase="fec-on-best-red",
            fec_n=int(fec_n),
            red_enable=True,
            red_kmin=best_red.red_kmin,
            red_kmax=best_red.red_kmax,
            red_pmax=best_red.red_pmax,
            red_wq=best_red.red_wq,
        )
        print(f"[{idx}] {exp.label}")
        idx += 1
        _run_one(exp, args, skip_build=bool(args.skip_build))
        experiments.append(exp)

    _write_reports(report_dir, experiments, baseline)


if __name__ == "__main__":
    main()
