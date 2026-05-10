# analysis 脚本说明与运行命令

本文档专门说明 `analysis/` 目录下各个脚本的用途、输入、输出和可直接运行的命令。

适用前提：

- 当前工作目录在仓库根目录 `ns-3.19/`
- 仿真结果已经存在于 `mix/output/[id]-<timestamp>/`
- 你知道自己想分析哪个实验编号，或至少知道这些脚本里写死的实验编号在你的工作树里确实存在

## 先说结论

`analysis/` 里的脚本大致分三类：

1. `deep_analyse.py`
   - 核心分析库
   - 负责按实验编号读取 `mix/output/[id]-.../`
   - 很多其他脚本都依赖它

2. `flow_analyse.py`
   - 面向单个实验的“定制保存版”绘图工具
   - 适合你手工指定实验 ID、交换机 ID、flow ID 来看图

3. 其他 `plot*.py` / `autoplot*.py`
   - 多数是论文或阶段性实验出图脚本
   - 往往已经把实验编号范围写死在脚本里
   - 直接运行能出图，但前提是那些编号对应的实验目录还在

## 依赖

建议先安装：

```bash
python3 -m pip install numpy pandas matplotlib seaborn ipython
```

说明：

- `seaborn` 主要给 `plot_beta_sens_v.py` 和 `plot_beta_delta_sens.py` 用
- `ipython` 是因为 `deep_analyse.py` 里导入了 `IPython.display`

## 数据来源

这些脚本主要读取以下文件：

- `flow_output`：流完成情况、FCT slowdown
- `config.txt`：配置项
- `link_utilization`
- `buffer_monitor`
- `rate_monitor`
- `rtt_log`
- `drop_log`
- `cnp_log`
- `cnp_trigger_prob_log`
- `accumulated_bytes_log`
- `pfc_file`

注意：

- 有些日志默认是关闭的，比如 `qp_rate_log`、`cnp_log`、`pfc_file`、`accumulated_bytes_log`
- 如果脚本依赖这些文件，而文件本身是空的或不存在，脚本会报空、返回空图，或者没有数据

## 使用建议

如果你现在要分析自己的 Uno 实验，建议优先用这两个入口：

1. `deep_analyse.py`
2. `flow_analyse.py`

其他很多 `plot*.py` 更像“历史出图脚本”，适合复现作者当时那组图，不一定适合直接分析你当前的单 DC / 多 DC Uno 实验。

## 1. deep_analyse.py

### 用途

核心分析库。提供：

- 按实验编号加载结果目录
- 计算平均 / P99 FCT
- 区分 intra / inter 流
- 查看 drop rate、buffer、链路利用率
- 画单实验的若干图

### 重要限制

`deep_analyse.py` 里 `auto_save_plot` 目前把 `savefig` 注释掉了，所以很多 `ana.plot_xxx()` 会 `show()`，但不一定真的保存 PDF。

如果你要“稳定保存图”，优先用 `flow_analyse.py` 里的 `*_custom()` 版本。

### 推荐命令

打印一组实验的基本 FCT 表：

```bash
python3 -c "from analysis.deep_analyse import get_basic_result; print(get_basic_result('7'))"
```

打印一组实验的 avg / p99 FCT：

```bash
python3 -c "from analysis.deep_analyse import show_fct; show_fct('7')"
```

对单个实验做一轮“全面分析”（打印 avg/p99/drop/large/small，并保存一张 FCT CDF）：

```bash
cd analysis && python -c "from deep_analyse import get_analyser; from flow_analyse import plot_fct_cdf_custom; a = get_analyser(8); print('avg', a.get_avg_fct()); print('p99', a.get_p99_fct()); print('drop', a.get_drop_rate()); print('large', a.get_large_flow_fct()); print('small', a.get_small_flow_fct()); plot_fct_cdf_custom(a)"
```

拿到最新实验：

```bash
python3 -c "from analysis.deep_analyse import latest; a = latest(); print(a.id, a.dir)"
```

查看某个实验的平均 FCT：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; a = get_analyser(7); print(a.get_avg_fct())"
```

查看某个实验的 P99 FCT：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; a = get_analyser(7); print(a.get_p99_fct())"
```

查看某个实验的 drop rate：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; a = get_analyser(7); print(a.get_drop_rate())"
```

直接执行脚本本体：

```bash
python3 analysis/deep_analyse.py
```

说明：

- 这不是通用 CLI
- 当前 `__main__` 只会尝试对实验 `132` 运行 `analyze_cnp_k(...)`
- 更适合作为库被 `python3 -c` 或 Jupyter 调用

## 2. flow_analyse.py

### 用途

给单个实验画“明确保存为 PDF”的图。适合你手工指定：

- 实验 ID
- 某条链路
- 某个 AS 对
- 某个 flow ID
- 某个交换机

输出默认保存在仓库根目录下的 `figures/`。

### 推荐命令

画单个实验的 FCT CDF：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_fct_cdf_custom; a = get_analyser(7); plot_fct_cdf_custom(a)"
```

