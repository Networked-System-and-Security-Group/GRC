#!/usr/bin/env python3
"""编译矩阵里的一档数据面（+ 控制面），并把**这一版的全部代码**另存到一个文件夹。

产物目录（每档一个，互不覆盖）：

    builds/b<桶数>-s<槽数>-w<窗口>/
        VERSION.md          # 参数、改动清单、编译结果、资源占用（人看）
        build.json          # 同一份信息的机器可读版
        src/                # 这一版的数据面源码（改过的）
            gscc.p4  header.p4  util.p4
        ctrl/               # 这一版用的控制面源码（拷贝，保证可追溯）
            ctrl.c  headers.h
        resources/          # bf-p4c 资源报表
            metrics.json  mau.resources.log  table_summary.log
        compile.log         # 编译器完整输出

二进制（tofino2.bin / context.json / bf-rt.json / ctrl）留在交换机的
<switch_work>/builds/ 下，build.json 里记 哈希与路径。

例：
    python3 scripts/build.py --slots 16 --window 0
    python3 scripts/build.py --slots 128 --window 0 --tag b256-s128-w0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import shlex
from pathlib import Path

import p4patch
from semantics import SCHEMA, offset_bins
from common import (
    CTRL_DIR, P4_DIR, REPO_ROOT, emit, pull_file, push_file, ssh_script, testbed, topology_header,
)

BUILDS_DIR = REPO_ROOT / "builds"


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def default_tag(buckets: int, slots: int, window: int) -> str:
    return f"b{buckets}-s{slots}-w{window}-v2"


def fingerprint(buckets, slots, window):
    h = hashlib.sha256(json.dumps([buckets, slots, window, SCHEMA, testbed()], sort_keys=True).encode())
    for f in sorted(list(P4_DIR.glob("*.p4")) + list(CTRL_DIR.glob("*.h")) + list(CTRL_DIR.glob("*.c")) +
                    [Path(__file__), Path(__file__).with_name("p4patch.py"), Path(__file__).with_name("semantics.py")]):
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()


# --------------------------------------------------------------------------
# 1. 生成这一版的源码目录
# --------------------------------------------------------------------------
def materialise(buckets: int, slots: int, window: int, tag: str) -> tuple[Path, list[str]]:
    out = BUILDS_DIR / tag
    src_dir = out / "src"
    ctrl_dir = out / "ctrl"
    src_dir.mkdir(parents=True, exist_ok=True)
    ctrl_dir.mkdir(parents=True, exist_ok=True)

    base = (P4_DIR / "gscc.p4").read_text(encoding="utf-8")
    patched, changes = p4patch.patch_p4(base, buckets, slots, window)
    (src_dir / "gscc.p4").write_text(patched, encoding="utf-8")
    for name in ("header.p4", "util.p4"):
        shutil.copyfile(P4_DIR / name, src_dir / name)

    (src_dir / "testbed.p4").write_text(topology_header(testbed()["endpoints"]))

    for name in ("ctrl.c", "headers.h"):
        shutil.copyfile(CTRL_DIR / name, ctrl_dir / name)
    # headers.h 里 #include "../config.h"，相对 ctrl/ 的父目录
    shutil.copyfile(CTRL_DIR / "config.h", out / "config.h")

    return out, changes


# --------------------------------------------------------------------------
# 2. 远端编译
# --------------------------------------------------------------------------
def compile_remote(tag: str, out_dir: Path, timeout: int = 900) -> dict:
    bed = testbed()
    switch = bed["switch_ssh"]
    h = hashlib.sha256()
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file() and p.suffix in (".c", ".h", ".p4")):
        h.update(path.read_bytes())
    remote = f"{bed['switch_work']}/builds/{tag}-{h.hexdigest()[:16]}"
    for sub in ("src", "ctrl"):
        for f in (out_dir / sub).iterdir():
            push_file(switch, f, f"{remote}/{sub}/{f.name}")
    # ctrl/headers.h 里 #include "../config.h"
    push_file(switch, out_dir / "config.h", f"{remote}/config.h")

    script = f"""
export SDE={bed["sde"]}
export SDE_INSTALL={bed["sde_install"]}
export PATH=$SDE_INSTALL/bin:$PATH
export LD_LIBRARY_PATH=$SDE_INSTALL/lib:$SDE/p4studio/dependencies/source/libcli
cd {remote} || exit 1
rm -rf build bf-rt.json compile.log ctrl/ctrl ctrl/ctrl_build.log

echo "===== bf-p4c ====="
( cd src && bf-p4c --std p4-16 --target tofino2 --arch t2na --verbose 2 \\
      --bf-rt-schema {remote}/bf-rt.json -o {remote}/build gscc.p4 \\
      > {remote}/compile.log 2>&1 )
echo "P4C_EXIT=$?"
tail -25 {remote}/compile.log
test -f build/gs_pipe/tofino2.bin && echo "BIN_OK" || echo "BIN_MISSING"
test -f build/gs_pipe/context.json && echo "CTX_OK" || echo "CTX_MISSING"

