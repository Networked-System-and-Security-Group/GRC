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
import traceback
from pathlib import Path

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


def plot_cdf(series, label=None, color=None):
    """辅助函数：绘制单个数据集的 CDF"""
    if series.empty: return
    sorted_vals = np.sort(series)
    y = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
    plt.plot(sorted_vals, y, label=label, color=color)

class Analyser:
    def __init__(self, id):
        self.id = str(id)
        self.dir = get_dir_by_id(self.id)
        self.flow_df: pd.DataFrame = None    # 全量流记录
        self.rtt_info: pd.DataFrame = None #timestamp_ns,switch_id,dst_as,next_hop,rtt1_ms,rtt2_ms,timeout_count
        self.drop_info: pd.DataFrame = None #timestamp_ns,switch_id,next_hop,flow_id,seq_num,type
        self.link_info: pd.DataFrame = None #timestamp_ns,src_id,dst_id,flow_id,bytes
        self.buffer_info: pd.DataFrame = None #timestamp_ns,switch_id,next_hop,ingress_bytes,egress_bytes
        self.qp_rate_info: pd.DataFrame = None #timestamp_ns,flow_id,rate,alpha,target_rate
        self.as_rate_info: pd.DataFrame = None #timestamp_ns,src_as,dst_as,real_rate,ref_rate
        self.cnp_info: pd.DataFrame = None #timestamp_ns,switch_id,flow_id
        self.accumulated_bytes_info: pd.DataFrame = None #timestamp_ns,switch_id,dst_as,accumulated_bytes
        self.pfc_info: pd.DataFrame = None #timestamp_ns,node_id,is_switch,nbr_id,is_pause
        self.config: map[str, object] = {}
        self.read_config()
        with (Path(__file__).parent.parent / self.config['TOPOLOGY_FILE']).open() as f:
            self.topo = json.load(f)

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
        """绘制AS间的real_rate和ref_rate对比图"""
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
        plt.plot(df['timestamp_ns'] / 1e9, df['ref_rate'] / 1e9, label='Base Rate', color='red', linestyle='--')
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
                fig, ax1 = plt.subplots(figsize=(5, 4), dpi=300)
                ax1.plot(df['timestamp_ns'] / 1e9, df['rate'] / 1e9 * 8, label=f'Flow {flow_id}')
                #ax1.plot(df['timestamp_ns'] / 1e9, df['target_rate'] / 1e9, label='Target Rate', linestyle='--')
                ax1.set_xlabel('Timestamp (s)', fontsize=22)
                ax1.set_ylabel('Rate (Gbps)', fontsize=22)
                ax1.tick_params(axis='both', which='major', labelsize=18)
                ax1.set_ylim(0,100)
                ax1.set_xlim(1.98,2.8)
                fig.gca().spines['top'].set_visible(False)
                fig.gca().spines['right'].set_visible(False)
                fig.savefig('motivation2.pdf', bbox_inches='tight')
                #ax2 = ax1.twinx()
                #ax2.plot(df['timestamp_ns'] / 1e9, df['alpha'], label='Alpha', linestyle=':', color='orange')
                #ax2.set_ylabel('Alpha', fontsize=22)
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
    def plot_rtt(self, src_as, dst_as):
        self.__read_rtt_info()
        for as_obj in self.topo['as_topologies']:
            if as_obj['as_id'] == src_as:
                switch_id = as_obj['dci_switch']
                break
        else:
            print(f'No switch found for src_as {src_as}')
            return
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
        self.__read_flow_info()
        def _plot(series, label, color):
            if series.empty: return
            sorted_vals = np.sort(series)
            y = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
            plt.plot(sorted_vals, y, label=label, color=color)
        flow_df = self.flow_df
        _plot(flow_df['fct_slowdown'], 'Overall', 'blue')
        _plot(self.get_intra_df()['fct_slowdown'], 'Intra', 'green')
        _plot(self.get_inter_df()['fct_slowdown'], 'Inter', 'red')
        plt.grid(True, ls='--', alpha=.7)
        plt.xlabel('FCT Slowdown')
        plt.ylabel('CDF')
        plt.legend()
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
        plt.title(f"Buffer Utilization switch {switch_id}, {'egress' if egress else 'ingress'}")
        plt.legend()

    @auto_save_plot
    def plot_pfc(self, node):
        """绘制指定 node 和 nbr 的 PFC 时间轴"""
        if self.pfc_info is None:
            self.pfc_info = pd.read_csv(op.join(self.dir, 'pfc_file'))
        plt.figure(figsize=(8, 4))
        y = 1
        y_tickets = []
        for nbr, df in self.pfc_info[(self.pfc_info['node_id'] == node) \
                                      & (self.pfc_info['is_pause'] == 1)].groupby('nbr_id'):
            plt.scatter(df['timestamp_ns'] / 1e9, np.ones(len(df)) *y, label=nbr, s=1)
            y += 1
            y_tickets.append(nbr)
        plt.yticks(range(1, y), y_tickets)
        plt.xlabel('时间戳(s)', fontsize=12, fontproperties=font_prop)
        plt.title(f'PFC Timeline: node {node}')
        plt.legend()
        plt.tight_layout()

    def print_info(self):
        print(f'===ID:{self.id}===')

    def get_avg_fct(self):
        self.__read_flow_info()
        return (
            self.flow_df['fct_slowdown'].mean(),
            self.get_intra_df()['fct_slowdown'].mean(),
            self.get_inter_df()['fct_slowdown'].mean()
        )

    def get_p99_fct(self):
        self.__read_flow_info()
        return (
            self.flow_df['fct_slowdown'].quantile(.99),
            self.get_intra_df()['fct_slowdown'].quantile(.99),
            self.get_inter_df()['fct_slowdown'].quantile(.99)
        )
    
    def get_fct(self):
        return (self.get_avg_fct(), self.get_p99_fct())
    
    def diagnose_slow_flow(self, threshold=99):
        """
        Diagnoses slow flows based on a given threshold for the 'fct_slowdown' column.
        """
        self.__read_flow_info()
        slow_df = self.get_inter_df().copy()
        
        # Get the 99th percentile of the 'fct_slowdown' column
        cutoff = slow_df['fct_slowdown'].quantile(0.99)
        slow_df = slow_df[slow_df['fct_slowdown'] > cutoff]

        start_time = self.flow_df['start_time'].min()
        end_time = self.flow_df['finish_time'].max()

        # Define time bins (time steps) based on the given range
        time_bins = np.arange(start_time, end_time, 1e-4)  # 每秒一个时间点 
        
        plt.figure(figsize=(5, 4))
        
        # Grouping by source AS and destination AS
        for (src_as, dst_as), group in slow_df.groupby(['src_as', 'dst_as']):
            # Binning start and end times of each flow
            start_bin_indices = np.digitize(group['start_time'], time_bins) - 1
            end_bin_indices = np.digitize(group['finish_time'], time_bins) - 1

            # Efficiently counting overlaps using a histogram-like approach
            counts = np.zeros(len(time_bins) - 1, dtype=int)
            
            # For each flow, increment the bins it starts and ends in
            for start_bin, end_bin in zip(start_bin_indices, end_bin_indices):
                counts[start_bin:end_bin + 1] += 1  # Increment the bins that overlap with this flow
            
            # Create DataFrame for the result
            result_df = pd.DataFrame({'Time Bin': time_bins[:-1], 'Count': counts})
            
            # Plotting
            plt.plot(time_bins[:-1], counts, label=f'{src_as}->{dst_as}')
        
        plt.title('Heatmap of Overlapping Intervals in Time Bins')
        plt.legend()
        plt.tight_layout()

        # 选出最慢的20条流并展示
        top20 = slow_df.sort_values('fct_slowdown', ascending=False).head(20)
        display(top20[['flow_id', 'src', 'dst', 'fct_slowdown', 'start_time', 'finish_time', 'src_as', 'dst_as']])
        


    def __read_rtt_info(self):
        if self.rtt_info is None:
            self.rtt_info = pd.read_csv(op.join(self.dir, 'rtt_log'))

    def __read_flow_info(self):
        if self.flow_df is not None:
            return
        with open(op.join(self.dir, 'flow_output'), 'r') as f:
            raw = json.load(f)
        host2as = {}
        for as_obj in self.topo['as_topologies']:
            for host in as_obj['hosts']:
                host2as[host] = as_obj["as_id"]
        df = pd.DataFrame(raw)
        df['fct_slowdown'] = (df['finish_time'] - df['start_time']) / df['std_fct']
        df['src_as']        = df['src'].apply(lambda x : host2as[x])
        df['dst_as']        = df['dst'].apply(lambda x : host2as[x])
        self.flow_df = df

    def get_intra_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['src_as'] == self.flow_df['dst_as']]

    def get_inter_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['src_as'] != self.flow_df['dst_as']]

    def __read_drop_info(self):
        self.__read_flow_info()
        if self.drop_info is None:
            self.drop_info = pd.read_csv(op.join(self.dir,'drop_log'))
            self.drop_info['src_as'] = self.drop_info['flow_id'].map(lambda x: self.id_to_flow[x].src_as if x in self.id_to_flow else None)
            self.drop_info['dst_as'] = self.drop_info['flow_id'].map(lambda x: self.id_to_flow[x].dst_as if x in self.id_to_flow else None)

    def __read_drop_info(self):
        self.__read_flow_info()
        if self.drop_info is None:
            self.drop_info = pd.read_csv(op.join(self.dir, 'drop_log'))
            self.drop_info = self.drop_info.merge(
                self.flow_df[['flow_id', 'src_as', 'dst_as']],
                on='flow_id', how='left'
            )

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

    def read_config(self):
        with open(op.join(self.dir, 'config.txt')) as f:
            lines = f.readlines()
            lines = [l.strip() for l in lines if l.strip()]
            self.config = {l.split()[0] : l.split(maxsplit=2)[-1] for l in lines}

    def rtt_detail(self):
        file_path = op.join(self.dir, 'wan_log')
        time_vals = []
        rtt_vals = []
        sensitive_rtt_vals = []
        # 读取并解析文件
        with open(file_path, 'r') as f:
            for line in f:
                try:
                    parts = line.strip().split(',')
                    now = float(parts[0].split(':')[1])
                    rtt = float(parts[1].split(':')[1])
                    sensitive_rtt = float(parts[2].split(':')[1])
                    # count = int(parts[3].split(':')[1])  # 可选

                    time_vals.append(now)
                    rtt_vals.append(rtt)
                    sensitive_rtt_vals.append(sensitive_rtt)
                except (IndexError, ValueError):
                    print(f"Skipping invalid line: {line}")

        # 绘图
        plt.figure(figsize=(12, 4), dpi=300)
        plt.scatter(time_vals, rtt_vals, label='RTT', s=2)
        plt.plot(time_vals, sensitive_rtt_vals, label='Sensitive RTT', linestyle='--', color='orange')

        plt.xlabel('Time (Now)')
        plt.ylabel('RTT Value')
        plt.title('RTT and Sensitive RTT Over Time')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()

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
            traceback.print_exc()

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
        
def plot_motivation_expr():
    a = get_analyser(863)
    b = get_analyser(864)
    plt.figure(figsize=(5, 4), dpi=300)
    plot_cdf(a.get_inter_df()['fct_slowdown'], label='Disable-ECN')
    plot_cdf(b.get_inter_df()['fct_slowdown'], label='Enable-ECN')
    plt.xscale('log')
    plt.ylim(0, 1)
    plt.xlim(1, 200)
    plt.xlabel('FCT Slowdown', fontsize=22)
    plt.ylabel('CDF', fontsize=22)
    plt.xticks(fontsize=18)
    plt.yticks(fontsize=18)
    plt.legend(fontsize=18)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.savefig('motivation1.pdf', bbox_inches='tight')
    #plt.grid(True, linestyle='--', alpha=0.7)

def plot_motivation_expr2():
    get_analyser(863).plot_qp_rate([467])
if __name__ == '__main__':
    pass
    # %%
    plot_motivation_expr()
    plot_motivation_expr2()
