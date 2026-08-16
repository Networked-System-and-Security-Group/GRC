# TCP/RDMA 队列共存三组实验：RDMA 150-180、TCP 600G/100ms

> 状态：已完成。357/358/359 均因全部 36,027 条 RDMA 流完成而正常结束。q3 的 RDMA 平均 slowdown 低于 q1 `1.71%`，但原始 RDMA 平均/P99 FCT 分别高 `2.53%`/`9.35%`；TCP 最终完成量还受到 q3 比 q1 多运行 `40.3 ms` 的影响。因此，本次结果不支持“q3 在 RDMA 或 TCP 上整体更优”的无条件结论。

## 1. 实验目的

在 `expr-0815-tcp-rdma-queue-coexist-150-180-3way` 的 353/354/355 实验基础上，仅将 TCP 输入由 `w-tcp-300-100.txt` 替换为新生成的 `w-tcp-600-100.txt`，保持三组比较：

| 实验组 | RDMA 队列 | TCP 队列 | TCP 输入 |
|---|---:|---:|---|
| q1 隔离 | 3 | 1 | `config/w-tcp-600-100.txt` |
| q3 共用 | 3 | 3 | `config/w-tcp-600-100.txt` |
| 无 TCP | 3 | 不生效 | 不配置 `TCP_FLOW_FILE` |

这里的“q1 隔离”仅指源端优先级队列不同。TCP 与 RDMA 仍会共享 NIC、后续 egress port 和网络链路，不能把 q1 当作完全无竞争基线；359 才是无 TCP 输入的 RDMA-only 对照。

## 2. 固定输入与配置

| 项目 | 实际值 |
|---|---|
| 拓扑 | `config/cernet_topo.txt` |
| RDMA 流量 | `config/w-dynamic-150-180.txt`，36,027 条流，SHA256 `2349e1807c9bf72ca41e8ee7e937d7b1a30ce832f0bcf9c6e806ff686775446b` |
| RDMA 时间范围 | `2.000000700-2.128999006 s` |
| TCP 流量 | `config/w-tcp-600-100.txt`，109,166 条流，187,709,123,415 bytes，SHA256 `bfe43ab95595e8bb1e102b81bf697c1b3ecfdf6886a0051f8b89ba5df682a128` |
| TCP 时间范围 | `2.000003727-2.099999068 s` |
| TCP 生成命令 | `python3 config/large_traffic_gen.py --wan-rate 600G --wan-duration-ms 100 --wan-base-time 2.0 --wan-output w-tcp-600-100.txt --wan-only` |
| 拥塞控制 / 负载均衡 | DCQCN（`CC_MODE=1`）/ FECMP（`LB_MODE=0`） |
| WAN 拥塞控制 | GSCC（`WAN_CC_MODE=1`） |
| PFC / IRN | 开启 / 关闭 |
| buffer | `BUFFER_SIZE=9`，`DCI_BUFFER_SIZE=0`，`WAN_BUFFER_SIZE=0` |
| 监控间隔 | `SW_MONITORING_INTERVAL=10000 ns` |
| 配置流量窗口 | `FLOWGEN_START_TIME=2.0 s`，`FLOWGEN_STOP_TIME=2.05 s` |
| 随机种子 | `RANDOM_SEED=1` |

`FLOWGEN_STOP_TIME=2.05 s` 早于 RDMA/TCP 输入末尾时间。其保留目的是与 349/350 和 353/354/355 的配置口径一致，并不代表网络在 `2.05 s` 停止接受已调度的流。

## 3. 结束条件、登记与配置验收

三份配置均显式设置：

```text
WAIT_TCP_COMPLETION 0
```

所以仿真只要所有 RDMA 流完成就强制结束，不等待 TCP 全部完成。TCP 输入照常调度，已发生的 TCP 完成事件会写入 `config.log`；未在 RDMA 完成前结束的 TCP 流构成右删失样本。这个设计使 357/358 的 TCP 终止时间不同，不能直接将最终 TCP 完成量解释为单纯的 q1/q3 队列效果。

[`register.sh`](register.sh) 顺序申请 ID 并用 349/350 的配置模板规范化输出；[`launch_registered.sh`](launch_registered.sh) 为每组单独启动 detached 会话。[`verify_configs.sh`](verify_configs.sh) 在完成后再次执行并通过：两份输入 SHA256 正确；q1/q3 的 `TCP_QUEUE_INDEX` 分别为 `1`/`3`；357/358 都使用 `config/w-tcp-600-100.txt`；359 无 `TCP_FLOW_FILE`；去除 `FLOW_FILE`、输出目录、队列、TCP 文件、`WAIT_TCP_COMPLETION`、时间和 tag 等授权字段后，三份配置分别与相应 349/350 基线一致。

