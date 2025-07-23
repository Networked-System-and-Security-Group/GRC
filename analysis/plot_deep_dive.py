import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from deep_analyse import *
# 这是绘制消融实验的脚本，分别是无消融，消融RTT梯度，消融选择性覆盖
# 颜色和图例定义
color_list = [
    (130/255, 0, 180/255),  # GSCC紫色
    "orange",               # DCQCN橙色
    "red",                  # 红色
    "blue"                  # 蓝色
]

legend_list = ["normal", "no rtt diff", "no selective cover"]

def autolabel(rects, ax):
    """在每个柱子上方添加数值标签"""
    for rect in rects:
        height = rect.get_height()
        ax.annotate('{:.2f}'.format(height),  # 保留两位小数
                    xy=(rect.get_x() + rect.get_width()/2, height),
                    xytext=(0, 3),  # 3点垂直偏移
                    textcoords="offset points",
                    ha='center', va='bottom',
                    fontsize=10)

def plot_grouped_bars(data, xlabel, ylabel, filename, xticks=None, xlim=None):
    """
    绘制分组柱状图，每组有多个柱（数量取决于data[i]的长度）
    
    参数:
      data: dict[label, y_list]  # 注意这里与折线图不同，y_list是每个组的柱子值列表
      xlabel, ylabel: 坐标轴标签
      filename: 保存文件名
      xticks: 自定义x轴刻度列表（可选）
      xlim: 自定义x轴范围（可选）
    """
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    
    # 确定组数和柱子数
    group_labels = list(data.keys())
    num_groups = len(group_labels)
    num_bars = len(next(iter(data.values())))  # 获取第一个组的柱子数
    
    # 柱子的宽度和位置计算
    bar_width = 0.25
    group_width = num_bars * bar_width + 0.15  # 每组总宽度+间距
    index = np.arange(num_groups) * group_width  # 每组中心位置
    
    # 绘制每个柱子
    bars = []
    for i in range(num_bars):
        # 获取当前柱子的所有组的值
        y_values = [data[group][i] for group in group_labels]
        rects = ax.bar(
            index + i * bar_width, 
            y_values, 
            bar_width,
            color=color_list[i],
            label=legend_list[i] if i < len(legend_list) else f'Bar {i+1}',
            edgecolor='black',
            linewidth=0.5
        )
        bars.append(rects)
        # 在每个柱子上添加数值标签
        autolabel(rects, ax)
    
    # 设置x轴标签和刻度
    ax.set_xlabel(xlabel, fontsize=16)
    ax.set_ylabel(ylabel, fontsize=16)
    ax.set_xticks(index + bar_width * (num_bars-1)/2)
    ax.set_xticklabels(group_labels, fontsize=14)
    
    # 设置y轴
    y_max = max([max(y) for y in data.values()])
    raw_step = y_max / 10
    step = 0.5 if raw_step <= 1 else np.ceil(raw_step * 2) / 2
    y_ticks = np.arange(0, y_max + step, step)
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_ticks, fontsize=14)
    ax.set_ylim(0, y_max * 1.05)
    
    # 图例和网格
    ax.legend(frameon=False, fontsize=14, loc='upper left', bbox_to_anchor=(0, 1.1))
    ax.grid(axis='y', alpha=0.3)
    
    # 去除多余边框
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # 保存图像
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")

# 获取数据
result = get_basic_result('45-47')
print(result)
data = result.T.values.tolist()

# 重组数据格式为分组柱状图需要的格式
data_to_plot = {
    'Avg FCT': data[1],
    'Avg intra_flow FCT': data[2],
    'Avg inter_flow FCT': data[3]
}

plot_grouped_bars(
    data_to_plot,
    xlabel="Metric Type",
    ylabel="Avg. FCT Slowdown",
    filename="deep_dive.pdf"
)