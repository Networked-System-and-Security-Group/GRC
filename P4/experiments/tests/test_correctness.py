"""Independent arithmetic and rejection oracles; hardware semantics tested separately."""
import copy
import importlib.util
import random
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from semantics import classify_ranges, offset_bins, split_range32, EMPTY_PSN, SCHEMA
from deploy import validate_context
from run import scientific_row
from traffic import parse_client, validate_qp_pairs, traffic_commands
from matrix import build_plan
from common import load_matrix, REPO_ROOT, topology_header, validate_testbed
from background import HOST_COUNTERS, IPV6_COUNTERS


ENDPOINTS = {
    'client': dict(device='rdma_a',interface='net_a',ip='192.0.2.1',switch_port=0),
    'server': dict(device='rdma_b',interface='net_b',ip='192.0.2.2',switch_port=8),
}


class TestbedTests(unittest.TestCase):
    def test_requires_two_distinct_ports_on_one_pipe(self):
        cfg=dict(switch_ssh='switch-example',traffic_ssh='traffic-example',
                 endpoints=copy.deepcopy(ENDPOINTS),bfrt_pythonpath=[])
        for k in ('switch_work','traffic_work','sde','sde_install','switchd_conf','bfrt_python'):
            cfg[k]='/example/'+k
        self.assertEqual(validate_testbed(cfg),cfg)
        self.assertIn('GSCC_CLIENT_IPV4 32w0xc0000201',topology_header(cfg['endpoints']))
        cfg['endpoints']['server']['switch_port']=128
        with self.assertRaisesRegex(ValueError,'same Tofino2 pipe'):
            validate_testbed(cfg)


class OffsetTests(unittest.TestCase):
    def test_partition_and_full_width_matches(self):
        rng=random.Random(92031)
        for slots,window in [(16,0),(16,16),(16,32),(16,64),(32,0),(64,0),(128,0)]:
            ranges=classify_ranges(slots,window); bins=offset_bins(slots)
            for (lo,hi,*_),nxt in zip(ranges,ranges[1:]): self.assertLess(hi,nxt[0])
            self.assertEqual(sum(hi-lo+1 for lo,hi,*_ in ranges),2*(2**24-1)+1)
            vectors=[(0,0),(0,2**24-16),(2**24-16,0),(2**23,0),(0,2**23)]
            for d in [0,1,-1,16,-16,32,-32,64,-64,65,-65,1024,-1024,2048,-2048,65535,-65535,65536,-65536]:
                vectors.append((100000+d,100000))
            vectors += [(rng.randrange(2**24),rng.randrange(2**24)) for _ in range(15000)]
            for ack, stored in vectors:
                signed=ack-stored
                if signed>=2**23: signed-=2**24
                if signed<-(2**23): signed+=2**24
                d=(stored-ack)&0xffffffff
                matches=[(bucket,hit) for lo,hi,bucket,hit in ranges if lo<=d<=hi]
                self.assertEqual(len(matches),1)
                bucket,hit=matches[0]
                self.assertEqual(bool(hit),abs(signed)<=window)
                self.assertLessEqual(bins[bucket]['lo'],signed); self.assertGreaterEqual(bins[bucket]['hi'],signed)
            for ack in (0,1,2**24-1):
                self.assertFalse(any(lo<=(EMPTY_PSN-ack)&0xffffffff<=hi for lo,hi,*_ in ranges))

    def test_rectangles_preserve_range(self):
        rng=random.Random(12)
        for lo,hi,*_ in classify_ranges(16,64):
            rect=split_range32(lo,hi)
            self.assertEqual(sum((b-a+1)*(d-c+1) for a,b,c,d in rect),hi-lo+1)
            for v in [lo,hi,max(0,lo-1),min(2**32-1,hi+1),rng.randrange(lo,hi+1)]:
                matches=sum(a<=v>>16<=b and c<=v&65535<=d for a,b,c,d in rect)
                self.assertEqual(matches,int(lo<=v<=hi))


