from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle

gscc_c = (130/255, 0, 180/255)
_style_list = [
    (':', "orange", 'o'),
    ('--', "orange", 's'),
    (':', "c", 'o'),
    ('--', "c", 's'),
    (':', gscc_c, '^'),
    ('--', gscc_c, 'd'),
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
        
        # 计算y最大值时排除None值
        if filtered_y:  # 确保过滤后的数据不为空
            current_max = max(filtered_y)
            y_max = max(y_max, current_max)

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

    # Y 轴刻度：0 到 y_max，分 10 段，隔行显示
    raw_step = (y_max or 1) / 10
    step = 0.5 if raw_step <= 1 else np.ceil(raw_step * 2) / 2
    all_ticks = np.arange(0, y_max + step, step)
    visible = [t if True or i % 2 != len(all_ticks) % 2 else ''
               for i, t in enumerate(all_ticks)]
    plt.yticks(all_ticks, visible, fontsize=14)

    # 轴标签、图例、网格、去除多余边框
    plt.xlabel(xlabel, fontsize=16)
    plt.ylabel(ylabel, fontsize=16)
    #plt.legend(frameon=False, fontsize=16, loc='upper left', bbox_to_anchor=(0,1.1))
    plt.grid(axis='y', alpha=0.3)
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 设置范围
    plt.ylim(0, all_ticks[-1])
    if xlim:
        plt.xlim(*xlim)

    # 保存并关闭
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")

def main():
    # 负责绘制
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--expr', type=str)
    parser.add_argument('-f', '--flow_type', type=str, default='s')

    args = parser.parse_args()
    flow_type = args.flow_type
    expr = args.expr
    figure = 4

    dcqcn_inter = [[] for _ in range(0, figure)]
    dcqcn_intra = [[] for _ in range(0, figure)]
    dcqcn_ecn_inter = [[] for _ in range(0, figure)]
    dcqcn_ecn_intra = [[] for _ in range(0, figure)]
    gscc_intra = [[] for _ in range(0, figure)]
    gscc_inter = [[] for _ in range(0, figure)]

    wan_cc_mode = 0
    for ana in analyser_iter(expr):
        try:
            avg_vals, avg_intra, avg_inter = ana.get_avg_fct()
            p99_vals, p99_intra, p99_inter = ana.get_p99_fct()

            lavg, l_inter_avg, l_inter_p99, l_intra_avg = ana.get_large_flow_fct()
            savg, s_inter_avg, s_inter_p99, s_intra_avg = ana.get_small_flow_fct()

            if wan_cc_mode == 0:
                dcqcn_inter[0].append(avg_inter)
                dcqcn_inter[1].append(p99_inter)
                dcqcn_inter[2].append(s_inter_avg)
                dcqcn_inter[3].append(l_inter_avg)

                dcqcn_intra[0].append(avg_intra)
                dcqcn_intra[1].append(p99_intra)

            elif wan_cc_mode == 2:
                dcqcn_ecn_inter[0].append(avg_inter)
                dcqcn_ecn_inter[1].append(p99_inter)
                dcqcn_ecn_inter[2].append(s_inter_avg)
                dcqcn_ecn_inter[3].append(l_inter_avg)

                dcqcn_ecn_intra[0].append(avg_intra)
                dcqcn_ecn_intra[1].append(p99_intra)
            else:
                gscc_intra[0].append(avg_intra)
                gscc_intra[1].append(p99_intra)

                gscc_inter[0].append(avg_inter)
                gscc_inter[1].append(p99_inter)
                gscc_inter[2].append(s_inter_avg)
                gscc_inter[3].append(l_inter_avg)

        except Exception as e:
            print(f'Error processing {ana.id}: {e}')
            if wan_cc_mode == 0:
                dcqcn_inter[0].append(None)
                dcqcn_inter[1].append(None)
                dcqcn_inter[2].append(None)
                dcqcn_inter[3].append(None)

                dcqcn_intra[0].append(None)
                dcqcn_intra[1].append(None)

            elif wan_cc_mode == 2:
                dcqcn_ecn_inter[0].append(None)
                dcqcn_ecn_inter[1].append(None)
                dcqcn_ecn_inter[2].append(None)
                dcqcn_ecn_inter[3].append(None)

                dcqcn_ecn_intra[0].append(None)
                dcqcn_ecn_intra[1].append(None)
            else:
                gscc_intra[0].append(None)
                gscc_intra[1].append(None)

                gscc_inter[0].append(None)
                gscc_inter[1].append(None)
                gscc_inter[2].append(None)
                gscc_inter[3].append(None)
        
        wan_cc_mode = (wan_cc_mode + 1) % 3

    static_flow = [30, 40, 50, 60, 70]
    dynamic_flow = [0, 50, 100, 150, 200]

    if flow_type == 'd':
        x_data = dynamic_flow
        x_label = 'Dynamic traffic throughput (Gbps)'
    else:
        x_data = static_flow
        x_label = 'Average inter-DC Throughput (Gbps)'

    plot_cnt = 0
    # 绘制Average normalized FCT
    data_to_plot = {
        'DCQCN_inter': (x_data, process_y_data(dcqcn_inter[plot_cnt])),
        'DCQCN_intra': (x_data, process_y_data(dcqcn_intra[plot_cnt])),
        'DCQCN_inter with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_inter[plot_cnt])),
        'DCQCN_intra with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_intra[plot_cnt])),
        'GSCC_inter': (x_data, process_y_data(gscc_inter[plot_cnt])),
        'GSCC_intra': (x_data, process_y_data(gscc_intra[plot_cnt]))
    }
    print((dcqcn_inter[plot_cnt][2] - gscc_inter[plot_cnt][2]) / dcqcn_inter[plot_cnt][2])
    print((dcqcn_intra[plot_cnt][2] - gscc_intra[plot_cnt][2]) / dcqcn_intra[plot_cnt][2])

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="Average normalized FCT",
        filename="Average-normalized-FCT.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1])
    )

    # 绘制 P99 normalized FCT
    plot_cnt += 1
    data_to_plot = {
        'DCQCN_inter': (x_data, process_y_data(dcqcn_inter[plot_cnt])),
        'DCQCN_intra': (x_data, process_y_data(dcqcn_intra[plot_cnt])),
        'DCQCN_inter with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_inter[plot_cnt])),
        'DCQCN_intra with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_intra[plot_cnt])),
        'GSCC_inter': (x_data, process_y_data(gscc_inter[plot_cnt])),
        'GSCC_intra': (x_data, process_y_data(gscc_intra[plot_cnt]))
    }

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="P99 normalized FCT",
        filename="P99-normalized-FCT.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1])
    )

    # 绘制Small flows' normalized FCT
    plot_cnt += 1
    data_to_plot = {
        'DCQCN_inter': (x_data, process_y_data(dcqcn_inter[plot_cnt])),
        'DCQCN_intra': (x_data, process_y_data(dcqcn_intra[plot_cnt])),
        'DCQCN_inter with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_inter[plot_cnt])),
        'DCQCN_intra with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_intra[plot_cnt])),
        'GSCC_inter': (x_data, process_y_data(gscc_inter[plot_cnt])),
        'GSCC_intra': (x_data, process_y_data(gscc_intra[plot_cnt]))
    }

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="Small flows' normalized FCT",
        filename="Small-flows-normalized-FCT.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1])
    )

    # 绘制Large flows' normalized FCT
    plot_cnt += 1
    data_to_plot = {
        'DCQCN_inter': (x_data, process_y_data(dcqcn_inter[plot_cnt])),
        'DCQCN_intra': (x_data, process_y_data(dcqcn_intra[plot_cnt])),
        'DCQCN_inter with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_inter[plot_cnt])),
        'DCQCN_intra with wide-area ECN': (x_data, process_y_data(dcqcn_ecn_intra[plot_cnt])),
        'GSCC_inter': (x_data, process_y_data(gscc_inter[plot_cnt])),
        'GSCC_intra': (x_data, process_y_data(gscc_intra[plot_cnt]))
    }

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="Large flows' normalized FCT",
        filename="Large-flows-normalized-FCT.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1])
    )

    quit()

if __name__ == "__main__":
    main()