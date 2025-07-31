from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle

gscc_c = (130/255, 0, 180/255)
_style_list = [
    ('--', 'r', 'o'),
    ('--', 'g', 'o'),
    ('--', 'c', 'o'),
    ('--', 'm', 'o')
]

def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None, logtag=0):
    """
    针对任意多条曲线，按 _style_list 轮换样式画图，支持处理None值。
    y轴刻度为整数，范围为数据最小y值-1向下取整到最大y值+1向上取整

    参数:
      data: dict[label, (x_list, y_list)]
      xlabel, ylabel: 坐标轴标签
      filename: 保存文件名（含路径或相对路径）
      xticks: 自定义 x 轴刻度列表（可选）
      xlim: 自定义 x 轴范围 (xmin, xmax)（可选）
    """
    import numpy as np
    import os.path as op
    from itertools import cycle
    import matplotlib.pyplot as plt  # 假设已定义_style_list
    
    plt.figure(figsize=(5, 4), dpi=300)
    style_cycle = cycle(_style_list)
    y_min = float('inf')  # 初始化最小值为无穷大
    y_max = -float('inf')  # 初始化最大值为负无穷

    # 逐条绘制并计算y的最值
    for label, (x, y) in data.items():
        # 过滤掉y为None的点
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(x, y):
            if yi is not None:  # 只保留y不为None的点
                filtered_x.append(xi)
                filtered_y.append(yi)
        
        ls, col, mk = next(style_cycle)
        plt.plot(
            filtered_x, filtered_y,  # 使用过滤后的数据
            label=label,
            linestyle=ls,
            color=col,
            marker=mk,
            linewidth=2.5,
            markersize=4
        )
        
        # 计算y的最大最小值（排除None值）
        if filtered_y:  # 确保过滤后的数据不为空
            current_min = min(filtered_y)
            current_max = max(filtered_y)
            if current_min < y_min:
                y_min = current_min
            if current_max > y_max:
                y_max = current_max

    # 处理没有有效数据的情况
    if y_min == float('inf') or y_max == -float('inf'):
        y_min, y_max = 0, 1  # 设置默认范围
    
    # 计算y轴范围：最小值-1向下取整到最大值+1向上取整
    y_lim_min = np.floor(y_min - 1)  # 向下取整
    y_lim_max = np.ceil(y_max + 1)   # 向上取整

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

    # 计算Y轴刻度（确保为整数）
    range_total = y_lim_max - y_lim_min
    # 根据范围大小确定合适的整数步长
    if range_total <= 5:
        step = 1
    elif range_total <= 20:
        step = 2 if range_total % 2 == 0 else 1
    else:
        # 对于较大范围，使用5或10的倍数作为步长
        step = 5 if range_total <= 50 else 10
    
    # 生成整数刻度列表，确保覆盖整个范围
    all_ticks = np.arange(y_lim_min, y_lim_max + step, step, dtype=int)
    # 处理刻度显示，隔行显示避免拥挤（只显示整数）
    visible = [int(t) if i % 2 == 0 else '' for i, t in enumerate(all_ticks)]
    plt.yticks(all_ticks, visible, fontsize=14)

    # 轴标签、图例、网格、去除多余边框
    plt.xlabel(xlabel, fontsize=16)
    plt.ylabel(ylabel, fontsize=16)
    plt.legend(frameon=False, fontsize=16, loc='upper left', bbox_to_anchor=(0,1.1))
    plt.grid(axis='y', alpha=0.3)
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 设置y轴范围
    plt.ylim(y_lim_min, y_lim_max)
    # 设置x轴范围
    if xlim:
        plt.xlim(*xlim)

    # 保存并关闭
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")

def get_avg_inter(expr):
    result = []
    for ana in analyser_iter(expr):
        try:
            avg, avg_intra, avg_inter = ana.get_avg_fct()
            result.append(avg_inter)
        except:
            result.append(None)
    return result


def main():
    expr_str = '351,354,357,360,410'
    result = get_avg_inter(expr_str)

    no_rtt_diff_expr = '396,399,402,405,411'
    new_result = get_avg_inter(no_rtt_diff_expr)

    period_expr = '481-485'
    period_result = get_avg_inter(period_expr)

    hashing_expr = '527-531'
    hashing_result = get_avg_inter(hashing_expr)

    x_data = [0,50,100,150,200]
    data_to_plot = {
        'GSCC-inter': (x_data, result),
        'GSCC-inter-no-rtt-diff': (x_data, new_result),
        'GSCC-inter-no-periodic-update': (x_data, period_result),
        'GSCC-inter-no-2level-hashing': (x_data, hashing_result)
    }
    plot_auto_lines(
        data_to_plot,
        xlabel="Dynamic traffic throughput (Gbps)",
        ylabel="Average-normalized-FCT",
        filename="ablation.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1])
    )
    return

if __name__ == "__main__":
    main()