from collections import OrderedDict
import math
from matplotlib.lines import Line2D

from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt


plt.rcParams["pdf.fonttype"] = 42

MAIN_FIGSIZE = (5.6, 3.1)
LEGEND_FIGSIZE = (8.8, 1.5)
TICK_FONTSIZE = 16
LABEL_FONTSIZE = 18.4
LEGEND_FONTSIZE = 13.6
AVG_Y_MAX = 12
P99_Y_MAX = 120
GRID_ALPHA = 0.25
GRID_LINEWIDTH = 0.8
GRID_LINESTYLE = "--"
VERTICAL_GUIDES = (60, 120)
DCQCN_SR_FINISH_TIME_CUTOFF_S = 3.0

LINE_STYLES = {
    "Inter": "-",
    "Intra": "-",
}

SCHEME_STYLES = {
    "DCQCN": {"color": "#F28E2B", "marker": "o"},
    "DCQCN-SR": {"color": "#4E79A7", "marker": "s"},
    "GEMINI": {"color": "#2A9D8F", "marker": "D"},
    "UnoCC": {"color": "#E15759", "marker": "^"},
    "GRC": {"color": "#8F63B8", "marker": "v"},
}

DEFAULT_EXPRS = OrderedDict(
    [
        ("DCQCN", "392-395"),
        ("DCQCN-SR", "414-417"),
        ("GEMINI", "477-480"),
        ("UnoCC", "437-440"),
        ("GRC", "336-339"),
    ]
)

FLOW_SET_CONFIGS = {
    "w": {
        "file_name": "websearch",
        "exprs": DEFAULT_EXPRS,
    },
    "a": {
        "file_name": "alistorage",
        "exprs": DEFAULT_EXPRS,
    },
}


def get_plot_style(scheme, traffic_class):
    scheme_style = SCHEME_STYLES[scheme]
    return {
        "linestyle": LINE_STYLES[traffic_class],
        "color": scheme_style["color"],
        "marker": scheme_style["marker"],
    }


def get_integer_ticks(y_values, target_tick_count=6, fixed_max=None):
    if not y_values:
        if fixed_max is None:
            return 0, 1, np.array([0, 1], dtype=int)
        return 0, fixed_max, np.array([0, fixed_max], dtype=int)

    if fixed_max is None:
        y_min = int(np.floor(min(y_values)))
        y_max = int(np.ceil(max(y_values)))
    else:
        y_min = int(np.floor(min(min(v, fixed_max) for v in y_values)))
        y_max = int(fixed_max)
    if y_max <= y_min:
        y_min = max(0, y_max - 1)

    span = y_max - y_min
    approx_step = max(1, int(np.ceil(span / max(target_tick_count - 1, 1))))
    magnitude = 10 ** int(math.floor(math.log10(approx_step)))

    for factor in (1, 2, 3, 4, 5, 6, 8, 10):
        step = factor * magnitude
        if step >= approx_step:
            break

    tick_min = int(math.floor(y_min / step) * step)
    tick_max = int(math.ceil(y_max / step) * step)
    ticks = np.arange(tick_min, tick_max + step, step, dtype=int)
    return tick_min, tick_max, ticks


