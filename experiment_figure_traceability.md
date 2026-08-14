# 论文实验图片与当前分支数据的复现核对

核对对象：`ICNP_26_RDMA_WAN_Optimization_experiment_figures.zip` 中的 22 张 PDF。

核对分支：`final-gscc`。

## 核对方法

不是仅根据文件名或脚本中硬编码的 ID 判断来源。对可匹配的图片，使用当前分支的绘图脚本和 `mix/output` 中的数据在临时目录重新绘图，再与 ZIP 中的 PDF 比较：

- 曲线图：比较 PDF 中彩色数据点相对于坐标轴的矢量坐标；所有可见数据点完全重合。
- 其余图：以相同 DPI 渲染后比较像素；`beta/delta`、`epoch` 和 WebSearch 图例为零像素差。
- `cdf.pdf` 与 `tcp_fct.pdf` 的像素差仅为 PDF 渲染抗锯齿误差，确认使用当前脚本的数据源。

因此，只有下表中标记为“已确认”的图片可以可靠地声称由当前分支的代码和数据绘制。

## 已确认：重画结果与 ZIP 中论文图一致

| ZIP 图片 | 当前脚本 | 实验 ID / 数据来源 |
|---|---|---|
| `websearch-Average-normalized-FCT-Inter.pdf` | `analysis/new_autoplot.py` | 见下方 WebSearch ID 组 |
| `websearch-Average-normalized-FCT-Intra.pdf` | `analysis/new_autoplot.py` | 同上 |
| `websearch-P99-normalized-FCT-Inter.pdf` | `analysis/new_autoplot.py` | 同上 |
| `websearch-P99-normalized-FCT-Intra.pdf` | `analysis/new_autoplot.py` | 同上 |
| `websearch-Legend.pdf` | `analysis/new_autoplot.py` | 图例，无实验数据 |
| `websearch-Max-Buffer-Util.pdf` | `analysis/buffer_plot_max.py` | WebSearch ID 组；取 peak WAN buffer |
| `datamining-Average-normalized-FCT-Inter.pdf` | `analysis/overall_dataming.py` | 见下方 DataMining ID 组 |
| `datamining-Average-normalized-FCT-Intra.pdf` | `analysis/overall_dataming.py` | 同上 |
| `datamining-P99-normalized-FCT-Inter.pdf` | `analysis/overall_dataming.py` | 同上 |
| `datamining-P99-normalized-FCT-Intra.pdf` | `analysis/overall_dataming.py` | 同上 |
| `beta_delta_inter_avg_fct_3d.pdf` | `expr-para-sensi/plot_beta_delta_sens.py` | `445-449,344-363`，指标 `inter_avg_fct` |
| `beta_delta_wan_buffer_p99_3d.pdf` | `expr-para-sensi/plot_beta_delta_sens.py` | `445-449,344-363`，指标 `wan_buffer_p99` |
| `epoch_duration.pdf` | `analysis/plot_epoch_duration.py` | `364-368` |
| `cdf.pdf` | `analysis/cdf.py` | 无 ns-3 实验 ID；读取 `traffic_gen/WebSearch.txt` 和 `traffic_gen/mining.txt` |
| `tcp_fct.pdf` | `analysis/tcp/tcp.py` | 无 ns-3 实验 ID；使用脚本内硬编码数组 |

### WebSearch ID 组

横轴是动态流量吞吐量 `0/60/120/180 Gbps`。

| 算法 | ID |
|---|---|
| DCQCN | `392-395` |
| DCQCN-SR | `414-417` |
| GEMINI | `477-480` |
| UnoCC | `437-440` |
| GRC | `336-339` |

### DataMining ID 组

横轴同样是 `0/60/120/180 Gbps`。

| 算法 | ID |
|---|---|
| DCQCN | `452-455` |
| DCQCN-SR | `464-467` |
| GEMINI | `481-484` |
| UnoCC | `441-444` |
| GRC | `460-463` |

