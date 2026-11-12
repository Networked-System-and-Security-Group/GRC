#!/usr/bin/env python3
"""Request one atomic, nonce-addressed snapshot from the v2 controller."""
import argparse
import json
import shlex
import time
import uuid
from common import emit, ssh, testbed
from semantics import SCHEMA


def deployment():
    bed = testbed()
    return json.loads(ssh(bed['switch_ssh'], 'cat ' + shlex.quote(bed['switch_work'] + '/active.json')))


def validate(s, nonce=None, active=None):
    if s.get('schema') != SCHEMA:
        raise ValueError('Legacy or unknown snapshot schema')
    for field, n in [('kind', 8), ('k_hist', 64), ('off_hist', 132)]:
        if len(s.get(field, [])) != n:
            raise ValueError('Incomplete ' + field)
        if any(type(v) != int or not 0 <= v < 2**32 for v in s[field]):
            raise ValueError('Invalid counter ' + field)
    for field in ['ack_req','ack_total','rtt_ok','fail_empty','fail_psn','pkt','cnp_generated','rtt_count']:
        if type(s.get(field)) != int or not 0 <= s[field] < 2**32:
            raise ValueError('Missing or invalid ' + field)
    if type(s.get('rtt_sum_ns_mod32_samples')) != int or not 0 <= s['rtt_sum_ns_mod32_samples'] < 2**64:
        raise ValueError('Invalid RTT sum')
    if not s.get('quiet') or s['end_us'] <= s['start_us'] or type(s.get('pipe')) is not int or s['pipe'] not in range(4):
        raise ValueError('Snapshot not quiet / invalid time / pipe')
    if nonce is not None and s.get('nonce') != nonce:
        raise ValueError('Stale snapshot nonce')
    if active and (s.get('build_id') != active['build_id'] or s.get('pid') != active['pid'] or s['pipe'] != active['pipe']):
        raise ValueError('Snapshot does not belong to deployed binary')
    return s


def snapshot(active=None, timeout=30):
    active = active or deployment()
    switch = testbed()['switch_ssh']
    nonce = uuid.uuid4().hex
    root = active['snapshot_dir']
    req = shlex.quote(root + '/request')
    tmp = shlex.quote(root + '/' + nonce + '.request')
    dest = shlex.quote(root + '/' + nonce + '.json')
    ssh(switch, f'printf %s {nonce} > {tmp} && mv {tmp} {req}')
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        raw = ssh(switch, f'if test -f {dest}; then cat {dest}; fi')
        if raw.strip():
            return validate(json.loads(raw), nonce, active)
        time.sleep(.2)
    raise TimeoutError('No complete controller snapshot for ' + nonce)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    emit(snapshot())
