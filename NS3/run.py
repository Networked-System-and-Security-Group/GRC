#!/usr/bin/python3
# -*- coding: utf-8 -*-
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
import re

# randomID
#random.seed(datetime.now())
MAX_RAND_RANGE = 1000000000

# config template
config_template = """TOPOLOGY_FILE config/{topo}.txt
FLOW_FILE config/{flow}.txt
OUTPUT_DIR_PATH mix/output/{id}
SW_MONITORING_INTERVAL {sw_monitoring_interval}

FLOWGEN_START_TIME {flowgen_start_time}
FLOWGEN_STOP_TIME {flowgen_stop_time}
BUFFER_SIZE {buffer_size}
DCI_BUFFER_SIZE {dci_buffer_size}
WAN_BUFFER_SIZE {wan_buffer_size}

CC_MODE {cc_mode}
LB_MODE {lb_mode}
ENABLE_PFC {enabled_pfc}
ENABLE_IRN {enabled_irn}

ALPHA_RESUME_INTERVAL 10
RATE_DECREASE_INTERVAL 10
CLAMP_TARGET_RATE 0
RP_TIMER 50
FAST_RECOVERY_TIMES 1
EWMA_GAIN {ewma_gain}
RATE_AI {ai}Mb/s
RATE_HAI {hai}Mb/s
MIN_RATE 100Mb/s
DCTCP_RATE_AI {dctcp_ai}Mb/s

ERROR_RATE_PER_LINK 0.0000
L2_CHUNK_SIZE 40000
L2_ACK_INTERVAL {ack_interval}
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
PRINT_LOG {print_log}


KMAX_MAP {kmax_map}
KMIN_MAP {kmin_map}
PMAX_MAP {pmax_map}
RANDOM_SEED {random_seed}
TIME {time}
WAN_CC_MODE {wan_cc_mode}
MSG {msg}
"""


