# 实验迭代索引

| 实验 | 目的 | 内容 | 结论 | 索引 |
|---|---|---|---|---|
| `expr-0810-tcp-rdma-queue-coexist`（335/336） | 比较 TCP q1 与 TCP/RDMA 共用 q3 的共存效果 | 在 `cernet_topo`、相同 RDMA/TCP 负载和固定随机种子下，统计 RDMA/TCP FCT、slowdown、CNP、buffer、链路和丢包 | 336 共用 q3 的 RDMA 平均 FCT/slowdown 较低约 2.11%/4.41%，TCP 已完成流平均 FCT 略高 0.22%；两组均有 8 条 TCP 流未完成，不能据此推广为普遍优劣 | [`expr-0810-tcp-rdma-queue-coexist/report.md`](../expr-0810-tcp-rdma-queue-coexist/report.md) |
| `expr-0810-tcp-rdma-queue-coexist`（337/338） | 在较高 `w-dynamic-150-200` 负载下复比较 TCP q1 隔离与 q3 共用 | 使用 `w-dynamic-150-200` + `w-tcp-300`，统计 38,156 条 RDMA 和 10,989 条 TCP 的 FCT、slowdown、丢包、CNP、buffer 与链路 | 338 共用 q3 的 RDMA 平均 FCT/slowdown 较低 9.28%/12.63%，ingress 丢包减少 34.76%；两组各有 9 条 TCP 流未完成，且 DCI egress 峰值增加 90.96%，结论限定于单次固定种子 | [`expr-0810-tcp-rdma-queue-coexist/report.md`](../expr-0810-tcp-rdma-queue-coexist/report.md#11-第二轮实验w-dynamic-150-200337338) |
| `expr-0810-tcp-rdma-queue-coexist-75-90-200`（339/340） | 在无丢包的 `w-dynamic-75-90-200` 负载下比较 TCP q1 隔离与 q3 共用，并审计 TCP 启动/FCT | 使用 53,879 条 RDMA 和 10,989 条 TCP，统计 RDMA/TCP FCT、slowdown、CNP、buffer 与链路；逐流还原 TCP 实际 sender start | 发现动态安装应用时存在相对/绝对时间混用：输入时间约 1.0 s，sender 实际约 2.0 s 启动，旧 TCP FCT 均值虚高约 1.010 s；修正后 339/340 平均 FCT 为 132.764/133.293 ms。340 的平均 RDMA FCT低 0.17%，但平均/P99 slowdown 高 1.38%/5.56%；两组各有 8 条 TCP 流未完成 | [`expr-0810-tcp-rdma-queue-coexist-75-90-200/report.md`](../expr-0810-tcp-rdma-queue-coexist-75-90-200/report.md#60-重要更正原报告的-tcp-fct-统计包含了调度-bug-引入的约-1-s) |
| `expr-0813-tcp-rdma-queue-coexist-300-500`（341/342，运行中） | 在源 q1/q3 队列对比中延长 TCP 输入窗口至 500 ms | 保持 `cernet_topo + w-dynamic-75-90` 及其他参数不变，仅将 TCP 文件替换为 `w-tcp-300-500`，分别启动 q1 隔离与 q3 共用组 | 待仿真完成后统计；两组已在独立 detached 会话正常运行，`config.txt` 已核对目标文件与 q1/q3 设置，首个 TCP 完成事件为 `1.90273 s` | [`expr-0813-tcp-rdma-queue-coexist-300-500/report.md`](../expr-0813-tcp-rdma-queue-coexist-300-500/report.md) |
| `expr-0810-tcp-rdma-queue-coexist-75-90-200`（343/344，已完成） | 在修正 TCP 启动逻辑后的 q1 隔离与 q3 共用对比 | 使用 `cernet_topo + w-dynamic-75-90-200 + w-tcp-300`、DCQCN、FECMP、PFC 和固定种子；343/344 间仅变更 TCP 队列，TCP 输入时间及启动代码与 339/340 历史版本不同 | 两组 RDMA 均完成，TCP 完成 `10983/10989` 与 `10982/10989`；q3 组平均 RDMA/TCP FCT 仅高 0.02%/0.20%，但 RDMA P99 slowdown 高 6.83%。应用层 offered payload 为 TCP 18.951 GB（17.1120%）与 RDMA 91.797 GB（82.8880%） | [`expr-0810-tcp-rdma-queue-coexist-75-90-200/report.md`](../expr-0810-tcp-rdma-queue-coexist-75-90-200/report.md#11-复跑-0813344) |
| `expr-0813-tcp-rdma-queue-coexist-300-200`（345/346，运行中） | 比较 200 ms、名义 300 Gbps WAN TCP 下的 q1 隔离与 q3 共用 | 使用 `w-dynamic-75-90-200 + w-tcp-300-200`；TCP 输入位于 `2.0–2.2 s`，两组仅变更 TCP 队列 | 已在独立 SID 启动 345（q1）和 346（q3），均已读入 109,704 条 TCP flow 并进入仿真。TCP payload 为 187.611 GB；沿用 `FLOWGEN_STOP_TIME=2.05 s`，监控与输入窗口不完全重合 | [`expr-0813-tcp-rdma-queue-coexist-300-200/report.md`](../expr-0813-tcp-rdma-queue-coexist-300-200/report.md) |
| `expr-0814-tcp-rdma-queue-coexist-300-100`（349/350，已完成） | 比较 100 ms、名义 300 Gbps WAN TCP 下的 q1 隔离与 q3 共用，并解释 RDMA FCT 未显著恶化的机制 | 使用 20,020 条 `w-dynamic-75-90` RDMA 和 54,953 条、93.600 GB 的 `w-tcp-300-100`；补充逐 flow 配对、大小/启动时间分组、CNP 时间窗及 host/switch 调度和 DCQCN/GSCC 审计 | q1 仍与 RDMA 共享 NIC、egress port 和链路，并非无竞争基线；两组无已记录丢包，q3 的 GSCC CNP 主输入期触发率只高 `0.0537` 个百分点。全部流中 q3 变慢占 `49.30%`，代价集中在 `>=5 MB`（`+0.56%`）和最后 25 ms 启动流（`+1.08%`），被其他流抵消，故总体平均 FCT反而低 `1.39%`；结论限定于单拓扑、单种子、单次运行 | [`expr-0814-tcp-rdma-queue-coexist-300-100/report.md`](../expr-0814-tcp-rdma-queue-coexist-300-100/report.md) |
| `expr-0814-tcp-rdma-queue-coexist-300-100-rerun`（351/352，运行中） | 使用同一输入和设置完整复现 349/350 的 q1 隔离与 q3 共用实验 | 复用 `w-dynamic-75-90 + w-tcp-300-100`；校正当前 runner 默认值漂移后，排除输出路径、时间和 tag，351/352 配置分别与 349/350 逐行一致 | 两组已在沙箱外独立 SID 启动，PID 为 1250004/1250006，日志推进到约 2.005 s 且无真实错误；本次不做结果分析 | [`expr-0814-tcp-rdma-queue-coexist-300-100-rerun/report.md`](../expr-0814-tcp-rdma-queue-coexist-300-100-rerun/report.md) |
| `expr-0815-tcp-rdma-queue-coexist-150-180-3way`（353/354/355，已完成） | 在更高 RDMA 输入下比较 TCP q1、TCP q3 和无 TCP 三组 | 保留 349/350 的其余配置，RDMA 改为 36,027 条 `w-dynamic-150-180`，TCP 组使用 54,953 条 `w-tcp-300-100`；355 不配置 TCP 输入 | 三组 RDMA 均完成；q3 相对 q1 的 RDMA 平均/P99 slowdown 低 1.77%/6.46%，但 TCP 少完成 718 条、payload completion 低 0.911 个百分点。TCP FCT 仅为右删失的已完成子集，不能据此宣称 q3 整体更优 | [`expr-0815-tcp-rdma-queue-coexist-150-180-3way/report.md`](../expr-0815-tcp-rdma-queue-coexist-150-180-3way/report.md) |
| `expr-0815-tcp-rdma-queue-coexist-150-180-600-100-3way`（357/358/359，运行中） | 将三组实验的 TCP 输入提高至名义 600G、100ms，并采用 RDMA-only 完成终止 | RDMA 固定为 36,027 条 `w-dynamic-150-180`；q1/q3 使用新生成的 109,166 条 `w-tcp-600-100`，无 TCP 组不设置 TCP 输入；三组显式 `WAIT_TCP_COMPLETION=0` | 三组已在沙箱外独立 SID 正常启动，PID 为 1831281/1831311/1831335，日志持续推进且无启动期异常；本次只启动，不分析结果 | [`expr-0815-tcp-rdma-queue-coexist-150-180-600-100-3way/report.md`](../expr-0815-tcp-rdma-queue-coexist-150-180-600-100-3way/report.md) |
| `expr-0815-tcp-periodic-completion-smoke`（356，已完成） | 验证 TCP 完成事件改为 1 ms 周期批量输出 | 使用 1 条 RDMA 和 6 条小 TCP flow，检查批次边界、唯一性、真实完成时刻及旧正则兼容性 | 6 条 TCP flow 在 2.000112538–2.000393689 s 完成，到 2.001 s 才作为单个批次输出；记录无重复、无遗漏，且旧 FCT 正则可解析全部真实完成时刻 | [`expr-0815-tcp-periodic-completion-smoke/report.md`](../expr-0815-tcp-periodic-completion-smoke/report.md) |
| `expr-p4-sort`（2026-11-12，未放行） | 验证 P4 驻留探针偏移、ACK/AckReq 数量、窗口失配与背景隔离的正确性 | 修正 PSN 位宽、SALU 持久状态、范围键、控制预算、累计统计、真实 QPN CNP 映射；执行 Tofino2 有限实机诊断及物理计数核对 | 七档加PSN回绕共8条实机及离线审计通过；用户因时间有限选择提前交付，专用诊断未完成；IPv6原样保留，完整矩阵未启动 | [`expr-p4-sort/report.md`](../expr-p4-sort/report.md)；[隔离记录](../expr-p4-sort/NETWORK_ISOLATION.md) |
| `expr-p4-sort`（2026-11-12，定时限速变更） | 缩短低速固定 n 矩阵耗时 | 限速改为真实 5 秒、内窗 3 秒带宽，独立 NIC 全程 Write 核对；保留 13 个不限速成功点、生成剩余 225 点续跑清单 | 18 项本地检查、2 条实机及离线复算、在线预检通过；旧失败保留，完整矩阵待用户在 tmux 续跑 | [`expr-p4-sort/report.md`](../expr-p4-sort/report.md)；[续跑说明](../expr-p4-sort/HANDOFF.md) |
| `expr-p4-sort`（2026-11-12，矩阵完成整理） | 汇总固定时长限速与不限速实机数据 | 对225条续跑与13条保留记录逐条复算、核对CSV/源码哈希及238条件覆盖，导出Excel/CSV/直方图和图表 | 233有效、5失败、0缺失/重复；4条BFRT未放流、1条CNP处理差1；续跑3.66小时，单次试验不作显著性结论 | [`实机结果报告`](../expr-p4-sort/results/completed-duration-20261112/report.md) |
| `expr-p4-sort`（2026-11-12，失败点补跑） | 补齐原矩阵 5 个失败条件，核对 PPT 的 ACK 匹配结论 | Tofino2 顺序补跑；保留 CNP 与原审计；按零偏移桶重算精确率，与窗口接受率分列 | 5/5 补跑通过，矩阵 238/238 有效；原 CNP 失败点补跑生成和处理均为 612,962；40 万 Writes/QP 时只有 24/49 条精确率超过 80% | [补跑报告](../expr-p4-sort/results/completed-duration-20261112-rerun/report.md) |


## 2026-11-15：P4 identifier 实机对比，资格短测完成，矩阵准备中

- 目标：区分原 PSN 匹配中的身份错误、槽位保护更新和按连接分桶的影响，重画热力图。
- 已做：保留旧代码和历史结果，在独立 expr-p4-identifier 目录增加同报文测量器；SDE 编译通过；1/64 QP、1000 Write/QP 实机短测计数审计通过；ASIC 包发生器验证共享槽不同身份拒绝、保留未超时项、重传刷新和超时替换。
- 当前结果：1 QP 精确匹配 1055/1063；64 QP 66020/68157，同 QP 核验后相等；共享桶保护更新 66030/68157，QP 分桶 68157/68157。仅单次短测，无长实验结论。
- 下一步：完成其余配置硬件资格检查，执行 98 条件 × 3 次重复并离线审计。报告：docs/experiments/1115-p4-identifier/report.md。

## 2026-11-15：论文式 PSN 哈希选槽主批次运行中

- 核对 Algorithm 1 后，把论文采样器选槽从 PSN 低位改为 CRC32(PSN) mod S。原 PSN 路径和共享桶保护路径保持原选槽，新增路径仍只计数。
- 原低位补充批次在两条试验之间停止，封存 49 条有效记录及 3 次失败尝试。主批次为 `expr-p4-identifier-seqhash`，不混合两批。
- 七档编译、实机短测、64 QP×40 万次长测和 ASIC 状态机诊断均通过。主批次正在 112 的 tmux 执行 98 条件×3 次；未解释背景流量会被拒绝并重试。
- 离线分析补充：精确命中所属 QP、未命中时槽位所属 QP、同记录窗口阈值、原始 ACK/AckReq 整数和双端核对的起始 PSN。每次归档脚本、资格构建和环境身份均复核。
- 下一步：等待全 294 条有效结果，审计 98 格各 n=3 后生成最终热力图和结论。详见 [`报告`](experiments/1115-p4-identifier/report.md)。

## 2026-11-15：identifier 主批次完成，294/294 有效

- 完成真实 Tofino2 上 98 条件×3 次独立冷启动；303 次尝试中 9 次无效并保留，全部补跑通过，无缺失。主批耗时 6.52 小时，全量离线复算、来源摘要与环境核对通过。
- W0、64 QP、每 QP 40 万 Write：原版/共桶保护/论文式采样的三次中位数，S16 为 29.27%/44.78%/77.11%，S32 为 32.84%/51.77%/91.79%，S64 为 42.57%/62.39%/99.82%，S128 为 76.49%/82.63%/99.93%。
- 总计 1,251,441,743 个 ACK 中，18 个原 PSN 相等匹配属于不同 QP。低命中主要表现为槽里已是另一个 PSN；单 QP 也观测到大量偏移 −64。ACK 总数接近 AckReq，不能将失配比例解释为 ACK 聚合率。
- 新路径是论文身份与保护更新机制的 RoCE 适配，按 QP 分桶及 CRC32(PSN) 选槽，并行观察原反馈产生的同一批报文；不等于完整 RTT 控制器或 WAN 性能验证。
- 最终报告、三张中文主图和逐次计数保存于 [`1115-p4-identifier`](experiments/1115-p4-identifier/report.md)。PNG/SVG/PDF 已生成，已检查中文图版面、300 dpi 和 PDF 字体嵌入。

## 2026-11-15：GRC 论文采样独立反馈闭环

- 在独立 `expr-p4-paper-loop` 实现 AckReq/ACK 身份匹配、纳秒 RTT、重传过滤、算法 2 速率更新和算法 3 CNP；去掉旧 PSN 窗口反馈路径，不修改旧实验。
- Tofino2 实机定向包和两次真实 RNIC 短测通过。64 QP、5 秒配置下，946,742 个 RTT 样本全部被控制面消费；CNP 生成与网卡处理各 27,088 个。两次离线重算通过；未启动大矩阵。详见 [验收报告](experiments/1115-p4-paper-loop/report.md)。

## 2026-11-15：独立闭环热力图复测准备

- 用已经接管 RTT 和 CNP 反馈的新版替换旧旁路热力图。沿用旧图的 256 个桶、1–64 QP 和每 QP 4 万 / 40 万次 Write；只跑 S16、S32、S64，去掉 W 行。42 格各三轮，共 126 次。
- 三档独立编译物核对了采样表大小及旧窗口表缺失；每档各一个真实 ASIC/RNIC 点均通过短测和离线复算，编排机预检通过。正式批次交由用户在实验室 tmux 启动，完成后从原始记录离线审计和出图。见 [本轮方案](experiments/1115-p4-paper-heatmap/report.md)。

## 2026-11-15：独立闭环热力图完成，126/126 有效

- 正式批次覆盖 42 个条件，每格冷启动三次。128 次尝试有 2 次计数核验失败，均已补跑，126 次通过本地离线复算。
- 64 QP、每 QP 40 万 Write 时，16/32/64 槽的 ACK identifier 命中率中位数为 71.80% / 90.56% / 99.87%；4 万 Write 时，32 槽各档位中位数已达 99.94% 或以上。
- 后续组会/论文配图使用新版独立闭环图。旧旁路数据保留作历史比较，不混算。见[正式结果](experiments/1115-p4-paper-heatmap/report.md#正式结果2026-11-15)。