### Beta/Delta 参数敏感性图

每个 `INV_DELTA` 取值都使用 `BETA={0, 0.15, 0.3, 0.45, 0.6}`：

| `INV_DELTA` | ID |
|---|---|
| 1 MiB | `445-449` |
| 2 MiB | `344-348` |
| 4 MiB | `349-353` |
| 8 MiB | `354-358` |
| 16 MiB | `359-363` |

`418-422` 是 12 MiB 的补充实验，但当前绘图脚本的默认 ID 列表不包含它，且论文 PDF 的坐标轴也不显示 12 MiB。

### Epoch 图

`364-368` 均使用 `w-dynamic-150-180-v1`，其 `WAN_EPOCH_US` 分别为 `1000/2000/3000/4000/5000`，即 1–5 ms。

## 实验启动脚本与原始启动证据

这里的“启动脚本”与上表的“绘图脚本”不同：前者负责调用 `run.py` 产生 `mix/output/[id]-*/`，后者读取这些目录绘图。下表记录实际能找到的启动证据；找不到原始启动命令时，不把后续重构的命令伪称为原始脚本。

| 实验组 | ID | 启动脚本 / 原始证据 | 可信结论 |
|---|---|---|---|
| WebSearch + DataMining GEMINI | `477-480`、`481-484` | `gemini.sh` | 当前仓库保留的批量启动脚本；八条命令与所有对应 `config.txt` 一致。 |
| Beta/Delta，2/4/8/16 MiB | `344-363` | `beta_delta_sensitivity.py` | 当前脚本循环五个 Beta 和四个 `INV_DELTA`；其有效参数与 20 份 `config.txt` 一致。 |
| Beta/Delta，1 MiB | `445-449` | 未找到保存在仓库的启动脚本；`~/.bash_history` 第 775-779 条记录了五条手动 `run.py` 命令 | 这些命令的 `BETA`、`INV_DELTA=1048576`、`ENABLE_V/W=TRUE` 与实际 `config.txt` 一致。 |
| Epoch duration | `364-368` | `epoch_hash_scan.py --experiment epoch` | 脚本的第一组 flow 为 `w-dynamic-150-180-v1`，连续生成 1–5 ms 的这五份配置；实际 `config.txt` 也记录了 `No.1/10` 至 `No.5/10`。 |
| DataMining DCQCN、IRN、UnoCC、GRC | `452-455,464-467,441-444,460-463` | 未找到单独保存的 batch 脚本；`~/.bash_history` 第 784-801、883-886 条保留直接 `run.py` 命令 | 命令和 `config.txt` 对应；尤其 IRN 使用 `--pfc 1 --irn 1`，GRC 使用 `ENABLE_W=TRUE`、`INV_DELTA=6291456`、`W_MAX=4.0`、`GSCC_FAIR=TRUE`。 |
| WebSearch UnoCC | `437-440` | 未找到单独保存的 batch 脚本；`~/.bash_history` 第 874-877 条 | 参数 `--cc unocc --wan_cc_mode 2 --uno_ai_factor 0.01` 与 `config.txt` 一致。 |
| WebSearch DCQCN、DCQCN-SR、GRC | `392-395`、`414-417`、`336-339` | 仓库、所有本地分支历史及当前 bash history 均未找到原始启动脚本或原始命令 | 只能以保留的 `config.txt` 为可靠依据，不能声称已找回其原始 launcher。 |

`cdf.pdf` 和 `tcp_fct.pdf` 没有 ns-3 启动实验：前者由 `analysis/cdf.py` 直接读取 CDF 输入文件，后者由 `analysis/tcp/tcp.py` 使用硬编码数组。

## 实际 `config.txt` 审计（以输出目录为准）

