import os
import os.path as op
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from deep_analyse import get_analyser
# 这个脚本用于绘图分析流情况（不知道为什么我这边运行deep_analyse.py，auto_save_plot会失效，因此单开了一个）
# 字体设置（保持与deep_analysis.py一致）
font_path = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
try:
    from matplotlib.font_manager import FontProperties
    font_prop = FontProperties(fname=font_path)
except:
    font_prop = None  # 兼容无对应字体的环境


def plot_link_utilization_custom(ana, src_id, dst_id, output_dir="figures"):
    """自定义链路利用率绘图，直接保存PDF"""
    # 1. 加载数据
    if ana.link_info is None:
        ana.link_info = pd.read_csv(op.join(ana.dir, 'link_utilization'))
    
    # 2. 过滤数据
    df = ana.link_info[
        (ana.link_info['src_id'] == src_id) & 
        (ana.link_info['dst_id'] == dst_id)
    ]
    if df.empty:
        print(f'No link info for {src_id}->{dst_id}')
        return
    
    # 3. 绘图
    plt.figure(figsize=(10, 6))
    plt.plot(df['timestamp_ns'], df['bytes'] / 1e9, label='Link Utilization')
    plt.xlabel('Timestamp (ns)')
    plt.ylabel('GB/s')
    plt.title(f'Link Utilization: {src_id}->{dst_id}')
    
    # 4. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"link_{src_id}_{dst_id}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存链路利用率PDF: {save_path}")


def plot_as_rate_custom(ana, src_as, dst_as, output_dir="figures"):
    """自定义AS速率绘图，直接保存PDF"""
    # 1. 加载数据
    if ana.as_rate_info is None:
        ana.as_rate_info = pd.read_csv(op.join(ana.dir, 'rate_monitor'))
    
    # 2. 过滤数据
    df = ana.as_rate_info[
        (ana.as_rate_info['src_as'] == src_as) & 
        (ana.as_rate_info['dst_as'] == dst_as)
    ]
    if df.empty:
        print(f'No rate info for AS {src_as}->{dst_as}')
        return
    
    # 3. 绘图
    plt.figure(figsize=(10, 6))
    plt.plot(df['timestamp_ns'], df['real_rate'] / 1e9, label='Real Rate')
    plt.plot(df['timestamp_ns'], df['ref_rate'] / 1e9, label='Ref Rate', linestyle='--')
    plt.xlabel('Timestamp (ns)')
    plt.ylabel('Rate (GB/s)')
    plt.title(f'AS Rate: {src_as}->{dst_as}')
    plt.legend()
    
    # 4. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"as_rate_{src_as}_{dst_as}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存AS速率PDF: {save_path}")


def plot_rtt_custom(ana, src_as, dst_as, output_dir="figures"):
    """自定义RTT绘图函数，直接保存PDF"""
    # 1. 读取RTT数据
    if ana.rtt_info is None:
        ana.rtt_info = pd.read_csv(op.join(ana.dir, 'rtt_log'))
    
    # 2. 查找源AS对应的交换机
    switch_id = None
    for as_obj in ana.topo['as_topologies']:
        if as_obj['as_id'] == src_as:
            switch_id = as_obj['dci_switch']
            break
    
    if switch_id is None:
        print(f'No switch found for src_as {src_as}')
        return
    
    # 3. 过滤数据
    df = ana.rtt_info[
        (ana.rtt_info['switch_id'] == switch_id) & 
        (ana.rtt_info['dst_as'] == dst_as)
    ]
    
    if df.empty:
        print(f'No RTT info for switch {switch_id} and dst_as {dst_as}')
        return
    
    # 4. 创建图表
    plt.figure(figsize=(8, 5))
    
    # 按next_hop分组并绘制不同路径的RTT
    for nxt, grp in df.groupby('next_hop'):
        plt.plot(grp['timestamp_ns'], grp['rtt1_ms'], 
                 label=f'{nxt}-Sens', linestyle='-', marker='.', markersize=4)
    
    # 5. 设置图表属性
    plt.xlabel('Timestamp (ns)', fontsize=12)
    plt.ylabel('RTT (ms)', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(fontsize=10)
    plt.title(f'RTT from AS{src_as} to AS{dst_as} (Switch {switch_id})')
    
    # 6. 保存图表
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"rtt_as{src_as}_to_{dst_as}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存RTT PDF: {save_path}")


