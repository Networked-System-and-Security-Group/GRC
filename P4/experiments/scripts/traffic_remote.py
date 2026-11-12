#!/usr/bin/env python3
"""Remote traffic worker. Only terminates child processes created by this run."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from network_environment import read_environment, validate_environment
from background import HOST_COUNTERS, IPV6_COUNTERS, rdma_counters, validate_idle_guard


def counters(endpoints):
    out = {}
    for role, endpoint in endpoints.items():
        dev, iface = endpoint["device"], endpoint["interface"]
        root = Path('/sys/class/infiniband') / dev / 'ports/1'
        for group in ('counters','hw_counters'):
            for p in (root/group).glob('*'):
                try:
                    v = p.read_text().strip()
                    if v.isdigit(): out[f'{role}/{group}/{p.name}'] = int(v)
                except OSError:
                    pass
        raw=subprocess.run(['ethtool','-S',iface],capture_output=True,text=True,check=True).stdout
        required={'tx_packets_phy','rx_packets_phy','rx_crc_errors_phy','rx_discards_phy',
                  'tx_discards_phy','tx_errors_phy','rx_pause_ctrl_phy','tx_pause_ctrl_phy'}
        found=set()
        for line in raw.splitlines():
            name,sep,value=line.strip().partition(':')
            if sep and name in required | HOST_COUNTERS:
                group='physical' if name in required else 'host'
                out[f'{role}/{group}/{name}']=int(value);found.add(name)
        if found!=required | HOST_COUNTERS:raise RuntimeError('Missing NIC counters: '+str((required | HOST_COUNTERS)-found))
        found=set()
        for line in (Path('/proc/net/dev_snmp6')/iface).read_text().splitlines():
            name,value=line.split()
            if name in IPV6_COUNTERS:
                out[f'{role}/ipv6/{name}']=int(value);found.add(name)
        if found!=IPV6_COUNTERS:raise RuntimeError('Missing IPv6 protocol counters')
    return out


def quiet_counters(endpoints, include_physical=True):
    """Require two idle samples beyond the mlx5 cache lifetime; never average."""
    first = counters(endpoints)
    time.sleep(.1)
    second = counters(endpoints)
    if (first!=second if include_physical else rdma_counters(first)!=rdma_counters(second)):
        raise RuntimeError('NIC counters changed across the idle guard')
    return first, second


def gate_idle_counters(endpoints):
    """Record startup frames; take stable boundaries while QPs cannot send."""
    start=time.monotonic();quiet_since=start;previous=counters(endpoints);events=[]
    while time.monotonic()-start<90:
        time.sleep(1)
        current=counters(endpoints);now=time.monotonic()
        changes={k:current[k]-previous[k] for k in current if current[k]!=previous[k]}
        if changes:
            events.append(dict(elapsed_s=now-start,changes=changes));quiet_since=now
        elif now-quiet_since>=2:
            return previous,current,dict(quiet_s=now-quiet_since,wait_s=now-start,events=events)
        previous=current
    raise RuntimeError('Could not obtain stable counter boundaries while QPs were gated')


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text())
    root = Path(cfg['remote_dir'])
    endpoints = cfg['endpoints']
    result = {'cfg': cfg, 'start_ns': time.time_ns()}
    children=[]
    def stop(*_):
        raise RuntimeError('Traffic worker interrupted')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        lock = open('/tmp/gscc-experiment-traffic.lock', 'w')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if subprocess.run(['pgrep','-x','ib_write_bw'], stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('Existing ib_write_bw; refusing to mix traffic')
        deadline=time.monotonic()+90
        while not all('ACTIVE' in (Path('/sys/class/infiniband')/d/'ports/1/state').read_text() for d in (endpoint['device'] for endpoint in endpoints.values())):
            if time.monotonic()>deadline: raise RuntimeError('RDMA link not ACTIVE')
            time.sleep(1)
        before_guard, before = quiet_counters(endpoints, include_physical=False)
        result.update(before_nic=before, before_nic_guard=before_guard,
                      version=subprocess.run(['ib_write_bw','--version'],capture_output=True,text=True).stdout.strip())
        result['network_before'] = read_environment(endpoints)
        validate_environment(result['network_before'], endpoints)
        if cfg.get('use_qp_gate',True):
            if os.environ.get('LD_PRELOAD'): raise RuntimeError('Unexpected inherited LD_PRELOAD')
            cmd=['gcc','-Wall','-Wextra','-Werror','-O2','-shared','-fPIC','-o',str(root/'qp_gate.so'),str(root/'qp_gate.c'),'-ldl']
            built=subprocess.run(cmd,capture_output=True,text=True)
            (root/'gate-build.log').write_text(built.stdout+built.stderr)
            if built.returncode: raise RuntimeError('QP gate compilation failed')
            result['gate_source_sha256']=hashlib.sha256((root/'qp_gate.c').read_bytes()).hexdigest()
        def endpoint_env(role):
            env=dict(os.environ)
            if cfg.get('use_qp_gate',True):
                env.update(LD_PRELOAD=str(root/'qp_gate.so'),P4SORT_GATE_DIR=str(root),
                           P4SORT_GATE_ROLE=role,P4SORT_GATE_QPS=str(cfg['flows']))
            return env
        with (root/'server.log').open('w') as sf, (root/'client.log').open('w') as cf:
            server = subprocess.Popen(cfg['server_cmd'], stdout=sf, stderr=subprocess.STDOUT, start_new_session=True,env=endpoint_env('server'))
            children.append(server)
            time.sleep(2)
            if server.poll() is not None: raise RuntimeError('Server exited before client')
            client = subprocess.Popen(cfg['client_cmd'], stdout=cf, stderr=subprocess.STDOUT, start_new_session=True,env=endpoint_env('client'))
            children.append(client)
            if cfg.get('use_qp_gate',True):
                deadline=time.monotonic()+120
                while not all((root/(role+'-qp.json')).exists() for role in ('client','server')):
                    if time.monotonic()>deadline or any(p.poll() is not None for p in children):
                        raise RuntimeError('Endpoints did not reach QP startup gate')
                    time.sleep(.05)
                pair_evidence={role:json.loads((root/(role+'-qp.json')).read_text()) for role in ('client','server')}
                gated_guard,gated,idle=gate_idle_counters(endpoints)
                initial=result['before_nic']
                if rdma_counters(gated)!=rdma_counters(initial):
                    raise RuntimeError('RDMA counters changed before QP gate release')
                # Neighbor discovery during connection setup is recorded separately;
                # physical data measurement starts only once both endpoints are gated.
                result['setup_nic']=initial
                result['before_nic']=gated;result['before_nic_guard']=gated_guard
                result['qp_gate']=dict(endpoints=pair_evidence,nic_while_gated=gated,nic_guard=gated_guard,idle=idle)
                temp=root/'gate-ready.tmp';temp.write_text(json.dumps(result['qp_gate']));temp.rename(root/'gate-ready.json')
                deadline=time.monotonic()+180
                while not (root/'release').exists():
                    if (root/'cancel').exists() or time.monotonic()>deadline:
                        raise RuntimeError('CNP mapping gate was not released')
                    time.sleep(.05)
            start = time.monotonic()
            result['client_rc'] = client.wait(timeout=cfg['timeout_s'])
            result['wall_s'] = time.monotonic()-start
            result['server_rc'] = server.wait(timeout=30)
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        for p in children:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL); p.wait()
        result['child_returncodes']=[p.returncode for p in children]
        time.sleep(.1)
        result['after_nic'] = counters(endpoints)
        time.sleep(.1)
        result['after_nic_guard'] = counters(endpoints)
        try:
            result['post_window_background'] = validate_idle_guard(result['after_nic'],result['after_nic_guard'])
        except ValueError as exc:
            result['error'] = result.get('error','') + ' ' + str(exc)
        try:
            result['network_after'] = read_environment(endpoints)
            validate_environment(result['network_after'], endpoints)
            if result.get('network_before') != result['network_after']:
                raise ValueError('Test-port network configuration changed during measurement')
        except Exception as exc:
            result['error'] = result.get('error', '') + ' ' + str(exc)
        result['end_ns'] = time.time_ns()
        (root/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
    return 0 if result.get('client_rc') == result.get('server_rc') == 0 and 'error' not in result else 1


if __name__ == '__main__':
    sys.exit(main())