画某个交换机的 egress buffer：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_buffer_custom; a = get_analyser(7); plot_buffer_custom(a, switch_id=36, egress=True)"
```

画某个交换机的 ingress buffer：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_buffer_custom; a = get_analyser(7); plot_buffer_custom(a, switch_id=36, egress=False)"
```

画某个 AS 对的速率曲线：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_as_rate_custom; a = get_analyser(7); plot_as_rate_custom(a, src_as=0, dst_as=1)"
```

画某个 AS 对的 RTT：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_rtt_custom; a = get_analyser(7); plot_rtt_custom(a, src_as=0, dst_as=1)"
```

画某条链路利用率：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_link_utilization_custom; a = get_analyser(7); plot_link_utilization_custom(a, src_id=222, dst_id=226)"
```

画某个 flow 的 CNP 时间分布：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_cnp_timestamps_custom; a = get_analyser(7); plot_cnp_timestamps_custom(a, flow_id=0, start_time=2.0, end_time=2.05)"
```

画某几个 flow 的 QP rate：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_qp_rate_custom; a = get_analyser(7); plot_qp_rate_custom(a, flow_ids=[0,1,2])"
```

查看单条流的完整诊断信息（元数据、路径、drop、QP rate、CNP、链路样本汇总）：

```bash
source /home/micraow/miniconda3/etc/profile.d/conda.sh && conda activate math_modeling && python -c "from analysis.deep_analyse import get_analyser; a = get_analyser(8); a.print_flow_detail(13676)"
```

直接执行脚本本体：

```bash
python3 analysis/flow_analyse.py
```

说明：

- 当前 `__main__` 写死了实验 `286`
- 会跑 `diagnose_slow_flow()`、`show_drop()`，然后尝试把 `0..5` 的 AS 对速率图都画出来
- 如果 `286` 不存在，这条命令没有直接复用价值

## 3. autoplot.py

### 用途

针对一组实验编号，自动生成四张总览图：

- `Average-normalized-FCT.pdf`
- `P99-normalized-FCT.pdf`
- `Small-flows-normalized-FCT.pdf`
- `Large-flows-normalized-FCT.pdf`

它假设输入实验按 3 类算法交替排列：

1. `wan_cc_mode = 0`
2. `wan_cc_mode = 2`
3. `GSCC`

再按 5 个负载点循环。

### 命令

```bash
python3 analysis/autoplot.py -e '448-462' -f d
```

说明：

- `-e/--expr`：实验编号表达式
- `-f/--flow_type`：`d` 表示动态流负载横轴，`s` 表示静态 inter throughput 横轴

如果你的实验不是按这套顺序排的，图会错位。

## 4. integrated_autoplot.py

### 用途

生成 2x2 综合图，把 avg / p99 / small / large 四类指标放在同一个 PDF 里。

### 现状

虽然有 `-e/-f/-l` 参数，但当前脚本内部真正使用的是写死编号：

- `448,451,454,457,460`
- `449,452,455,458,461`
- `562-566`

传入 `-e` 目前主要只影响输出文件名。

### 命令

```bash
python3 analysis/integrated_autoplot.py -e demo -f d -l 1
```

输出示例：

- `demo-d-1.pdf`

## 5. new_autoplot.py

### 用途

生成两张总览图：

- `*-Average-normalized-FCT.pdf`
- `*-P99-normalized-FCT.pdf`

### 现状

脚本内部当前默认启用的是一组 AliStorage 相关的固定实验编号：

- `380,383,386,389,392`
- `381,384,387,390,393`
- `567-569,605,606`

`-f a/w` 主要影响输出文件名前缀，不会自动切换到另一套编号，除非你手改脚本。

### 命令

```bash
python3 analysis/new_autoplot.py -f a
```

或：

```bash
python3 analysis/new_autoplot.py -f w
```

## 6. buffer_plot.py

### 用途

画三条 buffer 曲线：

- `w/o-GSCC`
- `inf-w/o-GSCC`
- `GSCC`

输出文件：

- `buffer.pdf`

### 现状

内部写死编号：

- `448,451,454,457,460`
- `449,452,455,458,461`
- `562-566`

### 命令

```bash
python3 analysis/buffer_plot.py
```

## 7. plot_parameter_sensitivity.py

### 用途

画消融图，比较：

- 正常 GSCC
- no-rtt-diff
- no-periodic-update
- no-2level-hashing

输出文件：

- `ablation.pdf`

### 命令

```bash
python3 analysis/plot_parameter_sensitivity.py
```

## 8. plot_epoch_duration.py

### 用途

画 epoch duration 敏感性图。

输出文件：

- `epoch_duration.pdf`

### 现状

内部使用固定实验编号表达式：

- `461,642-645`

### 命令

```bash
python3 analysis/plot_epoch_duration.py
```

## 9. plot_T.py

### 用途

画不同 `T` 参数下的平均归一化 FCT。

输出文件：

- `gscc_parameter.pdf`

### 命令

```bash
python3 analysis/plot_T.py
```

## 10. plot_beta_sens_v.py

### 用途

分析 `beta` 与 `V` 开关的敏感性，输出：

- 单独 3D 图
- 合并 3D 图
- CSV 结果表

### 可选 metric

- `inter_avg_fct`
- `wan_buffer_avg`
- `wan_buffer_p99`

### 命令

默认 metric：

```bash
python3 analysis/plot_beta_sens_v.py
```

指定 metric：

```bash
python3 analysis/plot_beta_sens_v.py wan_buffer_avg
```

## 11. plot_beta_delta_sens.py

### 用途

分析 `beta` 与 `InvDelta` 的联合敏感性，输出：

- heatmap
- 3D 曲面
- CSV 结果表

### 可选 metric

- `inter_avg_fct`
- `wan_buffer_avg`
- `wan_buffer_p99`

### 命令

默认 metric：

```bash
python3 analysis/plot_beta_delta_sens.py
```

指定 metric：

```bash
python3 analysis/plot_beta_delta_sens.py wan_buffer_p99
```

## 12. 3d_plot.py

### 用途

生成 3D 参数曲面图，当前脚本写死了：

- `H`
- `beta`
- 两组动态吞吐结果

输出：

- `gscc_para_H_beta_150_100.pdf`
- `gscc_para_H_beta_150_200.pdf`

### 命令

```bash
python3 analysis/3d_plot.py
```

## 13. avg_NFCT_plot.py

### 用途

早期均匀流量实验图，画：

- Avg FCT
- Avg intra FCT
- Avg inter FCT

输出：

- `uniform_flow_analysis.pdf`

### 现状

内部写死使用：

- `get_basic_result('1-4')`

### 命令

```bash
python3 analysis/avg_NFCT_plot.py
```

## 14. cal_drop.py

### 用途

计算两组实验中的最大 drop rate，并直接打印结果。

### 命令

```bash
python3 analysis/cal_drop.py
```

说明：

- 内部写死了 `gscc_web` 和 `gscc_ali` 两组实验编号
- 不生成图，只打印数值

## 15. plot.py

### 用途

早期论文出图脚本，输出：

- `auto_styled_lines.png`

### 现状

内部写死：

- `get_basic_result('428-442')`

### 命令

```bash
python3 analysis/plot.py
```

## 16. plot2.py

### 用途

另一张论文出图脚本，输出：

- `5.2a.png`

### 现状

内部当前启用：

- `get_basic_result('559-570,737-742')`

### 命令

```bash
python3 analysis/plot2.py
```

## 17. plot poster.py

### 用途

海报/总览图脚本，输出：

- `overall.pdf`

### 现状

内部写死：

- `get_basic_result('577-594')`

### 命令

```bash
python3 "analysis/plot poster.py"
```

## 怎么判断该用哪个脚本

如果你现在是在分析自己的 Uno 实验，建议按下面顺序：

1. 先用 `deep_analyse.py`
   - 看 `get_avg_fct()`
   - 看 `get_p99_fct()`
   - 看 `get_drop_rate()`

2. 再用 `flow_analyse.py`
   - 画你关心的单实验图
   - 这是最稳的“按需诊断”工具

3. 最后才考虑 `autoplot.py`、`buffer_plot.py`、`plot_T.py` 这些
   - 它们更适合“批量画一整组论文图”
   - 默认强依赖特定实验编号布局

## 对 Uno 单 DC / 多 DC 的建议

### 单 DC

优先用：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; a = get_analyser(7); print(a.get_avg_fct(), a.get_p99_fct())"
```

和：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_fct_cdf_custom; a = get_analyser(7); plot_fct_cdf_custom(a)"
```

### 多 DC

优先用：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; a = get_analyser(3); print(a.get_avg_fct(), a.get_p99_fct(), a.get_buffer_information())"
```

再按需看：

```bash
python3 -c "from analysis.deep_analyse import get_analyser; from analysis.flow_analyse import plot_as_rate_custom, plot_rtt_custom; a = get_analyser(3); plot_as_rate_custom(a, 0, 1); plot_rtt_custom(a, 0, 1)"
```

## 最后提醒

很多脚本能跑，不等于适合你当前实验。

判断标准只有两个：

1. 它依赖的日志文件，你这次实验是否真的产出了
2. 它写死的实验编号，是否和你当前实验编号布局一致

如果你后面要把这些脚本真正整理成“面向当前 Uno 实验”的工具，最值得先改的是：

- 给 `flow_analyse.py` 补 CLI 参数
- 给 `deep_analyse.py` 恢复 `savefig`
- 给 `autoplot.py` / `buffer_plot.py` 去掉写死编号