已逐份检查上述已确认图片涉及的 70 份 `mix/output/[id]-*/config.txt`。本节仅压缩列出实际生效、且能区分实验组的字段；每份完整配置仍保存在相应 ID 的输出目录，才是最终权威记录。

除下表明确列出的差异外，每个四点负载组内仅 `FLOW_FILE`、`MSG`、`OUTPUT_DIR_PATH` 和 `TIME` 随 ID 改变。ID 的升序分别对应动态负载 `0/60/120/180 Gbps`。

所有这些 ns-3 运行共同确认的基础字段为：`TOPOLOGY_FILE=config/cernet_topo.txt`、`FLOWGEN_START_TIME=2.0`、`BUFFER_SIZE=9`、`DCI_BUFFER_SIZE=0`、`WAN_BUFFER_SIZE=0`、`LB_MODE=0`、`ENABLE_PFC=1`、`ERROR_RATE_PER_LINK=0.0000`、`ENABLE_QCN=1`、`USE_DYNAMIC_PFC_THRESHOLD=1`、`PACKET_PAYLOAD_SIZE=1000`、`RANDOM_SEED=1`。

### WebSearch：实际配置

所有本组 `FLOWGEN_STOP_TIME=2.2`，`FLOW_FILE` 为 `config/w-dynamic-150-{0,60,120,180}-v1.txt`。

| 图中算法 | ID | `CC_MODE` | `WAN_CC_MODE` | `ENABLE_IRN` | `HAS_WIN` / `VAR_WIN` | 额外实际字段 |
|---|---|---:|---:|---:|---|---|
| DCQCN | `392-395` | 1 | 2 | 0 | 0 / 0 | 无 |
| DCQCN-SR（输出目录标记为 IRNnoBDP） | `414-417` | 1 | 2 | 1 | 0 / 0 | 无 |
| GEMINI | `477-480` | 9 | 0 | 0 | 1 / 1 | `KMIN_MAP=400`、`KMAX_MAP=400`、`PMAX_MAP=1`（各速率档） |
| UnoCC | `437-440` | 10 | 0 | 0 | 1 / 1 | `UNO_AI_FACTOR=0.01`、`UNO_EWMA_GAIN=0.65`、`UNO_PHANTOM_ENABLED=1` |
| GRC（输出目录标记为 GSCC） | `336-339` | 1 | 1 | 0 | 0 / 0 | 无额外 raw parameter |

### DataMining：实际配置

所有本组 `FLOWGEN_STOP_TIME=2.2`，`FLOW_FILE` 为 `config/m-dynamic-70-150-{0,60,120,180}-v1.txt`。

| 图中算法 | ID | `CC_MODE` | `WAN_CC_MODE` | `ENABLE_IRN` | `HAS_WIN` / `VAR_WIN` | 额外实际字段 |
|---|---|---:|---:|---:|---|---|
| DCQCN | `452-455` | 1 | 2 | 0 | 0 / 0 | 无 |
| DCQCN-SR（输出目录标记为 IRN） | `464-467` | 1 | 2 | 1 | 0 / 0 | 无 |
| GEMINI | `481-484` | 9 | 0 | 0 | 1 / 1 | `KMIN_MAP=400`、`KMAX_MAP=400`、`PMAX_MAP=1`（各速率档） |
| UnoCC | `441-444` | 10 | 2 | 0 | 1 / 1 | `UNO_AI_FACTOR=0.01`、`UNO_EWMA_GAIN=0.65`、`UNO_PHANTOM_ENABLED=1` |
| GRC（输出目录标记为 GSCC） | `460-463` | 1 | 1 | 0 | 0 / 0 | `ENABLE_W=TRUE`、`INV_DELTA=6291456`、`W_MAX=4.0`、`GSCC_FAIR=TRUE` |

注意：此处如实记录 `config.txt` 中的数值，尤其 `WAN_CC_MODE`；不要仅根据图例算法名称或当前 `run.py` 的默认值反推它。

### Beta/Delta 与 Epoch：实际配置