## 4. 实验 ID 与完成状态

| 实验组 | ID / 输出目录 | TCP 队列 | 最终模拟时间 | RDMA 完成 | TCP 完成 | 结束原因 |
|---|---|---:|---:|---:|---:|---|
| q1 隔离 | 357 / `mix/output/[357]-0815-1408-rdma150-180-tcp600-100-q1/` | 1 | 2.2480 s | 36,027/36,027 | 72,647/109,166 | RDMA completed |
| q3 共用 | 358 / `mix/output/[358]-0815-1415-rdma150-180-tcp600-100-q3/` | 3 | 2.2883 s | 36,027/36,027 | 73,161/109,166 | RDMA completed |
| 无 TCP | 359 / `mix/output/[359]-0815-1415-rdma150-180-tcp600-100-no-tcp/` | 不生效 | 2.2285 s | 36,027/36,027 | 0/0 | RDMA completed |

每份 `config.log` 都包含 `Simulator is enforced to be finished`、最终的 RDMA/TCP 完成计数和 PFC summary；每份 `flow_output` 都恰有 36,027 条 RDMA 完成记录。357/358 还具有 109,166 条 TCP 输入记录和完成日志，359 没有 TCP 输入。完成后的 `flow_output`、`tcp_flows.txt`、`config.log`、`cnp_trigger_prob_log`、`drop_log`、`buffer_monitor`、`link_utilization`、`wan_log` 等原始结果均存在。三份最终日志未发现 `fatal`、`assertion failed`、`segmentation fault`、`aborted` 或未捕获运行时异常。

## 5. 分析方法与口径

分析入口为 [`analyze.py`](analyze.py)，汇总结果为 [`summary.csv`](summary.csv)。在仓库根目录复现：

```bash
MPLCONFIGDIR=/tmp/rdma-wan-mpl \
  .venv/bin/python expr-0815-tcp-rdma-queue-coexist-150-180-600-100-3way/analyze.py
```

- RDMA FCT 为 `finish_time - start_time`；slowdown 为实际 FCT 除以该流记录的 `std_fct`。脚本通过 `analysis.deep_analyse.get_analyser(ID).get_fct()` 对所有组的平均和 P99 slowdown 做数值断言。
- TCP FCT 为完成事件时间减去 `input_start_time + 1 ns`。当前 TCP sender 以输入绝对时间安装，故不使用历史版本的 `2 x input_start_time` 补偿。
- TCP FCT 的平均数和分位数只针对日志中已经完成的流；未完成流不会进入分位数。TCP payload completion 使用完成事件对应的 application payload，不含协议头、ACK、CNP、PFC、重传或逐跳转发副本。
- `drop_log` 的一行称为“丢包日志记录”。`flow_id=4294967295` 没有 RDMA flow ID，不能直接归因为 TCP 丢包；因此报告不将日志行数换算为端到端 TCP/RDMA payload 丢失率。
- `link_utilization` 记录 RDMA/UDP 数据，不能当作 TCP+RDMA 的总 wire byte 或 TCP 吞吐。三组运行时长不等，CNP、PFC、buffer 和 link 的原始累计量只用于描述拥塞状态，不作为严格的跨组速率比较。

## 6. RDMA 总体 FCT 与 slowdown

| 指标 | 357，q1 隔离 | 358，q3 共用 | q3 相对 q1 | 359，无 TCP |
|---|---:|---:|---:|---:|
| 平均 FCT | 7.753 ms | 7.949 ms | +2.53% | 5.600 ms |
| P50 FCT | 1.095 ms | 1.046 ms | -4.49% | 1.071 ms |
| P95 FCT | 37.371 ms | 38.973 ms | +4.29% | 21.312 ms |
| P99 FCT | 106.497 ms | 116.458 ms | +9.35% | 73.705 ms |
| 最大 FCT | 209.234 ms | 234.910 ms | +12.27% | 189.412 ms |
| 平均 slowdown | 3.137 | 3.083 | -1.71% | 2.764 |
| P95 slowdown | 9.891 | 9.819 | -0.73% | 8.092 |
| P99 slowdown | 18.894 | 19.741 | +4.48% | 16.476 |
| 最大 slowdown | 79.183 | 53.726 | -32.15% | 82.479 |