# LB/CC mode matching
cc_modes = {
    "dcqcn": 1,
    "hpcc": 3,
    "timely": 7,
    "dctcp": 8,
    "gemini": 9,
    "unocc": 10,
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
                        default='dcqcn', help="hpcc/dcqcn/timely/dctcp/gemini/unocc (default: dcqcn)")
    parser.add_argument('--lb', dest='lb', action='store',
                        default='fecmp', help="fecmp/pecmp/drill/conga (default: fecmp)")
    parser.add_argument('--pfc', dest='pfc', action='store',
                        type=int, default=1, help="enable PFC (default: 1)")
    parser.add_argument('--irn', dest='irn', action='store',
                        type=int, default=0, help="enable IRN (default: 0)")
    parser.add_argument('--simul_time', dest='simul_time', action='store',
                        default='0.05', help="traffic time to simulate (up to 3 seconds) (default: 0.1)")#
    parser.add_argument('--buffer', dest="buffer", action='store',
                        default='9', help="the switch buffer size (MB) (default: 9)")
    parser.add_argument('--dci_buffer', dest='dci_buffer', action='store',
                        type=int, default=0,
                        help="DCI switch buffer size (MB). 0 keeps the C++ default (default: 0)")
    parser.add_argument('--wan_buffer', dest='wan_buffer', action='store',
                        type=int, default=0,
                        help="WAN switch buffer size (MB). 0 keeps the C++ default (default: 0)")
    parser.add_argument('--bw', dest="bw", action='store',
                        default='100', help="the NIC bandwidth (Gbps) (default: 100)")
    parser.add_argument('--topo', dest='topo', action='store',
                        default='cernet_topo', help="the name of the topology file (default: leaf_spine_128_100G_OS2)")#
    parser.add_argument('--cdf', dest='cdf', action='store',
                        default='WebSearch', help="the name of the cdf file (default: WebSearch)")
    parser.add_argument('--enforce_win', dest='enforce_win', action='store',
                        type=int, default=0, help="enforce to use window scheme (default: 0)")
    parser.add_argument('--sw_monitoring_interval', dest='sw_monitoring_interval', action='store',
                        type=int, default=10000, help="interval of sampling statistics for queue status (default: 10000ns)")
    parser.add_argument('--my_flow', type=str, default='w-dynamic-100-150', help="use my own flow, if '', use default flow")#
    parser.add_argument('--tcp_flow', type=str, default='', help="optional TCP flow file path; enables TCP/RDMA mixed-run")
    # NOTE: argparse with type=bool is almost always wrong (e.g. "0" becomes True).
    # Use 0/1 integers for stable CLI behavior.
    parser.add_argument('--debug', type=int, default=0, help="debug (0/1)")
    parser.add_argument('--stdout', type=int, default=0, help="stdout (0/1)")
    parser.add_argument('--print_log', type=int, default=0, help="enable verbose runtime prints in selected modules (0/1)")
    parser.add_argument('--inter_load_all', type=int, default=60, help="不同DC之间之间通信的负载，单位Gbps")
    parser.add_argument('--intra_load', type=int, default=30, help="单个host在DC内之间通信的负载")
    parser.add_argument('--wan_cc_mode', type=int, default=1, help="DC间拥塞控制方案")#
    parser.add_argument('--uno_ai_factor', type=float, default=0.001)
    parser.add_argument('--uno_beta', type=float, default=0.5)
    parser.add_argument('--uno_ewma_gain', type=float, default=0.65)
    parser.add_argument('--uno_k', type=float, default=-1.0, help="UnoCC K in bytes; <=0 means BDP/7")
    parser.add_argument('--uno_gentle_scale', type=float, default=0.3)
    parser.add_argument('--uno_delay_threshold', type=float, default=0.05)
    parser.add_argument('--uno_epoch_rtt_factor', type=float, default=2.0)
    parser.add_argument('--uno_intra_rtt_ns', type=int, default=0, help="0 derives min intra-DC RTT from topology")
    parser.add_argument('--uno_phantom_enabled', type=int, default=1)
    parser.add_argument('--uno_phantom_size_kb', type=int, default=50150)
    parser.add_argument('--uno_phantom_kmin_pct', type=int, default=5)
    parser.add_argument('--uno_phantom_kmax_pct', type=int, default=60)
    parser.add_argument('--uno_phantom_pmax', type=float, default=1.0)
    parser.add_argument('--uno_phantom_slowdown_pct', type=float, default=10.0)
    parser.add_argument('--msg', type=str, default='', help="message")
    parser.add_argument('--config', type=str, default='', help="config.txt file to use, if '', generate a new config.txt file")
    parser.add_argument(
        '--extra',
        action='append',
        default=[],
        help="temporary passthrough config knob, format KEY=VALUE; can be repeated",
    )

    args = parser.parse_args()

    if opcode := os.system("./waf") != 0:
        print("Error: Failed to compile")
        sys.exit(opcode)
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

    def _slugify_msg(raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        raw = re.sub(r"\s+", "-", raw)
        raw = re.sub(r"[^\w.-]+", "-", raw, flags=re.UNICODE)
        raw = re.sub(r"-{2,}", "-", raw).strip("-_.")
        return raw

    msg = args.msg.strip()
    config_ID = f"[{config_index}]-{datetime.now().strftime('%m%d-%H%M')}"
    msg_tag = _slugify_msg(msg)
    if msg_tag:
        config_ID = f"{config_ID}-{msg_tag}"
    
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
    dci_buffer = int(args.dci_buffer)
    wan_buffer = int(args.wan_buffer)
    topo = args.topo
    enforce_win = args.enforce_win
    cdf = args.cdf
    flowgen_start_time = FLOWGEN_DEFAULT_TIME  # default: 2.0
    flowgen_stop_time = flowgen_start_time + \
        float(args.simul_time)  # default: 2.0
    sw_monitoring_interval = int(args.sw_monitoring_interval)

    my_flow = args.my_flow
    tcp_flow = args.tcp_flow.strip()
    debug = bool(args.debug)
    stdout = bool(args.stdout)
    print_log = int(args.print_log)
    intra_load = args.intra_load
    inter_load_all = args.inter_load_all
    wan_cc_mode = args.wan_cc_mode
    # Parse passthrough extras: KEY=VALUE (VALUE kept as raw string)
    extra_kv = {}
    for item in args.extra:
        if '=' not in item:
            raise Exception(f"CONFIG ERROR : --extra expects KEY=VALUE, got: {item}")
        k, v = item.split('=', 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise Exception(f"CONFIG ERROR : --extra has empty KEY in: {item}")
        extra_kv[k] = v

    # get over-subscription ratio from topoogy name


    # Sanity checks
    # if enabled_irn == 1 and enabled_pfc == 1:
    #     raise Exception(
    #         "CONFIG ERROR : If IRN is turn-on, then you should turn off PFC (for better perforamnce).")
    if enabled_irn == 0 and enabled_pfc == 0:
        raise Exception(
            "CONFIG ERROR : Either IRN or PFC should be true (at least one).")
    if float(args.simul_time) < 0.005:
        raise Exception("CONFIG ERROR : Runtime must be larger than 5ms (= warmup interval).")

    if my_flow == '':
        flow = f"WAN_{cdf}_{intra_load}_{inter_load_all}_{args.simul_time}"
    else:
        flow = my_flow

    # Normalize flow name: allow users to pass either "name", "name.txt",
    # or "config/name.txt". The config template always prefixes "config/" and
    # appends ".txt", so we store the stem here.
    if flow:
        flow = flow.strip()
        if flow.startswith('config/'):
            flow = flow[len('config/'):]
        if flow.endswith('.txt'):
            flow = flow[:-4]

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
    if (cc_mode == 3 or cc_mode == 8 or cc_mode == 9 or cc_mode == 10 or enforce_win == 1):
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

    ack_interval = 1 if cc_mode == 9 or cc_mode == 10 else 40000

    if (cc_mode == 1):  # DCQCN
        ai = 10 * bw / 25
        hai = 25 * bw / 25
        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        ewma_gain = 0.00390625

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                        flowgen_start_time=flowgen_start_time,
                                        flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                        buffer_size=buffer, dci_buffer_size=dci_buffer, wan_buffer_size=wan_buffer, lb_mode=lb_mode,
                                        enabled_pfc=enabled_pfc, enabled_irn=enabled_irn,
                                        cc_mode=cc_mode,
                                        ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                        has_win=has_win, var_win=var_win,
                                        fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                        kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, random_seed=1, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        ack_interval=ack_interval, wan_cc_mode=wan_cc_mode, msg=msg, print_log=print_log)
    elif cc_mode == 7:
        ai = 10 * bw / 10
        hai = 50 * bw / 10
        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        ewma_gain = 0.00390625

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                        flowgen_start_time=flowgen_start_time,
                                        flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                        buffer_size=buffer, dci_buffer_size=dci_buffer, wan_buffer_size=wan_buffer, lb_mode=lb_mode,
                                        enabled_pfc=enabled_pfc, enabled_irn=enabled_irn,
                                        cc_mode=cc_mode,
                                        ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                        has_win=has_win, var_win=var_win,
                                        fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                        kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, random_seed=1, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        ack_interval=ack_interval, wan_cc_mode=wan_cc_mode, msg=msg, print_log=print_log)
    elif cc_mode == 9:
        ai = 10 * bw / 10
        hai = 50 * bw / 10
        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        ewma_gain = 0.0625
        # GEMINI uses a dedicated shallow ECN window: 400KB hard threshold.
        kmax_map = "6 %d %d %d %d %d %d %d %d %d %d %d %d" % (
            bw*200000000, 400, bw*500000000, 400, bw*1000000000, 400, bw*2*1000000000, 400, bw*2500000000, 400, bw*4*1000000000, 400)
        kmin_map = "6 %d %d %d %d %d %d %d %d %d %d %d %d" % (
            bw*200000000, 400, bw*500000000, 400, bw*1000000000, 400, bw*2*1000000000, 400, bw*2500000000, 400, bw*4*1000000000, 400)
        pmax_map = "6 %d %d %d %d %d %.2f %d %.2f %d %.2f %d %.2f" % (
            bw*200000000, 1.0, bw*500000000, 1.0, bw*1000000000, 1.0, bw*2*1000000000, 1.0, bw*2500000000, 1.0, bw*4*1000000000, 1.0)

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                        flowgen_start_time=flowgen_start_time,
                                        flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                        buffer_size=buffer, dci_buffer_size=dci_buffer, wan_buffer_size=wan_buffer, lb_mode=lb_mode, 
                                        enabled_pfc=enabled_pfc, enabled_irn=enabled_irn,
                                        cc_mode=cc_mode,
                                        ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                        has_win=has_win, var_win=var_win,
                                        fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                        kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, random_seed=1, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        ack_interval=ack_interval, wan_cc_mode=wan_cc_mode, msg=msg, print_log=print_log)
    elif cc_mode == 10:
        ai = 10 * bw / 25
        hai = 25 * bw / 25
        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        ewma_gain = 0.65

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                        flowgen_start_time=flowgen_start_time,
                                        flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                        buffer_size=buffer, dci_buffer_size=dci_buffer, wan_buffer_size=wan_buffer, lb_mode=lb_mode,
                                        enabled_pfc=enabled_pfc, enabled_irn=enabled_irn,
                                        cc_mode=cc_mode,
                                        ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                        has_win=has_win, var_win=var_win,
                                        fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                        kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, random_seed=1, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        ack_interval=ack_interval, wan_cc_mode=wan_cc_mode, msg=msg, print_log=print_log)
        config += (
            f"UNO_AI_FACTOR {args.uno_ai_factor}\n"
            f"UNO_BETA {args.uno_beta}\n"
            f"UNO_EWMA_GAIN {args.uno_ewma_gain}\n"
            f"UNO_K {args.uno_k}\n"
            f"UNO_GENTLE_SCALE {args.uno_gentle_scale}\n"
            f"UNO_DELAY_THRESHOLD {args.uno_delay_threshold}\n"
            f"UNO_EPOCH_RTT_FACTOR {args.uno_epoch_rtt_factor}\n"
            f"UNO_INTRA_RTT_NS {args.uno_intra_rtt_ns}\n"
            f"UNO_PHANTOM_ENABLED {args.uno_phantom_enabled}\n"
            f"UNO_PHANTOM_SIZE_KB {args.uno_phantom_size_kb}\n"
            f"UNO_PHANTOM_KMIN_PCT {args.uno_phantom_kmin_pct}\n"
            f"UNO_PHANTOM_KMAX_PCT {args.uno_phantom_kmax_pct}\n"
            f"UNO_PHANTOM_PMAX {args.uno_phantom_pmax}\n"
            f"UNO_PHANTOM_SLOWDOWN_PCT {args.uno_phantom_slowdown_pct}\n"
        )
    else:
        print("unknown cc:{}".format(args.cc))

    with open(config_name, "w") as file:
        if not args.config:
            if tcp_flow:
                if not config.endswith('\n'):
                    config += '\n'
                config += f"TCP_FLOW_FILE {tcp_flow}\n"
            if extra_kv:
                if not config.endswith('\n'):
                    config += '\n'
                for k, v in extra_kv.items():
                    config += f"{k} {v}\n"
            file.write(config)
        else:
            # 先读入已有的config文件，将其中的OUTPUT_DIR_PATH替换为新的目录, TIME替换为当前时间
            # 使用正则判断某行是不是 OUTPUT_DIR_PATH 或 TIME开头，然后替换整行
            with open(args.config, "r") as existing_file:
                existing_config = existing_file.read()
            existing_config = re.sub(r'^OUTPUT_DIR_PATH.*$', f'OUTPUT_DIR_PATH mix/output/{config_ID}', existing_config, flags=re.MULTILINE)
            existing_config = re.sub(r'^TIME .*$' , f'TIME {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', existing_config, flags=re.MULTILINE)

            # Keep run.py knobs authoritative even when reusing a config file.
            def _upsert_line(cfg: str, key: str, value: str) -> str:
                pattern = rf'^{re.escape(key)}\\s+.*$'
                line = f'{key} {value}'
                if re.search(pattern, cfg, flags=re.MULTILINE):
                    return re.sub(pattern, line, cfg, flags=re.MULTILINE)
                if not cfg.endswith('\n'):
                    cfg += '\n'
                return cfg + line + '\n'

            existing_config = _upsert_line(existing_config, 'DCI_BUFFER_SIZE', str(dci_buffer))
            existing_config = _upsert_line(existing_config, 'WAN_BUFFER_SIZE', str(wan_buffer))
            existing_config = _upsert_line(existing_config, 'PRINT_LOG', str(print_log))
            if cc_mode == 10:
                existing_config = _upsert_line(existing_config, 'L2_ACK_INTERVAL', str(ack_interval))

            if tcp_flow:
                existing_config = _upsert_line(existing_config, 'TCP_FLOW_FILE', tcp_flow)

            for k, v in extra_kv.items():
                existing_config = _upsert_line(existing_config, k, v)
            file.write(existing_config)

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
