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
MARKER_SIZE = 6.5
GRID_ALPHA = 0.25
GRID_LINEWIDTH = 0.8
GRID_LINESTYLE = "--"

SCHEME_STYLES = {
    "DCQCN": {"color": "#F28E2B", "marker": "o"},
    "DCQCN-SR": {"color": "#4E79A7", "marker": "s"},
    "GEMINI": {"color": "#2A9D8F", "marker": "D"},
    "UNO": {"color": "#E15759", "marker": "^"},
    "GRC": {"color": "#8F63B8", "marker": "v"},
}

DEFAULT_EXPRS = OrderedDict(
    [
        ("DCQCN", "392-395"),
        ("DCQCN-SR", "414-417"),
        ("GEMINI", "477-480"),
        ("UNO", "437-440"),
        ("GRC", "336-339"),
    ]
)
# DEFAULT_EXPRS = OrderedDict(
#     [
#         ("DCQCN", "473-476"),
#         ("DCQCN-SR", "477-480"),
#         ("GEMINI", "328-331"),
#         ("UNO", "485-488"),
#         ("GRC", "336-339"),
#     ]
# )

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


def get_integer_ticks(y_values, target_tick_count=6):
    if not y_values:
        return 0, 1, np.array([0, 1], dtype=int)

    y_min = int(np.floor(min(y_values)))
    y_max = int(np.ceil(max(y_values)))
    if y_max <= y_min:
        y_max = y_min + 1

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
                markersize=MARKER_SIZE,
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


def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None):
    plt.figure(figsize=MAIN_FIGSIZE, dpi=300)
    y_values = []

    for label, spec in data.items():
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(spec["x"], spec["y"]):
            if yi is not None:
                filtered_x.append(xi)
                filtered_y.append(yi)
                y_values.append(yi)

        style = SCHEME_STYLES[spec["scheme"]]
        plt.plot(
            filtered_x,
            filtered_y,
            label=label,
            linestyle="-",
            color=style["color"],
            marker=style["marker"],
            linewidth=2.8,
            markersize=MARKER_SIZE,
            markerfacecolor="none",
            markeredgecolor=style["color"],
            markeredgewidth=1.6,
        )

    y_min, y_max, all_ticks = get_integer_ticks(y_values)

    if xticks is None:
        all_x = []
        for spec in data.values():
            for xi, yi in zip(spec["x"], spec["y"]):
                if yi is not None:
                    all_x.append(xi)
        tick_x = sorted(set(all_x))
        plt.xticks(tick_x, fontsize=TICK_FONTSIZE)
    else:
        tick_x = list(xticks)
        plt.xticks(tick_x, fontsize=TICK_FONTSIZE)

    plt.yticks(all_ticks, [str(int(t)) for t in all_ticks], fontsize=TICK_FONTSIZE)

    ax = plt.gca()
    plt.xlabel(xlabel, fontsize=LABEL_FONTSIZE)
    plt.ylabel(ylabel, fontsize=LABEL_FONTSIZE)
    ax.grid(axis="y", alpha=GRID_ALPHA, linewidth=GRID_LINEWIDTH, linestyle=GRID_LINESTYLE)
    for xpos in tick_x[1:-1]:
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


def get_buffer(expr):
    res = []
    for ana in analyser_iter(expr):
        try:
            _, _, peak_buffer = ana.get_wan_buffer_stats_50_150()
            res.append(peak_buffer)
        except Exception:
            res.append(None)
    return res


def get_flow_set_config(flow_set):
    if flow_set not in FLOW_SET_CONFIGS:
        supported = ", ".join(sorted(FLOW_SET_CONFIGS))
        raise ValueError(
            f"Unsupported flow_set '{flow_set}'. Supported flow_set values: {supported}."
        )
    return FLOW_SET_CONFIGS[flow_set]


def build_plot_data(x_data, values_by_scheme):
    data_to_plot = OrderedDict()
    for scheme, y_vals in values_by_scheme.items():
        data_to_plot[scheme] = {
            "x": x_data,
            "y": y_vals,
            "scheme": scheme,
        }
    return data_to_plot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--flow_set", default="w")
    args = parser.parse_args()

    config = get_flow_set_config(args.flow_set)
    file_name = config["file_name"]
    exprs = config["exprs"]

    x_data = [0, 60, 120, 180]
    x_label = "Dynamic traffic throughput (Gbps)"

    save_legend_figure(f"{file_name}-Max-Buffer-Legend.pdf")

    values_by_scheme = OrderedDict()
    for scheme, expr in exprs.items():
        values_by_scheme[scheme] = get_buffer(expr)

    plot_auto_lines(
        build_plot_data(x_data, values_by_scheme),
        xlabel=x_label,
        ylabel="Max Buf. Util. (MB)",
        filename=f"{file_name}-Max-Buffer-Util.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
    )


if __name__ == "__main__":
    main()
