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
    "GSCC": ('-.', gscc_c, 'd'),
    "inf-w/o-GSCC": (':', "c", '^'),
    "w/o-GSCC": ('-.', "orange", 'd'),
    "Gemini": ('-', 'tab:green', 's'),
    "UnoCC": ('--', 'tab:blue', 'o'),
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
    # 对于 4 个或更少子图，使用 1x4（一行四图）；否则使用 2x4
    if num_subplots <= 4:
        rows, cols = 1, 4
        fig_height = 3.6
        fig = plt.figure(figsize=(16, fig_height), dpi=300)
        gs = GridSpec(rows, cols, figure=fig, wspace=0.28, hspace=0.35)
    else:
        rows, cols = 2, 4
        # 固定两行四列布局；增大高度，避免标题/图例拥挤
        fig_height = 9.5
        fig = plt.figure(figsize=(16, fig_height), dpi=300)
        gs = GridSpec(rows, cols, figure=fig, wspace=0.3, hspace=0.55)

    # 收集所有子图中出现的算法（确保图例完整）
    all_algos = set()
    for cat_key, _, _ in flow_categories[:rows*cols]:
        all_algos.update(data.get(cat_key, {}).keys())
    all_algos = sorted(all_algos)

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

    for idx, (cat_key, cat_title, cat_xlabel) in enumerate(flow_categories[:rows*cols]):
        r = idx // cols
        c = idx % cols
        ax = fig.add_subplot(gs[r, c])
        cat_data = data.get(cat_key, {})

        # 绘制当前子图的所有折线（使用算法对应的固定样式）
        for algo, (x, y) in cat_data.items():
            filtered = [(xi, yi) for xi, yi in zip(x, y) if yi is not None]
            if not filtered:
                continue
            filtered_x, filtered_y = zip(*filtered)
            
            # 关键：使用算法绑定的固定样式
            base_ls, color, mk = ALGO_STYLES[algo]
            # 根据子图类型（inter/intra）覆盖线型：inter -> dashed, intra -> solid
            if 'inter' in cat_key:
                ls = '--'
            elif 'intra' in cat_key:
                ls = '-'
            else:
                ls = base_ls
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
        # 如果用户请求对数轴（logtag==1），使用对数（但当前默认不使用）。
        # 否则采用截断（clipping）策略：将 y 轴上限设为上分位数（95%），超出的点被截断显示为空白。
        if logtag == 1:
            all_ys = []
            for algo_data in cat_data.values():
                all_ys.extend([yi for yi in algo_data[1] if yi is not None and yi > 0])
            if all_ys:
                ax.set_yscale('log')
                min_y = min(all_ys)
                ax.set_ylim(bottom=min_y / 10)
        else:
            all_ys = []
            for algo_data in cat_data.values():
                all_ys.extend([yi for yi in algo_data[1] if yi is not None])
            if not all_ys:
                continue
            min_y = float(np.nanmin(all_ys))
            max_y = float(np.nanmax(all_ys))
            # 使用 90% 分位数作为上限（仍然截断）
            top = float(np.nanpercentile(all_ys, 90))
            # 底部预留改为相对于显示范围（top-min_y）留 2% 空白，避免极端值导致多余空白
            display_span = top - min_y
            if display_span > 0:
                bottom = min_y - 0.02 * display_span
            else:
                # 若所有值相同，底部比最小值小 2%
                bottom = min_y * 0.98
            # 避免底部小于 0（指标为正时没必要显示负值）
            if bottom < 0:
                bottom = 0.0
            # 如果所有值都相同或 top<=bottom，给一点余量
            if top <= bottom:
                top = bottom * 1.1 if bottom != 0 else 1.0
            # 确保上限至少比最小值大一点
            if top <= bottom:
                top = bottom + 1.0
            ax.set_ylim(bottom=bottom, top=top)
            # 标注被截断的点数量
            clipped_count = sum(1 for v in all_ys if v > top)
            # if clipped_count > 0:
                # ax.text(0.98, 0.92, f'Clipped: {clipped_count}', transform=ax.transAxes,
                #         ha='right', va='top', fontsize=8, color='red')

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    # 添加图例（包含所有子图的算法）
    if show_legend:
        fig.legend(
            legend_lines, legend_labels,
            loc='upper center',
            bbox_to_anchor=(0.5, 1.01),
            fontsize=10,
            ncol=len(legend_labels),
            columnspacing=2.0,
            handletextpad=0.5
        )

    plt.subplots_adjust(left=0.06, right=0.99, bottom=0.06, top=0.82, wspace=0.28, hspace=0.55)

    plt.savefig(filename, bbox_inches='tight', format='pdf')
    plt.close()
    print(f"Saved figure to {filename} (图例显示: {show_legend})")

def get_avg_fct(expr):
    inter = []
    intra = []
    for ana in analyser_iter(expr):
        try:
            # deep_analyse.Analyser.get_avg_fct() 返回 (overall, intra, inter)
            _, avg_intra, avg_inter = ana.get_avg_fct()
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
            # deep_analyse.Analyser.get_p99_fct() 返回 (overall_p99, intra_p99, inter_p99)
            _, p99_intra, p99_inter = ana.get_p99_fct()
            inter.append(p99_inter)
            intra.append(p99_intra)
        except:
            inter.append(None)
            intra.append(None)
    return inter,intra


def get_small_inter_fct(expr):
    """返回每个 experiment 的 small-flow (inter-DC) 平均 FCT 列表"""
    vals = []
    for ana in analyser_iter(expr):
        try:
            # get_small_flow_fct returns (overall_mean, inter_mean, inter_p99, intra_mean)
            tup = ana.get_small_flow_fct()
            vals.append(tup[1])
        except:
            vals.append(None)
    return vals


