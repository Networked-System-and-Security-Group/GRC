#!/usr/bin/env python3
"""One cold-start trial with explicit scientific checks and raw evidence retention."""
import argparse
import csv
import fcntl
import json
import re
from pathlib import Path
import sys
import time
import uuid
import collect
import deploy
from common import SCHEMA, RESULTS_DIR, pull_file, emit, testbed
from traffic import run_traffic, validate_qp_pairs, traffic_commands
from network_environment import validate_environment
from background import account_background, validate_idle_guard

COUNTERS=['ack_req','ack_total','rtt_ok','fail_empty','fail_psn','pkt','cnp_generated','rtt_count']
COLUMNS=['schema','run_id','rep','config','buckets','slots','iters','flows','rate_gbps','size','integrity_ok',
         'issues','bw_mibps','ack_req','ack_total','rtt_ok','fail_empty','fail_psn','pkt','cnp_generated',
         'data_packets_observed','data_packets_expected','ack_per_ackreq','ackreq_per_data','data_per_ack',
         'match_pct','rtt_sample_weighted_mean_us_mod32','rtt_max_ns','kind','wall_s','build_id',
         'background','timing_has_background','post_window_background',
         'measurement_mode','duration_s','margin_s','reported_sample_iters','writes_observed','counter_scope',
         'applied_rtt_samples','budget_writes','max_epoch_us','identity_match_pct','filter_rejects']


