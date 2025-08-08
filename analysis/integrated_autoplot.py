from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle
from matplotlib.gridspec import GridSpec
gscc_c = (130/255,0,180/255)


# 关键：为每个算法绑定固定样式（而非按顺序循环）
ALGO_STYLES = {
    "w/o-GSCC-inter": ('-.', "orange", 'd'),
    "w/o-GSCC-intra": (':', "orange", '^'),
    "inf-w/o-GSCC-inter": ('-.', "c", 'd'),
    "inf-w/o-GSCC-intra": (':', "c", '^'),
    "GSCC-inter": ('-.', gscc_c, 'd'),
    "GSCC-intra": (':', gscc_c, '^')
}

def plot_auto_lines(data, ylabel, filename,  
                    xticks=None, xlim=None, 
                    logtag=0, 
                    flow_categories=None,
                    show_legend=True):
    """
    支持不同子图折线数量不一致，确保同算法样式统一、图例完整
    """
    num_subplots = len(flow_categories)
    rows, cols = 2, 4
    
    if show_legend:
        height_ratios = [0.1, 0.9]
        fig_height = 4
    else:
        height_ratios = [0.0, 0.9]
        fig_height = 3.6

    fig = plt.figure(figsize=(16, fig_height), dpi=300)
    gs = GridSpec(rows, cols, figure=fig,
                 height_ratios=height_ratios,
                 wspace=0.3)

    # 收集所有子图中出现的算法（确保图例完整）
    all_algos = set()
    for cat_key in [k for k, _, _ in flow_categories[:4]]:
        all_algos.update(data.get(cat_key, {}).keys())
    all_algos = sorted(all_algos)  # 排序保证图例顺序固定

    # 生成图例线条和标签（按固定样式）
    legend_lines = []
    legend_labels = []
    for algo in all_algos:
        ls, color, mk = ALGO_STYLES[algo]
        # 创建一个隐藏的线条用于图例（不影响实际绘图）
        line = plt.Line2D([], [], linestyle=ls, color=color, marker=mk,
                         label=algo, linewidth=2.5, markersize=4)
        legend_lines.append(line)
        legend_labels.append(algo)

    for idx, (cat_key, cat_title, cat_xlabel) in enumerate(flow_categories[:4]):
        ax = fig.add_subplot(gs[1, idx])
        cat_data = data.get(cat_key, {})

        # 绘制当前子图的所有折线（使用算法对应的固定样式）
        for algo, (x, y) in cat_data.items():
            filtered = [(xi, yi) for xi, yi in zip(x, y) if yi is not None]
            if not filtered:
                continue
            filtered_x, filtered_y = zip(*filtered)
            
            # 关键：使用算法绑定的固定样式
            ls, color, mk = ALGO_STYLES[algo]
            ax.plot(
                filtered_x, filtered_y,
                linestyle=ls,
                color=color,
                marker=mk,
                linewidth=2.5,
                markersize=4,
                label=algo
            )

        # 子图设置
        ax.set_title(cat_title, fontsize=12)
        ax.set_xlabel(cat_xlabel, fontsize=10)
        if idx == 0:
            ax.set_ylabel(ylabel, fontsize=10)

        if xticks is not None:
            ax.set_xticks(xticks)
        if xlim is not None:
            ax.set_xlim(*xlim)

        # y轴缩放处理
        if logtag == 1:
            ax.set_yscale('log')
            all_ys = []
            for algo_data in cat_data.values():
                all_ys.extend([yi for yi in algo_data[1] if yi is not None and yi > 0])
            if all_ys:
                min_y = min(all_ys)
                ax.set_ylim(bottom=min_y / 10)
        else:
            y_mins, y_maxs = [], []
            for algo_data in cat_data.values():
                filtered_ys = [yi for yi in algo_data[1] if yi is not None]
                if filtered_ys:
                    y_mins.append(min(filtered_ys))
                    y_maxs.append(max(filtered_ys))
            if y_mins and y_maxs:
                ax.set_ylim(bottom=min(y_mins), top=max(y_maxs) * 1.1)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    # 添加图例（包含所有子图的算法）
    if show_legend:
        fig.legend(
            legend_lines, legend_labels,
            loc='upper center',
            bbox_to_anchor=(0.5, 0.98),
            fontsize=10,
            ncol=len(legend_labels),
            columnspacing=2.0,
            handletextpad=0.5
        )

    plt.tight_layout()
    plt.subplots_adjust(top=0.85 if show_legend else 0.95)

    plt.savefig(filename, bbox_inches='tight', format='pdf')
    plt.close()
    print(f"Saved figure to {filename} (图例显示: {show_legend})")

