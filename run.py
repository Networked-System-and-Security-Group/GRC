#!/usr/bin/python3
from genericpath import exists
import subprocess
import os
import time
from xmlrpc.client import boolean
import numpy as np
import copy
import shutil
import random
from datetime import datetime
import sys
import os
import argparse
from datetime import date
import json

# randomID
random.seed(datetime.now())
MAX_RAND_RANGE = 1000000000

# config template
config_template = """TOPOLOGY_FILE config/{topo}.txt
FLOW_FILE config/{flow}.txt
OUTPUT_DIR_PATH mix/output/{id}
QLEN_MON_START {qlen_mon_start}
QLEN_MON_END {qlen_mon_end}
SW_MONITORING_INTERVAL {sw_monitoring_interval}

FLOWGEN_START_TIME {flowgen_start_time}
FLOWGEN_STOP_TIME {flowgen_stop_time}
BUFFER_SIZE {buffer_size}

CC_MODE {cc_mode}
LB_MODE {lb_mode}
ENABLE_PFC {enabled_pfc}
ENABLE_IRN {enabled_irn}

ALPHA_RESUME_INTERVAL 1
RATE_DECREASE_INTERVAL 4
CLAMP_TARGET_RATE 0
RP_TIMER 300 
FAST_RECOVERY_TIMES 1
EWMA_GAIN {ewma_gain}
RATE_AI {ai}Mb/s
RATE_HAI {hai}Mb/s
MIN_RATE 100Mb/s
DCTCP_RATE_AI {dctcp_ai}Mb/s

ERROR_RATE_PER_LINK 0.0000
L2_CHUNK_SIZE 40000
L2_ACK_INTERVAL 40000
L2_BACK_TO_ZERO 0

RATE_BOUND 1
HAS_WIN {has_win}
VAR_WIN {var_win}
FAST_REACT {fast_react}
MI_THRESH {mi}
INT_MULTI {int_multi}
GLOBAL_T 0
U_TARGET 0.95
MULTI_RATE 0
SAMPLE_FEEDBACK 0

ENABLE_QCN 1
USE_DYNAMIC_PFC_THRESHOLD 1
PACKET_PAYLOAD_SIZE 1000


KMAX_MAP {kmax_map}
KMIN_MAP {kmin_map}
PMAX_MAP {pmax_map}
RANDOM_SEED {random_seed}
TIME {time}
WAN_CC_MODE {wan_cc_mode}
"""


# LB/CC mode matching
cc_modes = {
    "dcqcn": 1,
    "hpcc": 3,
    "timely": 7,
    "dctcp": 8,
}

lb_modes = {
    "fecmp": 0,
    "drill": 2,
    "conga": 3,
    "letflow": 6,
    "conweave": 9,
    "dv":10,
    "caver":20,
    "hula": 12,
    "noshare":21,
}

topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000,  # 2-tier -> all 100Gbps
    "fat_k4_100G_OS2": 156000,  # 3-tier -> all 100Gbps
    "fat_k4_100G_OS1": 156000,
    "fat_k8_100G_OS2": 156000,  # 3-tier -> all 100Gbps
    "fat_k8_100G_OS1": 156000,
    "fat_k16_100G_OS1": 156000,
    "fat_k8_100G_bond_OS2": 156000,
    "fat_k8_100G_bond_OS1": 156000,
    "leaf_spine_k_4_bond_2_OS1": 104000,
    "leaf_spine_k_6_bond_2_OS1": 104000,
    "leaf_spine_k_8_bond_2_OS1": 104000,
    "leaf_spine_k_10_bond_2_OS1": 104000,
    "leaf_spine_k_12_bond_2_OS1": 104000,
    "leaf_spine_k_14_bond_2_OS1": 104000,
    "leaf_spine_k_16_bond_2_OS1": 104000,
    "leaf_spine_k_18_bond_2_OS1": 104000,
    "leaf_spine_k_4_bond_2_CLOS_3_OS1": 156000,
    "leaf_spine_k_4_bond_2_CLOS_3_OS1":156000,
    "Fabric_x_4_k_4_OS1":156000,
    "fat_k_4_OS1":156000,
    "fat_k_4_no_bond_OS1":156000,
    "fat_k_4_nobond_OS1":156000,
    "Congestion_OS1":104000,
}

FLOWGEN_DEFAULT_TIME = 2.0  # see /traffic_gen/traffic_gen.py::base_t
 