def plot_accumulated_bytes_custom(ana, switch_id, dst_as, output_dir="figures"):
    """自定义累积字节数绘图（新增）"""
    # 1. 加载数据
    if ana.accumulated_bytes_info is None:
        ana.accumulated_bytes_info = pd.read_csv(op.join(ana.dir, 'accumulated_bytes_log'))
    
    # 2. 过滤数据
    df = ana.accumulated_bytes_info[
        (ana.accumulated_bytes_info['switch_id'] == switch_id) &
        (ana.accumulated_bytes_info['dst_as'] == dst_as)
    ]
    if df.empty:
        print(f'No accumulated bytes info for switch {switch_id} and dst_as {dst_as}')
        return
    
    # 3. 绘图
    plt.figure(figsize=(10, 6))
    plt.plot(df['timestamp_ns'], df['accumulated_bytes'] / 1e3, label='Accumulated Bytes')
    plt.xlabel('Timestamp (ns)', fontsize=12)
    plt.ylabel('Accumulated Bytes (KB)', fontsize=12)
    plt.title(f'Accumulated Bytes: Switch {switch_id} -> dst_as {dst_as}', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(fontsize=10)
    
    # 4. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"accum_bytes_switch{switch_id}_dstas{dst_as}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存累积字节数PDF: {save_path}")


def plot_cnp_timestamps_custom(ana, flow_id, start_time=2.0, end_time=2.05, output_dir="figures"):
    """自定义CNP时间戳绘图（新增）"""
    # 1. 加载数据
    if ana.cnp_info is None:
        ana.cnp_info = pd.read_csv(op.join(ana.dir, 'cnp_log'))
    
    # 2. 过滤数据（按时间范围和流ID）
    df = ana.cnp_info[
        (ana.cnp_info['flow_id'] == flow_id) &
        (ana.cnp_info['timestamp_ns'] >= start_time * 1e9) &
        (ana.cnp_info['timestamp_ns'] <= end_time * 1e9)
    ]
    if df.empty:
        print(f'No CNP info for flow_id {flow_id} in [{start_time}, {end_time}]s')
        return
    
    # 3. 绘图（散点图）
    plt.figure(figsize=(10, 3))
    plt.scatter(df['timestamp_ns'], np.zeros_like(df['timestamp_ns']), alpha=0.6, s=3, label='CNP Events')
    plt.xlabel('Timestamp (ns)', fontsize=12)
    plt.title(f'CNP Timestamps: Flow {flow_id} (Time Range: {start_time}-{end_time}s)', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(fontsize=10)
    
    # 4. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"cnp_flow{flow_id}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存CNP时间戳PDF: {save_path}")


def plot_qp_rate_custom(ana, flow_ids, output_dir="figures"):
    """自定义QP速率绘图（新增）"""
    # 1. 加载数据
    if ana.qp_rate_info is None:
        ana.qp_rate_info = pd.read_csv(op.join(ana.dir, 'qp_rate_log'))
    
    # 2. 绘图
    plt.figure(figsize=(10, 6))
    for flow_id in flow_ids:
        df = ana.qp_rate_info[ana.qp_rate_info['flow_id'] == flow_id]
        if df.empty:
            print(f'No QP rate info for flow_id {flow_id}')
            continue
        plt.plot(df['timestamp_ns'] / 1e9, df['rate'] / 1e9, label=f'Flow {flow_id}')
    
    # 3. 设置图表属性
    plt.xlabel('Timestamp (s)', fontsize=12)
    plt.ylabel('Rate (GB/s)', fontsize=12)
    plt.title(f'QP Rate for Flows {flow_ids}', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(fontsize=10)
    
    # 4. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    flow_ids_str = "_".join(map(str, flow_ids))
    save_path = op.join(output_dir, f"qp_rate_flows{flow_ids_str}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存QP速率PDF: {save_path}")


def plot_fct_cdf_custom(ana, output_dir="figures"):
    """自定义FCT慢化CDF绘图（新增）"""
    # 1. 加载流数据
    ana._Analyser__read_flow_info()  # 调用Analyser内部方法读取流信息
    flow_df = ana.flow_df
    intra_df = ana.get_intra_df()
    inter_df = ana.get_inter_df()
    
    # 2. 定义CDF绘图辅助函数
    def plot_cdf(series, label, color):
        if series.empty:
            print(f"Warning: No data for {label}")
            return
        sorted_vals = np.sort(series)
        y = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
        plt.plot(sorted_vals, y, label=label, color=color)
    
    # 3. 绘图
    plt.figure(figsize=(10, 6))
    plot_cdf(flow_df['fct_slowdown'], 'Overall', 'blue')
    plot_cdf(intra_df['fct_slowdown'], 'Intra-AS', 'green')
    plot_cdf(inter_df['fct_slowdown'], 'Inter-AS', 'red')
    
    # 4. 设置图表属性
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.xlabel('FCT Slowdown', fontsize=12)
    plt.ylabel('CDF', fontsize=12)
    plt.title('FCT Slowdown CDF', fontsize=14)
    plt.legend(fontsize=10)
    plt.xscale('log')  # 对数坐标更适合展示慢化比分布
    plt.ylim(0, 1.05)
    
    # 5. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"fct_cdf_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存FCT CDF PDF: {save_path}")


def plot_buffer_custom(ana, switch_id, egress=True, output_dir="figures"):
    """自定义缓冲区利用率绘图（新增）"""
    # 1. 加载数据
    if ana.buffer_info is None:
        ana.buffer_info = pd.read_csv(op.join(ana.dir, 'buffer_monitor'))
    
    # 2. 过滤数据
    df = ana.buffer_info[ana.buffer_info['switch_id'] == switch_id]
    if df.empty:
        print(f'No buffer info for switch {switch_id}')
        return
    
    # 3. 选择 ingress/egress 数据
    col = 'egress_bytes' if egress else 'ingress_bytes'
    df = df[['timestamp_ns', 'next_hop', col]].rename(columns={col: 'bytes'})
    
    # 4. 绘图
    plt.figure(figsize=(10, 6))
    for next_hop, group in df.groupby('next_hop'):
        plt.plot(group['timestamp_ns'] / 1e9, group['bytes'] / 1e6, label=f'Next Hop {next_hop}')
    
    # 5. 设置图表属性
    plt.xlabel('Timestamp (s)', fontsize=12)
    plt.ylabel('Queue Length (MB)', fontsize=12)
    buf_type = "Egress" if egress else "Ingress"
    plt.title(f'Buffer Utilization: Switch {switch_id} ({buf_type})', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(fontsize=10)
    
    # 6. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    buf_type_str = "egress" if egress else "ingress"
    save_path = op.join(output_dir, f"buffer_{buf_type_str}_switch{switch_id}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存缓冲区利用率PDF: {save_path}")


def plot_pfc_custom(ana, node_id, output_dir="figures"):
    """自定义PFC暂停事件绘图（新增）"""
    # 1. 加载数据
    if ana.pfc_info is None:
        ana.pfc_info = pd.read_csv(op.join(ana.dir, 'pfc_file'))
    
    # 2. 过滤数据（只保留暂停事件）
    df = ana.pfc_info[
        (ana.pfc_info['node_id'] == node_id) &
        (ana.pfc_info['is_pause'] == 1)
    ]
    if df.empty:
        print(f'No PFC pause events for node {node_id}')
        return
    
    # 3. 绘图
    plt.figure(figsize=(10, 6))
    y_pos = 1
    y_labels = []
    for nbr_id, group in df.groupby('nbr_id'):
        # 每个邻居ID用不同y坐标绘制散点
        plt.scatter(group['timestamp_ns'] / 1e9, np.ones(len(group)) * y_pos, 
                   label=str(nbr_id), s=1, alpha=0.6)
        y_labels.append(nbr_id)
        y_pos += 1
    
    # 4. 设置图表属性
    plt.xlabel('Timestamp (s)', fontsize=12)
    plt.ylabel('Neighbor ID', fontsize=12)
    plt.title(f'PFC Pause Timeline: Node {node_id}', fontsize=14)
    plt.yticks(range(1, y_pos), y_labels)
    plt.legend(title='Neighbor ID', bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()  # 适配图例位置
    
    # 5. 保存PDF
    os.makedirs(output_dir, exist_ok=True)
    save_path = op.join(output_dir, f"pfc_node{node_id}_exp{ana.id}.pdf")
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"[Custom Plot] 已保存PFC事件PDF: {save_path}")


# 调用示例
if __name__ == "__main__":
    ana = get_analyser(286)  # 替换为实际实验ID
    ana.diagnose_slow_flow()
    print()
    ana.show_drop()
    for i in range(0,6):
        for j in range(0,6):
            if i!=j:
                plot_as_rate_custom(ana, src_as=i, dst_as=j)
    #plot_link_utilization_custom(ana, src_id=222, dst_id=226)
    #plot_rtt_custom(ana, src_as=0, dst_as=4)
    
    # 新增函数调用示例（根据需要启用）
    # plot_accumulated_bytes_custom(ana, switch_id=101, dst_as=3)
    # plot_cnp_timestamps_custom(ana, flow_id=1001, start_time=2.0, end_time=2.05)
    # plot_qp_rate_custom(ana, flow_ids=[8987, 8311, 10841])
    # plot_fct_cdf_custom(ana)
    # plot_buffer_custom(ana, switch_id=226, egress=True)
    # plot_pfc_custom(ana, node_id=222)