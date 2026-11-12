#!/usr/bin/env python3
"""Record small ASIC smoke trials and check that the same testbed is still in use."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

from build import fingerprint
from common import REPO_ROOT, RESULTS_DIR, load_matrix, ssh, testbed
from run import script_provenance

MATRIX = REPO_ROOT / 'matrix.yaml'
READINESS = REPO_ROOT / 'readiness.json'
ARTIFACTS = {'bf-rt.json', 'build/gs_pipe/context.json', 'build/gs_pipe/tofino2.bin', 'ctrl/ctrl'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def network_environment():
    bed = testbed()
    source = Path(__file__).with_name('network_environment.py').read_text()
    command = 'python3 - ' + shlex.quote(json.dumps(bed['endpoints']))
    return json.loads(ssh(bed['traffic_ssh'], command + " <<'GSCC_NETWORK_PY'\n" + source + '\nGSCC_NETWORK_PY'))


def environment_identity():
    bed = testbed()
    switch, traffic = bed['switch_ssh'], bed['traffic_ssh']
    sdk = bed['sde_install']
    ssh(switch, f'test -c /dev/bf0 && test -x {sdk}/bin/bf-p4c && test -r {bed["switchd_conf"]}')
    ssh(traffic, 'command -v ib_write_bw && command -v gcc && command -v ethtool && command -v ip')
    if ssh(switch, "pgrep -x 'bf-p4c|bf-p4c-tofino|bf-p4c-tofino2|p4c-barefoot|cc1|gcc' || true").strip():
        raise ValueError('Switch compiler active')
    if ssh(traffic, 'pgrep -x ib_write_bw || true').strip():
        raise ValueError('Existing traffic process; do not mix runs')
    nic_firmware = {role: ssh(traffic, f"cat /sys/class/infiniband/{ep['device']}/fw_ver").strip()
                    for role, ep in bed['endpoints'].items()}
    return dict(network=network_environment(), kernel=ssh(traffic, 'uname -r').strip(),
                firmware=nic_firmware,
                perftest=ssh(traffic, 'sha256sum "$(command -v ib_write_bw)"').split()[0],
                switch_driver=ssh(switch, f'sha256sum {sdk}/lib/libdriver.so').split()[0],
                switchd_conf=ssh(switch, f'sha256sum {bed["switchd_conf"]}').split()[0])


def manifest(matrix_path, online):
    builds = {}
    for cfg in load_matrix(matrix_path)['p4']:
        tag = cfg['tag']
        build = json.loads((REPO_ROOT / 'builds' / tag / 'build.json').read_text())
        source_id = fingerprint(cfg['buckets'], cfg['slots'], cfg['window'])
        expected = build['artifacts_sha256']
        if (not build['p4c_ok'] or not build['ctrl_ok'] or build['source_id'] != source_id or
                set(expected) != ARTIFACTS):
            raise ValueError(f'Incomplete or stale build: {tag}')
        if online:
            remote = shlex.quote(build['remote_dir'])
            names = ' '.join(map(shlex.quote, sorted(expected)))
            output = ssh(testbed()['switch_ssh'], f'cd {remote} && sha256sum {names}')
            if dict((name, checksum) for checksum, name in map(str.split, output.splitlines())) != expected:
                raise ValueError(f'Remote artifacts changed: {tag}')
        builds[tag] = {'source_id': source_id, 'artifacts_sha256': expected}
    return dict(matrix_sha256=digest(matrix_path), scripts_sha256=script_provenance()['sha256'], builds=builds)


def check(matrix_path=MATRIX, online=True):
    if not READINESS.is_file():
        raise ValueError('Run scripts/preflight.py --qualify on this testbed before launching the matrix.')
    ready = json.loads(READINESS.read_text())
    if manifest(matrix_path, online) != ready['manifest']:
        raise ValueError('Matrix, scripts or builds changed; repeat the ASIC smoke checks.')
    if online and environment_identity() != ready['environment']:
        raise ValueError('Testbed identity changed; repeat the ASIC smoke checks.')
    return {'smoke_passed': True, 'builds': len(ready['manifest']['builds'])}


def qualify(matrix_path):
    READINESS.unlink(missing_ok=True)
    before = environment_identity()
    expected = manifest(matrix_path, online=True)
    smoke = RESULTS_DIR / 'smoke' / uuid.uuid4().hex
    for cfg in load_matrix(matrix_path)['p4']:
        base = [sys.executable, str(REPO_ROOT / 'scripts/run.py'), '--config', cfg['tag'],
                '--flows', '1', '--size', '65536', '--csv', str(smoke / 'trials.csv'), '--rawdir', str(smoke / 'raw')]
        subprocess.run(base + ['--iters', '1000'], cwd=REPO_ROOT, check=True)
        if 'rate' in cfg.get('sweeps', []):
            subprocess.run(base + ['--duration', '5', '--rate-gbps', '1'], cwd=REPO_ROOT, check=True)
    if environment_identity() != before or manifest(matrix_path, online=True) != expected:
        raise ValueError('Testbed, build or scripts changed during smoke checks')
    READINESS.write_text(json.dumps(dict(manifest=expected, environment=before, smoke=str(smoke.relative_to(REPO_ROOT))),
                                    indent=2) + '\n')
    return {'smoke_passed': True, 'builds': len(expected['builds'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true')
    mode.add_argument('--environment-only', action='store_true')
    mode.add_argument('--qualify', action='store_true', help='Run bounded real-hardware smoke trials before the sweep')
    parser.add_argument('--matrix', type=Path, default=MATRIX)
    args = parser.parse_args()
    if args.qualify:
        result = qualify(args.matrix)
    elif args.environment_only:
        result = environment_identity()
    else:
        result = check(args.matrix, online=not args.offline)
    print(json.dumps(result))
