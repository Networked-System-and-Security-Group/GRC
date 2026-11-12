#!/usr/bin/env python3
"""按 matrix.yaml 生成/执行整套实验命令。

**plan 是唯一真相**：experiments.txt 是它的渲染，`all` 是它的执行。
所以三者的参数不可能不一致——这正是以前"文档和实际跑的对不上"的根因。

子命令：
    plan   打印完整命令清单（默认；`--out experiments.txt` 写文件）
    build  只编译所有版本（每档一个 builds/<tag>/ 目录）
    deploy 只部署某一个版本
    all    全流程：编译 → 部署 → 逐点打流 → 静默累计快照落 CSV

常用筛选：
    --only-config b256-s16-w0-v2,b256-s16-w16-v2
    --only-sweep unlimited
    --limit 3            # 每个 sweep 只跑前 3 个点（先冒烟）
    --dry-run

例：
    python3 scripts/matrix.py plan --out experiments.txt
    python3 scripts/matrix.py all --only-sweep unlimited
    python3 scripts/matrix.py all --only-config b256-s16-w0-v2 --limit 2 --dry-run
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from common import REPO_ROOT, emit, load_matrix

PY = "python3"
SCRIPTS = "scripts"


def _script(name: str) -> list[str]:
    """命令前缀：可执行文件 + 脚本（分开成两个元素，shlex 才不会加引号）。"""
    return [PY, f"{SCRIPTS}/{name}"]


def build_plan(matrix: dict, only_configs: list[str] | None,
               only_sweeps: list[str] | None, limit: int | None,
               offset_scan: str, force: bool = False,
               reps: int = 1) -> list[dict]:
    env = matrix.get("env", {})
    csv_path = env.get("csv", "results/measurements.csv")
    rawdir = env.get("rawdir", "results/raw")
    settle = env.get("settle_s", 7)
    sweeps = matrix["sweeps"]

    plan: list[dict] = []
    configs = matrix["p4"]
    if only_configs:
        configs = [c for c in configs if c["tag"] in only_configs]
        missing = set(only_configs) - {c["tag"] for c in configs}
        if missing:
            raise SystemExit(f"未知 config: {sorted(missing)}")

    for cfg in configs:
        tag, buckets, slots, window = cfg["tag"], cfg["buckets"], cfg["slots"], cfg["window"]
        plan.append({
            "kind": "build", "tag": tag, "desc": cfg.get("desc", ""),
            "cmd": [*_script("build.py"), "--buckets", str(buckets),
                    "--slots", str(slots), "--window", str(window), "--tag", tag]
                   + (["--force"] if force else []),
        })

        for sname in cfg.get("sweeps", ["unlimited"]):
            if only_sweeps and sname not in only_sweeps:
                continue
            spec = sweeps[sname]
            flows_list = spec["flows"]
            size = spec.get("size", 65536)

            if sname == "unlimited":
                points = [
                    {"iters": iters, "flows": q}
                    for iters in spec["iters"] for q in flows_list
                ]
            elif sname == "rate":
                points = [
                    {"rate": r, "flows": q, "duration": spec["duration_s"]}
                    for r in spec["rates_gbps"] for q in flows_list
                ]
            else:
                raise SystemExit(f"未知 sweep: {sname}")

            if limit:
                points = points[:limit]

            for pt in points:
                cmd = [*_script("run.py"), "--config", tag, "--flows", str(pt["flows"]),
                       "--size", str(size), "--settle", str(settle),
                       "--csv", csv_path, "--rawdir", rawdir]
                if "iters" in pt:
                    cmd += ["--iters", str(pt["iters"])]
                if "duration" in pt:
                    cmd += ["--duration", str(pt["duration"])]
                if "rate" in pt:
                    cmd += ["--rate-gbps", str(pt["rate"])]
                # Preserve repetition identity; no median hides a failed trial.
                for rep in range(1, max(reps, 1)+1):
                    plan.append({
                        "kind": "run", "tag": tag, "sweep": sname,
                        "flows": pt["flows"], "rate": pt.get("rate"),
                        "iters": pt.get("iters"), "duration": pt.get("duration"), "rep": rep, "cmd": list(cmd)+["--rep",str(rep)],
                    })
    return plan


def render(plan: list[dict], matrix: dict, argv0: str) -> str:
    n_cfg = len({p["tag"] for p in plan})
    n_run = sum(1 for p in plan if p["kind"] == "run")
    lines = [
        "# " + "=" * 76,
        "# GSCC ACK 实验命令（自动生成，别手改）",
        f"#   生成命令： {argv0} plan --out experiments.txt",
        "#   矩阵来源： matrix.yaml",
        f"#   版本数：   {n_cfg}",
        f"#   实验点数： {n_run}",
        "#",
        "# 执行方式（任选）：",
        "#   1) 直接照抄下面的命令，一条一条跑",
        "#   2) python3 scripts/matrix.py all                      # 全跑",
        "#   3) python3 scripts/matrix.py all --only-sweep unlimited",
        "#   4) python3 scripts/matrix.py all --limit 2 --dry-run  # 先看一眼",
        "#",
        "# 每次重复单独记录到 results/duration-measurements.csv；失败原始记录也保留。",
        "# 原始证据：results/duration-raw/<config>/<run_id>/trial.json。",
        "# 不限速固定 n；限速每点固定 5 秒（带宽统计取中间 3 秒）。",
        "# " + "=" * 76,
        "",
        "# 在单独编译并完成实机预检后运行；见 README.md。",
        "",
    ]

    cur_tag = None
    idx = 0
    tags = []
    for p in plan:
        if p["tag"] not in tags:
            tags.append(p["tag"])
    for p in plan:
        if p["tag"] != cur_tag:
            cur_tag = p["tag"]
            idx += 1
            cfg = next(c for c in matrix["p4"] if c["tag"] == cur_tag)
            lines.append("")
            lines.append(f"# ---- [{idx:02d}/{len(tags)}] {cur_tag}  "
                         f"桶 {cfg['buckets']} × 槽 {cfg['slots']} "
                         f"× 窗口 {cfg['window']}  {cfg.get('desc', '')}")
            lines.append("")

        if p["kind"] == "build":
            lines.append("# 编译（源码 + 资源报表存到 builds/" + p["tag"] + "/）")
            lines.append(shlex.join(p["cmd"]))
        elif p["kind"] == "deploy":
            lines.append("# 部署并重启控制面（自动带 GSCC_RTT_TABLE_SIZE）")
            lines.append(shlex.join(p["cmd"]))
            lines.append("")
        else:
            rate = "不限速" if p.get("rate") in (None, 0, 0.0) else f"{p['rate']} Gbps"
            n = f"-n {p['iters']}" if p.get("iters") else \
                f"-D {p['duration']} 秒"
            lines.append(f"# {p['sweep']}  {p['flows']} 条流  {n}  ({rate})")
            lines.append(shlex.join(p["cmd"]))
    lines.append("")
    return "\n".join(lines)


def execute(plan: list[dict], keep_going: bool, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fails = 0
    total = len(plan)
    with log_path.open("a", encoding="utf-8") as log:
        for i, p in enumerate(plan, 1):
            cmd = shlex.join(p["cmd"])
            head = f"[{i}/{total}] {p['kind']:6s} {p['tag']}" + (
                f"  sweep={p.get('sweep')} flows={p.get('flows')} "
                f"rate={p.get('rate')} iters={p.get('iters')} duration={p.get('duration')}"
                if p["kind"] == "run" else "")
            print(f"\n{'=' * 78}\n{head}\n$ {cmd}\n{'=' * 78}", flush=True)
            log.write(f"{head}\n$ {cmd}\n")
            proc = subprocess.run(p["cmd"], cwd=str(REPO_ROOT))  # list 形式，不走 shell
            log.write(f"rc={proc.returncode}\n")
            log.flush()
            if proc.returncode != 0:
                fails += 1
                print(f"!! 失败 rc={proc.returncode}: {cmd}", file=sys.stderr)
                if not keep_going:
                    print("默认遇错即停（--keep-going 可继续）", file=sys.stderr)
                    return proc.returncode
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="矩阵编排")
    ap.add_argument("action", nargs="?", default="plan",
                    choices=["plan", "build", "deploy", "all"])
    ap.add_argument("--matrix", default=str(REPO_ROOT / "matrix.yaml"))
    ap.add_argument("--only-config", default=None, help="逗号分隔的 config tag")
    ap.add_argument("--only-sweep", default=None, help="逗号分隔的 sweep 名")
    ap.add_argument("--limit", type=int, default=None, help="每个 sweep 只取前 N 个点")
    ap.add_argument("--offset-scan", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--out", default=None, help="plan 写到文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印不执行")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="build 时忽略 builds/<tag>/build.json 里已有的结果，强制重编")
    ap.add_argument("--reps", type=int, default=1,
                    help="每点独立重复次数；保留每次记录，不拼接各列中位数")
    ap.add_argument("--tag", default=None, help="deploy 用")
    args = ap.parse_args()

    matrix = load_matrix(args.matrix)
    only_configs = [x.strip() for x in args.only_config.split(",") if x.strip()] \
        if args.only_config else None
    only_sweeps = [x.strip() for x in args.only_sweep.split(",") if x.strip()] \
        if args.only_sweep else None

    plan = build_plan(matrix, only_configs, only_sweeps, args.limit, args.offset_scan,
                      force=args.force, reps=args.reps)

    if args.action == "plan":
        text = render(plan, matrix, "scripts/matrix.py")
        if args.out:
            out = Path(args.out)
            if not out.is_absolute():
                out = REPO_ROOT / out
            out.write_text(text, encoding="utf-8")
            emit({"written": str(out), "commands": len(plan),
                  "builds": sum(1 for p in plan if p["kind"] == "build"),
                  "runs": sum(1 for p in plan if p["kind"] == "run")})
        else:
            sys.stdout.write(text)
        return 0

    if args.action == "build":
        plan = [p for p in plan if p["kind"] == "build"]
    elif args.action == "deploy":
        if not args.tag:
            raise SystemExit("deploy 需要 --tag")
        if args.tag not in {p["tag"] for p in plan}: raise SystemExit("Unknown tag")
        plan = [{"kind":"deploy","tag":args.tag,"cmd":[*_script("deploy.py"),"--tag",args.tag]}]

    if args.dry_run:
        for p in plan:
            print(shlex.join(p["cmd"]))
        return 0

    if args.action == "all":
        from preflight import check
        if args.force:raise SystemExit('Rebuild separately, then requalify before running the matrix')
        check(Path(args.matrix))
    return execute(plan, args.keep_going, REPO_ROOT / "results" / "matrix.log")


if __name__ == "__main__":
    sys.exit(main())