def fixture():
    before=dict(schema=SCHEMA,nonce='a',build_id='abc',pid=7,boot_us=1,pipe=3,start_us=2,end_us=3,
                quiet=True,kind=[0]*8,k_hist=[0]*64,off_hist=[0]*132,rtt_sum_ns_mod32_samples=0,
                ack_req=0,ack_total=0,rtt_ok=0,fail_empty=0,fail_psn=0,pkt=0,cnp_generated=0,rtt_count=0,
                ambiguous_control_reads=0,rtt_max_ns=0)
    after=copy.deepcopy(before);after.update(nonce='b',start_us=4,end_us=5,ack_req=10,ack_total=8,rtt_ok=6,
        fail_empty=1,fail_psn=1,pkt=648,rtt_count=6,rtt_sum_ns_mod32_samples=12000,rtt_max_ns=2000)
    after['kind'][0:2]=[640,8];after['k_hist'][1]=8;after['off_hist'][0]=6;after['off_hist'][2]=1
    traffic=dict(iters=10,flows=1,size=65536,mtu=1024,rate_gbps=0,ok=True)
    network={role:dict(device=e['device'],interface=e['interface'],device_interfaces=[e['interface']],
                       ipv4=[e['ip']],ipv6=dict(disable_ipv6=0,router_solicitations=-1,accept_ra=0,autoconf=1))
             for role,e in ENDPOINTS.items()}
    traffic.update(endpoints=ENDPOINTS,network_before=network,network_after=copy.deepcopy(network))
    traffic['before_nic']={
        'client/counters/port_xmit_packets':0,'server/counters/port_rcv_packets':0,
        'server/hw_counters/rx_write_requests':0,'server/counters/port_xmit_packets':0,
        'client/counters/port_rcv_packets':0,'client/hw_counters/rp_cnp_handled':0,
        'client/hw_counters/rp_cnp_ignored':0}
    traffic['after_nic']=dict(zip(traffic['before_nic'],[640,640,10,8,8,0,0]))
    physical={'client/physical/tx_packets_phy':640,'server/physical/rx_packets_phy':640,
              'server/physical/tx_packets_phy':8,'client/physical/rx_packets_phy':8}
    traffic['before_nic'].update({k:0 for k in physical});traffic['after_nic'].update(physical)
    for dev in ENDPOINTS:
        for group,names in [('host',HOST_COUNTERS),('ipv6',IPV6_COUNTERS)]:
            for name in names:
                traffic['before_nic'][dev+'/'+group+'/'+name]=0
                traffic['after_nic'][dev+'/'+group+'/'+name]=0
    pairs=[dict(local=123,remote=456)]
    traffic.update(use_qp_gate=True,cnp_mapping=dict(installed=True,run_id='id',pairs=pairs),
        before_nic_guard=copy.deepcopy(traffic['before_nic']),after_nic_guard=copy.deepcopy(traffic['after_nic']),
        qp_gate=dict(endpoints=dict(client=dict(pairs=pairs),server=dict(pairs=[dict(local=456,remote=123)])),
                     nic_while_gated=copy.deepcopy(traffic['before_nic'])))
    cfg=dict(tag='fixture',buckets=256,slots=16,window=0)
    return cfg,before,after,traffic


