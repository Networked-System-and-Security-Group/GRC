#!/usr/bin/env python3
"""Cold-start one content-verified build; every trial receives fresh probe/control state."""
import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path
from build import fingerprint
from common import REPO_ROOT, push_file, pull_file, ssh, emit, testbed
from semantics import SCHEMA


def validate_context(context):
    tables=[t for t in context.get('tables',[]) if t.get('name','').endswith('gs_window_table')]
    if len(tables)!=1: raise ValueError('Missing/ambiguous compiled offset classifier')
    keys=tables[0].get('match_key_fields',[])
    if (len(keys)!=2 or len({k['name'] for k in keys})!=2 or
            len({k['position'] for k in keys})!=2 or any(k['bit_width']!=16 for k in keys)):
        raise ValueError('SDE context aliases the two range keys; negative 32-bit differences are unsafe')


def deploy(tag, wait=150):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tag):
        raise ValueError("Invalid build tag")
    bed = testbed()
    switch = bed["switch_ssh"]
    record=json.loads((REPO_ROOT/'builds'/tag/'build.json').read_text())
    c=record['cfg']
    if record.get('schema')!=SCHEMA or not record.get('p4c_ok') or not record.get('ctrl_ok'):
        raise ValueError('Not a successful v2 build')
    if record['source_id']!=fingerprint(c['buckets'],c['slots'],c['window']):
        raise ValueError('Source changed since build; rebuild before deployment')
    context=json.loads(ssh(switch,'cat '+record['remote_dir']+'/build/gs_pipe/context.json'))
    validate_context(context)
    if ssh(bed['traffic_ssh'], 'pgrep -x ib_write_bw || true').strip():
        raise RuntimeError('Traffic active; cannot restart switch')
    uid=uuid.uuid4().hex
    root=bed['switch_work']+'/deployments/'+uid
    local=REPO_ROOT/'results/v2-deployments'/uid; local.mkdir(parents=True)
    client_port = bed['endpoints']['client']['switch_port']
    server_port = bed['endpoints']['server']['switch_port']
    cfg=dict(record,build_id=record['source_id'],deployment_id=uid,deployment_dir=root,
             switch_work=bed['switch_work'], sde=bed['sde'], sde_install=bed['sde_install'],
             switchd_conf=bed['switchd_conf'], pipe=client_port >> 7,
             client_port=client_port, server_port=server_port)
    config=local/'config.json'; config.write_text(json.dumps(cfg,indent=2))
    push_file(switch,config,root+'/config.json')
    push_file(switch,Path(__file__).with_name('deploy_remote.py'),root+'/deploy.py')
    active=json.loads(ssh(switch,f'python3 {root}/deploy.py {root}/config.json',timeout=45))
    (local/'deployment.json').write_text(json.dumps(active,indent=2))
    end=time.monotonic()+wait
    while time.monotonic()<end:
        text=ssh(switch,f'tail -c 12000 {root}/controller.log')
        if 'GSCC 控制面启动成功' in text and 'initialized 1 devices' in text and 'Operational mode set to ASIC' in text:
            time.sleep(3)
            return active
        if not ssh(switch,f'kill -0 {active["pid"]} 2>/dev/null && echo alive',check=False).strip():
            pull_file(switch,root+'/controller.log',local/'controller.log')
            raise RuntimeError('Controller exited; see '+str(local/'controller.log'))
        time.sleep(2)
    pull_file(switch,root+'/controller.log',local/'controller.log')
    raise TimeoutError('Controller startup did not complete: '+str(local))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--tag',required=True)
    ap.add_argument('--offset-scan',choices=['auto','on'],default='auto',help='Compatibility; snapshots are always on demand')
    args=ap.parse_args(); emit(deploy(args.tag))
