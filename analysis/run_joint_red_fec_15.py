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


def _list_output_dirs():
    if not OUTPUT_ROOT.exists():
        return set()
    return {p.name for p in OUTPUT_ROOT.iterdir() if p.is_dir()}


@dataclass(frozen=True)
class Combo:
    label: str
    red_kmin: int
    red_kmax: int
    red_pmax: float
    red_wq: float
    fec_n: int


@dataclass
class Result:
    label: str
    red_kmin: int
    red_kmax: int
    red_pmax: float
    red_wq: float
    fec_n: int
    output_dir: str = ""
    total_flows: int = 0
    completed_flows: int = 0
    completion_rate: float = 0.0
    avg_fct: float = 0.0
    p99_fct: float = 0.0
    avg_ratio_vs_baseline: float = 0.0
    p99_ratio_vs_baseline: float = 0.0


def _run_one(combo: Combo, args, skip_build: bool):
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
        str(combo.fec_n),
        "--stdout",
        "1",
        "--msg",
        combo.label,
    ]
    if skip_build:
        cmd += ["--skip-build", "1"]
    cmd += [
        "--extra",
        "WAN_RED_ENABLE=TRUE",
        "--extra",
        f"WAN_RED_KMIN={combo.red_kmin}",
        "--extra",
        f"WAN_RED_KMAX={combo.red_kmax}",
        "--extra",
        f"WAN_RED_PMAX={combo.red_pmax}",
        "--extra",
        f"WAN_RED_WQ={combo.red_wq}",
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
    return Result(
        label=combo.label,
        red_kmin=combo.red_kmin,
        red_kmax=combo.red_kmax,
        red_pmax=combo.red_pmax,
        red_wq=combo.red_wq,
        fec_n=combo.fec_n,
        output_dir=str(out_dir),
        total_flows=metrics["total_flows"],
        completed_flows=metrics["completed_flows"],
        completion_rate=metrics["completion_rate"],
        avg_fct=metrics["avg_fct"],
        p99_fct=metrics["p99_fct"],
    )


def _run_baseline(args, skip_build: bool):
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
        "0",
        "--stdout",
        "1",
        "--msg",
        "baseline",
    ]
    if skip_build:
        cmd += ["--skip-build", "1"]
    subprocess.run(cmd, cwd=ROOT, check=True)

    after = _list_output_dirs()
    new_dirs = sorted(after - before)
    if len(new_dirs) != 1:
        raise RuntimeError(f"expected exactly one new output dir for baseline, got {new_dirs}")

    out_dir = OUTPUT_ROOT / new_dirs[0]
    flow_output = out_dir / "flow_output"
    if not flow_output.exists():
        raise FileNotFoundError(flow_output)

    metrics = _load_flow_metrics(flow_output)
    return metrics, str(out_dir)


def _write_reports(report_dir: Path, results: list[Result], baseline: dict):
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / "results.csv"
    md_path = report_dir / "results.md"
    json_path = report_dir / "results.json"

    rows = []
    for r in results:
        row = asdict(r)
        row["avg_ratio_vs_baseline"] = r.avg_fct / baseline["avg_fct"] if baseline["avg_fct"] else 0.0
        row["p99_ratio_vs_baseline"] = r.p99_fct / baseline["p99_fct"] if baseline["p99_fct"] else 0.0
        rows.append(row)

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    best = min(results, key=lambda r: (r.avg_fct, r.p99_fct, -r.completion_rate))

    lines = []
    lines.append("# WAN RED/FEC 15 组联调结果")
    lines.append("")
    lines.append(f"- baseline avg FCT: {baseline['avg_fct']:.6f}s")
    lines.append(f"- baseline p99 FCT: {baseline['p99_fct']:.6f}s")
    lines.append(f"- best observed: {best.label}")
    lines.append("")
    lines.append("| label | fec | red_kmin | red_kmax | red_pmax | red_wq | completion | avg_fct | p99_fct | avg_ratio | p99_ratio |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in sorted(results, key=lambda x: (x.avg_fct, x.p99_fct)):
        avg_ratio = r.avg_fct / baseline["avg_fct"] if baseline["avg_fct"] else 0.0
        p99_ratio = r.p99_fct / baseline["p99_fct"] if baseline["p99_fct"] else 0.0
        lines.append(
            "| {label} | {fec_n} | {red_kmin} | {red_kmax} | {red_pmax:.4f} | {red_wq:.6f} | {completion_rate:.2%} | {avg_fct:.6f} | {p99_fct:.6f} | {avg_ratio:.4f} | {p99_ratio:.4f} |".format(
                **asdict(r),
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
    parser.add_argument("--flow", default="w-dynamic-150-200-1000")
    parser.add_argument("--simul_time", type=float, default=0.01)
    parser.add_argument("--topo", default="cernet_topo")
    parser.add_argument("--wan_cc_mode", type=int, default=1)
    parser.add_argument("--skip-build", type=int, default=1)
    parser.add_argument("--baseline-output", default="")
    parser.add_argument("--report-name", default="")
    args = parser.parse_args()

    red_configs = [
        (131072, 1048576, 0.02, 0.001),
        (131072, 2097152, 0.05, 0.001),
        (262144, 1048576, 0.05, 0.002),
        (262144, 2097152, 0.05, 0.002),
        (524288, 2097152, 0.10, 0.005),
    ]
    fec_values = [0, 4, 10]
    combos = []
    for idx, (kmin, kmax, pmax, wq) in enumerate(red_configs, start=1):
        for fec_n in fec_values:
            combos.append(
                Combo(
                    label=f"joint-r{idx}-fec{fec_n}",
                    red_kmin=kmin,
                    red_kmax=kmax,
                    red_pmax=pmax,
                    red_wq=wq,
                    fec_n=fec_n,
                )
            )

    if not bool(args.skip_build):
        subprocess.run(["./waf"], cwd=ROOT, check=True)

    ts = args.report_name or datetime.now().strftime("wan-red-fec-15-%Y%m%d-%H%M%S")
    report_dir = REPORT_ROOT / ts
    if args.baseline_output:
        baseline_flow = Path(args.baseline_output) / "flow_output"
        if not baseline_flow.exists():
            raise SystemExit(f"baseline flow_output not found: {baseline_flow}")
        baseline = _load_flow_metrics(baseline_flow)
        baseline_dir = args.baseline_output
    else:
        baseline, baseline_dir = _run_baseline(args, skip_build=bool(args.skip_build))

    results = []
    for i, combo in enumerate(combos, start=1):
        print(f"[{i:02d}/15] {combo.label}")
        result = _run_one(combo, args, skip_build=bool(args.skip_build))
        result.avg_ratio_vs_baseline = result.avg_fct / baseline["avg_fct"] if baseline["avg_fct"] else 0.0
        result.p99_ratio_vs_baseline = result.p99_fct / baseline["p99_fct"] if baseline["p99_fct"] else 0.0
        results.append(result)

    _write_reports(report_dir, results, baseline)


if __name__ == "__main__":
    main()