q3 的 P50 FCT、平均/P95 slowdown 较低，但平均、P95、P99 和最大原始 FCT 都高于 q1，P99 slowdown 也增加。归一化平均改善不能覆盖原始尾延迟的劣化，因此不能把 q3 描述为 RDMA 的统一改善。

逐 flow 配对同一 36,027 个 RDMA ID 后，q3 有 18,113 条流更快、17,867 条更慢、47 条相同；配对 FCT 相对变化的中位数为 `-0.0055%`，接近零，而 P95 为 `+135.29%`、算术均值为 `+16.45%`。这进一步说明中心位置的小幅改善与少量显著变慢流并存，单个随机种子下不应只用平均 slowdown 下结论。

359 相对 q1 的平均/P99 原始 FCT 分别低约 `27.77%`/`30.79%`，平均/P99 slowdown 低约 `11.90%`/`12.80%`。TCP 共存确实是本负载下 RDMA 延迟的重要来源；不过 359 也在不同的 RDMA 完成时刻停止，拥塞累计日志不适合据此做严格差值分解。

## 7. RDMA intra/inter 分组

| 指标 | 357，q1 隔离 | 358，q3 共用 | q3 相对 q1 | 359，无 TCP |
|---|---:|---:|---:|---:|
| intra 平均 FCT（21,018 条） | 0.690 ms | 0.674 ms | -2.28% | 0.695 ms |
| intra P99 FCT | 11.134 ms | 10.819 ms | -2.83% | 10.998 ms |
| intra 平均 slowdown | 3.125 | 3.022 | -3.29% | 3.107 |
| intra P99 slowdown | 15.327 | 14.639 | -4.49% | 15.361 |
| inter 平均 FCT（15,009 条） | 17.644 ms | 18.136 ms | +2.79% | 12.470 ms |
| inter P99 FCT | 135.714 ms | 148.109 ms | +9.13% | 107.970 ms |
| inter 平均 slowdown | 3.155 | 3.170 | +0.48% | 2.284 |
| inter P99 slowdown | 20.974 | 22.356 | +6.59% | 17.749 |

q3 对 intra 的平均和尾部指标均有改善，但 inter 的平均/P99 FCT 和 slowdown 都恶化。总体平均 slowdown 的下降主要由 intra 组贡献，不能代表跨 DC RDMA 体验改善。相比含 TCP 两组，359 的 inter FCT 明显更低，而 intra 平均 FCT 基本不变，符合 TCP 竞争主要作用于跨 DC 路径的预期。

`std_fct` 是随实际路径记录的逐流归一化基线，FECMP 可使同一输入 flow 在不同实验中走不同路径。因此原始 FCT 和 slowdown 的变化比例不必一致；本报告并列二者，避免只报告对 q3 有利的归一化指标。

## 8. TCP FCT、完成覆盖与右删失

| 指标 | 357，q1 隔离 | 358，q3 共用 | q3 相对 q1（最终值） |
|---|---:|---:|---:|
| 已完成流 | 72,647/109,166（66.547%） | 73,161/109,166（67.018%） | +514 条，+0.471 个百分点 |
| 未完成流 | 36,519 | 36,005 | -514 条 |
| 已完成 payload | 16.950 GB / 187.709 GB（9.030%） | 23.400 GB / 187.709 GB（12.466%） | +6.450 GB，+3.436 个百分点 |
| 已完成流平均 FCT | 56.852 ms | 60.130 ms | +5.77% |
| P50 FCT | 40.950 ms | 38.661 ms | -5.59% |
| P95 FCT | 155.845 ms | 199.067 ms | +27.73% |
| P99 FCT | 205.671 ms | 245.463 ms | +19.35% |
| 最大 FCT | 246.845 ms | 285.652 ms | +15.72% |

最终值不能脱离终止时刻解释：358 在 `2.2883 s` 才因 RDMA 完成结束，比 357 的 `2.2480 s` 多 `40.3 ms`。将 358 的完成事件截到 357 的结束时刻后，q3 只有 69,241 条完成流（63.427%），比 q1 少 3,406 条；但完成 payload 为 17.388 GB（9.263%），比 q1 多 0.438 GB。之后的额外 40.3 ms 中，q3 又完成 3,920 条流和 6.012 GB payload，才形成表中的最终完成量优势。