def get_large_inter_fct(expr):
    """返回每个 experiment 的 large-flow (inter-DC) 平均 FCT 列表"""
    vals = []
    for ana in analyser_iter(expr):
        try:
            # get_large_flow_fct returns (overall_mean, inter_mean, inter_p99, intra_mean)
            tup = ana.get_large_flow_fct()
            vals.append(tup[1])
        except:
            vals.append(None)
    return vals


def get_small_intra_fct(expr):
    """返回每个 experiment 的 small-flow (intra-DC) 平均 FCT 列表"""
    vals = []
    for ana in analyser_iter(expr):
        try:
            tup = ana.get_small_flow_fct()
            vals.append(tup[3])
        except:
            vals.append(None)
    return vals


def get_large_intra_fct(expr):
    """返回每个 experiment 的 large-flow (intra-DC) 平均 FCT 列表"""
    vals = []
    for ana in analyser_iter(expr):
        try:
            tup = ana.get_large_flow_fct()
            vals.append(tup[3])
        except:
            vals.append(None)
    return vals

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

    dcqcn_expr = '0,3,290'
    gscc_expr = '274,275,294,299'
    dcqcn_inf_expr = '63,71,291,296'
    # 可替换：为 Gemini / UnoCC 填入对应的 experiment id 列表（逗号或范围）
    gemini_expr = '68,76,292,297'
    unocc_expr = '69,77,293,298'

    # 算法 -> expr 映射
    algo_exprs = {
        'w/o-GSCC': dcqcn_expr,
        'GSCC': gscc_expr,
        'inf-w/o-GSCC': dcqcn_inf_expr,
        'Gemini': gemini_expr,
        'UnoCC': unocc_expr,
    }
    x_data= [0,60,120,180]

    # helper: safe calls and normalization to x_data length
    def _normalize(lst, length):
        if lst is None:
            return [None] * length
        if len(lst) >= length:
            return list(lst)[:length]
        return list(lst) + [None] * (length - len(lst))

    def _safe_avg(expr):
        if not expr:
            return [None]*len(x_data), [None]*len(x_data)
        a_inter, a_intra = get_avg_fct(expr)
        return _normalize(a_inter, len(x_data)), _normalize(a_intra, len(x_data))

    def _safe_p99(expr):
        if not expr:
            return [None]*len(x_data), [None]*len(x_data)
        p_inter, p_intra = get_p99_fct(expr)
        return _normalize(p_inter, len(x_data)), _normalize(p_intra, len(x_data))

    def _safe_small(expr):
        if not expr:
            return [None]*len(x_data), [None]*len(x_data)
        s_inter = get_small_inter_fct(expr)
        s_intra = get_small_intra_fct(expr)
        return _normalize(s_inter, len(x_data)), _normalize(s_intra, len(x_data))

    def _safe_large(expr):
        if not expr:
            return [None]*len(x_data), [None]*len(x_data)
        l_inter = get_large_inter_fct(expr)
        l_intra = get_large_intra_fct(expr)
        return _normalize(l_inter, len(x_data)), _normalize(l_intra, len(x_data))

    # 计算每个算法对应的序列（按 x_data 长度归一化）
    algo_metrics = {}
    for algo, expr_str in algo_exprs.items():
        ai, aj = _safe_avg(expr_str)
        pi, pj = _safe_p99(expr_str)
        # si, sj = _safe_small(expr_str)
        # li, lj = _safe_large(expr_str)
        algo_metrics[algo] = {
            'avg_inter': ai,
            'avg_intra': aj,
            'p99_inter': pi,
            'p99_intra': pj,
            # 'small_inter': si,
            # 'small_intra': sj,
            # 'large_inter': li,
            # 'large_intra': lj,
        }

    # 现在把 inter/intra 拆成 8 个图：avg/p99/small/large 各自的 inter 与 intra
    data = {
        'avg_inter': { algo: (x_data, algo_metrics[algo]['avg_inter']) for algo in algo_metrics },
        'avg_intra': { algo: (x_data, algo_metrics[algo]['avg_intra']) for algo in algo_metrics },
        'p99_inter': { algo: (x_data, algo_metrics[algo]['p99_inter']) for algo in algo_metrics },
        'p99_intra': { algo: (x_data, algo_metrics[algo]['p99_intra']) for algo in algo_metrics },
        # 'small_inter': { algo: (x_data, algo_metrics[algo]['small_inter']) for algo in algo_metrics },
        # 'small_intra': { algo: (x_data, algo_metrics[algo]['small_intra']) for algo in algo_metrics },
        # 'large_inter': { algo: (x_data, algo_metrics[algo]['large_inter']) for algo in algo_metrics },
        # 'large_intra': { algo: (x_data, algo_metrics[algo]['large_intra']) for algo in algo_metrics },
    }

    flow_cats = [
        ("avg_inter", "(a) Avg normalized FCT (inter)", "Average inter-DC Throughput (Gbps)"),
        ("avg_intra", "(b) Avg normalized FCT (intra)", "Average intra-DC Throughput (Gbps)"),
        ("p99_inter", "(c) P99 normalized FCT (inter)", "Average inter-DC Throughput (Gbps)"),
        ("p99_intra", "(d) P99 normalized FCT (intra)", "Average intra-DC Throughput (Gbps)"),
        # ("small_inter", "(e) Small flows normalized FCT (inter)", "Average inter-DC Throughput (Gbps)"),
        # ("small_intra", "(f) Small flows normalized FCT (intra)", "Average intra-DC Throughput (Gbps)"),
        # ("large_inter", "(g) Large flows normalized FCT (inter)", "Average inter-DC Throughput (Gbps)"),
        # ("large_intra", "(h) Large flows normalized FCT (intra)", "Average intra-DC Throughput (Gbps)"),
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