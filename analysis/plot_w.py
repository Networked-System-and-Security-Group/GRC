from deep_analyse import get_analyser
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt


def plot_bar(enable_vals, disable_vals, *, ylabel: str, filename: str):
    # Styling consistent with plot_epoch_duration.py
    plt.figure(figsize=(5, 4), dpi=300)
    plt.rcParams['pdf.fonttype'] = 42

    categories = ["Avg", "P99"]
    x = np.arange(len(categories))
    width = 0.35

    enable_c = (130 / 255, 0, 180 / 255)
    disable_c = (0.55, 0.55, 0.55)

    plt.bar(x - width / 2, enable_vals, width, label="ENABLE_W", color=enable_c)
    plt.bar(x + width / 2, disable_vals, width, label="DISABLE_W", color=disable_c)

    plt.xticks(x, categories, fontsize=18)
    plt.yticks(fontsize=18)
    plt.xlabel("", fontsize=22)
    plt.ylabel(ylabel, fontsize=22)

    plt.legend(frameon=False, fontsize=16, loc='upper left', bbox_to_anchor=(0, 1.1))
    plt.grid(axis='y', alpha=0.3)
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(filepath, bbox_inches='tight')
    plt.close()
    print(f"Saved figure to {filepath}")


def main():
    p = argparse.ArgumentParser(description="Plot ENABLE_W/DISABLE_W ablation bar chart (Avg/P99 Inter FCT)")
    p.add_argument("--enable_id", type=int, default=361, help="experiment id for ENABLE_W")
    p.add_argument("--disable_id", type=int, default=309, help="experiment id for DISABLE_W")
    p.add_argument("--output", default="figures/w_ablation_361_309.pdf")
    p.add_argument(
        "--ylim",
        type=float,
        nargs=2,
        default=None,
        metavar=("YMIN", "YMAX"),
        help="optional y-axis limits, e.g. --ylim 1 2",
    )
    args = p.parse_args()

    ana_en = get_analyser(args.enable_id)
    ana_dis = get_analyser(args.disable_id)

    # Inter FCT only
    avg_en = ana_en.get_avg_fct()[2]
    p99_en = ana_en.get_p99_fct()[2]
    avg_dis = ana_dis.get_avg_fct()[2]
    p99_dis = ana_dis.get_p99_fct()[2]

    plot_bar(
        enable_vals=[avg_en, p99_en],
        disable_vals=[avg_dis, p99_dis],
        ylabel="Inter Normalized FCT",
        filename=args.output,
    )

    if args.ylim is not None:
        # If user asks for fixed ylim, re-plot with limits.
        # Keep this as a separate pass to avoid threading ylim through all calls.
        plt.figure(figsize=(5, 4), dpi=300)
        plt.rcParams['pdf.fonttype'] = 42

        categories = ["Avg.", "P99"]
        x = np.arange(len(categories))
        width = 0.35

        enable_c = (130 / 255, 0, 180 / 255)
        disable_c = (0.55, 0.55, 0.55)

        plt.bar(x - width / 2, [avg_en, p99_en], width, label="ENABLE_W", color=enable_c)
        plt.bar(x + width / 2, [avg_dis, p99_dis], width, label="DISABLE_W", color=disable_c)

        plt.xticks(x, categories, fontsize=18)
        plt.yticks(fontsize=18)
        plt.ylabel("Inter Normalized FCT", fontsize=22)
        plt.ylim(float(args.ylim[0]), float(args.ylim[1]))

        plt.legend(frameon=False, fontsize=16, loc='upper left', bbox_to_anchor=(0, 1.1))
        plt.grid(axis='y', alpha=0.3)
        ax = plt.gca()
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        filepath = args.output if op.isabs(args.output) else op.join(op.dirname(__file__), args.output)
        plt.savefig(filepath, bbox_inches='tight')
        plt.close()
        print(f"Saved figure to {filepath} (with ylim={args.ylim[0]}..{args.ylim[1]})")


if __name__ == '__main__':
    main()
