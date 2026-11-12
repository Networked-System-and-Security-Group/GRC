#!/usr/bin/env python3
"""Recompute v2 trials without dropping failed repetitions or accepting legacy data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from common import RESULTS_DIR
from run import scientific_row, append_csv, validate_guard, script_provenance
from semantics import SCHEMA


def audit(path):
    rec=json.loads(path.read_text())
    if rec.get('schema')!=SCHEMA: raise ValueError('Legacy data: cannot repair missing scientific evidence by recalculation')
    if 'error' in rec: raise ValueError(rec['error'])
    if rec.get('deployment',{}).get('build_id')!=rec['after']['build_id']: raise ValueError('Build provenance mismatch')
    saved=rec.get('scripts',{}).get('files',{})
    if not saved: raise ValueError('Missing script provenance')
    for name,expected in saved.items():
        source=path.parent/'scripts'/name
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise ValueError('Archived execution script changed/missing: '+name)
    if rec['traffic'].get('gate_source_sha256')!=saved.get('qp_gate.c'):
        raise ValueError('QP gate source does not match executed trial')
    current=script_provenance()['files']
    for name in ('run.py','collect.py','semantics.py','network_environment.py','background.py'):
        if saved.get(name)!=current.get(name):
            raise ValueError('Calculation contract changed; use archived analyzer: '+name)
    validate_guard(rec['after'],rec['after_guard'],rec['deployment'])
    row=scientific_row(rec['cfg'],rec['before'],rec['after'],rec['traffic'],rec['run_id'],rec['rep'])
    if row!=rec['row']: raise ValueError('Stored row differs from current calculation')
    return row


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rawdir',default=str(RESULTS_DIR/'duration-raw'))
    ap.add_argument('--csv',help='Create a new CSV retaining each repetition, including invalid ones')
    args=ap.parse_args()
    if args.csv and Path(args.csv).exists(): raise SystemExit('Output exists; choose a new filename')
    files=list(Path(args.rawdir).rglob('trial.json')); bad=[]; seen=set()
    for path in sorted(files):
        try:
            row=audit(path)
            if row['run_id'] in seen: raise ValueError('Duplicate run identity')
            seen.add(row['run_id'])
            if args.csv: append_csv(args.csv,row)
            if not row['integrity_ok']: bad.append({'file':str(path),'issues':row['issues']})
        except Exception as exc: bad.append({'file':str(path),'error':str(exc)})
    print(json.dumps({'trials':len(files),'failed':bad,'note':'Arithmetic checks alone do not establish hardware semantic correctness.'},ensure_ascii=False,indent=2))
    sys.exit(1 if bad or not files else 0)
