import argparse
import os.path as op

import matplotlib
import matplotlib.pyplot as plt
import numpy as np


matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

SCRIPT_DIR = op.dirname(op.abspath(__file__))
REPO_ROOT = op.abspath(op.join(SCRIPT_DIR, ".."))
TRAFFIC_DIR = op.join(REPO_ROOT, "traffic_gen")

MAIN_FIGSIZE = (5.6, 2.5)
TICK_FONTSIZE = 11
LABEL_FONTSIZE = 13
LEGEND_FONTSIZE = 10
GRID_ALPHA = 0.25
GRID_LINEWIDTH = 0.8
GRID_LINESTYLE = "--"

CDF_STYLES = {
    "WebSearch": {"color": "#4E79A7", "linestyle": "-"},
    "DataMining": {"color": "#E15759", "linestyle": "-"},
}

CDF_FILES = {
    "WebSearch": op.join(TRAFFIC_DIR, "WebSearch.txt"),
    "DataMining": op.join(TRAFFIC_DIR, "mining.txt"),
}


def read_cdf(path):
    data = np.loadtxt(path)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"Invalid CDF file: {path}")

    x = data[:, 0].astype(float)
    y = data[:, 1].astype(float) / 100.0

    return x, y


def plot_cdfs(output):
    fig, ax = plt.subplots(figsize=MAIN_FIGSIZE, dpi=300)

    for label, path in CDF_FILES.items():
        x, y = read_cdf(path)
        style = CDF_STYLES[label]
        ax.plot(
            x,
            y,
            label=label,
            color=style["color"],
            linestyle=style["linestyle"],
            linewidth=2.8,
            clip_on=True,
        )

    ax.set_xscale("symlog", linthresh=1e4)
    ax.set_xlim(0, 1e9)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("Flow Size (Bytes)", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("CDF", fontsize=LABEL_FONTSIZE)
    ax.set_yticks(np.linspace(0, 1.0, 6))
    ax.set_yticklabels(["0", "0.2", "0.4", "0.6", "0.8", "1"], fontsize=TICK_FONTSIZE)
    ax.tick_params(axis="x", labelsize=TICK_FONTSIZE)
    ax.tick_params(axis="both", which="both", width=1.0, color="#222222")
    ax.grid(axis="y", alpha=GRID_ALPHA, linewidth=GRID_LINEWIDTH, linestyle=GRID_LINESTYLE)
    ax.grid(
        axis="x",
        which="major",
        alpha=GRID_ALPHA,
        linewidth=GRID_LINEWIDTH,
        linestyle=GRID_LINESTYLE,
    )

    for spine in ("left", "bottom", "top", "right"):
        ax.spines[spine].set_visible(True)
        ax.spines[spine].set_linewidth(1.0)
        ax.spines[spine].set_linestyle("-")
        ax.spines[spine].set_color("#222222")

    ax.legend(
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        loc="lower right",
        handlelength=2.4,
    )

    output = output if op.isabs(output) else op.join(SCRIPT_DIR, output)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved figure to {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="cdf.pdf")
    args = parser.parse_args()
    plot_cdfs(args.output)


if __name__ == "__main__":
    main()
