# %%
from __future__ import annotations
import json
import multiprocessing
import subprocess
import matplotlib.pyplot as plt
import os.path as op
import re
import sys
from dataclasses import dataclass, field
from collections import Counter, OrderedDict, defaultdict
import numpy as np
import pandas as pd
from typing import Generator, Union, List, Dict
from scipy.stats import pearsonr, spearmanr
import readline
import os
import json
import pandas as pd
from IPython.display import display

def get_dir_by_id(config_id):
    '''return base_dir, lb_mode, load'''
    base_dir = op.join(op.dirname(__file__), '../mix/output') 
    command = f"ls -l {base_dir}"
    # 执行命令
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    full_config_id = [x.strip().split()[-1] for x in filter(lambda x : f'[{config_id}]' in x, result.stdout.split('\n'))]
    if not len(full_config_id) == 1:
        raise Exception(f'failed to find {config_id} experiment')
    full_config_id = full_config_id[0]
    return op.join(base_dir, full_config_id)

@dataclass
class PfcEvent:
    timestamp: int
    node_id: int
    node_type: int
    if_index: int
    type: int

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
                assert(False)
        self.src_as = get_as(self.src)
        self.dst_as = get_as(self.dst)

def plot_cdf(data, label=None, color=None):
    """
    辅助函数：绘制单个数据集的 CDF
    """
    if not data:  # 处理空数据情况
        return
    
    # 排序数据点
    sorted_data = np.sort(data)
    
    # 计算累积概率（y 值）
    y_values = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
    
    # 绘制 CDF 曲线
    plt.plot(sorted_data, y_values, label=label, color=color)

