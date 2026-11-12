#!/usr/bin/env python3
"""Read-only identity of the test ports; never require host IPv6 changes."""
import json
from pathlib import Path
import subprocess



def read_environment(endpoints):
    out = {}
    for role, endpoint in endpoints.items():
        device, iface = endpoint["device"], endpoint["interface"]
        net = Path('/sys/class/net') / iface
        ipv6 = Path('/proc/sys/net/ipv6/conf') / iface
        gids = Path('/sys/class/infiniband') / device / 'ports/1'
        addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr', 'show', 'dev', iface], text=True))
        out[role] = dict(
            device=device,
            ipv4=sorted(addr["local"] for port in addresses for addr in port.get("addr_info", [])),
            interface=iface,
            device_interfaces=sorted(p.name for p in
                (Path('/sys/class/infiniband') / device / 'device/net').iterdir()),
            mac=(net / 'address').read_text().strip(),
            mtu=int((net / 'mtu').read_text()),
            ipv6={key: int((ipv6 / key).read_text()) for key in
                  ('disable_ipv6', 'router_solicitations', 'accept_ra', 'autoconf')},
            gids={p.name: dict(gid=p.read_text().strip(),
                              type=(gids / 'gid_attrs/types' / p.name).read_text().strip())
                  for p in (gids / 'gids').iterdir()
                  if p.read_text().strip() != '0000:0000:0000:0000:0000:0000:0000:0000'})
    return out


def validate_environment(env, endpoints):
    if set(endpoints) != {'client', 'server'}:
        raise ValueError('Missing client/server testbed evidence')
    for role, endpoint in endpoints.items():
        device, iface = endpoint["device"], endpoint["interface"]
        record = env.get(role, {})
        if (record.get('device') != device or record.get('interface') != iface or
                iface not in record.get('device_interfaces', []) or endpoint['ip'] not in record.get('ipv4', [])):
            raise ValueError('Missing or changed RDMA/network interface mapping: ' + device)
        if not all(key in record.get('ipv6', {}) for key in
                   ('disable_ipv6', 'router_solicitations', 'accept_ra', 'autoconf')):
            raise ValueError('Incomplete network configuration evidence: ' + iface)
    # IPv6 state is recorded, not changed. Actual background frames are
    # accounted independently using protocol, host-stack and physical counters.
    return env


if __name__ == '__main__':
    import sys
    endpoints = json.loads(sys.argv[1])
    print(json.dumps(validate_environment(read_environment(endpoints), endpoints), sort_keys=True))
