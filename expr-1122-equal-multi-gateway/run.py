"""Equal-capacity multi-gateway WebSearch experiments."""
import argparse, importlib.util, json, os, re, subprocess, sys, zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_RUN = ROOT / 'expr-1121-multi-gateway-wan' / 'run.py'
spec = importlib.util.spec_from_file_location('base_run', BASE_RUN)
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
EXTRA = base.EXTRA
TRACE_DEFAULT = ['w-dynamic-150-0','w-dynamic-150-50','w-dynamic-150-100','w-dynamic-150-150']
CASES = {
    # split, cross-return, mirror
    'single-off': (False, False, False),
    'two-same-off': (True, False, False),
    'two-cross-off': (True, True, False),
    'two-cross-on': (True, True, True),
    'two-same-on': (True, False, True),
}

def make_topology(split, cross, mirror):
    topo = json.loads(base.BASE.read_text())
    sites = {site['as_id']: site for site in topo['as_topologies']}
    dc3 = sites[3]
    # Add the second gateway only for dual-gateway cases.
    if split:
        dc3['extra_dci_switches'] = [EXTRA]
        copied = [dict(link, src=EXTRA) for link in dc3['links'] if link['src'] == dc3['dci_switch']]
        dc3['links'].extend(copied)
        topo['wan_links'].extend([dict(link, src=EXTRA) for link in topo['wan_links']
                                  if link['src'] == dc3['dci_switch']])
        # Preserve total DC3-to-WAN capacity: 400G becomes 200G + 200G.
        for link in dc3['links']:
            if link['src'] == EXTRA or (link['src'] == dc3['dci_switch'] and link['dst'] == 226):
                link['bw'] = '200Gbps'
        for link in topo['wan_links']:
            if link['src'] in (dc3['dci_switch'], EXTRA) and link['dst'] == 226:
                link['bw'] = '200Gbps'
        # Fixed paths make the gateway assignment reproducible. The same hash
        # chooses the forward gateway and the return gateway unless cross=True.
        gateways = (dc3['dci_switch'], EXTRA)
        cores = {site_id: sorted(link['dst'] for link in spec['links']
                  if link['src'] == spec['dci_switch'] and link['dst'] in spec['switches'])
                 for site_id, spec in sites.items()}
        access = {link['src']: link['dst'] for link in topo['wan_links']
                  if link['src'] in {s['dci_switch'] for s in sites.values()} | {EXTRA}}
        core_nodes = set(topo['wan_switches'])
        backbone = [link for link in topo['wan_links'] if {link['src'], link['dst']} <= core_nodes]
        backbone_paths = {site_id: base.local_path({'switches': core_nodes, 'links': backbone, 'dci_switch': -1},
                          access[gateways[0]], access[spec['dci_switch']], access[spec['dci_switch']])
                          for site_id, spec in sites.items() if site_id != 3}
        paths = topo['pinned_wan_paths'] = []
        for site_id, spec in sites.items():
            if site_id == 3: continue
            remote_gw = spec['dci_switch']
            for local in dc3['hosts']:
                for remote in spec['hosts']:
                    choice = zlib.crc32(f'{local}:{remote}'.encode())
                    local_core = cores[3][(choice >> 1) % len(cores[3])]
                    remote_core = cores[site_id][(choice >> 3) % len(cores[site_id])]
                    fi = choice & 1
                    forward_gw = gateways[fi]
                    return_gw = gateways[fi ^ int(cross)]
                    left = base.local_path(dc3, local, forward_gw, local_core)
                    right = base.local_path(spec, remote, remote_gw, remote_core)
                    return_left = base.local_path(dc3, local, return_gw, local_core)
                    bp = backbone_paths[site_id]
                    paths.extend([left + bp + right[::-1], right + bp[::-1] + return_left[::-1]])
        if mirror:
            dc3['links'].append({'src': dc3['dci_switch'], 'dst': EXTRA, 'bw': '100Gbps', 'delay': '2us', 'loss': 0.0})
    topo['wan_link_num'] = len(topo['wan_links'])
    return topo

def prepare(trace, case, seed):
    split, cross, mirror = CASES[case]
    tag = f'eq1122-{trace}-{case}-s{seed}'
    topo = make_topology(split, cross, mirror)
    path = ROOT / 'config' / f'{tag}.txt'; path.write_text(json.dumps(topo, indent=2) + '\n')
    args = [sys.executable, '-u', 'run.py', '--skip-build', '1', '--prepare-only', '--topo', tag,
            '--my_flow', trace, '--tcp_flow', '', '--simul_time', '0.2', '--wan_cc_mode', '1',
            '--cc', 'dcqcn', '--lb', 'fecmp', '--msg', tag]
    extras = {'RANDOM_SEED': seed, 'WAN_ACK_MIRROR': int(mirror), 'WAN_TRACE_RTT_MATCH': 1,
              'GSCC_ACK_TS': 'TRUE', 'ENABLE_W': 'TRUE', 'INV_DELTA': 6291456, 'W_MAX': 4,
              'BETA': 0.3, 'GUARANTEED_RATE_FACTOR': 0.25, 'WAN_EPOCH_US': 1000,
              'GSCC_FAIR': 'TRUE', 'ENABLE_V': 'TRUE', 'EARLIEST_STOP_SECONDS': 2.35}
    for k,v in extras.items(): args += ['--extra', f'{k}={v}']
    out = subprocess.check_output(args, cwd=ROOT, text=True)
    m = re.search(r'^Config filename:(.+)$', out, re.M)
    if not m or not Path(m[1]).is_file(): raise RuntimeError(out)
    return Path(m[1])

def simulate(config):
    log = config.with_suffix('.log')
    with log.open('w') as f:
        p = subprocess.Popen([str(BINARY), str(config)], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=ENV)
        print(f'started {config.parent.name} pid={p.pid}', flush=True); status = p.wait()
    finished = 'Simulator is enforced to be finished' in log.read_text(errors='replace')
    output = config.parent / 'flow_output'
    if status or not finished or not output.is_file() or not output.stat().st_size:
        raise RuntimeError(f'{config.parent.name} failed exit={status} finished={finished}')
    print(f'finished {config.parent.name}', flush=True)

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--traces', default=','.join(TRACE_DEFAULT));
    p.add_argument('--cases', default=','.join(CASES)); p.add_argument('--seed', type=int, default=1)
    p.add_argument('--jobs', type=int, default=20, choices=range(1,81)); a=p.parse_args(); os.chdir(ROOT)
    BINARY=ROOT/'build/scratch/remote'
    if not os.access(BINARY, os.X_OK): p.error('build scratch/remote before running')
    ENV=os.environ.copy(); ENV['LD_LIBRARY_PATH']=os.pathsep.join(filter(None,(str(ROOT/'build'),ENV.get('LD_LIBRARY_PATH'))))
    configs=[prepare(t,c,a.seed) for t in a.traces.split(',') for c in a.cases.split(',')]
    with ThreadPoolExecutor(max_workers=a.jobs) as ex: list(ex.map(simulate, configs))
