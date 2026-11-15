#!/usr/bin/env python3
"""Compile the independent GRC feedback pipeline for Tofino2."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import shlex
from pathlib import Path

from common import (
    ARTIFACTS, SCHEMA, CTRL_DIR, P4_DIR, REPO_ROOT, emit, pull_file, push_file, ssh_script, testbed, topology_header,
)

BUILDS_DIR = REPO_ROOT / "builds"


def fingerprint(buckets=64, slots=16):
    h = hashlib.sha256(json.dumps([SCHEMA, buckets, slots, testbed()], sort_keys=True).encode())
    for f in sorted([*P4_DIR.glob('*.p4'), *CTRL_DIR.glob('*.h'), *CTRL_DIR.glob('*.c'), Path(__file__), Path(__file__).with_name('common.py')]):
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()


def materialise(tag, buckets, slots):
    out = BUILDS_DIR / tag
    (out / 'src').mkdir(parents=True)
    for name in ('gscc.p4', 'header.p4', 'util.p4'):
        shutil.copyfile(P4_DIR / name, out / 'src' / name)
    (out / 'src' / 'testbed.p4').write_text(topology_header(testbed()['endpoints']))
    p4 = out / 'src' / 'gscc.p4'
    text = p4.read_text()
    for old, new in (
        ('GS_RTT_TABLE_SIZE = 64 * 16;', f'GS_RTT_TABLE_SIZE = {buckets} * {slots};'),
        ('id_flow_hash[5:0] ++ gs_meta.id_sequence_hash[3:0]',
         f'id_flow_hash[{buckets.bit_length()-2}:0] ++ gs_meta.id_sequence_hash[{slots.bit_length()-2}:0]'),
    ):
        if text.count(old) != 1:
            raise ValueError('Unexpected sampler source: ' + old)
        text = text.replace(old, new)
    p4.write_text(text)
    (out / 'ctrl').mkdir(exist_ok=True)
    for name in ('ctrl.c', 'headers.h', 'paper_rate.h'):
        shutil.copyfile(CTRL_DIR / name, out / 'ctrl' / name)
    shutil.copyfile(CTRL_DIR / 'config.h', out / 'config.h')
    return out


def compile_remote(tag: str, out_dir: Path, source_id: str, timeout: int = 900) -> dict:
    bed = testbed()
    switch = bed["switch_ssh"]
    remote = f"{bed['switch_work']}/builds/{tag}-{source_id[:16]}"
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
    p4c_ok = "P4C_EXIT=0" in txt and "BIN_OK" in txt
    ctrl_ok = "CTRL_RC=0" in txt and "CTRL_BIN_OK" in txt
    if p4c_ok and ctrl_ok:
        hashes = ssh_script(switch, "cd " + shlex.quote(remote) + " && sha256sum " + " ".join(ARTIFACTS))
        artifacts = {line.split()[1]: line.split()[0] for line in hashes.splitlines()}
        pull_file(switch, f"{remote}/bf-rt.json", out_dir / "bf-rt.json")

    return {
        "remote_dir": remote,
        "artifacts_sha256": artifacts,
        "p4c_ok": p4c_ok,
        "ctrl_ok": ctrl_ok,
        "bin": f"{remote}/build/gs_pipe/tofino2.bin" if p4c_ok else None,
        "raw_tail": txt[-1500:],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='paper-loop-s16')
    ap.add_argument('--buckets', type=int, choices=(64, 256), default=64)
    ap.add_argument('--slots', type=int, choices=(16, 32, 64), default=16)
    args = ap.parse_args()
    if not re.fullmatch(r'paper-loop-[A-Za-z0-9_-]+', args.tag):
        raise SystemExit('Tag must start with paper-loop-')
    dest = BUILDS_DIR / args.tag
    if dest.exists():
        raise SystemExit('Choose a new tag to retain the earlier build')
    source_id = fingerprint(args.buckets, args.slots)
    out = materialise(args.tag, args.buckets, args.slots)
    build = compile_remote(args.tag, out, source_id)
    if fingerprint(args.buckets, args.slots) != source_id:
        raise RuntimeError("Sources changed during compilation; build is not qualified")
    control = {'mode': 'paper-loop', 'slots': args.slots, 'buckets': args.buckets, 'tag': args.tag}
    record = dict(schema=SCHEMA, source_id=source_id, cfg=control, **build)
    (out / 'build.json').write_text(json.dumps(record, indent=2))
    ok = build['p4c_ok'] and build['ctrl_ok']
    emit(dict(ok=ok, tag=args.tag))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
