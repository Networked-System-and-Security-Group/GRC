#!/usr/bin/env python3
"""Cold-start one content-verified build; every trial receives fresh probe/control state."""
import json
import re
import shlex
import time
import uuid
from pathlib import Path
from build import fingerprint
from common import ARTIFACTS, SCHEMA, REPO_ROOT, push_file, pull_file, ssh, testbed


def validate_context(context):
    names={t.get('name','').split('.')[-1] for t in context.get('tables',[])}
    if not {'id_flow_entries','paper_send_ts_reg','paper_rtt_floor_reg','gs_rtt_control_reg'} <= names:
        raise ValueError('Missing paper-loop sampling or control table')
    if {'gs_window_table','gs_rtt_id_reg','gs_rtt_timestamp_reg'} & names:
        raise ValueError('Legacy feedback must not be present in the paper loop')


def deploy(tag, wait=150):
    if not re.fullmatch(r'paper-loop-[A-Za-z0-9_-]+', tag):
        raise ValueError('Invalid build tag')
    bed = testbed()
    switch = bed['switch_ssh']
    record=json.loads((REPO_ROOT/'builds'/tag/'build.json').read_text())
    cfg=record['cfg']
    if (record.get('schema') != SCHEMA or not record.get('p4c_ok') or not record.get('ctrl_ok') or
            set(record.get('artifacts_sha256', {})) != set(ARTIFACTS) or cfg['tag'] != tag):
        raise ValueError('Not a successful paper-loop build')
    if record['source_id']!=fingerprint(cfg['buckets'],cfg['slots']):
        raise ValueError('Source changed since build; rebuild before deployment')
    context=json.loads(ssh(switch,'cat '+shlex.quote(record['remote_dir']+'/build/gs_pipe/context.json')))
    validate_context(context)
    schema=json.loads(ssh(switch,'cat '+shlex.quote(record['remote_dir']+'/bf-rt.json')))
    sizes={t['name'].split('.')[-1]:t['size'] for t in schema['tables'] if 'size' in t}
    if any(sizes.get(name)!=cfg['buckets']*cfg['slots'] for name in ('id_flow_entries','paper_send_ts_reg')):
        raise ValueError('Compiled sampler size differs from requested bucket/slot geometry')
    if ssh(switch, "pgrep -x 'bf-p4c|bf-p4c-tofino|bf-p4c-tofino2|p4c-barefoot|cc1|gcc' || true").strip():
        raise RuntimeError('Switch compiler active; cannot restart switch')
    if ssh(bed['traffic_ssh'], 'pgrep -x ib_write_bw || true').strip():
        raise RuntimeError('Traffic active; cannot restart switch')
    uid=uuid.uuid4().hex
    root=bed['switch_work']+'/deployments/'+uid
    local=REPO_ROOT/'results/deployments'/uid; local.mkdir(parents=True)
    client_port = bed['endpoints']['client']['switch_port']
    cfg=dict(record,build_id=record['source_id'],deployment_id=uid,deployment_dir=root,
             switch_work=bed['switch_work'],sde=bed['sde'],sde_install=bed['sde_install'],
             switchd_conf=bed['switchd_conf'],pipe=client_port >> 7,client_port=client_port,
             server_port=bed['endpoints']['server']['switch_port'])
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
