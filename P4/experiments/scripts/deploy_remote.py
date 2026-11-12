#!/usr/bin/env python3
"""Deploy an already hashed build; retain each binary, config and controller log."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time


def main():
    cfg=json.loads(Path(sys.argv[1]).read_text())
    root=Path(cfg['deployment_dir']); source=Path(cfg['remote_dir'])
    work=Path(cfg['switch_work']); deployments=work/'deployments'
    lock=open('/tmp/gscc-experiment-deploy.lock','w'); fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    for name, expected in cfg['artifacts_sha256'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Build artifact changed: '+name)
    conf=json.loads(Path(cfg['switchd_conf']).read_text())
    devices=conf['p4_devices']
    if len(devices)!=1 or devices[0]['device-id']!=0 or len(devices[0]['p4_programs'])!=1:
        raise ValueError('Expected one program on switch device 0')
    prog=devices[0]['p4_programs'][0]
    if len(prog['p4_pipelines'])!=1 or cfg['pipe'] not in prog['p4_pipelines'][0].get('pipe_scope',range(4)):
        raise ValueError('The switchd template must cover the experiment pipe with one pipeline')
    prog['program-name']='gscc_stat'
    prog['bfrt-config']=str(root/'bf-rt.json')
    prog.pop('model_json_path',None)
    pipe=prog['p4_pipelines'][0]
    pipe.update(path=str(root/'build'), config=str(root/'build/gs_pipe/tofino2.bin'),context=str(root/'build/gs_pipe/context.json'))
    # Only this managed family of controllers may be stopped. Unknown switchd blocks deployment.
    owned=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            exe=os.readlink(str(proc/'exe'))
            comm=(proc/'comm').read_text().strip()
        except OSError: continue
        if comm in ('ctrl','bf_switchd'):
            if exe.startswith(str(deployments) + '/'):
                owned.append(int(proc.name))
            else: raise RuntimeError('Unmanaged switch process '+proc.name)
    for pid in owned: os.kill(pid,signal.SIGTERM)
    deadline=time.monotonic()+20
    while any(Path('/proc',str(pid)).exists() for pid in owned) and time.monotonic()<deadline: time.sleep(.2)
    for pid in owned:
        if Path('/proc',str(pid)).exists():
            raise RuntimeError('Owned controller {} did not stop; preserved state, not replacing live files'.format(pid))
    # switchd worker threads / device close may finish just after the leader.
    # Do not overlap device ownership or RPC listeners across cold boots.
    deadline=time.monotonic()+20
    while True:
        busy=[]
        for port in (9090,50052,9999):
            with socket.socket() as sock:
                sock.settimeout(.2)
                if sock.connect_ex(('127.0.0.1',port))==0: busy.append(port)
        if not busy: break
        if time.monotonic()>deadline: raise RuntimeError('Previous switch RPC listeners still active: '+str(busy))
        time.sleep(.5)
    time.sleep(2)
    for name in cfg['artifacts_sha256']:
        dest=root/name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(str(source/name),str(dest))
    (root/'gscc_stat.conf').write_text(json.dumps(conf,indent=2))
    snaps=root/'snapshots'; snaps.mkdir(exist_ok=True)
    sde, install = cfg['sde'], cfg['sde_install']
    libs = [install + '/lib', sde + '/p4studio/dependencies/source/libcli']
    if os.environ.get('LD_LIBRARY_PATH'):
        libs.append(os.environ['LD_LIBRARY_PATH'])
    env = dict(os.environ, SDE=sde, SDE_INSTALL=install, LD_LIBRARY_PATH=':'.join(libs),
               GSCC_CONF=str(root/'gscc_stat.conf'), GSCC_PROG='gscc_stat',
               GSCC_PORTS=f"{cfg['client_port']},{cfg['server_port']}",
               GSCC_MIRROR_PORT=str(cfg['client_port']), GSCC_PIPE=str(cfg['pipe']),
               P4SORT_BUILD_ID=cfg['build_id'], P4SORT_SNAPSHOT_DIR=str(snaps))
    with (root/'controller.log').open('w') as log:
        child=subprocess.Popen([str(root/'ctrl/ctrl')],cwd=str(root),env=env,
                               stdout=log,stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL)
    cfg.update(pid=child.pid,snapshot_dir=str(snaps),started_ns=int(time.time()*1e9))
    (root/'deployment.json').write_text(json.dumps(cfg,indent=2))
    pending=work/'active.tmp'; pending.write_text(json.dumps(cfg)); pending.replace(work/'active.json')
    print(json.dumps(cfg))


if __name__=='__main__': main()
