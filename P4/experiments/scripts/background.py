"""Account identified host IPv6 control traffic separately from measured RDMA.

No packet-count tolerance is used. Unknown traffic, reset counters or missing
evidence fail. Passing this accounting does not prove zero timing disturbance.
"""

HOST_COUNTERS = {
    'tx_packets', 'tx_bytes',
    'tx_vport_unicast_packets', 'tx_vport_unicast_bytes',
    'tx_vport_multicast_packets', 'tx_vport_multicast_bytes',
    'tx_vport_broadcast_packets', 'tx_vport_broadcast_bytes',
    'tx_multicast_phy', 'tx_broadcast_phy', 'tx_mac_control_phy',
}
IPV6_COUNTERS = {
    'Ip6OutRequests', 'Ip6OutMcastPkts', 'Ip6OutOctets', 'Ip6OutMcastOctets',
    'Icmp6OutMsgs', 'Icmp6OutErrors', 'Icmp6OutRouterSolicits',
    'Icmp6OutMLDv2Reports', 'Icmp6OutType133', 'Icmp6OutType143',
}


def rdma_counters(record):
    return {k: v for k, v in record.items() if '/counters/' in k or '/hw_counters/' in k}


def account_background(before, after, dev):
    def delta(group, name):
        key = dev + '/' + group + '/' + name
        a, b = before.get(key), after.get(key)
        if type(a) is not int or type(b) is not int or b < a:
            raise ValueError('Missing/reset background counter: ' + key)
        return b-a

    host = {k: delta('host', k) for k in HOST_COUNTERS}
    ip = {k: delta('ipv6', k) for k in IPV6_COUNTERS}
    rs, mld = ip['Icmp6OutRouterSolicits'], ip['Icmp6OutMLDv2Reports']
    frames = rs + mld
    expected = {
        'Ip6OutRequests': frames, 'Ip6OutMcastPkts': frames,
        'Icmp6OutMsgs': frames, 'Icmp6OutErrors': 0,
        'Icmp6OutType133': rs, 'Icmp6OutType143': mld,
        'Ip6OutMcastOctets': ip['Ip6OutOctets'],
    }
    for name, count in expected.items():
        if ip[name] != count:
            raise ValueError('Unclassified IPv6 traffic: ' + dev + '/' + name)
    octets = ip['Ip6OutOctets']
    # RS size is observed as 56 IPv6 bytes on this testbed. MLDv2 can vary;
    # its actual byte total is retained rather than assumed to be one size.
    if (not frames and octets) or octets < rs*56 + mld*48 or (not mld and octets != rs*56):
        raise ValueError('IPv6 control byte count inconsistent: ' + dev)
    ethernet_bytes = octets + 14*frames
    expected_host = dict(tx_packets=frames, tx_bytes=ethernet_bytes,
                         tx_vport_unicast_packets=0, tx_vport_unicast_bytes=0,
                         tx_vport_multicast_packets=frames, tx_vport_multicast_bytes=ethernet_bytes,
                         tx_vport_broadcast_packets=0, tx_vport_broadcast_bytes=0,
                         tx_multicast_phy=frames, tx_broadcast_phy=0, tx_mac_control_phy=0)
    for name, count in expected_host.items():
        if host[name] != count:
            raise ValueError('Host/IPv6/physical background counts disagree: '+dev+'/'+name)
    # Ethernet header + FCS + preamble/SFD + IFG = 14 + 4 + 8 + 12 bytes.
    wire_bytes = octets + 38*frames
    return dict(router_solicitations=rs, mldv2_reports=mld, frames=frames,
                ipv6_bytes=octets, wire_bytes=wire_bytes,
                serialization_ns_at_100g=wire_bytes*8/100)


def validate_idle_guard(before, after):
    """RDMA must be stopped; explicitly account any control frames after its window."""
    if not rdma_counters(before) or rdma_counters(before) != rdma_counters(after):
        raise ValueError('RDMA counters changed across final idle guard')
    result = {}
    for dev in ('client', 'server'):
        result[dev] = account_background(before, after, dev)
        for key in before:
            if key.startswith(dev+'/physical/'):
                expected = result[dev]['frames'] if key.endswith('/tx_packets_phy') else 0
                if key not in after or after[key]-before[key] != expected:
                    raise ValueError('Unexplained physical activity across final guard: '+key)
    return result