def save_legend_figure(filename):
    handles = []
    for scheme, style in SCHEME_STYLES.items():
        handles.append(
            Line2D(
                [0],
                [0],
                color=style["color"],
                linestyle="-",
                linewidth=2.8,
                marker=style["marker"],
                markersize=6.5,
                markerfacecolor="none",
                markeredgecolor=style["color"],
                markeredgewidth=1.6,
                label=scheme,
            )
        )

    fig, ax = plt.subplots(figsize=LEGEND_FIGSIZE, dpi=300)
    ax.axis("off")
    ax.legend(
        handles=handles,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        loc="center",
        ncol=len(handles),
        handlelength=2.4,
        columnspacing=1.4,
    )

    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    fig.savefig(filepath, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print(f"Saved legend to {filepath}")


def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None, y_axis=None, logtag=0):
    """
    针对任意多条曲线画图，支持处理 None 值。

    参数:
      data: dict[label, (x_list, y_list)]
      xlabel, ylabel: 坐标轴标签
      filename: 保存文件名（含路径或相对路径）
      xticks: 自定义 x 轴刻度列表（可选）
      xlim: 自定义 x 轴范围 (xmin, xmax)（可选）
    """
    plt.figure(figsize=MAIN_FIGSIZE, dpi=300)
    y_values = []
    series = []

    for label, spec in data.items():
        x = spec["x"]
        y = spec["y"]
        scheme = spec["scheme"]
        traffic_class = spec["traffic_class"]
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(x, y):
            if yi is not None:
                filtered_x.append(xi)
                filtered_y.append(yi)
                y_values.append(yi)

        style = get_plot_style(scheme, traffic_class)
        series.append((label, style, filtered_x, filtered_y))

    if y_axis is None:
        y_min, y_max, all_ticks = get_integer_ticks(y_values)
    else:
        y_min, y_max, all_ticks = y_axis

    for label, style, filtered_x, filtered_y in series:
        plt.plot(
            filtered_x,
            filtered_y,
            label=label,
            linestyle=style["linestyle"],
            color=style["color"],
            linewidth=2.8,
            clip_on=True,
        )

        marker_x = []
        marker_y = []
        for xi, yi in zip(filtered_x, filtered_y):
            if y_min <= yi <= y_max:
                marker_x.append(xi)
                marker_y.append(yi)

        plt.plot(
            marker_x,
            marker_y,
            linestyle="None",
            color=style["color"],
            marker=style["marker"],
            markersize=6.5,
            markerfacecolor="none",
            markeredgecolor=style["color"],
            markeredgewidth=1.6,
            clip_on=True,
        )

    if xticks is None:
        all_x = []
        for spec in data.values():
            for xi, yi in zip(spec["x"], spec["y"]):
                if yi is not None:
                    all_x.append(xi)
        all_x = sorted(set(all_x))
        plt.xticks(all_x, fontsize=TICK_FONTSIZE)
    else:
        plt.xticks(xticks, fontsize=TICK_FONTSIZE)

    plt.yticks(all_ticks, [str(int(t)) for t in all_ticks], fontsize=TICK_FONTSIZE)

    ax = plt.gca()
    plt.xlabel(xlabel, fontsize=LABEL_FONTSIZE)
    plt.ylabel(ylabel, fontsize=LABEL_FONTSIZE)
    ax.grid(axis="y", alpha=GRID_ALPHA, linewidth=GRID_LINEWIDTH, linestyle=GRID_LINESTYLE)
    for xpos in VERTICAL_GUIDES:
        ax.axvline(
            xpos,
            color="#b0b0b0",
            alpha=GRID_ALPHA,
            linewidth=GRID_LINEWIDTH,
            linestyle=GRID_LINESTYLE,
            zorder=0,
        )

    for spine in ("left", "bottom", "top", "right"):
        ax.spines[spine].set_visible(True)
        ax.spines[spine].set_linewidth(1.0)
        ax.spines[spine].set_linestyle("-")
        ax.spines[spine].set_color("#222222")

    ax.tick_params(axis="both", which="both", width=1.0, color="#222222")

    plt.ylim(y_min, y_max)
    if xlim:
        plt.xlim(*xlim)

    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches="tight")
    plt.close()
    print(f"Saved figure to {filepath}")


def get_avg_fct(expr, finish_time_cutoff_s=None):
    inter = []
    intra = []
    all_vals = []
    for ana in analyser_iter(expr):
        try:
            if finish_time_cutoff_s is None:
                avg, avg_intra, avg_inter = ana.get_avg_fct()
            else:
                (avg, avg_intra, avg_inter), _ = ana.get_fct_until_finish_time(
                    finish_time_cutoff_s
                )
            inter.append(avg_inter)
            intra.append(avg_intra)
            all_vals.append(avg)
        except Exception:
            inter.append(None)
            intra.append(None)
            all_vals.append(None)
    return inter, intra, all_vals


