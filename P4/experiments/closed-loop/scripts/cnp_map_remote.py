#!/usr/bin/env python3
"""Install exact receiver-to-sender QPN pairs before the startup gate opens."""
import json,sys,socket,struct
import bfrt_grpc.client as gc
cfg=json.load(open(sys.argv[1]));ip=struct.unpack('!I',socket.inet_aton(cfg['sender_ip']))[0]
c=gc.ClientInterface('localhost:50052',25,0);c.bind_pipeline_config('gscc_stat');info=c.bfrt_info_get('gscc_stat')
try:
    t=info.table_get('gs_Egress.gs_set_cnp_qpn_table');target=gc.Target(0)
    keys=[t.make_key([gc.KeyTuple('gs_hdr.gs_ipv4.gs_dst_addr',ip),gc.KeyTuple('gs_hdr.gs_bth.gs_dst_qpn',p['remote'])]) for p in cfg['pairs']]
    values=[t.make_data([gc.DataTuple('sender_qpn',p['local'])],'gs_Egress.gs_set_cnp_qpn') for p in cfg['pairs']]
    # A fresh deployment must have no stale mapping.
    if list(t.entry_get(target,None,{'from_hw':True})):raise RuntimeError('CNP mapping not empty')
    t.entry_add(target,keys,values)
    rows=[(d.to_dict(),k.to_dict()) for d,k in t.entry_get(target,None,{'from_hw':True})]
    actual={(k['gs_hdr.gs_ipv4.gs_dst_addr']['value'],k['gs_hdr.gs_bth.gs_dst_qpn']['value'],d['sender_qpn']) for d,k in rows}
    expected={(ip,p['remote'],p['local']) for p in cfg['pairs']}
    if actual!=expected:raise RuntimeError('CNP map readback mismatch')
    flow=info.table_get('gs_Ingress.id_flow_map')
    dst=struct.unpack('!I',socket.inet_aton(cfg['receiver_ip']))[0]
    entries=[(ip,dst,p['remote'],p['local']) for p in cfg['pairs']]+[(dst,ip,p['local'],p['local']) for p in cfg['pairs']]
    fk=[flow.make_key([gc.KeyTuple('gs_hdr.gs_ipv4.gs_src_addr',a),gc.KeyTuple('gs_hdr.gs_ipv4.gs_dst_addr',b),gc.KeyTuple('gs_hdr.gs_bth.gs_dst_qpn',q)]) for a,b,q,f in entries]
    fd=[flow.make_data([gc.DataTuple('flow',f)],'gs_Ingress.id_set_flow') for a,b,q,f in entries]
    if list(flow.entry_get(target,None,{'from_hw':True})):raise RuntimeError('Identifier flow map not empty')
    flow.entry_add(target,fk,fd)
    flow_rows=[(d.to_dict(),k.to_dict()) for d,k in flow.entry_get(target,None,{'from_hw':True})]
    actual_flow={(k['gs_hdr.gs_ipv4.gs_src_addr']['value'],k['gs_hdr.gs_ipv4.gs_dst_addr']['value'],k['gs_hdr.gs_bth.gs_dst_qpn']['value'],d['flow']) for d,k in flow_rows}
    if actual_flow!=set(entries):raise RuntimeError('Identifier flow map readback differs')
finally:c.tear_down_stream()
print(json.dumps(dict(installed=True,run_id=cfg['run_id'],pairs=cfg['pairs'],readback=rows,identifier_readback=flow_rows)))
