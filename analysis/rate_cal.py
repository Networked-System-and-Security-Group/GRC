from collections import OrderedDict
import argparse
import math
from matplotlib.lines import Line2D

from deep_analyse import analyser_iter
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

RATE_GBPS = [50, 75, 100]
DEFAULT_EXPR = "493,494,495"
GRC_EXPR = "339"
DEFAULT_AVG_OUTPUT = "rate_cal_avg.pdf"
DEFAULT_P99_OUTPUT = "rate_cal_p99.pdf"
Y_FIXED_MAX = 15

SERIES_STYLES = {
    "Avg.": {"color": "#F28E2B", "marker": "o"},
    "P99": {"color": "#8F63B8", "marker": "v"},
    "GRC": {"color": "#4E79A7", "marker": None},
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


def plot_auto_lines(
    data,
    xlabel,
    ylabel,
    filename,
    xticks=None,
    xlim=None,
    hlines=None,
    fixed_y_max=Y_FIXED_MAX,
    y_top_padding=0.0,
):
    plt.figure(figsize=MAIN_FIGSIZE, dpi=300)
    y_values = []
    series = []
    hlines = hlines or OrderedDict()

    for label, (x, y) in data.items():
        filtered_x = []
        filtered_y = []
        for xi, yi in zip(x, y):
            if yi is not None:
                filtered_x.append(xi)
                filtered_y.append(yi)
                y_values.append(yi)

        series.append((label, filtered_x, filtered_y))

    for value in hlines.values():
        if value is not None:
            y_values.append(value)

    if y_values and fixed_y_max is None and y_top_padding > 0:
        data_min = min(y_values)
        data_max = max(y_values)
        span = max(data_max - data_min, data_max, 1.0)
        y_values.append(data_max + span * y_top_padding)

    y_min, y_max, all_ticks = get_integer_ticks(y_values, fixed_max=fixed_y_max)

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

    for label, value in hlines.items():
        if value is None:
            continue
        style = SERIES_STYLES[label]
        plt.axhline(
            value,
            color=style["color"],
            linestyle="--",
            linewidth=2.2,
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
    visible_labels = list(data.keys()) + list(hlines.keys())
    for label in visible_labels:
        style = SERIES_STYLES[label]
        marker = style["marker"]
        linestyle = "--" if label in hlines else "-"
        handles.append(
            Line2D(
                [0],
                [0],
                color=style["color"],
                linestyle=linestyle,
                linewidth=2.2 if label in hlines else 2.8,
                marker=marker,
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


def get_inter_fct(expr):
    inter_avg = []
    inter_p99 = []
    for ana in analyser_iter(expr):
        try:
            inter_avg.append(ana.get_avg_fct()[2])
            inter_p99.append(ana.get_p99_fct()[2])
        except Exception as exc:
            print(f"Skip run {getattr(ana, 'id', '?')}: {exc}")
            inter_avg.append(None)
            inter_p99.append(None)
    return inter_avg, inter_p99


def get_grc_fct(expr):
    inter_avg, inter_p99 = get_inter_fct(expr)
    avg = inter_avg[0] if inter_avg else None
    p99 = inter_p99[0] if inter_p99 else None
    return avg, p99


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot inter-DC normalized FCT against dynamic traffic rate."
    )
    parser.add_argument(
        "expr",
        nargs="?",
        default=DEFAULT_EXPR,
        help='experiment id list, for example "101-105" or "101,103,105"',
    )
    parser.add_argument(
        "--grc-expr",
        default=GRC_EXPR,
        help="experiment id list for the GRC baseline line",
    )
    parser.add_argument(
        "--avg-output",
        default=DEFAULT_AVG_OUTPUT,
        help="Avg. output PDF path, relative paths are resolved under analysis/",
    )
    parser.add_argument(
        "--p99-output",
        default=DEFAULT_P99_OUTPUT,
        help="P99 output PDF path, relative paths are resolved under analysis/",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    expr = args.expr.strip()
    if not expr:
        raise SystemExit(
            'No experiment IDs configured. Fill DEFAULT_EXPR or run: '
            'python3 analysis/rate_cal.py "ID1-ID5"'
        )

    inter_avg, inter_p99 = get_inter_fct(expr)
    grc_avg, grc_p99 = get_grc_fct(args.grc_expr)
    if len(inter_avg) != len(RATE_GBPS):
        print(
            f"Warning: got {len(inter_avg)} runs for {len(RATE_GBPS)} rate points; "
            "values are paired by order."
        )

    plot_auto_lines(
        OrderedDict([("Avg.", (RATE_GBPS, inter_avg))]),
        xlabel="Dynamic traffic throughput (Gbps)",
        ylabel="Avg. Inter Normalized FCT",
        filename=args.avg_output,
        xticks=RATE_GBPS,
        xlim=(RATE_GBPS[0], RATE_GBPS[-1]),
        hlines=OrderedDict([("GRC", grc_avg)]),
    )

    plot_auto_lines(
        OrderedDict([("P99", (RATE_GBPS, inter_p99))]),
        xlabel="Dynamic traffic throughput (Gbps)",
        ylabel="P99 Inter Normalized FCT",
        filename=args.p99_output,
        xticks=RATE_GBPS,
        xlim=(RATE_GBPS[0], RATE_GBPS[-1]),
        hlines=OrderedDict([("GRC", grc_p99)]),
        fixed_y_max=None,
        y_top_padding=0.08,
    )


if __name__ == "__main__":
    main()
