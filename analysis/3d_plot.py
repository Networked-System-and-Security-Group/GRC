from deep_analyse import *
import argparse
import os.path as op
import numpy as np
import matplotlib.pyplot as plt
from itertools import cycle
import numpy as np

from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D

# 定义3D图的样式循环列表：(颜色映射, 散点标记, 表面透明度, 散点颜色)
_style_list_3d = [
    ('coolwarm', 'o', 0.7, 'red'),    # 冷到热的颜色映射（蓝到红）
    ('bwr', 's', 0.7, 'blue'),        # 蓝到红的颜色映射
]


def plot_3d_surface(data, xlabel, ylabel, zlabel, filename,
                    xticks=None, yticks=None, xlim=None, ylim=None,
                    elev=30, azim=45):
    """
    绘制三维表面图和散点，确保Z轴标签完全显示
    """
    plt.figure(figsize=(6, 4.5), dpi=300)
    ax = plt.subplot(111, projection='3d')
    
    # 关键修改1：调整边距，为Z轴标签预留空间
    plt.subplots_adjust(
        left=0.15,    # 左侧边距适当增大
        right=0.95,
        #bottom=0.15,  # 底部边距适当增大
        #top=0.95,
        wspace=0,
        hspace=0
    )
    style_cycle = cycle(_style_list_3d)

    # 收集所有数据范围和图例元素
    all_x, all_y, all_z = [], [], []
    legend_handles = []
    legend_labels = []
    all_z_values = []

    # 收集所有z值用于统一颜色映射范围
    for label, (x, y, z) in data.items():
        for xi, yi, zi in zip(x, y, z):
            if (xi is not None) and (yi is not None) and (zi is not None):
                if not (np.isnan(xi) or np.isnan(yi) or np.isnan(zi)):
                    all_z_values.append(zi)

    # 确定全局z值范围
    z_min, z_max = (min(all_z_values), max(all_z_values)) if all_z_values else (0, 1)

    # 逐条绘制数据系列
    for label, (x, y, z) in data.items():
        # 过滤无效值
        filtered_x, filtered_y, filtered_z = [], [], []
        for xi, yi, zi in zip(x, y, z):
            if (xi is not None) and (yi is not None) and (zi is not None):
                if not (np.isnan(xi) or np.isnan(yi) or np.isnan(zi)):
                    filtered_x.append(xi)
                    filtered_y.append(yi)
                    filtered_z.append(zi)

        if not filtered_x:
            continue

        # 转换为numpy数组
        x_arr = np.array(filtered_x)
        y_arr = np.array(filtered_y)
        z_arr = np.array(filtered_z)

        # 获取样式
        cmap, marker, alpha, scatter_color = next(style_cycle)

        # 绘制表面图
        surf = ax.plot_trisurf(x_arr, y_arr, z_arr,
                               cmap=cmap, edgecolor='gray',
                               linewidth=0.5, alpha=alpha,
                               vmin=z_min, vmax=z_max)

        # 绘制散点
        scatter = ax.scatter(x_arr, y_arr, z_arr,
                            marker=marker, s=50,
                            edgecolor='black', linewidth=0.8,
                            color=scatter_color)

        # 收集数据范围和图例元素
        all_x.extend(filtered_x)
        all_y.extend(filtered_y)
        all_z.extend(filtered_z)
        legend_handles.append(scatter)
        legend_labels.append(label)

    # 设置坐标轴刻度
    if xticks is not None:
        ax.set_xticks(xticks)
        if xlabel == 'H':
            ax.set_xticklabels([f'$\\frac{{1}}{{{int(1 / h)}}}$' for h in xticks])
    if yticks is not None:
        ax.set_yticks(yticks)

    # 关键修改2：增加Z轴标签的距离（labelpad）
    #ax.set_xlabel(xlabel, fontsize=14, labelpad=4)  # X轴标签距离
    #ax.set_ylabel(ylabel, fontsize=14, labelpad=4)  # Y轴标签距离
    ax.set_zlabel(zlabel, fontsize=14, labelpad=4)   # Z轴标签距离增大（重点）
    ax.xaxis._axinfo["tick"]["pad"] = 0  # X轴刻度距离
    ax.yaxis._axinfo["tick"]["pad"] = 0  # Y轴刻度距离
    ax.zaxis._axinfo["tick"]["pad"] = 0  # Z轴刻度距离（3D图需单独设置Z轴）
    # 设置坐标轴刻度字体大小（关键修改）
    ax.tick_params(axis='x', labelsize=14)  # x轴刻度字体大小
    ax.tick_params(axis='y', labelsize=14)  # y轴刻度字体大小
    ax.tick_params(axis='z', labelsize=14)  # z轴刻度字体大小

    # 设置轴范围
    if xlim:
        ax.set_xlim(*xlim)
    elif all_x:
        ax.set_xlim(min(all_x), max(all_x))
    if ylim:
        ax.set_ylim(*ylim)
    elif all_y:
        ax.set_ylim(min(all_y), max(all_y))

    # 关键修改3：微调视角（可选，根据实际显示效果调整）
    ax.view_init(elev=30, azim=45)  # 略微降低仰角，避免Z轴标签被遮挡

    # 保存图形（确保标签完整显示）
    filepath = filename if op.isabs(filename) else op.join(op.dirname(__file__), filename)
    plt.savefig(
        filepath, 
        format='pdf', 
        bbox_inches='tight',  # 自动裁剪多余空白，但保留必要空间
        pad_inches=0.3        # 适当增加边界预留，避免标签被裁
    )
    plt.show()
    print(f"Saved 3D figure to {filepath}")


def get_avg_inter(expr):
    result = []
    for ana in analyser_iter(expr):
        avg, avg_intra, avg_inter = ana.get_avg_fct()
        result.append(avg_inter)
    return result

def calculate_variation(data):
    data_np = np.array(data)
    avg = np.mean(data_np)
    range_val = np.ptp(data_np)
    cv = (range_val / avg) * 100
    print(cv)

# 使用示例
if __name__ == "__main__":
    H_vals = [1/12, 1/16, 1/20, 1/24]
    beta_vals = [0.5, 0.6, 0.7]
    result_150_100 = get_avg_inter('503-514')
    result_150_200 = get_avg_inter('515-526')
    calculate_variation(result_150_100)
    calculate_variation(result_150_200)


    # 生成数据列表
    x_list = []
    y_list = []
    for h in H_vals:
        for b in beta_vals:
            x_list.append(h)
            y_list.append(b)

    # 为每组数据创建单独的数据字典
    data_150_100 = {
        'GSCC-inter-150-100': (x_list, y_list, result_150_100)
    }
    
    data_150_200 = {
        'GSCC-inter-150-200': (x_list, y_list, result_150_200)
    }

    # 分别绘制两组数据
    plot_3d_surface(
        data=data_150_100,
        xlabel='H',
        ylabel='$\\beta$',
        zlabel='Dynamic traffic throughput (Gbps)',
        filename='gscc_para_H_beta_150_100.pdf',
        xticks=H_vals,
        yticks=beta_vals,
        elev=30,  # 微调仰角（与函数内默认一致）
        azim=45
    )
    
    plot_3d_surface(
        data=data_150_200,
        xlabel='H',
        ylabel='$\\beta$',
        zlabel='Dynamic traffic throughput (Gbps)',
        filename='gscc_para_H_beta_150_200.pdf',
        xticks=H_vals,
        yticks=beta_vals,
        elev=30,
        azim=45
    )