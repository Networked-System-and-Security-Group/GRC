import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle
from deep_analyse import *

gscc_c = (130/255,0,180/255)
dcqcn_c = "orange"
_style_list = [
    ('--',              dcqcn_c, 'o'),
    ('--',              gscc_c,           's'),
    (':',               dcqcn_c,          'o'),
    (':',               gscc_c,  's'),
]

def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None):
    """
    针对任意多条曲线，按 _style_list 轮换样式画图。

    参数:
      data: dict[label, (x_list, y_list)]
      xlabel, ylabel: 坐标轴标签
      filename: 保存文件名（含路径或相对路径）
      xticks: 自定义 x 轴刻度列表（可选）
      xlim: 自定义 x 轴范围 (xmin, xmax)（可选）
    """
    plt.figure(figsize=(5, 4), dpi=300)
    style_cycle = cycle(_style_list)
    y_max = 0

    # 逐条绘制
    for label, (x, y) in data.items():
        ls, col, mk = next(style_cycle)
        print(x,y)
        plt.plot(
            x, y,
            label=label,
            linestyle=ls,
            color=col,
            marker=mk,
            linewidth=2.5,
            markersize=4
        )
        if y:
            y_max = max(y_max, max(y))

    # X 轴刻度
    if xticks is None:
        all_x = sorted({xi for xs, _ in data.values() for xi in xs})
        plt.xticks(all_x, fontsize=14)
    else:
        plt.xticks(xticks, fontsize=14)

    # Y 轴刻度：0 到 y_max，分 10 段，隔行显示
    raw_step = (y_max or 1) / 10
    step = 0.5 if raw_step <= 1 else np.ceil(raw_step * 2) / 2
    all_ticks = np.arange(0, y_max + step, step)
    visible = [t if True or i % 2 != len(all_ticks) % 2 else ''
               for i, t in enumerate(all_ticks)]
    #plt.yscale('log', base=2)
    plt.yticks(all_ticks, visible, fontsize=14)

    # 轴标签、图例、网格、去除多余边框
    plt.xlabel(xlabel, fontsize=16)
    plt.ylabel(ylabel, fontsize=16)
    plt.legend(frameon=False, fontsize=16, loc='upper left', bbox_to_anchor=(0,1.1))
    plt.grid(axis='y', alpha=0.3)
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 设置范围
    plt.ylim(0.8, all_ticks[-1])
    #plt.ylim(0.9, 10)
    if xlim:
        plt.xlim(*xlim)

    # 保存并关闭
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")

#df = get_basic_result('551-556,539-550')
df = get_basic_result('577-594')
avg_fct_inter = np.array(df['Avg_Inter_FCT']).reshape(6, 3).T
print(avg_fct_inter)
avg_fct_intra = np.array(df['Avg_Intra_FCT']).reshape(6, 3).T
print(avg_fct_intra)

data = {
    'DCQCN-Inter':    ([60,80,100,120,140,160], avg_fct_inter[0].tolist()),
    'GSCC-Inter':   ([60,80,100,120,140,160], avg_fct_inter[2].tolist()),
    'DCQCN-Intra':    ([60,80,100,120,140,160], avg_fct_intra[0].tolist()),
    'GSCC-Intra':   ([60,80,100,120,140,160], avg_fct_intra[2].tolist()),
}
plot_auto_lines(
    data,
    xlabel="Avg. Inter-DC Throughput (Gbps)",
    ylabel="Avg. FCT Slowdown",
    filename="overall.pdf",
    xticks=[60,80,100,120,140,160],
    xlim=(55,160)
)
quit()