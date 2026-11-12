#!/usr/bin/env python3
"""Fixed-count or timed RDMA Write; preserve separate full endpoint evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import shlex
import sys
import time
import uuid
from pathlib import Path
from common import REPO_ROOT, RESULTS_DIR, push_file, pull_file, ssh, emit, testbed
RE_BW_ROW = re.compile(r'^\s*(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$', re.M)


def parse_client(text, size, iters, flows):
    rows = RE_BW_ROW.findall(text)
    if len(rows) != 1:
        raise ValueError('Expected exactly one complete CLIENT result row')
    nbytes, exchanges, _, bw, _ = rows[0]
    if int(nbytes) != size or int(exchanges) <= 0 or (iters is not None and int(exchanges) != iters * flows):
        raise ValueError(f'Perftest reported unexpected size/count {nbytes}/{exchanges}')
    if not re.search(r'Mtu\s*:\s*1024\b', text, re.I):
        raise ValueError('Perftest did not confirm MTU 1024')
    return float(bw)


def validate_qp_pairs(gate, flows):
    ends=gate['endpoints']
    client=ends['client']['pairs'];server=ends['server']['pairs']
    for pairs in (client,server):
        if len(pairs)!=flows or len({p['local'] for p in pairs})!=flows or len({p['remote'] for p in pairs})!=flows:
            raise ValueError('Missing/duplicate QP pairs')
        if any(not 0<p[k]<2**24 for p in pairs for k in ('local','remote')):
            raise ValueError('Invalid 24-bit QPN')
    if {(p['local'],p['remote']) for p in client}!={(p['remote'],p['local']) for p in server}:
        raise ValueError('Endpoint QP maps disagree')
    return client


def install_cnp_map(gate, flows, run_id, output_dir):
    pairs=validate_qp_pairs(gate,flows)
    bed = testbed()
    switch = bed['switch_ssh']
    config=dict(run_id=run_id,sender_ip=bed['endpoints']['client']['ip'],pairs=pairs)
    path=output_dir/'cnp-map.json';path.write_text(json.dumps(config,indent=2))
    remote=bed['switch_work']+'/qp-maps/'+run_id
    push_file(switch,path,remote+'/config.json')
    push_file(switch,Path(__file__).with_name('cnp_map_remote.py'),remote+'/install.py')
    env = ['env', 'LD_LIBRARY_PATH='+bed['sde_install']+'/lib',
           'PYTHONPATH='+':'.join(bed['bfrt_pythonpath'])]
    output=ssh(switch,shlex.join(env+[bed['bfrt_python'],remote+'/install.py',remote+'/config.json']))
    (output_dir/'cnp-map-readback.txt').write_text(output)
    record=json.JSONDecoder().raw_decode(output)[0]
    if record.get('installed') is not True or record.get('run_id')!=run_id or record.get('pairs')!=pairs:
        raise ValueError('CNP map installation identity mismatch')
    return record


def traffic_commands(iters, flows, rate_gbps, size, duration_s=None, endpoints=None):
    if (iters is None) == (duration_s is None):
        raise ValueError('Choose exactly one of iters or duration_s')
    if flows < 1 or size < 1 or rate_gbps < 0 or (iters is not None and iters < 5):
        raise ValueError('Invalid traffic parameters')
    if duration_s is not None and (not 5 <= duration_s <= 60 or size != 65536):
        raise ValueError('Timed trials require 5..60 seconds and 65536-byte Writes')
    timing = ['-D',str(duration_s),'-f','1'] if duration_s is not None else ['-n',str(iters)]
    endpoints = endpoints if endpoints is not None else testbed()['endpoints']
    common = ['-F','--wait_destroy=1','-m','1024','-s',str(size),*timing,'-q',str(flows),'-p','20001']
    client = ['ib_write_bw','-d',endpoints['client']['device'], *common]
    if rate_gbps:
        client += [f'--rate_limit={rate_gbps}', '--rate_units=g','--rate_limit_type=SW','--burst_size=1']
    return ['ib_write_bw','-d',endpoints['server']['device'],*common], client+[endpoints['server']['ip']]


def run_traffic(iters, flows, rate_gbps, size, run_id, output_dir, use_qp_gate=True, duration_s=None):
    bed = testbed()
    traffic_host = bed['traffic_ssh']
    busy=ssh(bed['switch_ssh'],"pgrep -x 'bf-p4c|bf-p4c-tofino|bf-p4c-tofino2|p4c-barefoot|cc1|gcc' || true")
    if busy.strip():raise RuntimeError('Switch compiler active; refusing a traffic measurement')
    server,client=traffic_commands(iters,flows,rate_gbps,size,duration_s)
    remote = bed['traffic_work'] + '/runs/' + run_id
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    expected_s = duration_s if duration_s is not None else (iters * flows * size * 8 / (rate_gbps*1e9) if rate_gbps else 0)
    cfg = dict(iters=iters,flows=flows,rate_gbps=rate_gbps,size=size,mtu=1024,run_id=run_id,
               remote_dir=remote,endpoints=bed['endpoints'],timeout_s=max(1800,int(expected_s*4+120)),use_qp_gate=use_qp_gate,
               server_cmd=server,client_cmd=client)
    if duration_s is not None:
        cfg.update(duration_s=duration_s,margin_s=1,timeout_s=duration_s+30)
    path = output_dir/'traffic-config.json'; path.write_text(json.dumps(cfg,indent=2))
    push_file(traffic_host, path, remote+'/config.json')
    push_file(traffic_host, Path(__file__).with_name('traffic_remote.py'), remote+'/worker.py')
    push_file(traffic_host, Path(__file__).with_name('network_environment.py'), remote+'/network_environment.py')
    push_file(traffic_host, Path(__file__).with_name('background.py'), remote+'/background.py')
    gate_source=REPO_ROOT/'traffic/qp_gate.c'
    (output_dir/'qp_gate.c').write_bytes(gate_source.read_bytes())
    push_file(traffic_host,gate_source,remote+'/qp_gate.c')
    mapping=None;gate_error=None
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker=executor.submit(ssh,traffic_host,f'python3 {remote}/worker.py {remote}/config.json',cfg['timeout_s']+400,False)
        if use_qp_gate:
            try:
                deadline=time.monotonic()+150
                while True:
                    ready=ssh(traffic_host,f'if test -f {remote}/gate-ready.json; then cat {remote}/gate-ready.json; fi')
                    if ready:break
                    if worker.done() or time.monotonic()>deadline:raise RuntimeError('Traffic ended or timed out before QP gate')
                    time.sleep(.2)
                gate=json.loads(ready);(output_dir/'qp-gate.json').write_text(json.dumps(gate,indent=2))
                mapping=install_cnp_map(gate,flows,run_id,output_dir)
                ssh(traffic_host,f'touch {remote}/release')
            except Exception as exc:
                gate_error=str(exc);ssh(traffic_host,f'touch {remote}/cancel',check=False)
        worker_output=worker.result()
    (output_dir/'worker.log').write_text(worker_output)
    pull_file(traffic_host, remote+'/result.json',output_dir/'result.json')
    for name in ('client.log','server.log','gate-build.log'):
        try: pull_file(traffic_host, remote+'/'+name, output_dir/name)
        except RuntimeError as exc: (output_dir/(name+'.missing')).write_text(str(exc))
    result = json.loads((output_dir/'result.json').read_text())
    result.update(cfg)
    result['cnp_mapping']=mapping
    if gate_error: result['error']=gate_error
    result['ok'] = result.get('client_rc') == result.get('server_rc') == 0 and 'error' not in result
    try:
        log=(output_dir/'client.log').read_text()
        result['bw_mibps'] = parse_client(log,size,iters,flows)
        if duration_s is not None:
            result['reported_sample_iters']=int(RE_BW_ROW.findall(log)[0][1])
        if use_qp_gate:
            local=[int(v,16) for v in re.findall(r'local address:.*?QPN 0x([0-9a-fA-F]+)',log)]
            peer=[int(v,16) for v in re.findall(r'remote address:.*?QPN 0x([0-9a-fA-F]+)',log)]
            if mapping is None or len(local)!=flows or len(peer)!=flows or set(zip(local,peer))!={(p['local'],p['remote']) for p in mapping['pairs']}:
                raise ValueError('Perftest logs disagree with gated CNP mapping')
    except (ValueError,OSError) as exc:
        result['ok']=False; result['parse_error']=str(exc)
    return result


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    timing=ap.add_mutually_exclusive_group(required=True)
    timing.add_argument('--iters',type=int)
    timing.add_argument('--duration',type=int)
    ap.add_argument('--flows',type=int,default=1)
    ap.add_argument('--size',type=int,default=65536)
    ap.add_argument('--rate-gbps',type=float,default=0)
    args=ap.parse_args(); run_id=uuid.uuid4().hex
    r=run_traffic(args.iters,args.flows,args.rate_gbps,args.size,run_id,RESULTS_DIR/'v2-traffic'/run_id,duration_s=args.duration)
    emit(r); sys.exit(0 if r['ok'] else 1)
