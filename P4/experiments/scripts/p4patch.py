#!/usr/bin/env python3
"""Generate immutable matrix source with full-width modular PSN classification."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from common import P4_DIR
from semantics import classify_ranges, split_range32

# 基版里这几行的原始写法（精确匹配，改基版就必须同步改这里）
RE_TABLE_SIZE = re.compile(r"const bit<32> GS_RTT_TABLE_SIZE = \d+;")
RE_BUCKET_MASK = re.compile(
    r"const bit<32> GS_RTT_BUCKET_MASK = [^;]+;\s*//[^\n]*"
)
RE_SHIFT = re.compile(r"<< 8\)")
RE_OFF_SHIFT = re.compile(r"const int GS_OFF_SHIFT = \d+;")
RE_PSN_SLICE = re.compile(r"gs_psn_now\[7:0\]")
# 窗口判定表的命中集合（基版写的是 w=32 的 {0,1,2,62,63}）
RE_WIN_ENTRIES = re.compile(r"// BEGIN GENERATED OFFSET RANGES.*?// END GENERATED OFFSET RANGES", re.S)
RE_BUCKET_COMMENT = re.compile(r"// 64 个桶 × 16 个槽 = 1024 项；序号用 PSN 低 4 位（连续包刚好铺满 16 槽）")


def _expect(pattern: re.Pattern, text: str, n: int, what: str) -> None:
    got = len(pattern.findall(text))
    if got != n:
        raise SystemExit(
            f"基版 gscc.p4 结构不符：{what} 期望出现 {n} 次，实际 {got} 次。\n"
            f"  正则: {pattern.pattern[:120]}\n"
            f"  基版被改过？先确认 p4/gscc.p4 是 256 桶 × 256 槽的观测版。"
        )


def patch_p4(text: str, buckets: int, slots: int, window: int) -> tuple[str, list[str]]:
    """返回 (改造后的源码, 改动说明)。window=0 表示精确匹配。"""
    if buckets <= 0 or buckets & (buckets - 1):
        raise SystemExit(f"桶数必须是 2 的幂：{buckets}")
    if slots < 2 or slots & (slots - 1):
        raise SystemExit(f"每桶槽数必须是 2 的幂且 >= 2：{slots}")
    if window < 0:
        raise SystemExit(f"窗口不能为负：{window}")
    if window and window % slots:
        # 窗口按"槽代"放宽：同槽 PSN 相差 slots 的倍数，窗口必须是槽数的整数倍
        raise SystemExit(f"窗口 {window} 必须是每桶槽数 {slots} 的整数倍")

    shift = slots.bit_length() - 1
    table_size = buckets * slots
    changes = []

    # 1) 表深
    _expect(RE_TABLE_SIZE, text, 1, "GS_RTT_TABLE_SIZE 声明")
    text, n = RE_TABLE_SIZE.subn(
        f"const bit<32> GS_RTT_TABLE_SIZE = {table_size};", text
    )
    changes.append(f"GS_RTT_TABLE_SIZE = {table_size}  ({buckets} 桶 × {slots} 槽)")

    # 2) 桶掩码（原版是 table/256-1，只对 256 槽/桶成立）
    _expect(RE_BUCKET_MASK, text, 1, "GS_RTT_BUCKET_MASK 声明")
    text, n = RE_BUCKET_MASK.subn(
        f"const bit<32> GS_RTT_BUCKET_MASK = {buckets - 1};  // {buckets} buckets", text
    )
    changes.append(f"GS_RTT_BUCKET_MASK = {buckets - 1}")

    # 3) 桶左移量
    _expect(RE_SHIFT, text, 1, "索引里的 `<< 8`")
    text, n = RE_SHIFT.subn(f"<< {shift})", text)
    changes.append(f"index shift 8 -> {shift}  (×{slots} 槽/桶, 共 {n} 处)")

    # 3b) PSN 偏移直方图的"一代槽"（= 每桶槽数）
    _expect(RE_OFF_SHIFT, text, 1, "GS_OFF_SHIFT 常量")
    text, _ = RE_OFF_SHIFT.subn(f"const int GS_OFF_SHIFT = {shift};", text)
    changes.append(f"GS_OFF_SHIFT = {shift}  (偏移直方图按 {slots} 个 PSN 一代槽分桶)")

    # 4) PSN 切片
    _expect(RE_PSN_SLICE, text, 1, "索引里的 `gs_psn_now[7:0]`")
    text, n = RE_PSN_SLICE.subn(f"gs_psn_now[{shift - 1}:0]", text)
    changes.append(f"psn[7:0] -> psn[{shift - 1}:0]  (共 {n} 处)")

    _expect(RE_WIN_ENTRIES, text, 1, "full-width offset ranges")
    ranges = classify_ranges(slots, window)
    entries = [f"            (16w{a} .. 16w{b}, 16w{c} .. 16w{d}): gs_classify_offset(8w{bucket}, 32w{hit});"
               for lo, hi, bucket, hit in ranges for a,b,c,d in split_range32(lo, hi)]
    text = RE_WIN_ENTRIES.sub("// BEGIN GENERATED OFFSET RANGES\n" + "\n".join(entries) +
                              "\n            // END GENERATED OFFSET RANGES", text)
    changes.append(f"full32 offset ranges={len(ranges)}, modulo24 signed window=±{window}")

    # 6) 顺手把过时注释改对（不影响逻辑）
    text = RE_BUCKET_COMMENT.sub(
        f"// {buckets} 个桶 × {slots} 个槽 = {table_size} 项；"
        f"序号用 PSN 低 {shift} 位", text
    )

    # 兜底：改完不该再残留旧常量
    stale_list = ["= 65536;", "GS_RTT_TABLE_SIZE / 256 - 1", "<< 8)", "gs_psn_now[7:0]"]
    if shift != 8:
        stale_list.append("GS_OFF_SHIFT = 8;")
    for stale in stale_list:
        if stale in text:
            raise SystemExit(f"改造后仍残留旧写法：{stale}")

    return text, changes


def check() -> int:
    base = (P4_DIR / "gscc.p4").read_text()
    for slots, window in [(16,0), (16,16), (16,32), (16,64), (32,0), (64,0), (128,0)]:
        text, changes = patch_p4(base, 256, slots, window)
        assert "gs_meta.gs_rtt_stored_id[31:16]: range" in text
        assert "GS_OFF_BUCKETS = 132;" in text
        print(f"s{slots}-w{window}: " + "; ".join(changes))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="生成某一档的 gscc.p4")
    ap.add_argument("--buckets", type=int, default=256)
    ap.add_argument("--slots", type=int, default=16, help="每桶槽数（16/32/64/128）")
    ap.add_argument("--window", type=int, default=0, help="匹配窗口（包），0=精确匹配")
    ap.add_argument("--src", default=str(P4_DIR / "gscc.p4"))
    ap.add_argument("--out", required=False, help="输出文件路径")
    ap.add_argument("--check", action="store_true", help="自检：跑一遍所有档位")
    args = ap.parse_args()

    if args.check:
        return check()

    text, changes = patch_p4(
        Path(args.src).read_text(encoding="utf-8"),
        args.buckets, args.slots, args.window,
    )
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        for c in changes:
            print("  " + c)
        print(f"written: {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