def scientific_row(cfg, before, after, traffic, run_id, rep):
    collect.validate(before); collect.validate(after)
    for f in ['pid','boot_us','pipe','build_id']:
        if before[f]!=after[f]: raise ValueError('Snapshot identity changed: '+f)
    if before['nonce']==after['nonce'] or before['end_us']>=after['start_us']:
        raise ValueError('Stale or overlapping snapshots')
    # Every trial cold starts; refuse carry-over instead of trying to hide it with subtraction.
    if any(before[k] for k in COUNTERS) or any(before['kind']) or before['rtt_sum_ns_mod32_samples']:
        raise ValueError('Nonzero baseline: background traffic or stale state')
    row=dict(schema=SCHEMA,run_id=run_id,rep=rep,config=cfg['tag'],
             **{k:cfg[k] for k in ('buckets','slots')},
             **{k:traffic[k] for k in ('iters','flows','rate_gbps','size')},
             **{k:after[k] for k in COUNTERS},kind=after['kind'],
             build_id=after['build_id'],bw_mibps=traffic.get('bw_mibps'),wall_s=traffic.get('wall_s'),rtt_max_ns=after.get('rtt_max_ns'))
    issues=[]
    def require(ok,why):
        if not ok: issues.append(why)
    require(traffic.get('ok') is True,'traffic process/parse failed')
    try:
        validate_environment(traffic.get('network_before', {}), traffic.get('endpoints', {}))
        validate_environment(traffic.get('network_after', {}), traffic.get('endpoints', {}))
        require(traffic['network_before']==traffic['network_after'],'test-port network configuration changed')
    except ValueError as exc:
        issues.append('Network environment invalid: '+str(exc))
    require(traffic.get('use_qp_gate') is True,'missing QP startup gate')
    mapping=traffic.get('cnp_mapping') or {}
    require(mapping.get('installed') is True and mapping.get('run_id')==run_id,'missing/foreign exact CNP map')
    try:
        pairs=validate_qp_pairs(traffic['qp_gate'],traffic['flows'])
        require(mapping.get('pairs')==pairs,'installed CNP map differs from endpoint QPs')
        require(traffic['qp_gate']['nic_while_gated']==traffic['before_nic'],'RDMA traffic before mapping release')
    except (KeyError,ValueError) as exc:
        issues.append('QP mapping evidence invalid: '+str(exc))
    require(traffic.get('before_nic_guard')==traffic.get('before_nic'),'NIC baseline not quiet')
    try:
        row['post_window_background']=validate_idle_guard(traffic.get('after_nic',{}),traffic.get('after_nic_guard',{}))
    except ValueError as exc:
        issues.append(str(exc));row['post_window_background']=None
    duration=traffic.get('duration_s')
    if duration is None:
        messages=traffic['iters']*traffic['flows']
    else:
        # Duration-mode perftest reports only the interior sampling interval.
        # ASIC snapshots include margins and drain; derive full-window Writes
        # independently from receiver NIC, never from the switch itself.
        key='server/hw_counters/rx_write_requests'
        begin=traffic.get('before_nic',{}).get(key);end=traffic.get('after_nic',{}).get(key)
        messages=end-begin if begin is not None and end is not None else None
        require(messages is not None and messages>0,'missing/invalid full-window NIC Write count')
        sample=traffic.get('reported_sample_iters')
        require(isinstance(sample,int) and sample>0 and messages is not None and sample<=messages,
                'perftest sample count exceeds full-window NIC Writes or is missing')
        wall=traffic.get('wall_s')
        require(traffic['iters'] is None and traffic['size']==65536 and traffic['mtu']==1024 and
                5<=duration<=60 and traffic.get('margin_s')==1,'invalid duration contract')
        require(wall is not None and duration-1<=wall<=duration+30,'duration run elapsed time out of bounds')
        # At 100G even the conservative 90 s upper bound cannot wrap these
        # counters with full 1024-byte data segments and <=1 ACK per segment.
        require(2*(duration+30)*100e9/(1024*8)<2**32,'duration counter-wrap bound exceeded')
        row.update(measurement_mode='duration',duration_s=duration,margin_s=traffic.get('margin_s'),
                   reported_sample_iters=sample,writes_observed=messages,
                   counter_scope='whole_run_including_margins_and_drain')
    expected=messages*((traffic['size']+traffic['mtu']-1)//traffic['mtu']) if messages is not None else None
    require(expected is not None and 0<=expected*2 < 2**32,'counter-wrap bound exceeded')
    row['data_packets_expected']=expected
    row['data_packets_observed']=after['kind'][0]
    require(after['kind'][0]==expected,'observed Write count differs from expected (background/retry/loss/setup packets)')
    require(after['pkt']==after['kind'][0],'Rate-control packet count differs from RDMA data count')
    require(after['kind'][1]==after['ack_total'],'positive ACK counter inconsistent')
    require(not any(after['kind'][2:]),'NAK, ingress CNP, unsupported or out-of-scope RoCE present')
    require(after['ack_total']>0 and after['ack_req']>0,'no positive ACK or AckReq samples')
    require(after['rtt_ok']+after['fail_empty']+after['fail_psn']==after['ack_total'],'ACK outcome partition inconsistent')
    require(after['ack_req']<=after['kind'][0],'AckReq exceeds observed data')
    require(after['rtt_count']==after['rtt_ok'] and after['rtt_count']>0,'RTT count inconsistent/empty')
    require(after['applied_rtt_samples'] == after['rtt_count'], 'Live controller did not consume every accepted RTT')
    require(after['budget_writes'] > before['budget_writes'], 'No control budget writes during run')
    require(traffic.get('qp_gate',{}).get('endpoints',{}).get('client',{}).get('timeout_exponents')==[14]*traffic['flows'], 'Unqualified QP RTO')
    row.update(applied_rtt_samples=after['applied_rtt_samples'],budget_writes=after['budget_writes']-before['budget_writes'],
               max_epoch_us=after['max_epoch_us'],filter_rejects=after['fail_empty'],
               identity_match_pct=100*(after['rtt_ok']+after['fail_empty'])/after['ack_total'] if after['ack_total'] else None)
    require(after.get('ambiguous_control_reads',0)==before.get('ambiguous_control_reads',0),'control sum cannot be uniquely unwrapped')
    for name, end in traffic.get('after_nic',{}).items():
        start=traffic.get('before_nic',{}).get(name)
        suffix=name.split('/')[-1]
        if start is not None and end!=start and suffix in {
            'packet_seq_err','out_of_sequence','local_ack_timeout_err','implied_nak_seq_err',
            'roce_adp_retrans','req_cqe_error','resp_cqe_error','req_remote_access_errors',
            'req_remote_invalid_request','rx_icrc_encapsulated','port_rcv_errors','port_xmit_discards'}:
            issues.append(f'NIC error/retransmit counter changed: {name} {end-start}')
        if '/physical/' in name and suffix not in ('rx_packets_phy','tx_packets_phy') and end!=start:
            issues.append(f'Physical link error/pause/discard changed: {name} {end-start}')
    # Independent NIC counters check both switch observations and message construction.
    def nic_delta(name):
        begin=traffic.get('before_nic',{}).get(name)
        end=traffic.get('after_nic',{}).get(name)
        require(begin is not None and end is not None, 'missing NIC evidence: '+name)
        if begin is None or end is None: return None
        require(end>=begin, 'NIC counter reset: '+name)
        return end-begin
    # Independent NIC evidence is mandatory, including offline audit.
    background={}
    for dev in ('client','server'):
        try:background[dev]=account_background(traffic.get('before_nic',{}),traffic.get('after_nic',{}),dev)
        except ValueError as exc:issues.append(str(exc))
    row['background']=background
    row['timing_has_background']=any(v['frames'] for v in background.values()) if len(background)==2 else None
    checks={
        'client/counters/port_xmit_packets':row['data_packets_observed'],
        'server/counters/port_rcv_packets':row['data_packets_observed'],
        'server/hw_counters/rx_write_requests':messages,
        'server/counters/port_xmit_packets':after['ack_total']+after['kind'][2]+after['kind'][3],
        'client/counters/port_rcv_packets':after['ack_total']+after['kind'][2]+after['kind'][3]+after['cnp_generated'],
        'client/hw_counters/rp_cnp_handled':after['cnp_generated'],
        'client/hw_counters/rp_cnp_ignored':0,
        'client/physical/tx_packets_phy':row['data_packets_observed']+background.get('client',{}).get('frames',0),
        'server/physical/rx_packets_phy':row['data_packets_observed'],
        'server/physical/tx_packets_phy':after['ack_total']+background.get('server',{}).get('frames',0),
        'client/physical/rx_packets_phy':after['ack_total']+after['cnp_generated'],
    }
    for name,expected_value in checks.items():
        require(nic_delta(name)==expected_value,'NIC/switch counts disagree: '+name)
    count=after['rtt_count']
    rttsum=after['rtt_sum_ns_mod32_samples']
    require((count>0 or rttsum==0) and rttsum<=count*(2**32-1),'RTT cumulative sum invalid')
    row['rtt_sample_weighted_mean_us_mod32']=rttsum/count/1000 if count else None
    def ratio(a,b): return a/b if b else None
    row.update(ack_per_ackreq=ratio(row['ack_total'],row['ack_req']),
               ackreq_per_data=ratio(row['ack_req'],row['data_packets_observed']),
               data_per_ack=ratio(row['data_packets_observed'],row['ack_total']),
               match_pct=100*row['rtt_ok']/row['ack_total'] if row['ack_total'] else None,
               integrity_ok=not issues,issues=issues)
    return row


def validate_guard(after, guard, active=None):
    collect.validate(guard, active=active)
    for k in ['pid','boot_us','pipe','build_id']:
        if guard[k] != after[k]: raise ValueError('Guard identity changed: '+k)
    if guard['nonce'] == after['nonce'] or guard['start_us'] <= after['end_us']:
        raise ValueError('Stale/overlapping guard')
    for k in COUNTERS+['kind','rtt_sum_ns_mod32_samples','ambiguous_control_reads','applied_rtt_samples']:
        if guard[k] != after[k]: raise ValueError('State changed after post-run snapshot: '+k)


def append_csv(path, row):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+',newline='') as f:
        fcntl.flock(f,fcntl.LOCK_EX); f.seek(0)
        header=next(csv.reader(f),None)
        if header is not None and header!=COLUMNS:
            raise ValueError('CSV schema differs; preserve legacy CSV and use a v2 path')
        f.seek(0,2); writer=csv.DictWriter(f,fieldnames=COLUMNS,extrasaction='ignore')
        if header is None: writer.writeheader()
        writer.writerow({k:json.dumps(v,separators=(',',':')) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',required=True)
    timing=ap.add_mutually_exclusive_group(required=True)
    timing.add_argument('--iters',type=int);timing.add_argument('--duration',type=int)
    ap.add_argument('--flows',type=int,default=1); ap.add_argument('--size',type=int,default=65536)
    ap.add_argument('--rate-gbps',type=float,default=0); ap.add_argument('--rep',type=int,default=1)
    ap.add_argument('--settle',type=float,default=1)
    ap.add_argument('--csv',default=str(RESULTS_DIR/'closed-loop.csv'))
    ap.add_argument('--rawdir',default=str(RESULTS_DIR/'raw'))
    args=ap.parse_args()
    if not re.fullmatch(r'paper-loop-[A-Za-z0-9_-]+', args.config):
        ap.error('Invalid build tag')
    traffic_commands(args.iters,args.flows,args.rate_gbps,args.size,args.duration)
    lock=open('/tmp/gscc-experiment-local.lock','w'); fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    run_id=uuid.uuid4().hex
    root=Path(args.rawdir)/args.config/run_id; root.mkdir(parents=True)
    rec=dict(schema=SCHEMA,run_id=run_id,rep=args.rep,started_ns=time.time_ns(),requested=vars(args))
    active=None
    try:
        active=deploy.deploy(args.config)
        rec.update(deployment=active,cfg=active['cfg'])
        before=collect.snapshot(active); rec['before']=before
        if any(before['kind']): raise ValueError('Baseline contains traffic; refusing trial')
        traffic=run_traffic(args.iters,args.flows,args.rate_gbps,args.size,run_id,root/'traffic',duration_s=args.duration)
        rec['traffic']=traffic
        time.sleep(max(args.settle,.5))
        after=collect.snapshot(active); rec['after']=after
        time.sleep(.5)
        guard=collect.snapshot(active); rec['after_guard']=guard
        validate_guard(after,guard,active)
        rec['row']=scientific_row(rec['cfg'],before,after,traffic,run_id,args.rep)
    except Exception as exc:
        rec['error']=str(exc)
        if 'row' in rec:
            rec['row']['integrity_ok']=False
            rec['row']['issues'].append('Trial incomplete: '+str(exc))
    finally:
        rec['ended_ns']=time.time_ns()
        if active:
            try: pull_file(testbed()['switch_ssh'],active['deployment_dir']+'/controller.log',root/'controller.log')
            except Exception as exc: rec['log_error']=str(exc)
        (root/'trial.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2))
    if 'row' in rec: append_csv(args.csv,rec['row'])
    emit(rec.get('row',{'run_id':run_id,'integrity_ok':False,'error':rec.get('error'),'raw':str(root)}))
    return 0 if rec.get('row',{}).get('integrity_ok') else 1


if __name__=='__main__': sys.exit(main())