| 图 | ID | 真实 `FLOW_FILE` / 时间 | `CC_MODE` / `WAN_CC_MODE` | 实际 raw parameter |
|---|---|---|---|---|
| Beta/Delta | `445-449` | `w-dynamic-150-180-v1.txt`；`FLOWGEN_STOP_TIME=2.2` | 1 / 1 | `BETA={0,0.15,0.3,0.45,0.6}`，`INV_DELTA=1048576`，`ENABLE_V=TRUE`，`ENABLE_W=TRUE` |
| Beta/Delta | `344-363` | 同上 | 1 / 1 | 同一组 Beta；`INV_DELTA={2097152,4194304,8388608,16777216}`，`ENABLE_V=TRUE`，`ENABLE_W=TRUE` |
| Epoch | `364-368` | `w-dynamic-150-180-v1.txt`；`FLOWGEN_STOP_TIME=2.05` | 1 / 1 | `WAN_EPOCH_US={1000,2000,3000,4000,5000}` |

特别更正：用于论文 beta/delta 两图的 `344-363` 和 `445-449` 的实际 `config.txt` **没有** `GSCC_FAIR` 字段。不要把 12 MiB 补充实验文档中的 `GSCC_FAIR=TRUE` 描述外推到这 25 份已绘图数据。

## 已否定：不能使用当前数据复现

### `2layer_hash_ablation_bar.pdf`

虽然 `analysis/plot_2layer_hash_ablation_bar.py` 的文件名和版式与该图相同，但该脚本默认 ID `368/369` 与当前实验数据不匹配。

从论文 PDF 的矢量柱高反推出的数值约为：

| 图中标签 | Avg | P99 |
|---|---:|---:|
| 2-level hashing | 1.054 | 1.889 |
| Naive hashing | 1.071 | 1.947 |

当前 `mix/output` 中的默认 ID 实际为 epoch sweep：

| ID | 实际配置 | Overall Avg FCT | Overall P99 FCT |
|---|---|---:|---:|
| `368` | `WAN_EPOCH_US=5000`，`w-dynamic-150-180-v1` | 2.759763 | 15.719136 |
| `369` | `WAN_EPOCH_US=1000`，`w-dynamic-150-120-v1` | 2.661883 | 14.498976 |

该图的 y 轴上限为 2.2；因此其不可能由当前 `368/369` 的数据重画得到。当前 `mix/output` 的 506 个实验（ID `0-505`）中也没有发现 `ENABLE_2LAYER_HASH` 配置。不要把 `368/369` 引用为论文 hashing 消融图的可信来源。

## 无法从当前分支可靠确认来源

以下 6 张图在当前分支中没有找到可以重画出相同图形的代码与数据组合，因此不应推断其实验 ID：

- `fairness.pdf`
- `fitting.pdf`
- `moti/moti-cdf.pdf`
- `design/paper_clamp_1ms_twoflow_sender_rates_clean.pdf`
- `design/paper_pure_virtual_twoflow_sender_rates_clean.pdf`
- `topo.pdf`

补充说明：

- `moti/moti-cdf.pdf` 的标签是 `GEMINI/DCQCN/IDEAL`。当前 `analysis/deep_analyse.py` 中的 motivation 函数虽引用 ID `40/41`，但输出名和标签是 `Disable-ECN/Enable-ECN`，不可对应。
- 两张 `design` 图看起来是理论模型的 sender-rate 图，并非 `mix/output` 的 ns-3 实验结果；当前理论脚本的输出文件名和版式也不一致。
- `topo.pdf` 的 PDF Creator 是 WPS 演示，属于手工绘制的拓扑示意图，不使用实验 ID。

## 最终结论

压缩包共 22 张 PDF：15 张已通过实际重画校验；1 张（hashing 消融）与当前 ID 数据明确不匹配；其余 6 张无法从当前分支可靠追溯。
