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
import matplotlib
matplotlib.rcParams['pdf.fonttype'] = 42  # TrueType 字体
matplotlib.rcParams['ps.fonttype'] = 42  # TrueType 字体

font_prop = None

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
        self.cnp_trigger_prob_info: pd.DataFrame = None #timestamp_ns,switch_id,src_as,dst_as,cnp_cnt,pkt_cnt,prob
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
    def plot_accumulated_bytes(self, src_as, dst_as):
        """绘制指定 switch_id 和 dst_as 的 accumulated_bytes 变化曲线"""
        self.__read_accumulated_bytes_info()
        for as_obj in self.topo['as_topologies']:
            if as_obj['as_id'] == src_as:
                switch_id = as_obj['dci_switch']
                break
        else:
            print(f'No switch found for src_as {src_as}')
            return
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

    def __read_cnp_trigger_prob_info(self):
        if self.cnp_trigger_prob_info is None:
            self.cnp_trigger_prob_info = pd.read_csv(op.join(self.dir, 'cnp_trigger_prob_log'))

    @auto_save_plot
    def plot_cnp_timestamps(self, flow_id:int, start_time:float=2.0, end_time:float=2.05, bin_ms:float=1.0):
        """按时间槽统计 CNP 数量（折线图）"""
        self.__read_cnp_info()
        df = self.cnp_info[(self.cnp_info['flow_id'] == flow_id) &
                           (self.cnp_info['timestamp_ns'] >= start_time*1e9) &
                           (self.cnp_info['timestamp_ns'] <= end_time*1e9)]
        if df.empty:
            print(f'No CNP info for flow_id {flow_id}')
            return

        start_ns = int(start_time * 1e9)
        end_ns = int(end_time * 1e9)
        bin_ns = int(bin_ms * 1e6)
        if bin_ns <= 0:
            raise ValueError('bin_ms must be > 0')

        edges = np.arange(start_ns, end_ns + bin_ns, bin_ns)
        counts, _ = np.histogram(df['timestamp_ns'].to_numpy(), bins=edges)
        centers = (edges[:-1] + edges[1:]) / 2

        plt.figure(figsize=(10, 3))
        plt.plot(centers / 1e9, counts, linewidth=1.2)
        plt.xlabel('Time (s)', fontsize=12)
        plt.ylabel(f'CNP count / {bin_ms:g} ms', fontsize=12)
        plt.title(f'CNP Counts for Flow {flow_id}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)

    @auto_save_plot
    def plot_cnp_trigger_prob(self, src_as:int, dst_as:int, ewma_span:int=1):
        """绘制 epoch 粒度的 CNP 触发概率：prob = cnp_cnt / pkt_cnt"""
        self.__read_cnp_trigger_prob_info()

        for as_obj in self.topo['as_topologies']:
            if as_obj['as_id'] == src_as:
                switch_id = as_obj['dci_switch']
                break
        else:
            print(f'No switch found for src_as {src_as}')
            return

        df = self.cnp_trigger_prob_info[
            (self.cnp_trigger_prob_info['switch_id'] == switch_id) &
            (self.cnp_trigger_prob_info['src_as'] == src_as) &
            (self.cnp_trigger_prob_info['dst_as'] == dst_as)
        ].sort_values('timestamp_ns')
        if df.empty:
            print(f'No cnp_trigger_prob_log for {src_as}->{dst_as} (switch {switch_id})')
            return

        prob = df['prob']
        if ewma_span and ewma_span > 1:
            prob = prob.ewm(span=ewma_span, adjust=False).mean()

        plt.figure(figsize=(5, 4), dpi=300)
        plt.plot(df['timestamp_ns'] / 1e9, prob, label='CNP trigger prob')
        xlabel_kwargs = {'fontproperties': font_prop} if font_prop is not None else {}
        plt.xlabel('Time (s)', fontsize=14, **xlabel_kwargs)
        plt.ylabel('prob', fontsize=14, **xlabel_kwargs)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)

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
        plt.xlabel('Time (s)', fontsize=14)
        plt.ylabel('Rate (GB/s)', fontsize=14)
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
        plt.xlabel('Time (s)', fontsize=14)
        plt.ylabel('Rate (GB/s)', fontsize=14)
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

    def get_drop_number(self):
        self.__read_drop_info()
        return len(self.drop_info)
    
    def get_drop_rate(self):
        drop_cnt = self.get_drop_number()
        self.__read_flow_info()

        total_cnt = np.ceil(self.flow_df['fsize'] / 1000).sum()
        return drop_cnt/total_cnt

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
        plt.xlabel('Timestamp (s)', fontsize=16)
        plt.ylabel('Queue Length (MB)', fontsize=16)
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
        plt.xlabel('Timestamp (s)', fontsize=12)
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
    
    def get_large_flow_fct(self):
        self.__read_flow_info()
        df = self.get_large_flow_df().copy()
        return ( df['fct_slowdown'].mean(), 
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].mean(),
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].quantile(.99), 
                df[ df['src_as'] == df['dst_as'] ]['fct_slowdown'].mean())
    
    def get_small_flow_fct(self):
        self.__read_flow_info()
        df = self.get_small_flow_df().copy()
        return ( df['fct_slowdown'].mean(), 
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].mean(),
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].quantile(.99), 
                df[ df['src_as'] == df['dst_as'] ]['fct_slowdown'].mean())
    
    def get_buffer_information(self):
        self.__read_buffer_info()
        df = self.buffer_info[
            (self.buffer_info['timestamp_ns'] >= 2010000000) & (self.buffer_info['timestamp_ns'] <= 2100000000)
        ].groupby(['timestamp_ns', 'switch_id'])['egress_bytes'].sum().reset_index()
        return df['egress_bytes'].mean()

    def get_wan_buffer_stats(self):
        """
        Returns (mean, p99) of buffer occupancy (egress_bytes) for WAN switches.
        aggregated over all queues and time.
        """
        self.__read_buffer_info()
        wan_set = set(map(int, self.topo.get('wan_switches', [])))
        if not wan_set:
            return (0.0, 0.0)

        df = self.buffer_info[self.buffer_info['switch_id'].isin(wan_set)]
        if df.empty:
            return (0.0, 0.0)
            
        # Each row is a queue sample.
        # We calculate statistics across all samples (all queues, all times).
        return df['egress_bytes'].mean(), df['egress_bytes'].quantile(0.99)


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
    
    def get_large_flow_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['fsize'] >= 5000000]
    
    def get_small_flow_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['fsize'] < 1000000]

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

    def _read_optional_csv(self, attr_name: str, filename: str):
        current = getattr(self, attr_name)
        if current is not None:
            return current
        path = op.join(self.dir, filename)
        if (not op.exists(path)) or os.path.getsize(path) == 0:
            return None
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return None
        setattr(self, attr_name, df)
        return df

    def get_flow_detail(self, flow_id: int, top_links: int = 10) -> dict:
        self.__read_flow_info()
        flow_rows = self.flow_df[self.flow_df['flow_id'] == flow_id]
        if flow_rows.empty:
            raise ValueError(f'flow_id {flow_id} not found in experiment {self.id}')

        flow = flow_rows.iloc[0].to_dict()
        detail = {
            'flow': flow,
            'drop_events': None,
            'drop_summary': None,
            'qp_rate_samples': None,
            'qp_rate_stats': None,
            'cnp_events': None,
            'link_samples': None,
            'link_summary': None,
        }

        drop_df = self._read_optional_csv('drop_info', 'drop_log')
        if drop_df is not None and not drop_df.empty and 'flow_id' in drop_df.columns:
            if 'src_as' not in drop_df.columns or 'dst_as' not in drop_df.columns:
                drop_df = drop_df.merge(
                    self.flow_df[['flow_id', 'src_as', 'dst_as']],
                    on='flow_id', how='left'
                )
                self.drop_info = drop_df
            flow_drop = drop_df[drop_df['flow_id'] == flow_id].copy()
            if not flow_drop.empty:
                detail['drop_events'] = flow_drop
                detail['drop_summary'] = (
                    flow_drop.groupby(['switch_id', 'next_hop', 'type'])
                    .size()
                    .reset_index(name='count')
                    .sort_values('count', ascending=False)
                )

        qp_df = self._read_optional_csv('qp_rate_info', 'qp_rate_log')
        if qp_df is not None and not qp_df.empty and 'flow_id' in qp_df.columns:
            flow_qp = qp_df[qp_df['flow_id'] == flow_id].copy()
            if not flow_qp.empty:
                detail['qp_rate_samples'] = flow_qp
                rate_gbps = flow_qp['rate'] * 8 / 1e9
                qp_stats = {
                    'samples': int(len(flow_qp)),
                    't_start_s': float(flow_qp['timestamp_ns'].min() / 1e9),
                    't_end_s': float(flow_qp['timestamp_ns'].max() / 1e9),
                    'rate_mean_gbps': float(rate_gbps.mean()),
                    'rate_min_gbps': float(rate_gbps.min()),
                    'rate_p50_gbps': float(rate_gbps.quantile(0.5)),
                    'rate_p99_gbps': float(rate_gbps.quantile(0.99)),
                    'rate_max_gbps': float(rate_gbps.max()),
                }
                if 'target_rate' in flow_qp.columns:
                    target_gbps = flow_qp['target_rate'] * 8 / 1e9
                    qp_stats.update({
                        'target_mean_gbps': float(target_gbps.mean()),
                        'target_max_gbps': float(target_gbps.max()),
                    })
                if 'alpha' in flow_qp.columns:
                    qp_stats.update({
                        'alpha_min': float(flow_qp['alpha'].min()),
                        'alpha_max': float(flow_qp['alpha'].max()),
                    })
                detail['qp_rate_stats'] = qp_stats

        cnp_df = self._read_optional_csv('cnp_info', 'cnp_log')
        if cnp_df is not None and not cnp_df.empty and 'flow_id' in cnp_df.columns:
            flow_cnp = cnp_df[cnp_df['flow_id'] == flow_id].copy()
            if not flow_cnp.empty:
                detail['cnp_events'] = flow_cnp

        link_df = self._read_optional_csv('link_info', 'link_utilization')
        if link_df is not None and not link_df.empty and 'flow_id' in link_df.columns:
            flow_link = link_df[link_df['flow_id'] == flow_id].copy()
            if not flow_link.empty:
                detail['link_samples'] = flow_link
                detail['link_summary'] = (
                    flow_link.groupby(['src_id', 'dst_id'])['bytes']
                    .agg(['count', 'sum', 'max'])
                    .reset_index()
                    .sort_values('sum', ascending=False)
                    .head(top_links)
                )

        return detail

    def print_flow_detail(self, flow_id: int, top_links: int = 10):
        detail = self.get_flow_detail(flow_id, top_links=top_links)
        flow = detail['flow']
        duration = float(flow['finish_time'] - flow['start_time'])
        path = flow.get('passed_nodes', [])

        print(f'=== Flow {flow_id} @ Experiment {self.id} ===')
        print(
            f"src={flow['src']} (AS{flow['src_as']}) -> "
            f"dst={flow['dst']} (AS{flow['dst_as']})"
        )
        print(
            f"size={int(flow['fsize'])}B start={flow['start_time']:.9f}s "
            f"finish={flow['finish_time']:.9f}s duration={duration:.9f}s"
        )
        print(
            f"std_fct={flow['std_fct']:.9f}s slowdown={flow['fct_slowdown']:.6f}"
        )
        print(f"path={path} hop_count={len(path)}")

        if detail['drop_events'] is None:
            print('drops=0')
        else:
            print(f'drops={len(detail["drop_events"])}')
            print(detail['drop_summary'].to_string(index=False))

        if detail['cnp_events'] is None:
            print('cnp_events=0')
        else:
            flow_cnp = detail['cnp_events']
            print(
                f"cnp_events={len(flow_cnp)} "
                f"time_range=[{flow_cnp['timestamp_ns'].min()/1e9:.9f}, "
                f"{flow_cnp['timestamp_ns'].max()/1e9:.9f}]s"
            )

        if detail['qp_rate_stats'] is None:
            print('qp_rate_samples=0')
        else:
            print('qp_rate_stats=')
            for k, v in detail['qp_rate_stats'].items():
                print(f'  {k}: {v}')

        if detail['link_summary'] is None:
            print('link_samples=0')
        else:
            print('top_link_samples=')
            print(detail['link_summary'].to_string(index=False))

    def wan_high_buffer_intervals(
        self,
        *,
        quantile: float = 0.90,
        direction: str = 'both',
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        min_duration_s: float = 0.0,
        max_gap_s: float | None = None,
        return_samples: bool = False,
    ) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
        """找出 WAN 交换机在“哪些时间段、哪些队列(端口->next_hop)”buffer 占用非常高。

        - 把所有时刻、所有 WAN 交换机、所有队列的 used_bytes 收集
        - 取 used_bytes 的 quantile 作为阈值
        - 对每条队列，输出超过阈值的连续时间段 (t_start,t_end)

        参数：
        - quantile: 分位数阈值，例如 0.9 表示 >= P90（最拥挤 10%）
        - direction: 'ingress'|'egress'|'both'
        - start_time_s/end_time_s: 时间窗过滤（秒）
        - min_duration_s: 过滤太短的事件段
        - max_gap_s: 允许把相邻采样点合并为同一段的最大间隔（默认用 SW_MONITORING_INTERVAL*1.5）
        - return_samples: True 时额外返回筛选后的采样（便于自定义画图）

        返回：events_df（每行一个高占用时间段）；可选 (events_df, samples_df)
        """
        self.__read_buffer_info()

        if not (0.0 < float(quantile) <= 1.0):
            raise ValueError('quantile must be in (0,1]')

        direction = str(direction).lower().strip()
        if direction not in {'ingress', 'egress', 'both'}:
            raise ValueError("direction must be 'ingress', 'egress', or 'both'")

        wan_set = set(map(int, self.topo.get('wan_switches', [])))
        if not wan_set:
            raise ValueError('topology has no wan_switches')

        df = self.buffer_info.copy()
        df = df[df['switch_id'].isin(wan_set)]
        if start_time_s is not None:
            df = df[df['timestamp_ns'] >= start_time_s * 1e9]
        if end_time_s is not None:
            df = df[df['timestamp_ns'] <= end_time_s * 1e9]
        if df.empty:
            events = pd.DataFrame(
                columns=[
                    'switch_id', 'next_hop', 'direction',
                    't_start_s', 't_end_s', 'duration_s',
                    'peak_bytes', 't_peak_s',
                    'threshold_bytes', 'quantile'
                ]
            )
            return (events, df) if return_samples else events

        # default continuity gap from SW_MONITORING_INTERVAL
        try:
            interval_ns = int(float(self.config.get('SW_MONITORING_INTERVAL', 0)))
        except Exception:
            interval_ns = 0
        if max_gap_s is None:
            max_gap_ns = int(interval_ns * 1.5) if interval_ns > 0 else 0
        else:
            max_gap_ns = int(float(max_gap_s) * 1e9)

        # long-form samples
        samples: list[pd.DataFrame] = []
        if direction in {'ingress', 'both'}:
            s = df[['timestamp_ns', 'switch_id', 'next_hop', 'ingress_bytes']].copy()
            s = s.rename(columns={'ingress_bytes': 'used_bytes'})
            s['direction'] = 'ingress'
            samples.append(s)
        if direction in {'egress', 'both'}:
            s = df[['timestamp_ns', 'switch_id', 'next_hop', 'egress_bytes']].copy()
            s = s.rename(columns={'egress_bytes': 'used_bytes'})
            s['direction'] = 'egress'
            samples.append(s)
        samples_df = pd.concat(samples, axis=0, ignore_index=True)

        # Deduplicate: keep max usage for a (queue,time)
        samples_df = (
            samples_df
            .groupby(['timestamp_ns', 'switch_id', 'next_hop', 'direction'], as_index=False)['used_bytes']
            .max()
        )

        threshold_bytes = float(samples_df['used_bytes'].quantile(float(quantile)))
        samples_df['over'] = samples_df['used_bytes'] >= threshold_bytes
        samples_df = samples_df.sort_values(['switch_id', 'next_hop', 'direction', 'timestamp_ns']).reset_index(drop=True)

        events: list[dict] = []
        min_dur_ns = int(float(min_duration_s) * 1e9)
        for (sw, nh, d), g in samples_df.groupby(['switch_id', 'next_hop', 'direction'], sort=False):
            ts = g['timestamp_ns'].to_numpy()
            used = g['used_bytes'].to_numpy()
            over = g['over'].to_numpy()

            in_seg = False
            seg_start_i = 0
            last_over_ts = 0
            seg_peak_i = 0
            for i in range(len(g)):
                if over[i]:
                    if not in_seg:
                        in_seg = True
                        seg_start_i = i
                        seg_peak_i = i
                    else:
                        if max_gap_ns > 0 and (ts[i] - last_over_ts) > max_gap_ns:
                            start_ts = ts[seg_start_i]
                            end_ts = last_over_ts
                            if end_ts - start_ts >= min_dur_ns:
                                events.append({
                                    'switch_id': int(sw),
                                    'next_hop': int(nh),
                                    'direction': d,
                                    't_start_s': float(start_ts / 1e9),
                                    't_end_s': float(end_ts / 1e9),
                                    'duration_s': float((end_ts - start_ts) / 1e9),
                                    'peak_bytes': int(used[seg_peak_i]),
                                    't_peak_s': float(ts[seg_peak_i] / 1e9),
                                    'threshold_bytes': float(threshold_bytes),
                                    'quantile': float(quantile),
                                })
                            seg_start_i = i
                            seg_peak_i = i

                    if used[i] >= used[seg_peak_i]:
                        seg_peak_i = i
                    last_over_ts = ts[i]
                else:
                    if in_seg:
                        start_ts = ts[seg_start_i]
                        end_ts = last_over_ts
                        if end_ts - start_ts >= min_dur_ns:
                            events.append({
                                'switch_id': int(sw),
                                'next_hop': int(nh),
                                'direction': d,
                                't_start_s': float(start_ts / 1e9),
                                't_end_s': float(end_ts / 1e9),
                                'duration_s': float((end_ts - start_ts) / 1e9),
                                'peak_bytes': int(used[seg_peak_i]),
                                't_peak_s': float(ts[seg_peak_i] / 1e9),
                                'threshold_bytes': float(threshold_bytes),
                                'quantile': float(quantile),
                            })
                        in_seg = False

            if in_seg:
                start_ts = ts[seg_start_i]
                end_ts = last_over_ts
                if end_ts - start_ts >= min_dur_ns:
                    events.append({
                        'switch_id': int(sw),
                        'next_hop': int(nh),
                        'direction': d,
                        't_start_s': float(start_ts / 1e9),
                        't_end_s': float(end_ts / 1e9),
                        'duration_s': float((end_ts - start_ts) / 1e9),
                        'peak_bytes': int(used[seg_peak_i]),
                        't_peak_s': float(ts[seg_peak_i] / 1e9),
                        'threshold_bytes': float(threshold_bytes),
                        'quantile': float(quantile),
                    })

        events_df = pd.DataFrame(events)
        if not events_df.empty:
            events_df = events_df.sort_values(['t_start_s', 'switch_id', 'peak_bytes'], ascending=[True, True, False]).reset_index(drop=True)

        return (events_df, samples_df) if return_samples else events_df

    def _get_dci_switch_id(self, as_id: int) -> int:
        for as_obj in self.topo.get('as_topologies', []):
            if int(as_obj.get('as_id')) == int(as_id):
                return int(as_obj.get('dci_switch'))
        raise ValueError(f'No dci_switch found for as_id {as_id}')

    def _build_wan_graph(self) -> dict[int, set[int]]:
        graph: dict[int, set[int]] = defaultdict(set)
        for link in self.topo.get('wan_links', []):
            u = int(link['src'])
            v = int(link['dst'])
            graph[u].add(v)
            graph[v].add(u)
        return graph

    def _shortest_path(self, graph: dict[int, set[int]], src: int, dst: int) -> list[int]:
        if src == dst:
            return [src]
        q = [src]
        prev: dict[int, int | None] = {src: None}
        for u in q:
            for v in graph.get(u, []):
                if v in prev:
                    continue
                prev[v] = u
                if v == dst:
                    q = []
                    break
                q.append(v)

        if dst not in prev:
            return []
        path = [dst]
        cur = dst
        while prev[cur] is not None:
            cur = prev[cur]
            path.append(cur)
        path.reverse()
        return path

    def get_wan_key_path(self, src_as: int, dst_as: int) -> list[int]:
        """Return hop-minimal WAN path between src_as's and dst_as's DCI switches (node id list)."""
        src = self._get_dci_switch_id(src_as)
        dst = self._get_dci_switch_id(dst_as)
        graph = self._build_wan_graph()
        return self._shortest_path(graph, src, dst)

    @auto_save_plot
    def plot_wan_path_buffer(
        self,
        src_as: int,
        dst_as: int,
        *,
        egress: bool = True,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        unit: str = 'MB',
    ):
        """Plot per-hop WAN queue length overlay along the shortest WAN path."""
        self.__read_buffer_info()

        path = self.get_wan_key_path(src_as, dst_as)
        if not path or len(path) < 2:
            print(f'No WAN path found for AS {src_as}->{dst_as}')
            return

        wan_set = set(map(int, self.topo.get('wan_switches', [])))
        col = 'egress_bytes' if egress else 'ingress_bytes'

        df = self.buffer_info.copy()
        if start_time_s is not None:
            df = df[df['timestamp_ns'] >= start_time_s * 1e9]
        if end_time_s is not None:
            df = df[df['timestamp_ns'] <= end_time_s * 1e9]
        if df.empty:
            print('No buffer_monitor samples in the selected time range')
            return

        unit = str(unit).upper()
        if unit == 'B':
            scale = 1.0
        elif unit == 'KB':
            scale = 1e3
        elif unit == 'MB':
            scale = 1e6
        elif unit == 'GB':
            scale = 1e9
        else:
            print(f'Unknown unit {unit}, fallback to MB')
            scale = 1e6
            unit = 'MB'

        hop_series: dict[str, pd.Series] = {}
        for u, v in zip(path[:-1], path[1:]):
            # only plot WAN switch queues
            if int(u) not in wan_set:
                continue
            hop_df = df[(df['switch_id'] == int(u)) & (df['next_hop'] == int(v))]
            if hop_df.empty:
                continue
            series = (
                hop_df.groupby('timestamp_ns')[col]
                .mean()
                .sort_index()
                / scale
            )
            hop_series[f'{u}->{v}'] = series

        if not hop_series:
            print(f'No WAN-hop buffer data found on path: {path}')
            return

        aligned = pd.concat(hop_series, axis=1).ffill().fillna(0.0)
        total = aligned.sum(axis=1)

        plt.figure(figsize=(10, 5))
        x = aligned.index / 1e9
        for label, series in aligned.items():
            plt.plot(x, series.values, linewidth=1.0, label=label)
        plt.plot(x, total.values, linewidth=2.0, color='black', label='SUM')
        plt.xlabel('Timestamp (s)', fontsize=12)
        plt.ylabel(f'Queue ({unit})', fontsize=12)
        plt.title(f'WAN path buffer: AS {src_as}->{dst_as} | path {path}')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=9, ncol=2)

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

    def analyze_cnp_k(self, w_max=4, start_time=2.01, end_time=2.1):
        """
        Calculates x = prob^0.75 * RefRate and finds optimal k such that k*x falls in [1, w_max].
        """
        self.__read_cnp_trigger_prob_info()
        self.__read_as_rate_info()
        
        t_start_ns = start_time * 1e9
        t_end_ns = end_time * 1e9
        
        # 1. Filter by time
        cnp_df = self.cnp_trigger_prob_info[
            (self.cnp_trigger_prob_info['timestamp_ns'] >= t_start_ns) & 
            (self.cnp_trigger_prob_info['timestamp_ns'] <= t_end_ns)
        ].copy()
        
        rate_df = self.as_rate_info[
            (self.as_rate_info['timestamp_ns'] >= t_start_ns) & 
            (self.as_rate_info['timestamp_ns'] <= t_end_ns)
        ].copy()

        if cnp_df.empty or rate_df.empty:
            print("No data in the specified time range.")
            return

        # 2. Map RefRate to CNP info
        # Map src_as to its DCI switch
        as_to_switch = {}
        for as_obj in self.topo['as_topologies']:
            as_to_switch[as_obj['as_id']] = as_obj['dci_switch']
        
        cnp_df['expected_switch'] = cnp_df['src_as'].map(as_to_switch)
        cnp_df = cnp_df[cnp_df['switch_id'] == cnp_df['expected_switch']]
        
        cnp_df = cnp_df.sort_values('timestamp_ns')
        rate_df = rate_df.sort_values('timestamp_ns')
        
        # Merge using asof
        merged_frames = []
        for (src, dst), group_cnp in cnp_df.groupby(['src_as', 'dst_as']):
            group_rate = rate_df[(rate_df['src_as'] == src) & (rate_df['dst_as'] == dst)]
            if group_rate.empty:
                continue
            
            # Using 2ms tolerance for matching
            # Timestamp is int64 (ns), so tolerance must be int
            merged = pd.merge_asof(
                group_cnp, 
                group_rate[['timestamp_ns', 'ref_rate']], 
                on='timestamp_ns', 
                direction='nearest',
                tolerance=int(2e6)
            )
            merged_frames.append(merged)
            
        if not merged_frames:
            print("Could not merge CNP and Rate data.")
            return
            
        full_df = pd.concat(merged_frames)
        full_df = full_df.dropna(subset=['ref_rate'])
        
        # 3. Calculate x = prob^0.75 * RefRate
        full_df['x'] = (full_df['prob'] ** 0.75) * full_df['ref_rate']
        
        # Filter valid x > 0
        valid_x = full_df[full_df['x'] > 1e-9]['x'].values
        
        if len(valid_x) == 0:
            print("No valid positive x values found.")
            return

        print(f"Total valid samples: {len(valid_x)}")
        
        # 4. Find Optimal k (Max Stabbing Query / Interval Problem)
        # For each x, valid k interval is [1/x, w_max/x]
        events = []
        for x_val in valid_x:
            l = 1.0 / x_val
            r = float(w_max) / x_val
            events.append((l, 1))
            events.append((r, -1))
        
        # Sort events by value, then type (process start (+1) before end (-1) if values equal for closed interval overlap logic, 
        # but actually for max points in [1, w_max], if k is exactly at boundary, it counts.
        # If we encounter End of one interval and Start of another at same K, ideally count should not drop then rise.
        # But standard way is fine for finding max.
        events.sort(key=lambda x: (x[0], -x[1])) 
        
        max_overlap = 0
        best_k = 0
        current_overlap = 0
        
        # We need to potentially check the interval between events, but since optimal k must start at some 1/x,
        # checking event points is sufficient.
        for val, type in events:
            current_overlap += type
            if current_overlap > max_overlap:
                max_overlap = current_overlap
                best_k = val 
        
        print(f"Optimal k: {best_k:.4e}")
        print(f"Max samples in range [1, {w_max}]: {max_overlap} ({max_overlap/len(valid_x)*100:.2f}%)")
        
        # 5. Plotting
        plt.figure(figsize=(12, 6))
        
        # Subplot 1: Distribution of log10(x)
        plt.subplot(1, 2, 1)
        # Use log scale because x = prob * Rate can span orders of magnitude
        log_x = np.log10(valid_x)
        plt.hist(log_x, bins=50, color='skyblue', edgecolor='black', alpha=0.7)
        plt.title('Distribution of log10(x)\n(x = prob^0.75 * RefRate)')
        plt.xlabel('log10(x)')
        plt.ylabel('Count')
        plt.grid(True, linestyle='--', alpha=0.5)
        
        # Subplot 2: Distribution of k*x
        plt.subplot(1, 2, 2)
        adjusted_x = valid_x * best_k
        # Plot in log scale for X axis to see [1, 4] clearly if data spans widely
        # But request implies [1, 4] is the target linear range.
        # Let's clip visual range or just show histogram around [0, w_max*2]
        plt.hist(adjusted_x, bins=100, range=(0, w_max * 2), color='orange', edgecolor='black', alpha=0.7, label='k*x')
        plt.axvline(1, color='red', linestyle='--', linewidth=2, label='Lower (1)')
        plt.axvline(w_max, color='green', linestyle='--', linewidth=2, label=f'Upper ({w_max})')
        plt.title(f'Distribution of k*x (k={best_k:.2e})\nCoverage: {max_overlap/len(valid_x)*100:.1f}%')
        plt.xlabel('k * x')
        plt.ylabel('Count')
        plt.legend()
        plt.grid(True, linestyle='--', alpha=0.5)
        
        save_name = f'cnp_k_analysis_{self.id}_w{w_max}.pdf'
        plt.tight_layout()
        plt.savefig(save_name)
        print(f"Plot saved to {save_name}")
        plt.close()
        
        return best_k

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
    a = get_analyser(40)
    b = get_analyser(41)
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
    get_analyser(40).plot_qp_rate([467])

if __name__ == '__main__':
    # Test CNP K analysis on experiment 132
    try:
        ana = get_analyser(132)
        ana.analyze_cnp_k(w_max=4, start_time=2.01, end_time=2.1)
    except Exception as e:
        print(f"Error running analysis on 132: {e}")
        # traceback.print_exc()

# %%
