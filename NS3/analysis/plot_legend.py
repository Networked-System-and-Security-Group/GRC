# make_legend_one_row.py
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

gscc_c = (130/255, 0, 180/255)
_style_list = [
    (':', "orange", 'o'),
    ('--', "orange", 's'),
    (':', "c", 'o'),
    ('--', "c", 's'),
    (':', gscc_c, '^'),
    ('--', gscc_c, 'd'),
]

labels = [
    "GSCC-inter",
    "GSCC-intra",
    "inf-w/o-GSCC-inter",
    "inf-w/o-GSCC-intra",
    "w/o-GSCC-inter",
    "w/o-GSCC-intra",
]

def make_legend_pdf(out="legend.pdf", fontsize=10):
    handles = [
        Line2D([0], [0],
               linestyle=ls, color=col, marker=mk,
               linewidth=2.5, markersize=6,
               label=lab)
        for (ls, col, mk), lab in zip(_style_list, labels)
    ]

    # 画布随便大点，反正你会裁剪
    fig = plt.figure(figsize=(20, 0.6), dpi=300)
    ax = fig.add_subplot(111)
    ax.axis("off")

    ax.legend(
        handles=handles,
        loc="center",
        ncol=6,              # 一行
        frameon=False,
        fontsize=fontsize,

        # 下面这些是“减少中间空白”的关键
        handlelength=2.0,    # 线段长度（越短越紧凑）
        handletextpad=0.5,  # 线段与文字间距
        columnspacing=0.5,   # 每个 legend item 之间的间距（越小越紧凑）
        labelspacing=0.0,
        borderaxespad=0.0
    )

    fig.savefig(out, bbox_inches="tight", pad_inches=0.01)
    plt.close(fig)
    print(f"Saved {out}")

if __name__ == "__main__":
    make_legend_pdf("legend.pdf", fontsize=10)
