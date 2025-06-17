# %% 
from __future__ import annotations
import json
import subprocess
import matplotlib.pyplot as plt
import os
import os.path as op
import re
import sys
from dataclasses import dataclass, field
from collections import Counter, OrderedDict, defaultdict
import numpy as np
import pandas as pd
from typing import Generator, Union, List, Dict
import functools
from IPython.display import display
from matplotlib.font_manager import FontProperties
font_path = "/home/LAB/zhangjue25/myfont/simsun.ttc"
font_prop = FontProperties(fname=font_path)

def auto_save_plot(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 1. 调用原函数，完成绘图
        result = func(*args, **kwargs)

        # 2. 确定保存目录
        base_dir = op.join(op.dirname(__file__), 'figures')
        os.makedirs(base_dir, exist_ok=True)

        # 3. 构造文件名
        self = args[0]
        name = func.__name__.replace('plot_', '')
        arg_parts = [str(a) for a in args[1:]]
        kw_parts  = [f"{k}_{v}" for k, v in kwargs.items()]
        parts = [self.id, name] + arg_parts + kw_parts
        raw = "-".join(parts)
        safe = re.sub(r'[^0-9A-Za-z_\-]+', '_', raw)
        filename = f"{safe}.pdf"
        save_path = op.join(base_dir, filename)

        # 4. 保存并关闭当前 figure
        #plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()
        plt.close()

        print(f"[auto_save_plot] 已保存：{save_path}")
        return result
    return wrapper

def get_dir_by_id(config_id):
    '''return experiment output dir by id'''
    base_dir = op.join(op.dirname(__file__), '../mix/output')
    cmd = f"ls -l {base_dir}"
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    full = [x.strip().split()[-1] for x in result.stdout.split('\n') if f'[{config_id}]' in x]
    if len(full) != 1:
        raise Exception(f'failed to find {config_id} experiment')
    return op.join(base_dir, full[0])

def latest(offset=0):
    """获取最新的实验目录"""
    base_dir = op.join(op.dirname(__file__), '../mix/output')
    cmd = f"ls -lt {base_dir}"
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    latest_dir = result.stdout.split('\n')[1+offset].split()[-1]
    id = latest_dir.split('[')[-1].split(']')[0]
    print(f'latest experiment dir: {latest_dir}')
    return get_analyser(id)

@dataclass
class FlowInfo:
    src: int
    dst: int
    fsize: int
    start_time: float
    finish_time: float
    flow_id: int
    passed_nodes: List[int]
    std_fct: float
    fct_slowdown: Union[float, None] = field(init=False)
    src_as: Union[float, None] = field(init=False)
    dst_as: Union[float, None] = field(init=False)

    def __post_init__(self):
        self.fct_slowdown = (self.finish_time - self.start_time) / self.std_fct
        def get_as(id):
            if id in range(0, 16):
                return 0
            elif id in range(37, 53):
                return 1
            elif id in range(74, 90):
                return 2
            else:
                print(f'Unknown AS for id {id}')
                assert False
        self.src_as = get_as(self.src)
        self.dst_as = get_as(self.dst)

def plot_cdf(data, label=None, color=None):
    """辅助函数：绘制单个数据集的 CDF"""
    if not data:
        return
    sorted_data = np.sort(data)
    y_values = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
    plt.plot(sorted_data, y_values, label=label, color=color)

class Analyser:
    def __init__(self, id):
        self.id = str(id)
        self.dir = get_dir_by_id(self.id)
        self.flows: List[FlowInfo] = []
        self.id_to_flow: Dict[int, FlowInfo] = {}
        self.intra_flows: List[FlowInfo] = []
        self.inter_flows: List[FlowInfo] = []
        self.rtt_info: pd.DataFrame = None #timestamp_ns,switch_id,dst_as,next_hop,rtt1_ms,rtt2_ms,timeout_count
        self.drop_info: pd.DataFrame = None #timestamp_ns,switch_id,next_hop,flow_id,seq_num,type
        self.link_info: pd.DataFrame = None #timestamp_ns,src_id,dst_id,flow_id,bytes
        self.buffer_info: pd.DataFrame = None #timestamp_ns,switch_id,next_hop,ingress_bytes,egress_bytes
        self.qp_rate_info: pd.DataFrame = None #timestamp_ns,flow_id,rate,alpha,target_rate
        self.as_rate_info: pd.DataFrame = None #timestamp_ns,src_as,dst_as,real_rate,base_rate
        self.cnp_info: pd.DataFrame = None #timestamp_ns,switch_id,flow_id
        self.accumulated_bytes_info: pd.DataFrame = None #timestamp_ns,switch_id,dst_as,accumulated_bytes

    def __read_accumulated_bytes_info(self):
        if self.accumulated_bytes_info is None:
            self.accumulated_bytes_info = pd.read_csv(op.join(self.dir, 'accumulated_bytes_log'))

    @auto_save_plot
    def plot_accumulated_bytes(self, switch_id, dst_as):
        """绘制指定 switch_id 和 dst_as 的 accumulated_bytes 变化曲线"""
        self.__read_accumulated_bytes_info()
        df = self.accumulated_bytes_info[
            (self.accumulated_bytes_info['switch_id'] == switch_id) &
            (self.accumulated_bytes_info['dst_as'] == dst_as)
        ]
        if df.empty:
            print(f'No accumulated bytes info for switch {switch_id} and dst_as {dst_as}')
            return
        plt.figure(figsize=(10, 6))
        plt.plot(df['timestamp_ns'], df['accumulated_bytes'] / 1e3, label='Accumulated Bytes')
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.ylabel('Accumulated Bytes (KB)', fontsize=12)
        plt.title(f'Accumulated Bytes for Switch {switch_id} and dst_as {dst_as}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)


    def __read_cnp_info(self):
        if self.cnp_info is None:
            self.cnp_info = pd.read_csv(op.join(self.dir, 'cnp_log'))

    @auto_save_plot
    def plot_cnp_timestamps(self, flow_id:int, start_time:float=2.0, end_time:float=2.05):
        """绘制指定流ID的CNP发送时间点"""
        self.__read_cnp_info()
        df = self.cnp_info[(self.cnp_info['flow_id'] == flow_id) &
                           (self.cnp_info['timestamp_ns'] >= start_time*1e9) &
                           (self.cnp_info['timestamp_ns'] <= end_time*1e9)]
        if df.empty:
            print(f'No CNP info for flow_id {flow_id}')
            return
        plt.figure(figsize=(10, 3))
        plt.scatter(df['timestamp_ns'], np.zeros_like(df['timestamp_ns']), alpha=0.6, s=3)
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.title(f'CNP Timestamps for Flow {flow_id}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)

    @auto_save_plot
    def plot_as_rate(self, src_as, dst_as):
        """绘制AS间的real_rate和base_rate对比图"""
        self.__read_as_rate_info()
        df = self.as_rate_info[
            (self.as_rate_info['src_as'] == src_as) & 
            (self.as_rate_info['dst_as'] == dst_as)
        ]
        if df.empty:
            print(f'No rate info for AS {src_as}->{dst_as}')
            return
            
        plt.figure(figsize=(5, 4), dpi=300)
        plt.plot(df['timestamp_ns'] / 1e9, df['real_rate'] / 1e9, label='Real Rate', color='blue')
        plt.plot(df['timestamp_ns'] / 1e9, df['base_rate'] / 1e9, label='Base Rate', color='red', linestyle='--')
        plt.xlabel('时间轴(s)', fontsize=14, fontproperties=font_prop)
        plt.ylabel('速率(GB/s)', fontsize=14, fontproperties=font_prop)
        #plt.title(f'DC Rate Monitor: {src_as}->{dst_as}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)

    @auto_save_plot
    def plot_qp_rate(self, flow_ids: List[int]):
        """绘制多个 flow_id 的速率折线图，每个 flow 一条曲线"""
        self.__read_qp_rate_info()
        plt.figure(figsize=(5, 4), dpi=300)
        for flow_id in flow_ids:
            df = self.qp_rate_info[self.qp_rate_info['flow_id'] == flow_id]
            if df.empty:
                print(f'No QP rate info for flow_id {flow_id}')
                continue
            if len(flow_ids) == 1:
                fig, ax1 = plt.subplots()
                ax1.plot(df['timestamp_ns'] / 1e9, df['rate'] / 1e9, label=f'Flow {flow_id}')
                ax1.plot(df['timestamp_ns'] / 1e9, df['target_rate'] / 1e9, label='Target Rate', linestyle='--')
                ax1.set_xlabel('Timestamp (s)', fontsize=12)
                ax1.set_ylabel('Rate', fontsize=12)
                ax2 = ax1.twinx()
                ax2.plot(df['timestamp_ns'] / 1e9, df['alpha'], label='Alpha', linestyle=':', color='orange')
                ax2.set_ylabel('Alpha', fontsize=12)
                return
            else:
                plt.plot(df['timestamp_ns'] / 1e9, df['rate'] / 1e9, label=f'Flow {flow_id}')
        plt.xlabel('时间轴(s)', fontsize=14, fontproperties=font_prop)
        plt.ylabel('速率(GB/s)', fontsize=14, fontproperties=font_prop)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        #plt.title('QP Rate for Selected Flows', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=13)

    @auto_save_plot
    def plot_rtt(self, switch_id, dst_as):
        self.__read_rtt_info()
        df = self.rtt_info[(self.rtt_info['switch_id']==switch_id)&(self.rtt_info['dst_as']==dst_as)]
        if df.empty:
            print(f'No RTT info for switch {switch_id} and dst_as {dst_as}')
            return
        plt.figure(figsize=(8, 5))
        for nxt, grp in df.groupby('next_hop'):
            plt.plot(grp['timestamp_ns'], grp['rtt1_ms'], label=f'{nxt}-Sens', linestyle='-', marker='.', markersize=4)
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.ylabel('RTT (ms)', fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)

    @auto_save_plot
    def plot_fct_cdf(self):
        """绘制 FCT slowdown 的 CDF 图，包含 overall, intra 和 inter"""
        self.__read_flow_info()
        overall = [f.fct_slowdown for f in self.flows]
        intra   = [f.fct_slowdown for f in self.intra_flows]
        inter   = [f.fct_slowdown for f in self.inter_flows]
        plt.figure(figsize=(10, 6))
        plot_cdf(overall, label='Overall', color='blue')
        plot_cdf(intra,   label='Intra',   color='green')
        plot_cdf(inter,   label='Inter',   color='red')
        print(f'Avg slowdowns: O={np.mean(overall):.2f}, Intra={np.mean(intra):.2f}, Inter={np.mean(inter):.2f}')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.xlabel('FCT Slowdown', fontsize=12)
        plt.ylabel('CDF', fontsize=12)
        plt.title('CDF of FCT Slowdown', fontsize=14)
        plt.legend(fontsize=10)
        if max(overall+intra+inter)/min(overall+intra+inter) > 100:
            plt.xscale('log')
        plt.ylim(0, 1.05)

    @auto_save_plot
    def plot_drop(self, switch_id, src_as, dst_as):
        """绘制丢包散点图（改为 plt 接口）"""
        self.__read_drop_info()
        df = self.drop_info[
            (self.drop_info['switch_id']==switch_id)&
            (self.drop_info['src_as']==src_as)&
            (self.drop_info['dst_as']==dst_as)
        ]
        if df.empty:
            print(f'No drop info for switch {switch_id}, {src_as}->{dst_as}')
            return
        plt.figure(figsize=(8, 5))
        times = df['timestamp_ns']
        plt.scatter(times, np.zeros_like(times), alpha=0.6, s=50)
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.title(f'Drop Events: switch {switch_id}, src_as {src_as}, dst_as {dst_as}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)

    def show_drop(self):
        self.__read_drop_info()
        grouped = self.drop_info.groupby(['switch_id', 'src_as', 'dst_as']).size()
        for (switch_id, src_as, dst_as), count in grouped.items():
            print(f'Switch ID: {switch_id}, Src AS: {src_as}, Dst AS: {dst_as}, Drop Count: {count}')

    @auto_save_plot
    def plot_link_utilization(self, src_id, dst_id, monitor_interval=500e-6, smooth_window=1):
        self.__read_link_info()
        series = (
            self.link_info[
                (self.link_info['src_id']==src_id)&
                (self.link_info['dst_id']==dst_id)
            ]
            .groupby('timestamp_ns')['bytes']
            .sum()
            .sort_index()
        )
        if series.empty:
            print(f'No link info for {src_id}->{dst_id}')
            return
        series /= monitor_interval
        series = series.rolling(smooth_window, center=True).mean()
        plt.figure()
        plt.plot(series.index, series.values / 1e9)
        plt.xlabel('Timestamp (ns)')
        plt.ylabel('GB/s')
        plt.title(f'Link Utilization {src_id}->{dst_id}')

    @auto_save_plot
    def plot_buffer(self, switch_id, egress=True):
        self.__read_buffer_info()
        df = self.buffer_info[
            (self.buffer_info['switch_id']==switch_id)
        ]
        if df.empty:
            print(f'No buffer info for switch {switch_id}')
            return
     
        col = 'egress_bytes' if egress else 'ingress_bytes'
        df = df[['timestamp_ns', 'next_hop', col]].rename(columns={col: 'bytes'})
        plt.figure(figsize=(5,4), dpi=300)
        for next_hop, group in df.groupby('next_hop'):
            plt.plot(group['timestamp_ns'] / 1e9, group['bytes'] / 1e6, label=f'Hop {next_hop}')
        plt.xlabel('时间戳(s)', fontsize=16, fontproperties=font_prop)
        plt.ylabel('队列长度(MB)', fontsize=16, fontproperties=font_prop)
        plt.title(f'Buffer Utilization switch {switch_id}, hop {next_hop}')

    def print_info(self):
        print(f'===ID:{self.id}===')

    def get_avg_fct(self):
        self.__read_flow_info()
        vals = [f.fct_slowdown for f in self.flows]
        intra = [f.fct_slowdown for f in self.intra_flows]
        inter = [f.fct_slowdown for f in self.inter_flows]
        
        # Check if lists are empty before calculating mean
        avg_vals = np.mean(vals) if vals else None
        avg_intra = np.mean(intra) if intra else None
        avg_inter = np.mean(inter) if inter else None
        
        return avg_vals, avg_intra, avg_inter

    def get_p99_fct(self):
        self.__read_flow_info()
        vals = [f.fct_slowdown for f in self.flows]
        intra = [f.fct_slowdown for f in self.intra_flows]
        inter = [f.fct_slowdown for f in self.inter_flows]
        
        # Check if lists are empty before calculating percentile
        p99_vals = np.percentile(vals, 99) if vals else None
        p99_intra = np.percentile(intra, 99) if intra else None
        p99_inter = np.percentile(inter, 99) if inter else None
        
        return p99_vals, p99_intra, p99_inter
    
    def get_fct(self):
        return (self.get_avg_fct(), self.get_p99_fct())
    
    def diagnose_slow_flows(self, threshold=95):
        '''查看慢于99%的所有流'''
        self.__read_flow_info()
        slowdown_values = [f.fct_slowdown for f in self.inter_flows]
        if not slowdown_values:
            print("No inter flows found.")
            return
        threshold_value = np.percentile(slowdown_values, threshold)
        slow_flows = [f for f in self.inter_flows if f.fct_slowdown > threshold_value]
        slow_flows_sorted = sorted(slow_flows, key=lambda f: f.fct_slowdown, reverse=True)
        for flow in slow_flows_sorted:
            print(flow)

    def __read_rtt_info(self):
        if self.rtt_info is None:
            self.rtt_info = pd.read_csv(op.join(self.dir, 'rtt_log'))

    def __read_flow_info(self):
        if not self.flows:
            with open(op.join(self.dir, 'flow_output'),'r') as f:
                self.flows = [FlowInfo(**it) for it in json.load(f)]
            self.id_to_flow = {f.flow_id: f for f in self.flows}
            self.intra_flows = [f for f in self.flows if len(f.passed_nodes)<=5]
            self.inter_flows = [f for f in self.flows if len(f.passed_nodes)>5]

    def __read_drop_info(self):
        self.__read_flow_info()
        if self.drop_info is None:
            self.drop_info = pd.read_csv(op.join(self.dir,'drop_log'))
            self.drop_info['src_as'] = self.drop_info['flow_id'].map(lambda x: self.id_to_flow[x].src_as if x in self.id_to_flow else None)
            self.drop_info['dst_as'] = self.drop_info['flow_id'].map(lambda x: self.id_to_flow[x].dst_as if x in self.id_to_flow else None)

    def __read_link_info(self):
        if self.link_info is None:
            self.link_info = pd.read_csv(op.join(self.dir,'link_utilization'))

    def __read_buffer_info(self):
        if self.buffer_info is None:
            self.buffer_info = pd.read_csv(op.join(self.dir,'buffer_monitor'))

    def __read_qp_rate_info(self):
        if self.qp_rate_info is None:
            self.qp_rate_info = pd.read_csv(op.join(self.dir,'qp_rate_log'))

    def __read_as_rate_info(self):
        if self.as_rate_info is None:
            self.as_rate_info = pd.read_csv(op.join(self.dir, 'rate_monitor'))

_instances: Dict[str, Analyser] = {}
def get_analyser(id) -> Analyser:
    if str(id) not in _instances:
        _instances[str(id)] = Analyser(id)
    return _instances[str(id)]

def convert_str_to_id(config_ids_str: str) -> List[int]:
    ids = []
    for part in config_ids_str.split(','):
        if '-' in part:
            a, b = map(int, part.split('-'))
            ids.extend(range(a, b+1))
        else:
            ids.append(int(part))
    return ids

def analyser_iter(config_ids_str: str) -> Generator[Analyser, None, None]:
    for i in convert_str_to_id(config_ids_str):
        try:
            yield get_analyser(i)
        except Exception as e:
            print(f'{i}号实验数据异常：{e}')

def clear_data(config_ids_str: str):
    dirs = []
    for ana in analyser_iter(config_ids_str):
        dirs.append(ana.dir)
        print(ana.dir)
    if input('press y to delete these data') == 'y':
        for d in dirs:
            os.system(f'rm -r {d}')

def show_fct(config_ids_str: str):
    for ana in analyser_iter(config_ids_str):
        ana.print_info()
        avg, intra, inter = ana.get_avg_fct()
        print(f'[{ana.id}]Avg FCT: {avg:.2f}, Intra: {intra:.2f}, Inter: {inter:.2f}')
        p99, p99_intra, p99_inter = ana.get_p99_fct()
        print(f'[{ana.id}]P99 FCT: {p99:.2f}, Intra: {p99_intra:.2f}, Inter: {p99_inter:.2f}')

def batch_operation(config_ids_str: str, func_name: str, *args):
    for ana in analyser_iter(config_ids_str):
        func = getattr(ana, func_name)
        print(f'[{ana.id}] {func_name}({args})')
        func(*args)

def get_basic_result(config_ids_str: str):
    results = []
    for ana in analyser_iter(config_ids_str):
        try:
            avg_vals, avg_intra, avg_inter = ana.get_avg_fct()
            p99_vals, p99_intra, p99_inter = ana.get_p99_fct()
            results.append({
                'ID': ana.id,
                'Avg_FCT': avg_vals,
                'Avg_Intra_FCT': avg_intra,
                'Avg_Inter_FCT': avg_inter,
                'P99_FCT': p99_vals,
                'P99_Intra_FCT': p99_intra,
                'P99_Inter_FCT': p99_inter
            })
        except Exception as e:
            print(f'Error processing {ana.id}: {e}')
    df = pd.DataFrame(results)
    return df
        

if __name__ == '__main__':
    pass

# %%