def get_avg_fct(expr):
    inter = []
    intra = []
    for ana in analyser_iter(expr):
        try:
            _,avg_inter,avg_intra = ana.get_avg_fct()
            inter.append(avg_inter)
            intra.append(avg_intra)
        except:
            inter.append(None)
            intra.append(None)
    return inter,intra

def get_p99_fct(expr):
    inter = []
    intra = []
    for ana in analyser_iter(expr):
        try:
            _,avg_inter,avg_intra = ana.get_p99_fct()
            inter.append(avg_inter)
            intra.append(avg_intra)
        except:
            inter.append(None)
            intra.append(None)
    return inter,intra

def main():
    # 负责绘制
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--expr', type=str)
    parser.add_argument('-f', '--flow_type', type=str, default='s')
    parser.add_argument('-l', '--legend', type=int, default=1)


    args = parser.parse_args()
    flow_type = args.flow_type
    expr = args.expr
    show_legend = args.legend
    figure = 2

    dcqcn_expr = '448,451,454,457,460'
    gscc_expr = '449,452,455,458,461'
    dcqcn_inf_expr = '562-566'

    dcqcn_inter, dcqcn_intra = get_avg_fct(dcqcn_expr)
    gscc_inter, gscc_intra = get_avg_fct(gscc_expr)
    get_avg_fct(dcqcn_inf_expr)

    x_data= [0, 50, 100, 150, 200]


    data = {
        'f1':{
            "w/o-GSCC-inter": (x_data, []),
            "w/o-GSCC-intra": (x_data, []),
            "inf-w/o-GSCC-inter": (x_data, []),
            "inf-w/o-GSCC-intra": (x_data, []),
            "GSCC-inter": (x_data, []),
            "GSCC-intra": (x_data, [])
        },
        'f2':{
            "w/o-GSCC-inter": (x_data, []),
            "w/o-GSCC-intra": (x_data, []),
            "inf-w/o-GSCC-inter": (x_data, []),
            "inf-w/o-GSCC-intra": (x_data, []),
            "GSCC-inter": (x_data, []),
            "GSCC-intra": (x_data, [])
        },
        'f3':{
            "w/o-GSCC-inter": (x_data, []),
            "w/o-GSCC-intra": (x_data, []),
            "inf-w/o-GSCC-inter": (x_data, []),
            "inf-w/o-GSCC-intra": (x_data, []),
            "GSCC-inter": (x_data, []),
            "GSCC-intra": (x_data, [])
        },
        'f4':{
            "w/o-GSCC-inter": (x_data, []),
            "w/o-GSCC-intra": (x_data, []),
            "inf-w/o-GSCC-inter": (x_data, []),
            "inf-w/o-GSCC-intra": (x_data, []),
            "GSCC-inter": (x_data, []),
            "GSCC-intra": (x_data, [])
        },

    }

    flow_cats = [
        ("f1", "(a) Average normalized FCT", "Average inter-DC Throughput (Gbps)"),
        ("f2", "(b) P99 normalized FCT", "Average inter-DC Throughput (Gbps)"),
        ("f3", "(c) Small flows' normalized FCT", "Average inter-DC Throughput (Gbps)"),
        ("f4", "(d) Large flows' normalized FCT", "Average inter-DC Throughput (Gbps)")
    ]
    
    plot_auto_lines(
        data, ylabel="Normalized FCT",
        filename=f"{expr}-{flow_type}-{show_legend}.pdf",
        xticks=x_data, logtag=0,
        flow_categories=flow_cats,
        show_legend=show_legend
    )


if __name__ == "__main__":
    main()