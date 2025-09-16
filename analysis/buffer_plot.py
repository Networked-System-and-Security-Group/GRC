from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle
import math

gscc_c = (130/255, 0, 180/255)
_style_list = [
    ('--', 'orange', 'o'),
    ('--', 'c', 'o'),
    ('--', gscc_c, 'o'),
]


def process_y_data(y_list):
    """
    将y数据按索引模5分组，每组取平均值（排除None），返回长度为5的列表。
    若某组无有效数据（全为None），则对应位置为None。
    """
    # 初始化5个分组（对应模5的0-4）
    groups = [[] for _ in range(5)]
    for idx, val in enumerate(y_list):
        if val is not None:  # 只保留非None值
            mod = idx % 5  # 计算索引模5的结果
            groups[mod].append(val)
    # 计算每个分组的平均值（空分组返回None）
    processed = []
    for group in groups:
        if group:  # 分组非空时取平均
            processed.append(sum(group) / len(group))
        else:  # 分组为空时保留None
            processed.append(None)
    return processed

def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None, logtag=0):
    """
    针对任意多条曲线，按 _style_list 轮换样式画图，支持处理None值。
    当logtag为1时，Y轴使用对数坐标
    """
    plt.figure(figsize=(5, 4), dpi=300)
    plt.rcParams['pdf.fonttype']= 42
    style_cycle = cycle(_style_list)
    
    # 收集所有有效y值，用于计算y_min和y_max
    all_valid_y = []
    for label, (x, y) in data.items():
        # 过滤掉y为None的点
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(x, y):
            if yi is not None:  # 只保留y不为None的点
                filtered_x.append(xi)
                filtered_y.append(yi)
                all_valid_y.append(yi)  # 收集有效y值
        
        ls, col, mk = next(style_cycle)
        plt.plot(
            filtered_x, filtered_y,
            label=label,
            linestyle=ls,
            color=col,
            marker=mk,
            linewidth=3.5,
            markersize=4
        )
    
    # 计算实际的y_min和y_max（处理无有效数据的极端情况）
    if not all_valid_y:  # 无有效数据时，默认范围0-1
        y_min, y_max = 0, 1
    else:
        y_min = min(all_valid_y)
        y_max = max(all_valid_y)
    
    # 设置Y轴为对数坐标（如果logtag为1）
    if logtag == 1:
        plt.yscale('log')
        # 对数坐标下使用实际的最小最大值
        plt.ylim(y_min * 0.9, y_max * 1.1)  # 稍微扩展范围以便更好地显示数据
    else:
        # 线性坐标：y_min向下取整，y_max向上取整
        y_min_floor = math.floor(y_min)
        y_max_ceil = math.ceil(y_max)
        
        # 生成Y轴刻度
        range_ = y_max_ceil - y_min_floor
        if range_ == 0:  # 所有值相同的极端情况
            step = 1
        else:
            step = max(1, round(range_ / 10))  # 最多10个刻度，步长至少为1
        all_ticks = np.arange(y_min_floor, y_max_ceil + step, step)
        
        # 调整刻度显示（隔行显示，避免拥挤）
        visible = [t if i % 2 == 0 else '' for i, t in enumerate(all_ticks)]
        plt.yticks(all_ticks, visible, fontsize=14)
        plt.ylim(y_min_floor, y_max_ceil)
    
    # X轴刻度
    if xticks is None:
        all_x = []
        for xs, ys in data.values():
            for xi, yi in zip(xs, ys):
                if yi is not None:
                    all_x.append(xi)
        all_x = sorted(set(all_x))
        plt.xticks(all_x, fontsize=14)
    else:
        plt.xticks(xticks, fontsize=14)
    
    # 轴标签、图例、网格、去除多余边框
    plt.xlabel(xlabel, fontsize=16)
    plt.ylabel(ylabel, fontsize=16)
    plt.legend(frameon=False, fontsize=16, loc='upper left', bbox_to_anchor=(0,1.1))
    plt.grid(axis='y', alpha=0.3)
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    if xlim:
        plt.xlim(*xlim)
    
    # 保存并关闭
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")

def get_buffer(expr):
    res = []
    for ana in analyser_iter(expr):
        try:
            avg_buffer = ana.get_buffer_information()
            res.append(avg_buffer)
        except:
            res.append(None)
    return [x / 1e6 if x is not None else None for x in res]


def main():
    # dcqcn_res = get_buffer('309,312,315,318,321')
    # gscc_res = get_buffer('310,313,316,319,322')
    # dcqcn_ecn_res = get_buffer('311,314,317,320,323')

    # dcqcn_res = get_buffer('380,383,386,599,602')
    # gscc_res = get_buffer('381,384,387,600,603')

    # dcqcn_res = get_buffer('380,383,386,389,602')
    # gscc_res = get_buffer('381,384,387,390,603')
    # dcqcn_inf_res = get_buffer('567-569,605,606')

    dcqcn_res = get_buffer('448,451,454,457,460')
    gscc_res = get_buffer('449,452,455,458,461')
    dcqcn_inf_res = get_buffer('562-566')

    print(f"buffer{(dcqcn_res[4]-gscc_res[4])/dcqcn_res[4]}")

    x_data = [0, 50, 100, 150, 200]
    x_label = 'Dynamic traffic throughput (Gbps)'

    # 绘制Average normalized FCT
    data_to_plot = {
        'w/o-GSCC': (x_data, dcqcn_res),
        'inf-w/o-GSCC': (x_data, dcqcn_inf_res),
        'GSCC': (x_data, gscc_res)
    }

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="Buffer utilization (MB)",
        filename="buffer.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
    )

    quit()

if __name__ == "__main__":
    main()