echo "===== ctrl ====="
( cd ctrl && gcc -O2 -g -DBFRT_GENERIC_FLAGS -I. -I$SDE_INSTALL/include \\
      -o ctrl ctrl.c -L$SDE_INSTALL/lib \\
      -ldriver -lbf_switchd_lib -lpthread -lm > ctrl_build.log 2>&1 )
echo "CTRL_RC=$?"
tail -20 ctrl/ctrl_build.log 2>/dev/null
test -x ctrl/ctrl && echo "CTRL_BIN_OK" || echo "CTRL_BIN_MISSING"
"""
    txt = ssh_script(switch, script, timeout=timeout, check=False)
    (out_dir / "build-driver.log").write_text(txt, encoding="utf-8")
    pull_file(switch, f"{remote}/compile.log", out_dir / "compile.log")
    pull_file(switch, f"{remote}/ctrl/ctrl_build.log", out_dir / "ctrl_build.log")
    artifacts = {}
    if "P4C_EXIT=0" in txt and "CTRL_RC=0" in txt:
        names = ["build/gs_pipe/tofino2.bin", "build/gs_pipe/context.json", "bf-rt.json", "ctrl/ctrl"]
        hashes = ssh_script(switch, "cd " + shlex.quote(remote) + " && sha256sum " + " ".join(names))
        artifacts = {line.split()[1]: line.split()[0] for line in hashes.splitlines()}
        pull_file(switch, f"{remote}/bf-rt.json", out_dir / "bf-rt.json")

    p4c_ok = "P4C_EXIT=0" in txt and "BIN_OK" in txt
    ctrl_ok = "CTRL_RC=0" in txt and "CTRL_BIN_OK" in txt
    return {
        "remote_dir": remote,
        "artifacts_sha256": artifacts,
        "p4c_ok": p4c_ok,
        "ctrl_ok": ctrl_ok,
        "bin": f"{remote}/build/gs_pipe/tofino2.bin" if p4c_ok else None,
        "raw_tail": txt[-1500:],
    }


# --------------------------------------------------------------------------
# 3. 拉回资源报表
# --------------------------------------------------------------------------
def fetch_resources(remote_dir: str, out_dir: Path) -> dict:
    switch = testbed()["switch_ssh"]
    remote = f"{remote_dir}/build/gs_pipe/logs"
    local = out_dir / "resources"
    local.mkdir(exist_ok=True)
    got = {}
    for name in ("metrics.json", "mau.resources.log", "table_summary.log"):
        try:
            pull_file(switch, f"{remote}/{name}", local / name)
            got[name] = True
        except Exception as exc:                      # noqa: BLE001
            got[name] = f"missing ({exc})"
    return got


def parse_metrics(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    mau = data.get("mau", {})
    lat = {x.get("gress"): x.get("cycles") for x in mau.get("latency", [])}
    parser = data.get("parser", {})
    return {
        "sram": mau.get("srams"),
        "tcam": mau.get("tcams"),
        "map_ram": mau.get("map_rams"),
        "logical_tables": mau.get("logical_tables"),
        "action_bus_bytes": mau.get("action_bus_bytes"),
        "ingress_cycles": lat.get("ingress"),
        "egress_cycles": lat.get("egress"),
        "parser_tcam_rows_ingress": parser.get("ingress", {}).get("tcam_rows"),
    }


def parse_stage_table(path: Path) -> dict:
    """从 mau.resources.log 里取"用了几个 stage"和单 stage 峰值。"""
    if not path.exists():
        return {}
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 9 or not cells[0].isdigit():
            continue

        def pct(x):
            return float(x.rstrip("%")) if x.endswith("%") else 0.0

        rows.append({
            "stage": int(cells[0]),
            "sram_pct": pct(cells[6]),
            "map_ram_pct": pct(cells[7]),
            "tcam_pct": pct(cells[8]),
        })
    used = [r for r in rows if r["sram_pct"] or r["map_ram_pct"] or r["tcam_pct"]]
    return {
        "stages_used": len(used),
        "stage_ids": [r["stage"] for r in used],
        "max_sram_pct": max((r["sram_pct"] for r in used), default=0.0),
        "max_map_ram_pct": max((r["map_ram_pct"] for r in used), default=0.0),
        "max_tcam_pct": max((r["tcam_pct"] for r in used), default=0.0),
    }


# --------------------------------------------------------------------------
# 4. 写 VERSION.md
# --------------------------------------------------------------------------
def write_version(out_dir: Path, cfg: dict, build: dict, res: dict, changes: list[str]) -> None:
    md = f"""# {cfg['tag']}

由 `scripts/build.py` 自动生成，**不要手改**。改实验请改 `p4/gscc.p4` 基版或脚本，
然后重新编译（新目录）。

## 矩阵参数

