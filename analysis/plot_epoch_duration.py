from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle

gscc_c = (130/255, 0, 180/255)
_style_list = [
    ('-.', gscc_c, 'd'),
    (':', gscc_c, '^')
]

def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None, logtag=0):
    """
    针对任意多条曲线，按 _style_list 轮换样式画图，支持处理None值。

    参数:
      data: dict[label, (x_list, y_list)]
      xlabel, ylabel: 坐标轴标签
      filename: 保存文件名（含路径或相对路径）
      xticks: 自定义 x 轴刻度列表（可选）
      xlim: 自定义 x 轴范围 (xmin, xmax)（可选）
    """
    plt.figure(figsize=(5, 4), dpi=300)
    plt.rcParams['pdf.fonttype']= 42
    style_cycle = cycle(_style_list)
    y_values = []  # 收集所有非None的y值用于计算范围

    # 逐条绘制
    for label, (x, y) in data.items():
        # 过滤掉y为None的点
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(x, y):
            if yi is not None:  # 只保留y不为None的点
                filtered_x.append(xi)
                filtered_y.append(yi)
                y_values.append(yi)  # 收集有效的y值
        
        ls, col, mk = next(style_cycle)
        plt.plot(
            filtered_x, filtered_y,  # 使用过滤后的数据
            label=label,
            linestyle=ls,
            color=col,
            marker=mk,
            linewidth=3.5,
            markersize=4
        )

    # 计算y轴范围：ymin向下取整，ymax向上取整
    if y_values:  # 确保有有效数据
        # y_min = np.floor(min(y_values))  # 向下取整
        # y_max = np.ceil(max(y_values))   # 向上取整
        y_min = 0
        y_max = 8
    else:  # 没有有效数据时使用默认范围
        y_min, y_max = 0, 1

    # X 轴刻度
    if xticks is None:
        # 收集所有非None值对应的x坐标
        all_x = []
        for xs, ys in data.values():
            for xi, yi in zip(xs, ys):
                if yi is not None:
                    all_x.append(xi)
        all_x = sorted(set(all_x))  # 去重并排序
        plt.xticks(all_x, fontsize=14)
    else:
        plt.xticks(xticks, fontsize=14)

    # Y 轴刻度：从y_min到y_max，分10段，隔行显示
    raw_step = (y_max - y_min) / 10
    step = 0.5 if raw_step <= 1 else np.ceil(raw_step * 2) / 2
    all_ticks = np.arange(y_min, y_max + step, step)
    visible = [t if i % 2 != len(all_ticks) % 2 else ''
               for i, t in enumerate(all_ticks)]
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
    plt.ylim(y_min, y_max)  # 使用计算出的范围
    if xlim:
        plt.xlim(*xlim)

    # 保存并关闭
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")

def get_avg_fct(expr):
    res = []
    resn = []
    for ana in analyser_iter(expr):
        try:
            avg,avg_intra,avg_inter = ana.get_avg_fct()
            res.append(avg_inter)
            resn.append(avg_intra)
        except:
            res.append(None)
            resn.append(None)
    return res,resn

def main():
    expr = '461,642-645'
    x_data = [1,1.5,2,2.5,3]

    inter_res, intra_res = get_avg_fct(expr)
    x_label = 'Epoch duration (ms)'

    # 绘制Average normalized FCT
    data_to_plot = {
        "Inter": (x_data, inter_res),
        "Intra": (x_data, intra_res)
    }

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="Average normalized FCT",
        filename=f"epoch_duration.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1])
    )



if __name__ == '__main__':
    main()