两组最终完成集合相交 63,348 条，q1 独有 9,299 条、q3 独有 9,813 条。FCT 分位数既受不同完成集合影响，也受 q3 更长观测窗口影响；未完成的大量流还造成严重右删失。故本节只能报告观测到的完成子集，不能据此宣称 q3 具有更好的全样本 TCP FCT、完成率或吞吐。公平比较需要统一、足够长的结束时间，或等待两组 TCP 都完成后再计算。

## 9. 拥塞、丢包日志与 buffer

| 指标 | 357，q1 隔离 | 358，q3 共用 | q3 相对 q1 | 359，无 TCP |
|---|---:|---:|---:|---:|
| `drop_log` 记录数 | 904,979 | 1,049,806 | +16.00% | 210,911 |
| 有 RDMA flow ID 的记录 | 593,545 | 565,241 | -4.77% | 207,013 |
| 无 RDMA flow ID 的记录 | 311,434 | 484,565 | +55.59% | 3,898 |
| CNP 触发数 | 3,801,960 | 3,585,682 | -5.69% | 2,410,227 |
| CNP 触发率 | 11.526% | 11.749% | +0.224 个百分点 | 8.703% |
| PFC pause triggers | 4,191,785 | 3,722,645 | -11.19% | 4,145,644 |
| 全量 ingress 峰值 | 248.876 MB | 235.017 MB | -5.57% | 237.055 MB |
| 全量 egress 非零样本 P99 | 310.904 MB | 203.089 MB | -34.68% | 329.731 MB |
| DCI ingress 峰值 | 77.616 MB | 94.530 MB | +21.79% | 167.772 MB |
| DCI egress 峰值 | 47.999 MB | 48.441 MB | +0.92% | 144.146 MB |
| WAN egress 峰值 | 335.338 MB | 335.338 MB | 约 0% | 335.338 MB |
| WAN egress 非零样本 P99 | 332.101 MB | 214.039 MB | -35.55% | 335.337 MB |

q3 的 CNP 总触发数、PFC pause 次数和全量 egress P99 更低，且 WAN egress 的 P99 降幅较大；但它的总丢包日志记录增加 16.00%，无 RDMA flow ID 的记录增加 55.59%，DCI ingress 峰值增加 21.79%。这表明共用队列改变了拥塞位置和日志中 flow ID 的可见性，并未证明 TCP 丢包减少或整体网络更稳定。

三组的 WAN egress 峰值几乎相同，均接近 335 MB；同时运行时长不同，尤其 q3 多运行 40.3 ms。因此原始 CNP/PFC/丢包累计数与 buffer 极值只能作为辅助证据，不能与 RDMA FCT 建立未经验证的因果链。

RDMA `link_utilization` 聚合字节为 q1 114.706 GB、q3 105.454 GB、无 TCP 96.156 GB；每个时间戳的聚合峰值为 511.801/468.126/488.607 MB。该日志不含 TCP 数据，且采样总时长不同，故不用于评价 TCP 总吞吐或跨组的有效 payload 吞吐。

## 10. 结论与下一步

1. 357/358/359 都完成了全部 RDMA 流，输出与配置验收通过。600G/100ms TCP 输入下，RDMA-only 组相对含 TCP 组的跨 DC FCT 明显更低，确认 TCP 共存是主要干扰源。
2. q3 没有给出统一的 RDMA 改善。它降低平均 slowdown `1.71%`，并改善 intra 指标；但原始平均/P99 FCT 增加 `2.53%`/`9.35%`，inter 平均/P99 slowdown 也增加 `0.48%`/`6.59%`。对延迟敏感的跨 DC RDMA，当前证据更应关注原始尾 FCT 的劣化。
3. q3 的 TCP 最终完成量略高，但其运行时间也多 40.3 ms。截到相同的 q1 终止时刻后，q3 完成 flow 数较少而 payload 较多，表现并不单向；已完成子集的 TCP P95/P99 FCT 又更高。大量 TCP 流在 RDMA 完成时仍未结束，不能宣称 q3 的全样本 TCP 表现更好。
4. q3 的全局 queue P99、CNP 总量和 PFC 次数下降，但总丢包日志上升，且 DCI ingress 峰值更高。指标共同指向“拥塞重新分布”，而非已证明的端到端收益。
5. 后续比较应取消 RDMA-only 的提前终止影响：使用相同且足够长的固定 deadline，或令 `WAIT_TCP_COMPLETION=1` 并保证两组都达到相同 TCP 完成条件。报告应同时给出全样本 FCT、明确 timeout/右删失率、payload completion 及按时间归一化的拥塞指标；至少用多个随机种子重复后，再判断 q1/q3 的差异是否稳定。