class IntegrityTests(unittest.TestCase):
    def test_environment_evidence_without_admin_changes(self):
        cfg,b,a,t=fixture()
        self.assertTrue(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])
        for mutation in (lambda t:t.pop('network_before'),
                         lambda t:t['network_after']['server']['ipv6'].update(accept_ra=2),
                         lambda t:t['network_after']['client'].update(device_interfaces=[])):
            cfg,b,a,t=fixture();mutation(t)
            self.assertFalse(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])

    def test_identified_rs_accounted_unknown_extra_rejected(self):
        cfg,b,a,t=fixture()
        # Independent wire/protocol construction: one 56-byte IPv6 RS is
        # 70 Ethernet bytes, 74 with FCS, 94 including preamble and IFG.
        values={'ipv6/Ip6OutRequests':1,'ipv6/Ip6OutMcastPkts':1,
                'ipv6/Ip6OutOctets':56,'ipv6/Ip6OutMcastOctets':56,
                'ipv6/Icmp6OutMsgs':1,'ipv6/Icmp6OutRouterSolicits':1,
                'ipv6/Icmp6OutType133':1,'host/tx_packets':1,'host/tx_bytes':70,
                'host/tx_vport_multicast_packets':1,'host/tx_vport_multicast_bytes':70,
                'host/tx_multicast_phy':1}
        t['after_nic'].update({'client/'+k:v for k,v in values.items()})
        t['after_nic']['client/physical/tx_packets_phy']+=1
        t['after_nic_guard']=copy.deepcopy(t['after_nic'])
        r=scientific_row(cfg,b,a,t,'id',1)
        self.assertTrue(r['integrity_ok'],r['issues'])
        self.assertTrue(r['timing_has_background'])
        self.assertEqual(r['background']['client']['serialization_ns_at_100g'],7.52)
        self.assertEqual(r['data_packets_observed'],640)
        _,_,_,base=fixture()
        base['after_nic_guard']=copy.deepcopy(t['after_nic'])
        guarded=scientific_row(cfg,b,a,base,'id',1)
        self.assertTrue(guarded['integrity_ok'],guarded['issues'])
        self.assertFalse(guarded['timing_has_background'])
        self.assertEqual(guarded['post_window_background']['client']['frames'],1)
        base['after_nic_guard']['client/counters/port_xmit_packets']+=1
        self.assertFalse(scientific_row(cfg,b,a,base,'id',1)['integrity_ok'])
        for key in ['host/tx_packets','ipv6/Icmp6OutType133','physical/tx_packets_phy']:
            altered=copy.deepcopy(t);altered['after_nic']['client/'+key]+=1
            altered['after_nic_guard']=copy.deepcopy(altered['after_nic'])
            self.assertFalse(scientific_row(cfg,b,a,altered,'id',1)['integrity_ok'])
        t['after_nic'].pop('client/host/tx_bytes')
        t['after_nic_guard']=copy.deepcopy(t['after_nic'])
        self.assertFalse(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])

    def test_weighted_mean_and_observed_not_constructed(self):
        cfg,b,a,t=fixture();r=scientific_row(cfg,b,a,t,'id',1)
        self.assertTrue(r['integrity_ok'],r['issues']);self.assertEqual(r['rtt_sample_weighted_mean_us_mod32'],2)
        a['kind'][0]-=1
        r=scientific_row(cfg,b,a,t,'id',1)
        self.assertFalse(r['integrity_ok']);self.assertEqual(r['data_packets_observed'],639);self.assertEqual(r['data_packets_expected'],640)

    def test_stale_missing_mixed_busy_reset_rejected(self):
        for mutation in [lambda a:a.update(nonce='a'),lambda a:a.update(quiet=False),lambda a:a.update(pid=8),
                         lambda a:a.update(off_hist=[0]),lambda a:a.pop('ack_total'),lambda a:a.update(schema='legacy')]:
            cfg,b,a,t=fixture();mutation(a)
            with self.assertRaises((ValueError,KeyError)): scientific_row(cfg,b,a,t,'id',1)
        cfg,b,a,t=fixture(); b['kind'][0]=1
        with self.assertRaises(ValueError): scientific_row(cfg,b,a,t,'id',1)

    def test_background_nak_corrupt_hist_control_overflow(self):
        for mutation in [lambda a:a['kind'].__setitem__(2,1),lambda a:a['off_hist'].__setitem__(0,5),
                         lambda a:a.update(ambiguous_control_reads=1)]:
            cfg,b,a,t=fixture();mutation(a);self.assertFalse(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])

    def test_physical_background_rejected(self):
        cfg,b,a,t=fixture()
        t['after_nic']['client/physical/rx_packets_phy']+=1
        t['after_nic_guard']=copy.deepcopy(t['after_nic'])
        self.assertFalse(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])
        cfg,b,a,t=fixture()
        t['before_nic']['client/physical/tx_pause_ctrl_phy']=0
        t['after_nic']['client/physical/tx_pause_ctrl_phy']=1
        t['before_nic_guard']=copy.deepcopy(t['before_nic']);t['after_nic_guard']=copy.deepcopy(t['after_nic'])
        t['qp_gate']['nic_while_gated']=copy.deepcopy(t['before_nic'])
        self.assertFalse(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])

    def test_compiler_context_range_alias_rejected(self):
        good={'tables':[{'name':'gs_Ingress.gs_window_table','match_key_fields':[
            {'name':'offset_hi','position':0,'bit_width':16},
            {'name':'offset_lo','position':1,'bit_width':16}]}]}
        validate_context(good)
        for key in ['name','position']:
            bad=copy.deepcopy(good)
            fields=bad['tables'][0]['match_key_fields'];fields[1][key]=fields[0][key]
            with self.assertRaises(ValueError):validate_context(bad)

    def test_client_validation(self):
        good='Mtu : 1024\n 65536 20 1.0 2.0 0.0001\n'
        self.assertEqual(parse_client(good,65536,10,2),2)
        for bad in [good+good,good.replace('20','10'),good.replace('1024','4096'),'']:
            with self.assertRaises(ValueError):parse_client(bad,65536,10,2)

    def test_qp_mapping_and_nic_guards(self):
        for mutation in [lambda t:t['cnp_mapping'].update(pairs=[dict(local=456,remote=123)]),
                         lambda t:t['cnp_mapping'].update(run_id='another'),
                         lambda t:t.update(use_qp_gate=False),
                         lambda t:t['before_nic_guard'].__setitem__('client/counters/port_xmit_packets',1)]:
            cfg,b,a,t=fixture();mutation(t)
            self.assertFalse(scientific_row(cfg,b,a,t,'id',1)['integrity_ok'])
        _,_,_,t=fixture();t['qp_gate']['endpoints']['server']['pairs'][0]['remote']=124
        with self.assertRaises(ValueError):validate_qp_pairs(t['qp_gate'],1)

    def test_matrix_axes_repetitions(self):
        plan=build_plan(load_matrix(REPO_ROOT/'matrix.yaml'),None,None,None,'auto',reps=3)
        runs=[p for p in plan if p['kind']=='run']
        self.assertEqual(len(runs),238*3)
        self.assertEqual({p['iters'] for p in runs if p['sweep']=='unlimited'},{40000,400000})
        self.assertEqual({p['rep'] for p in runs},{1,2,3})
        for p in runs:
            if p['sweep']=='unlimited':
                self.assertIn('--iters',p['cmd']);self.assertNotIn('--duration',p['cmd'])
            else:
                self.assertEqual(p['duration'],5)
                self.assertIn('--duration',p['cmd']);self.assertNotIn('--iters',p['cmd'])

    def test_duration_counts_use_full_nic_window_not_reported_sample(self):
        cfg,b,a,t=fixture()
        t.update(iters=None,duration_s=5,margin_s=1,reported_sample_iters=6,wall_s=6.1)
        row=scientific_row(cfg,b,a,t,'id',1)
        self.assertTrue(row['integrity_ok'],row['issues'])
        self.assertEqual(row['data_packets_expected'],640)
        self.assertEqual(row['writes_observed'],10)
        for mutation in [lambda t:t.update(reported_sample_iters=11),
                         lambda t:t.update(wall_s=99),lambda t:t.update(margin_s=0),
                         lambda t:t['after_nic'].__setitem__('server/hw_counters/rx_write_requests',9),
                         lambda t:t['after_nic'].pop('server/hw_counters/rx_write_requests')]:
            changed=copy.deepcopy(t);mutation(changed)
            self.assertFalse(scientific_row(cfg,b,a,changed,'id',1)['integrity_ok'])

    def test_duration_command_and_parse(self):
        server,client=traffic_commands(None,64,.2,65536,5,endpoints=ENDPOINTS)
        for cmd in (server,client):
            self.assertNotIn('-n',cmd)
            self.assertEqual(cmd[cmd.index('-D')+1],'5')
            self.assertEqual(cmd[cmd.index('-f')+1],'1')
        self.assertEqual(parse_client('Mtu : 1024\n65536 123 0.0 23.8 0.0001\n',65536,None,64),23.8)
        for n,d in [(40000,5),(None,None),(None,1),(None,61)]:
            with self.assertRaises(ValueError):traffic_commands(n,64,.2,65536,d)


if __name__=='__main__': unittest.main()