class Analyser:
    def __init__(self, id):
        self.id = id = str(id)
        self.dir = get_dir_by_id(self.id)
        self.flows = []
        self.id_to_flow:dict[int, FlowInfo] = {}
        self.intra_flows = []
        self.inter_flows = []
        self.rtt_info:pd.DataFrame = None #timestamp_ns,switch_id,dst_as,next_hop,rtt1_ms,rtt2_ms,timeout_count
        self.drop_info:pd.DataFrame = None #timestamp_ns,switch_id,next_hop,flow_id,seq_num,type
        

    def plot_rtt(self, switch_id, dst_as):
        self.__read_rtt_info()
        rtt_info = self.rtt_info[(self.rtt_info['switch_id'] == switch_id) & (self.rtt_info['dst_as'] == dst_as)]
        if len(rtt_info) == 0:
            print(f'No RTT info for switch {switch_id} and dst_as {dst_as}')
            return
        grouped = rtt_info.groupby('next_hop')
        fig, ax = plt.subplots(figsize=(8, 5))

        for next_hop, group in grouped:
            ax.plot(group['timestamp_ns'], group['rtt1_ms'], label=f'NxtHop {next_hop} - SensitiveRTT', linestyle='-', marker='.', markersize=4)
            ax.plot(group['timestamp_ns'], group['rtt2_ms'], label=f'NxtHop {next_hop} - StableRTT', linestyle='--', marker='.', markersize=4)

        ax.set_xlabel('Timestamp (ns)', fontsize=12)
        ax.set_ylabel('RTT (ms)', fontsize=12)
        #ax.set_title(f'RTT for Switch {switch_id} and dst_as {dst_as}', fontsize=14)
        ax.legend(fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.7)

        fig.tight_layout()
        save_path = op.join(op.dirname(__file__), f'figures/{self.id}-RTT{switch_id}-{dst_as}.png')
        fig.savefig(save_path, dpi=300)
    
    def plot_fct_cdf(self, save_path=''):
        """
        绘制 FCT slowdown 的 CDF 图，包含 overall, intra 和 inter 三条曲线
        
        参数:
        - save_path: 图片保存路径，如果为 None 则不保存
        - show: 是否显示图像
        """
        self.__read_flow_info()
        if save_path == '':
            save_path = op.join(op.dirname(__file__), f'figures/FCT_CDF{self.id}.png')
        
        # 获取三种类型的 FCT slowdown 数据
        overall_fcts = [f.fct_slowdown for f in self.flows]
        intra_fcts = [f.fct_slowdown for f in self.intra_flows]
        inter_fcts = [f.fct_slowdown for f in self.inter_flows]
        
        plt.figure(figsize=(10, 6))
        
        # 绘制每种类型的 CDF 曲线
        plot_cdf(overall_fcts, label='Overall', color='blue')
        plot_cdf(intra_fcts, label='Intra-cluster', color='green')
        plot_cdf(inter_fcts, label='Inter-cluster', color='red')
        print(f'Overall: {np.mean(overall_fcts):.2f}, Intra: {np.mean(intra_fcts):.2f}, Inter: {np.mean(inter_fcts):.2f}')
        
        # 设置图形属性
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.xlabel('FCT Slowdown', fontsize=12)
        plt.ylabel('CDF', fontsize=12)
        plt.title('CDF of FCT Slowdown', fontsize=14)
        plt.legend(fontsize=10)
        
        # 设置 x 轴为对数刻度（可选，取决于数据范围）
        if max(overall_fcts + intra_fcts + inter_fcts) / min(overall_fcts + intra_fcts + inter_fcts) > 100:
            plt.xscale('log')
        
        # Y 轴范围从 0 到 1
        plt.ylim(0, 1.05)
        
        # 保存图片（如果提供路径）
        if save_path:
            plt.savefig(save_path, bbox_inches='tight', dpi=300)
            print(f'保存至 {op.abspath(save_path)}')

    def plot_drop(self, switch_id, src_as, dst_as):
        #绘制src_as到dst_as在switch_id上的丢包散点图
        self.__read_drop_info()
        drop_info = self.drop_info[(self.drop_info['switch_id'] == switch_id) 
                                   & (self.drop_info['src_as'] == src_as) 
                                   & (self.drop_info['dst_as'] == dst_as)]
        if len(drop_info) == 0:
            print(f'No drop info for switch {switch_id} and dst_as {dst_as}')
            return
        fig, ax = plt.subplots(figsize=(8, 5))
        times = drop_info['timestamp_ns']
        ax.scatter(times, np.zeros_like(times), alpha=0.6, edgecolors='w', s=50)
        
        ax.set_xlabel('Timestamp (ns)', fontsize=12)
        ax.set_title(f'Drop Events for Switch {switch_id}, Src AS {src_as}, Dst AS {dst_as}', fontsize=14)
        ax.grid(True, linestyle='--', alpha=0.7)
        
        fig.tight_layout()
        save_path = op.join(op.dirname(__file__), f'figures/{self.id}-Drop{switch_id}-{src_as}-{dst_as}.png')
        fig.savefig(save_path, dpi=300)
        print(f'Drop scatter plot saved to {save_path}')
        

    def print_info(self):
        print(f'===ID:{self.id}===')

    def get_avg_fct(self):
        self.__read_flow_info()
        overall = np.average([f.fct_slowdown for f in self.flows])
        intra = np.average([f.fct_slowdown for f in self.intra_flows])
        inter = np.average([f.fct_slowdown for f in self.inter_flows])
        return overall, intra, inter
    
    def get_p99_fct(self):
        self.__read_flow_info()
        overall = np.percentile([f.fct_slowdown for f in self.flows], 99)
        intra = np.percentile([f.fct_slowdown for f in self.intra_flows], 99)
        inter = np.percentile([f.fct_slowdown for f in self.inter_flows], 99)
        return overall, intra, inter



    def __read_rtt_info(self):
        if self.rtt_info is not None:
            return
        self.rtt_info = pd.read_csv(op.join(self.dir, 'rtt_log'))

    def __read_flow_info(self):
        if len(self.flows) != 0:
            return
        with open(op.join(self.dir, 'flow_output'), 'r') as f:
            self.flows = [FlowInfo(**item) for item in json.load(f)]
            self.id_to_flow = {f.flow_id: f for f in self.flows}
            self.intra_flows = list(filter(lambda x : len(x.passed_nodes) <= 5, self.flows))
            self.inter_flows = list(filter(lambda x : len(x.passed_nodes) > 5, self.flows))

    def __read_drop_info(self):
        self.__read_flow_info()
        if self.drop_info is not None:
            return
        self.drop_info = pd.read_csv(op.join(self.dir, 'drop_log'))
        self.drop_info['src_as'] = self.drop_info['flow_id'].apply(lambda x: self.id_to_flow[x].src_as if x in self.id_to_flow else None)
        self.drop_info['dst_as'] = self.drop_info['flow_id'].apply(lambda x: self.id_to_flow[x].dst_as if x in self.id_to_flow else None)


_instances = {}
def get_analyser(id) -> Analyser:
    if id not in _instances.keys():
        _instances[id] = Analyser(str(id))
    return _instances[id]

def convert_str_to_id(config_ids_str:str)->list:
    config_ids = []
    for part in config_ids_str.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            config_ids.extend(range(start, end + 1))
        else:
            config_ids.append(int(part))
    return config_ids


def analyser_iter(config_ids_str:str) -> Generator[Analyser, None, None]:
    for id in convert_str_to_id(config_ids_str):
        try:
            analyser = get_analyser(id)
            yield analyser
        except Exception as e:
            print(f'{id}号实验数据出现异常：{e}')

def clear_data(config_ids_str):
    removed_dirs = []
    for analyser in analyser_iter(config_ids_str):
        base_dir = analyser.dir
        print(base_dir)
        removed_dirs.append(base_dir)
    op = input('press y to delete these data')
    if op == 'y':
        for dir in removed_dirs:
            os.system(f'rm -r {dir}') 

if __name__ == '__main__':
    #print(get_analyser(148).get_avg_fct())
    #print(get_analyser(148).get_p99_fct())
    #get_analyser(148).plot_fct_cdf()
    pass

# %%