| 项 | 值 |
|---|---|
| 桶数 | {cfg['buckets']} |
| 每桶槽数 | {cfg['slots']} |
| RTT 表项数 | {cfg['buckets'] * cfg['slots']} |
| 匹配窗口 | {'精确匹配（d == 0）' if cfg['window'] == 0 else f"±{cfg['window']} 个包"} |
| PSN 切片 | `psn[{cfg['slots'].bit_length() - 2}:0]` |
| 桶左移 | `<< {cfg['slots'].bit_length() - 1}` |

## 相对基版 `p4/gscc.p4` 的改动

{chr(10).join('- ' + c for c in changes)}

## 编译

| 项 | 结果 |
|---|---|
| bf-p4c | {'OK' if build['p4c_ok'] else '**失败**'} |
| ctrl | {'OK' if build['ctrl_ok'] else '**失败**'} |
| 远端目录 | `{build['remote_dir']}` |
| 源码 md5（gscc.p4） | `{md5_of(out_dir / 'src' / 'gscc.p4')}` |
| ctrl.c md5 | `{md5_of(out_dir / 'ctrl' / 'ctrl.c')}` |

## 资源占用（bf-p4c --verbose 2）

| 指标 | 值 |
|---|---|
| ingress stage 数 | {res.get('stages_used', '?')} |
| SRAM 块 | {res.get('sram', '?')} |
| 单 stage SRAM 峰值 | {res.get('max_sram_pct', '?')}% |
| TCAM 块 / 峰值 | {res.get('tcam', '?')} / {res.get('max_tcam_pct', '?')}% |
| MapRAM 块 / 峰值 | {res.get('map_ram', '?')} / {res.get('max_map_ram_pct', '?')}% |
| 逻辑表数 | {res.get('logical_tables', '?')} |
| Action Data Bus | {res.get('action_bus_bytes', '?')} B |
| ingress 时延 | {res.get('ingress_cycles', '?')} cycles |
| egress 时延 | {res.get('egress_cycles', '?')} cycles |

> 控制面读表时用环境变量 `GSCC_RTT_TABLE_SIZE={cfg['buckets'] * cfg['slots']}`
> 打开对应扫描范围（见 `ctrl/ctrl.c` 的 `[P4SORT]` 段）。
"""
    (out_dir / "VERSION.md").write_text(md, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="编译矩阵里的一档")
    ap.add_argument("--buckets", type=int, default=256)
    ap.add_argument("--slots", type=int, default=16, help="每桶槽数 16/32/64/128")
    ap.add_argument("--window", type=int, default=0, help="匹配窗口（包数），0=精确")
    ap.add_argument("--tag", default=None, help="版本目录名（默认 b<b>-s<s>-w<w>）")
    ap.add_argument("--skip-compile", action="store_true", help="只生成源码目录，不编译")
    ap.add_argument("--force", action="store_true", help="目录已存在也重编")
    args = ap.parse_args()

    tag = args.tag or default_tag(args.buckets, args.slots, args.window)
    out_dir = BUILDS_DIR / tag
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tag):
        raise SystemExit("Invalid tag")
    source_id = fingerprint(args.buckets, args.slots, args.window)
    if (out_dir / "build.json").exists():
        old = json.loads((out_dir / "build.json").read_text())
        if not args.force:
            if old.get("source_id") != source_id:
                raise SystemExit("Source changed: use a new tag or --force (archives old source)")
            if not (old.get("p4c_ok") and old.get("ctrl_ok")):
                raise SystemExit("Previous build failed; use --force")
            emit({"tag": tag, "skipped": True, "ok": True})
            return 0
        archive = REPO_ROOT / "archive" / (tag + "-" + str(time.time_ns()))
        archive.parent.mkdir(exist_ok=True)
        out_dir.rename(archive)

    out_dir, changes = materialise(args.buckets, args.slots, args.window, tag)
    cfg = {"tag": tag, "buckets": args.buckets, "slots": args.slots, "window": args.window}

    if args.skip_compile:
        emit({"tag": tag, "cfg": cfg, "changes": changes, "compiled": False})
        return 0

    build = compile_remote(tag, out_dir)
    got = fetch_resources(build["remote_dir"], out_dir)
    res = {**parse_metrics(out_dir / "resources" / "metrics.json"),
           **parse_stage_table(out_dir / "resources" / "mau.resources.log")}

    record = {"schema": SCHEMA, "source_id": source_id, "offset_bins": offset_bins(args.slots), "cfg": cfg, **build, "resources": res, "resources_fetched": got,
              "changes": changes}
    (out_dir / "build.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    write_version(out_dir, cfg, build, res, changes)

    emit({
        "tag": tag, "ok": build["p4c_ok"] and build["ctrl_ok"],
        "p4c_ok": build["p4c_ok"], "ctrl_ok": build["ctrl_ok"],
        "dir": str(out_dir), **res,
    })
    return 0 if build["p4c_ok"] and build["ctrl_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