def main():
    # make directory if not exists
    isExist = os.path.exists(os.getcwd() + "/mix/output/")
    if not isExist:
        os.makedirs(os.getcwd() + "/mix/output/")
        print("The new directory is created - {}".format(os.getcwd() + "/mix/output/"))

    parser = argparse.ArgumentParser(description='run simulation')
    parser.add_argument('--cc', dest='cc', action='store',
                        default='dcqcn', help="hpcc/dcqcn/timely/dctcp (default: dcqcn)")
    parser.add_argument('--lb', dest='lb', action='store',
                        default='fecmp', help="fecmp/pecmp/drill/conga (default: fecmp)")
    parser.add_argument('--pfc', dest='pfc', action='store',
                        type=int, default=1, help="enable PFC (default: 1)")
    parser.add_argument('--irn', dest='irn', action='store',
                        type=int, default=0, help="enable IRN (default: 0)")
    parser.add_argument('--simul_time', dest='simul_time', action='store',
                        default='0.05', help="traffic time to simulate (up to 3 seconds) (default: 0.1)")
    parser.add_argument('--buffer', dest="buffer", action='store',
                        default='9', help="the switch buffer size (MB) (default: 9)")
    parser.add_argument('--bw', dest="bw", action='store',
                        default='100', help="the NIC bandwidth (Gbps) (default: 100)")
    parser.add_argument('--topo', dest='topo', action='store',
                        default='wan_topo_json', help="the name of the topology file (default: leaf_spine_128_100G_OS2)")
    parser.add_argument('--cdf', dest='cdf', action='store',
                        default='WebSearch', help="the name of the cdf file (default: WebSearch)")
    parser.add_argument('--enforce_win', dest='enforce_win', action='store',
                        type=int, default=0, help="enforce to use window scheme (default: 0)")
    parser.add_argument('--sw_monitoring_interval', dest='sw_monitoring_interval', action='store',
                        type=int, default=10000, help="interval of sampling statistics for queue status (default: 10000ns)")
    parser.add_argument('--my_flow', type=str, default='', help="use my own flow, if '', use default flow")
    parser.add_argument('--debug', type=bool, default=False, help="debug")
    parser.add_argument('--stdout', type=bool, default=False, help="stdout")
    parser.add_argument('--inter_load_all', type=int, default=60, help="不同DC之间之间通信的负载，单位Gbps")
    parser.add_argument('--intra_load', type=int, default=30, help="单个host在DC内之间通信的负载")
    parser.add_argument('--wan_cc_mode', type=int, default=1, help="DC间拥塞控制方案")
    parser.add_argument('--msg', type=str, default='', help="message")

    args = parser.parse_args()

    config_index = 0
    if not os.path.exists('./mix/index.txt'):
        with open('./mix/index.txt', 'w') as file:
            file.write('1')
    with open('./mix/index.txt', 'r+') as file:
        number = int(file.read().strip())
        config_index = number
        number += 1
        file.seek(0)
        file.write(str(number))
        file.truncate()

    config_ID = f"[{config_index}]-{datetime.now().strftime('%m-%d-%H:%M:%S')}" 
    # while (isExist):
    #     config_ID = str(random.randrange(MAX_RAND_RANGE))
    #     isExist = os.path.exists(os.getcwd() + "/mix/output/" + config_ID)

    # input parameters
    cc_mode = cc_modes[args.cc]
    lb_mode = lb_modes[args.lb]
    enabled_pfc = int(args.pfc)
    enabled_irn = int(args.irn)
    bw = int(args.bw)
    buffer = args.buffer
    topo = args.topo
    enforce_win = args.enforce_win
    cdf = args.cdf
    flowgen_start_time = FLOWGEN_DEFAULT_TIME  # default: 2.0
    flowgen_stop_time = flowgen_start_time + \
        float(args.simul_time)  # default: 2.0
    sw_monitoring_interval = int(args.sw_monitoring_interval)

    my_flow = args.my_flow
    debug = args.debug
    stdout = args.stdout
    intra_load = args.intra_load
    inter_load_all = args.inter_load_all
    wan_cc_mode = args.wan_cc_mode
    msg = args.msg

    # get over-subscription ratio from topoogy name


    # Sanity checks
    if enabled_irn == 1 and enabled_pfc == 1:
        raise Exception(
            "CONFIG ERROR : If IRN is turn-on, then you should turn off PFC (for better perforamnce).")
    if enabled_irn == 0 and enabled_pfc == 0:
        raise Exception(
            "CONFIG ERROR : Either IRN or PFC should be true (at least one).")
    if float(args.simul_time) < 0.005:
        raise Exception("CONFIG ERROR : Runtime must be larger than 5ms (= warmup interval).")

    if my_flow == '':
        flow = f"WAN_{cdf}_{intra_load}_{inter_load_all}_{args.simul_time}"
    else:
        flow = my_flow

    # check the file exists
    if (exists(os.getcwd() + "/config/" + flow + ".txt")):
        print(f"The file {flow} exists, so skip generating the traffic file...")
        pass
    else:  # make the input traffic file
        print(f"Generate a input traffic file {flow}...")
        os.system(f'python3 config/wan_traffic_gen.py --duration {args.simul_time} --inter_load_all {inter_load_all} --intra_load {intra_load} --cdf {cdf} --output {flow}.txt')

    # sanity check - bandwidth
    #with open("config/{topo}.txt".format(topo=args.topo), 'r') as f_topo:
    #    first_line = f_topo.readline().split(" ")
    #    n_host = int(first_line[0]) - int(first_line[1])
    #    n_link = int(first_line[2])
    #    i = 0
    #    for line in f_topo.readlines()[1:]:
    #        i += 1
    #        if (i > n_link):
    #            break
    #        parsed = line.split(" ")
    #        # if len(parsed) > 2 and (int(parsed[0]) < n_host or int(parsed[1]) < n_host):
    #        #     assert (int(parsed[2].replace("Gbps", "")) == int(bw))
    print("All NIC bandwidth is {bw}Gbps".format(bw=bw))


    ##################################################################

    # make directory if not exists
    isExist = os.path.exists(os.getcwd() + "/mix/output/" + config_ID + "/")
    print(os.getcwd() + "/mix/output/" + config_ID + "/")
    assert (not isExist)
    # if not isExist:
    os.makedirs(os.getcwd() + "/mix/output/" + config_ID + "/")
    print("The new directory is created  - {}".format(os.getcwd() +
          "/mix/output/" + config_ID + "/"))

    config_name = os.getcwd() + "/mix/output/" + config_ID + "/config.txt"
    print("Config filename:{}".format(config_name))

    # By default, DCQCN uses no window (rate-based).
    has_win = 0
    var_win = 0
    if (cc_mode == 3 or cc_mode == 8 or enforce_win == 1):  # HPCC or DCTCP or enforcement
        has_win = 1
        var_win = 1
        if enforce_win == 1:
            print("### INFO: Enforced to use window scheme! ###")

    # 1 BDP calculation
    #if topo2bdp.get(topo) == None:
    #    print("ERROR - topology is not registered in run.py!!", flush=True)
    #    return
    #bdp = int(topo2bdp[topo])
    #print("1BDP = {}".format(bdp))

    # DCQCN parameters (NOTE: HPCC's 400KB/1600KB is too large, although used in Microsoft)
    kmax_map = "6 %d %d %d %d %d %d %d %d %d %d %d %d" % (
        bw*200000000, 400, bw*500000000, 400, bw*1000000000, 400, bw*2*1000000000, 400, bw*2500000000, 400, bw*4*1000000000, 400)
    kmin_map = "6 %d %d %d %d %d %d %d %d %d %d %d %d" % (
        bw*200000000, 100, bw*500000000, 100, bw*1000000000, 100, bw*2*1000000000, 100, bw*2500000000, 100, bw*4*1000000000, 100)
    pmax_map = "6 %d %d %d %d %d %.2f %d %.2f %d %.2f %d %.2f" % (
        bw*200000000, 0.2, bw*500000000, 0.2, bw*1000000000, 0.2, bw*2*1000000000, 0.2, bw*2500000000, 0.2, bw*4*1000000000, 0.2)

    # queue monitoring
    qlen_mon_start = flowgen_start_time
    qlen_mon_end = flowgen_stop_time

    if (cc_mode == 1):  # DCQCN
        ai = 10 * bw / 25
        hai = 25 * bw / 25
        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        ewma_gain = 0.00390625

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                                        qlen_mon_start=qlen_mon_start, qlen_mon_end=qlen_mon_end, flowgen_start_time=flowgen_start_time,
                                        flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                        buffer_size=buffer, lb_mode=lb_mode, 
                                        enabled_pfc=enabled_pfc, enabled_irn=enabled_irn,
                                        cc_mode=cc_mode,
                                        ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                        has_win=has_win, var_win=var_win,
                                        fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                        kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, random_seed=1, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                                        wan_cc_mode=wan_cc_mode)
    elif cc_mode == 7:
        ai = 10 * bw / 10
        hai = 50 * bw / 10
        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        ewma_gain = 0.00390625

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                                        qlen_mon_start=qlen_mon_start, qlen_mon_end=qlen_mon_end, flowgen_start_time=flowgen_start_time,
                                        flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                        buffer_size=buffer, lb_mode=lb_mode, 
                                        enabled_pfc=enabled_pfc, enabled_irn=enabled_irn,
                                        cc_mode=cc_mode,
                                        ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                        has_win=has_win, var_win=var_win,
                                        fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                        kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, random_seed=1, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                                        wan_cc_mode=wan_cc_mode)
    else:
        print("unknown cc:{}".format(args.cc))

    with open(config_name, "w") as file:
        file.write(config)

    if msg:
        with open('mix/history.txt', 'a') as file:
            file.write(f'{config_ID}: {msg}\n')
    # run program
    print("Running simulation...")
    output_log = config_name.replace(".txt", ".log")
    run_command = "./waf --run 'scratch/remote {config_name}' > {output_log} 2>&1".format(
        config_name=config_name, output_log=output_log)

    print(run_command)
    if debug:
        os.system(f"./waf --run 'scratch/remote' --command-template='gdb --args %s {config_name}'\n")
    else:
        if stdout:
            os.system(f"./waf --run 'scratch/remote {config_name}'")
        else:
            os.system(f"./waf --run 'scratch/remote {config_name}' > {output_log} 2>&1 &")

if __name__ == "__main__":
    main()