def get_p99_fct(expr, finish_time_cutoff_s=None):
    inter = []
    intra = []
    for ana in analyser_iter(expr):
        try:
            if finish_time_cutoff_s is None:
                _, p99_intra, p99_inter = ana.get_p99_fct()
            else:
                _, (_, p99_intra, p99_inter) = ana.get_fct_until_finish_time(
                    finish_time_cutoff_s
                )
            inter.append(p99_inter)
            intra.append(p99_intra)
        except Exception:
            inter.append(None)
            intra.append(None)
    return inter, intra


def get_flow_set_config(flow_set):
    if flow_set not in FLOW_SET_CONFIGS:
        supported = ", ".join(sorted(FLOW_SET_CONFIGS))
        raise ValueError(
            f"Unsupported flow_set '{flow_set}'. Supported flow_set values: {supported}."
        )
    return FLOW_SET_CONFIGS[flow_set]


def build_plot_data(x_data, metric_by_scheme, traffic_class):
    data_to_plot = OrderedDict()
    for scheme, (inter_vals, intra_vals) in metric_by_scheme.items():
        y_vals = inter_vals if traffic_class == "Inter" else intra_vals
        data_to_plot[scheme] = {
            "x": x_data,
            "y": y_vals,
            "scheme": scheme,
            "traffic_class": traffic_class,
        }
    return data_to_plot


def get_shared_y_axis(metric_by_scheme, fixed_max=None):
    y_values = []
    for inter_vals, intra_vals in metric_by_scheme.values():
        y_values.extend(v for v in inter_vals if v is not None)
        y_values.extend(v for v in intra_vals if v is not None)
    return get_integer_ticks(y_values, fixed_max=fixed_max)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--flow_set", default="w")
    args = parser.parse_args()

    config = get_flow_set_config(args.flow_set)
    file_name = config["file_name"]
    exprs = config["exprs"]

    x_data = [0, 60, 120, 180]
    x_label = "Dynamic traffic throughput (Gbps)"

    save_legend_figure(f"{file_name}-Legend.pdf")

    avg_metric_by_scheme = OrderedDict()
    for scheme, expr in exprs.items():
        finish_time_cutoff_s = (
            DCQCN_SR_FINISH_TIME_CUTOFF_S if scheme == "DCQCN-SR" else None
        )
        inter_vals, intra_vals, _ = get_avg_fct(expr, finish_time_cutoff_s)
        avg_metric_by_scheme[scheme] = (inter_vals, intra_vals)

    avg_y_axis = get_shared_y_axis(avg_metric_by_scheme, fixed_max=AVG_Y_MAX)

    plot_auto_lines(
        build_plot_data(x_data, avg_metric_by_scheme, "Inter"),
        xlabel=x_label,
        ylabel="Avg. Normalized FCT",
        filename=f"{file_name}-Average-normalized-FCT-Inter.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
        y_axis=avg_y_axis,
    )

    plot_auto_lines(
        build_plot_data(x_data, avg_metric_by_scheme, "Intra"),
        xlabel=x_label,
        ylabel="Avg. Normalized FCT",
        filename=f"{file_name}-Average-normalized-FCT-Intra.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
        y_axis=avg_y_axis,
    )

    p99_metric_by_scheme = OrderedDict()
    for scheme, expr in exprs.items():
        finish_time_cutoff_s = (
            DCQCN_SR_FINISH_TIME_CUTOFF_S if scheme == "DCQCN-SR" else None
        )
        inter_vals, intra_vals = get_p99_fct(expr, finish_time_cutoff_s)
        p99_metric_by_scheme[scheme] = (inter_vals, intra_vals)

    p99_y_axis = get_shared_y_axis(p99_metric_by_scheme, fixed_max=P99_Y_MAX)

    plot_auto_lines(
        build_plot_data(x_data, p99_metric_by_scheme, "Inter"),
        xlabel=x_label,
        ylabel="P99 Normalized FCT",
        filename=f"{file_name}-P99-normalized-FCT-Inter.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
        y_axis=p99_y_axis,
    )

    plot_auto_lines(
        build_plot_data(x_data, p99_metric_by_scheme, "Intra"),
        xlabel=x_label,
        ylabel="P99 Normalized FCT",
        filename=f"{file_name}-P99-normalized-FCT-Intra.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
        y_axis=p99_y_axis,
    )


if __name__ == "__main__":
    main()
