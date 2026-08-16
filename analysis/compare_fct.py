from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def _load_flow_output(path: Path):
    data = json.loads(path.read_text())
    completed = [x for x in data if x.get("finish_time", 0) > x.get("start_time", 0)]
    fcts = [x["finish_time"] - x["start_time"] for x in completed]
    return data, completed, fcts


def _summary(label: str, path: Path):
    data, completed, fcts = _load_flow_output(path)
    all_cnt = len(data)
    done_cnt = len(completed)
    comp_rate = done_cnt / all_cnt if all_cnt else 0.0
    avg_fct = mean(fcts) if fcts else 0.0
    p99_fct = sorted(fcts)[max(int(len(fcts) * 0.99) - 1, 0)] if fcts else 0.0
    print(f"{label}")
    print(f"  flows: {all_cnt}")
    print(f"  completed: {done_cnt} ({comp_rate:.2%})")
    print(f"  avg_fct: {avg_fct:.6f}s")
    print(f"  p99_fct: {p99_fct:.6f}s")
    return {"all": all_cnt, "done": done_cnt, "avg": avg_fct, "p99": p99_fct}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if len(args.paths) < 2:
        raise SystemExit("need at least two experiments")

    rows = []
    for idx, raw in enumerate(args.paths):
        path = Path(raw)
        if path.is_dir():
            path = path / "flow_output"
        label = "baseline" if idx == 0 else f"exp{idx}"
        rows.append((label, _summary(label, path)))

    base = rows[0][1]
    for label, row in rows[1:]:
        if base["avg"]:
            print(f"{label}.avg_fct_ratio: {row['avg'] / base['avg']:.4f}")
        if base["p99"]:
            print(f"{label}.p99_fct_ratio: {row['p99'] / base['p99']:.4f}")
        print(f"{label}.completion_delta: {row['done'] - base['done']}")


if __name__ == "__main__":
    main()
