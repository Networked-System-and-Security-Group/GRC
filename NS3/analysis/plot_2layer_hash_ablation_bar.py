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

    # Colors: use same purple for enable; gray for disable
    enable_c = (130 / 255, 0, 180 / 255)
    disable_c = (0.55, 0.55, 0.55)

    plt.bar(x - width / 2, enable_vals, width, label="2-level hashing", color=enable_c)
    plt.bar(x + width / 2, disable_vals, width, label="Naive hashing", color=disable_c)

    plt.xticks(x, categories, fontsize=18)
    plt.yticks(fontsize=18)
    plt.xlabel("", fontsize=22)
    plt.ylabel(ylabel, fontsize=22)

    plt.ylim(1, 2.2)

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
    p = argparse.ArgumentParser(description="Plot bar chart for 2-layer hashing ablation (Avg/P99 FCT)")
    p.add_argument("--enable_id", type=int, default=368, help="experiment id for Enable 2-level hashing")
    p.add_argument("--disable_id", type=int, default=369, help="experiment id for Disable 2-level hashing")
    p.add_argument("--use_inter", action="store_true", help="use inter FCT (default uses overall Avg/P99)")
    p.add_argument("--output", default="2layer_hash_ablation_bar.pdf")
    args = p.parse_args()

    ana_en = get_analyser(args.enable_id)
    ana_dis = get_analyser(args.disable_id)

    if args.use_inter:
        avg_en = ana_en.get_avg_fct()[2]
        p99_en = ana_en.get_p99_fct()[2]
        avg_dis = ana_dis.get_avg_fct()[2]
        p99_dis = ana_dis.get_p99_fct()[2]
    else:
        avg_en = ana_en.get_avg_fct()[0]
        p99_en = ana_en.get_p99_fct()[0]
        avg_dis = ana_dis.get_avg_fct()[0]
        p99_dis = ana_dis.get_p99_fct()[0]

    plot_bar(
        enable_vals=[avg_en, p99_en],
        disable_vals=[avg_dis, p99_dis],
        ylabel="Normalized FCT",
        filename=args.output,
    )


if __name__ == '__main__':
    main()
