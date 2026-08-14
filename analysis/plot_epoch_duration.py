from collections import OrderedDict
import math
from matplotlib.lines import Line2D

from deep_analyse import *
import os.path as op
import numpy as np
import matplotlib.pyplot as plt


plt.rcParams["pdf.fonttype"] = 42

MAIN_FIGSIZE = (5.6, 3.1)
TICK_FONTSIZE = 16
LABEL_FONTSIZE = 18.4
LEGEND_FONTSIZE = 13.6
MARKER_SIZE = 6.5
GRID_ALPHA = 0.25
GRID_LINEWIDTH = 0.8
GRID_LINESTYLE = "--"

SERIES_STYLES = {
    "Avg.": {"color": "#F28E2B", "marker": "o"},
    "P99": {"color": "#8F63B8", "marker": "v"},
}


def get_integer_ticks(y_values, target_tick_count=6, fixed_max=None):
    if not y_values:
        if fixed_max is None:
            return 0, 1, np.array([0, 1], dtype=int)
        return 0, fixed_max, np.array([0, fixed_max], dtype=int)

    y_min = int(np.floor(min(y_values)))
    y_max = int(fixed_max) if fixed_max is not None else int(np.ceil(max(y_values)))
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


def plot_auto_lines(data, xlabel, ylabel, filename, xticks=None, xlim=None):
    plt.figure(figsize=MAIN_FIGSIZE, dpi=300)
    y_values = []
    series = []

    for label, (x, y) in data.items():
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(x, y):
            if yi is not None:
                filtered_x.append(xi)
                filtered_y.append(yi)
                y_values.append(yi)

        series.append((label, filtered_x, filtered_y))

    y_min, y_max, all_ticks = get_integer_ticks(y_values, fixed_max=15)

    for label, filtered_x, filtered_y in series:
        style = SERIES_STYLES[label]
        plt.plot(
            filtered_x,
            filtered_y,
            linestyle="-",
            color=style["color"],
            linewidth=2.8,
            clip_on=True,
        )
        plt.plot(
            filtered_x,
            filtered_y,
            linestyle="None",
            color=style["color"],
            marker=style["marker"],
            markersize=MARKER_SIZE,
            markerfacecolor="none",
            markeredgecolor=style["color"],
            markeredgewidth=1.6,
            clip_on=True,
        )

    if xticks is None:
        tick_x = sorted({xi for xs, _ in data.values() for xi in xs})
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

    handles = []
    for label, style in SERIES_STYLES.items():
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
                label=label,
            )
        )
    ax.legend(
        handles=handles,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        loc="upper left",
        handlelength=2.4,
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


def get_avg_fct(expr):
    inter = []
    intra = []
    p99 = []
    for ana in analyser_iter(expr):
        try:
            avg, avg_intra, avg_inter = ana.get_avg_fct()
            inter.append(avg_inter)
            intra.append(avg_intra)
            p99.append(ana.get_p99_fct()[2])
        except Exception:
            inter.append(None)
            intra.append(None)
            p99.append(None)
    return inter, intra, p99


def main():
    expr = "364-368"
    x_data = [1, 2, 3, 4, 5]
    x_label = "Epoch duration (ms)"

    inter_res, intra_res, inter_p99 = get_avg_fct(expr)
    data_to_plot = OrderedDict(
        [
            ("Avg.", (x_data, inter_res)),
            ("P99", (x_data, inter_p99)),
        ]
    )

    plot_auto_lines(
        data_to_plot,
        xlabel=x_label,
        ylabel="Normalized FCT",
        filename="epoch_duration.pdf",
        xticks=x_data,
        xlim=(x_data[0], x_data[-1]),
    )


if __name__ == "__main__":
    main()
