# UnoCC ns-3 Migration Implementation Report

本文档记录当前工作树中 UnoCC 迁移实现的范围、依据、参数设置、与 Uno 论文及 Uno_SC25 开源实现的对应关系，以及因本 ns-3 RDMA 模拟器结构造成的近似。

## 依据来源

- 论文 PDF：`/home/micraow/Documents/本科/科研/3712285.3759884.pdf`
  - 主要依据：Section 4.1 UnoCC、Algorithm 1、Section 4.1.1 AIMD、Section 4.1.2 Quick Adapt、Section 4.1.3 Phantom Queues、Table 2、evaluation parameter settings 段。
- Uno_SC25 开源实现：`/home/micraow/research/Uno_SC25`
  - `sim/lcp.cpp`
  - `sim/lcp.h`
  - `sim/common.cpp`
  - `sim/compositequeue.cpp`
  - `sim/datacenter/main_lcp_entry_modern.cpp`
- ns-3 迁移目标仓库：`/home/micraow/research/RDMA-WAN-Optimization/ns-allinone-3.19/ns-3.19`

## 实现概要

本次迁移把 UnoCC 分成三部分接入现有 ns-3 RDMA 框架：

1. Sender-side UnoCC 控制环：放在 `RdmaHw` 和 `RdmaQueuePair`。
2. Receiver ACK ECN 反馈：复用 ACK header 中已有字段，让 sender 能估算 epoch ECN fraction。
3. Switch-side phantom queue ECN marking：放在 `SwitchMmu`，并从 `scratch/remote.cc` 配置默认参数。

当前实现覆盖了论文 Algorithm 1 的主要路径：

- ACK 未 ECN marked 时 additive increase。
- 每个 epoch 根据 ECN fraction 做 multiplicative decrease。
- 用 RTT - RTTbase 判断 phantom-only 和 physical queue congestion，并对 phantom-only 使用 gentle reduction。
- 每个 QA period 检查 ACKed bytes，低于 `cwnd * beta` 时快速收缩 cwnd。
- phantom queue 在交换机 egress admission 时增加 occupancy，并按低于物理链路的 drain rate 懒更新。

## 修改文件清单

### `src/point-to-point/model/rdma-queue-pair.h`

实现内容：

- 新增 `CC_MODE_UNOCC = 9`，使 UnoCC 成为独立 CC mode。
- 新增 per-QP `uno` 状态块，保存：
  - `m_cwndBytes`
  - epoch ACKed bytes / ECN marked bytes
  - QA ACKed bytes
  - base RTT / last RTT
  - epoch / QA start time
  - epoch end packet timestamp boundary
  - QA cooldown
  - ECN fraction EWMA
  - epoch ECN 标志和 RTT sample 状态

对应依据：

- 论文 Algorithm 1 需要维护 `cwnd`、`ecn_fraction`、QA period 内 ACKed bytes。
- 论文 Section 4.1 需要 `RTTbase` 和 measured RTT。
- Uno_SC25 `LcpSrc` 中维护 `_cwnd`、`ecn_marked_bytes_in_epoch`、`total_new_bytes_acked_in_epoch`、`bytes_acked_in_qa_period` 等同类状态。

### `src/point-to-point/model/rdma-queue-pair.cc`

实现内容：

- 在 `RdmaQueuePair` 构造函数中初始化 UnoCC 状态，避免新 QP 进入未定义状态。

### `src/point-to-point/model/rdma-hw.h`

实现内容：

- 新增 UnoCC 参数成员：
  - `m_uno_ai_factor`
  - `m_uno_beta`
  - `m_uno_ewma_gain`
  - `m_uno_k`
  - `m_uno_gentle_scale`
  - `m_uno_delay_threshold`
  - `m_uno_intra_rtt_ns`
  - `m_uno_epoch_rtt_factor`
- 新增 UnoCC helper：
  - `InitUno`
  - `HandleAckUno`
  - `HandleCnpUno`
  - `HandleTimeoutUno`
  - `GetAckRttNsUno`
  - `GetAckTxTimestampNsUno`
  - `GetUnoEpochPeriodNs`
  - `UnoAdditiveIncrease`
  - `UnoEpochEnded`
  - `UnoProcessEpochEnd`
  - `UnoAdvanceEpoch`
  - `UnoProcessQaEnd`
  - `UnoCwndToRate`
  - `UnoApplyRateFromCwnd`

### `src/point-to-point/model/rdma-hw.cc`

实现内容：

- 在 `GetTypeId()` 中注册 UnoCC attributes，支持仿真配置覆盖默认值。
- 在 `AddQueuePair()` 中，当 `m_cc_mode == CC_MODE_UNOCC` 时调用 `InitUno()`。
- 在 ACK 处理路径中接入 `HandleAckUno()`。
- epoch 结束条件改为优先依据 ACK 回传的数据包发送时间戳，而不是单纯 wall-clock。
- 在 CNP 和 timeout 路径中接入 UnoCC 的保守反应。
- 在 receiver ACK 生成路径中为 UnoCC 增强 ECN 反馈：
  - 非 UnoCC 保持原来的 10us CNP throttle。
  - UnoCC 不使用该 throttle，因为论文需要按 ACK/epoch 统计 ECN marked packet fraction。
  - ACK 中通过 `irnNack`/`irnNackSize` 携带本 ACK interval 内的 ECN marked packet 数和 total packet 数。
  - sender 端按 `bytesAcked * markedPackets / totalPackets` 估算 epoch 内 ECN marked bytes。

关键公式：

- 初始 cwnd：
  - `cwnd = max(MTU, BDP)`
  - 对应 Uno_SC25 `STARTING_CWND_BDP_RATIO = 1.0`。
- AI：
  - `alphaBytes = BDP * UnoAiFactor` when `UnoAiFactor <= 1`
  - `cwnd += alphaBytes * bytesAcked / cwnd`
  - 对应论文 Algorithm 1 / Section 4.1.1。
- epoch MD：
  - `ecnFraction = epochEcnMarkedBytes / epochAckedBytes`
  - `E = EWMA(ecnFraction)`
  - `K = UnoK > 0 ? UnoK : intraBdp / 7`
  - `mdGain = 4K / (K + BDP)`
  - `mdScale = 1.0` if physical delay exists, otherwise `UnoGentleScale`
  - `cwnd *= 1 - E * mdGain * mdScale`
- QA：
  - if `qaAckedBytes < cwnd * beta`, then `cwnd = max(MTU, qaAckedBytes)`
  - after QA trigger, skip one epoch period for QA/MD.
- cwnd 到 ns-3 rate：
  - `rate = cwnd * 8 / RTT`
  - clamp 到 `[m_minRate, qp->m_max_rate]`

### `src/network/utils/custom-header.cc`

实现内容：

- 修正 `CustomHeader::GetAckSerializedSize()`，把 ACK/NACK 实际序列化和反序列化已经读写的 `irnNack`、`irnNackSize` 纳入长度计算。
- 这对 UnoCC ECN 反馈是必要的，因为当前实现复用这两个字段携带 ECN marked/total packet 计数。

### `src/point-to-point/model/switch-mmu.h`

实现内容：

- 新增 phantom queue 配置、状态和方法声明：
  - enable flag
  - physical queue 是否参与 marking
  - phantom occupancy
  - last drain update time
  - phantom queue size
  - phantom kmin/kmax/pmax
  - slowdown percentage
  - line rate

### `src/point-to-point/model/switch-mmu.cc`

实现内容：

- 初始化 Uno phantom queue 默认参数。
- 在 `UpdateEgressAdmission()` 中调用 `AddUnoPhantomBytes()`，即包进入物理 egress queue 时同步增加 phantom occupancy。
- 将原 `ShouldSendCN()` 拆为：
  - `ShouldSendCNRed()`：原物理队列 RED/ECN marking。
  - `ShouldSendCNUno()`：phantom queue RED/ECN marking，可选叠加物理队列 marking。
- phantom drain 使用 lazy update：
  - 每次查询或增加 phantom occupancy 时，根据 `now - lastUpdate` 扣减：
    - `drainedBytes = elapsed * lineRate * (1 - slowdownPct / 100) / 8`
  - 默认 `slowdownPct = 10`，即 drain rate 为 90% line rate。

对应依据：

- 论文 Section 4.1.3：phantom queue occupancy 随物理入队增加，以低于物理队列的速率 drain。
- Uno_SC25 `CompositeQueue`：
  - `_phantom_queue_slowdown = 10`
  - `_phantom_kmin/_phantom_kmax`
  - `decide_ECN()` 基于 phantom occupancy 做线性概率 marking。
  - data packet receive 时增加 phantom queue occupancy。

### `scratch/remote.cc`

实现内容：

- 增加 UnoCC 配置入口：
  - `UNO_AI_FACTOR`
  - `UNO_BETA`
  - `UNO_EWMA_GAIN`
  - `UNO_K`
  - `UNO_GENTLE_SCALE`
  - `UNO_DELAY_THRESHOLD`
  - `UNO_INTRA_RTT_NS`
  - `UNO_INTRA_RTT_US`
  - `UNO_INTER_RTT_NS`
  - `UNO_INTER_RTT_US`
  - `UNO_EPOCH_RTT_FACTOR`
  - `UNO_PHANTOM_ENABLED`
  - `UNO_PHANTOM_SIZE_KB`
  - `UNO_PHANTOM_KMIN_PCT`
  - `UNO_PHANTOM_KMAX_PCT`
  - `UNO_PHANTOM_PMAX`
  - `UNO_PHANTOM_SLOWDOWN_PCT`
  - `UNO_PHANTOM_USE_PHYSICAL`
- 当 `cc_mode == CC_MODE_UNOCC` 时，设置 `IntHeader::mode = 1`，复用 TIMELY timestamp RTT 通路。
- 对 DC switch、DCI switch、WAN switch 调用 `ConfigUnoPhantom()`。
- 对每个 host `RdmaHw` 设置 UnoCC attributes。

### `src/point-to-point/model/route-logger.cc`

当前工作树中有一处 `#include <cstdint>` 改动。该改动不属于 UnoCC 迁移逻辑；它是用户已有无关改动，本次没有回退。

## 参数对照

| 参数 | 论文依据 | Uno_SC25 依据 | 当前 ns-3 默认 | 说明 |
|---|---|---|---|---|
| `alpha` | Table 2: `0.001 * BDP`; Section 4.1.1 说明 alpha 是 BDP fraction | `lcp.cpp` 中 `ai_bytes = _bdp * 0.001` | `UNO_AI_FACTOR = 0.001` | `UnoAiFactor <= 1` 时按 BDP fraction 解释。 |
| `beta` | Table 2: `0.5`; QA 段说明阈值为 `cwnd * beta` | `common.cpp`: `QA_CWND_RATIO_THRESHOLD = 0.5` | `UNO_BETA = 0.5` | 对齐论文和开源。 |
| `K` | Table 2: `1/7 * intra-DC BDP` | `lcp.cpp` 默认 `lcp_k = _bdp / 7`，其中 `_bdp` 是 flow-specific BDP | `UNO_K = -1` 自动派生 `intraBdp / 7` | 这里优先匹配论文表格；开源默认对 inter flow 会用 inter BDP。可通过 `UNO_K` 覆盖。 |
| `Intra-DC RTT` | Table 2: `14us` | main 程序将 base intra RTT 传给 LCP | `UNO_INTRA_RTT_NS = 14000` | 用于默认 K 派生和 epoch period。 |
| `Inter-DC RTT` | Table 2: `2ms` | 论文脚本中的 inter-DC 场景也围绕该量级配置 | `UNO_INTER_RTT_NS = 2000000` | 这里只用于 phantom size 自动派生的 fallback；真实流 RTT 仍由 topology/link delay 决定。 |
| `epoch_period` | 论文说明 inter/intra 使用相同 epoch period，基于 intra-DC RTT | Uno_SC25 有 timestamp/ratio 相关逻辑 | `UNO_EPOCH_RTT_FACTOR = 1`，period = `14us` | 当前实现固定用 intra RTT，符合论文“same epoch period based on intra-DC RTT”。 |
| `phantom drain rate` | Table 2: `0.9 * physical queue drain rate`; Section 4.1.3 同义说明 | `CompositeQueue::_phantom_queue_slowdown = 10` | `UNO_PHANTOM_SLOWDOWN_PCT = 10` | drain rate = `1 - 10% = 0.9` line rate。 |
| phantom 是否叠加 physical ECN | 论文正文未强制要求两者串联 | `paper_script` / `artifact_scripts` 中 Uno 使用 `-use_phantom 1`，但未传 `-phantom_both_queues` | `UNO_PHANTOM_USE_PHYSICAL = false` | 当前默认按开源脚本走 phantom-only marking；物理 `25/75` 仍单独保留。 |
| `gentle scale` | Algorithm 1: phantom-only 时 scale 乘 `0.3` | Uno_SC25 `aimd_phantom` 里使用 `0.35` | `UNO_GENTLE_SCALE = 0.3` | 这里优先匹配论文算法。 |
| ECN EWMA gain | 论文只说 E 是 ECN fraction EWMA，没有给默认值 | `common.cpp`: `LCP_ECN_ALPHA = 1.0`；但 `paper_script` / `artifact_scripts` 大量使用 `-ecnAlpha 0.65` | `UNO_EWMA_GAIN = 0.65` | 当前默认优先贴近论文图脚本，而不是 Uno_SC25 源码中的全局默认。 |
| delay threshold | 论文算法写 `delay == 0` 区分 phantom-only | Uno_SC25 用 `rtt > _base_rtt * 1.055` 判定 physical queue delay | `UNO_DELAY_THRESHOLD = 0.05` | 近似开源 1.05/1.055 逻辑，避免 ns-3 timestamp 抖动导致严格等于 0 不稳定。 |
| 物理 ECN Min/Max threshold | 论文 parameter settings: 25% / 75% queue capacity | Uno_SC25 多数非-phantom ECN 场景也用 `kmin 25 / kmax 75` | 由原有物理 ECN 配置控制 | 这是物理队列 RED 阈值，不是 phantom queue 阈值。 |
| phantom ECN Min/Max threshold | 论文正文未单列默认值 | `paper_script` / `artifact_scripts` 中 Uno 常用 `-phantom_kmin 2 -phantom_kmax 60` | `UNO_PHANTOM_KMIN_PCT = 2`, `UNO_PHANTOM_KMAX_PCT = 60` | 当前默认优先贴近论文实际脚本，而不是沿用物理队列的 25/75。 |
| phantom `pmax` | 论文未单列 | `CompositeQueue` 在 `kmin..kmax` 区间线性增长，到 `kmax` 直接等价于概率 1 | `UNO_PHANTOM_PMAX = 1.0` | ns-3 这里显式参数化为 `1.0`，以复现开源实现的线性到满概率标记行为。 |
| phantom size | 论文 Table 2 未给统一默认值 | Uno_SC25 脚本按实验设置传 `22400515` 或 `89602060` 等 | 默认 `0`，运行时自动派生 `lineRate * UNO_INTER_RTT_NS / 8` | 该 fallback 比旧的 `ecnKmax` 更接近论文语义；若要精确复现实验图，应显式设置 `UNO_PHANTOM_SIZE_KB`。 |

## 行为对照

### ACK / AI

论文要求：

- ACK 到达且未 ECN marked 时，执行 `cwnd += alpha * bytes_acked / cwnd`。

当前实现：

- `HandleAckUno()` 从 ACK header 和 ECN 计数判断本 ACK 是否 ECN marked。
- `UnoAdditiveIncrease()` 只在未 ECN marked 且 `bytesAcked > 0` 时增加 cwnd。
- alpha 按 `BDP * UNO_AI_FACTOR` 计算。

对照结果：已实现。

### Epoch / MD

论文要求：

- 每个 epoch 至多做一次 MD。
- 如果 epoch 内存在 ECN marked packet，计算 ECN fraction 的 EWMA。
- `MD_ECN = E * 4K / (K + BDP)`。
- phantom-only congestion 时使用 gentle reduction。

当前实现：

- `UnoEpochEnded()` 优先用 ACK 回传的数据包发送时间戳与 `m_epochEndTxTsNs` 比较，timestamp 不可用时才退回 wall-clock。
- `UnoProcessEpochEnd()` 计算 `ecnFraction`、EWMA、`mdGain`、`mdScale`，再更新 cwnd。
- `UnoAdvanceEpoch()` 在 epoch 结束后把 packet timestamp 边界推进一个或多个 epoch period。
- `GetUnoEpochPeriodNs()` 固定使用 `m_uno_intra_rtt_ns * m_uno_epoch_rtt_factor`。

对照结果：主公式已实现；epoch 边界已经从 wall-clock 改为 packet timestamp 驱动，仍有 ns-3 适配近似，见后文限制。

### Quick Adapt

论文要求：

- 每 RTT 检查 QA period 内 ACKed bytes。
- 若 `bytes_acked_in_qa < cwnd * beta`，将 `cwnd` 快速降到 QA period 内 ACKed bytes。
- 触发后跳过一个 RTT，不触发 QA 或 MD。

当前实现：

- `UnoQaPeriodEnded()` 使用同一 Uno epoch period。
- `UnoProcessQaEnd()` 按 `qaAckedBytes < cwnd * beta` 触发。
- 触发后设置 `m_qaCooldownUntilNs = now + epochPeriod`，并 reset epoch。

对照结果：已实现主体逻辑；cwnd 下限和 QA period 选择存在 ns-3 适配，见后文限制。

### Phantom queue

论文要求：

- packet enqueued 到 physical queue 时，phantom queue occupancy 增加。
- phantom queue 以低于 physical queue 的 drain rate 下降。
- phantom queue 用于 ECN marking。

当前实现：

- `UpdateEgressAdmission()` 中增加 phantom occupancy。
- `UpdateUnoPhantomDrain()` 根据 elapsed time 以 `lineRate * 0.9` drain。
- `ShouldSendCNUno()` 基于 phantom occupancy 的 kmin/kmax/pmax 做线性 ECN marking。
- 默认 `UNO_PHANTOM_USE_PHYSICAL = false`，即保留物理 ECN 配置但不把它并入 Uno 的 phantom 标记路径；若开启该选项，则物理 ECN 可作为附加标记条件。

对照结果：已实现。

## 因 ns-3 框架造成的近似和未完全复刻点

### 1. cwnd 驱动被映射为 rate pacing

论文和 Uno_SC25 的 UnoCC 是 window-based congestion control，核心状态是 `_cwnd`。当前 ns-3 RDMA 框架的发送节奏主要由 `qp->m_rate` 控制，而不是直接由 cwnd gate 控制。

处理方式：

- 仍维护 UnoCC 内部 `m_cwndBytes`。
- 每次 ACK/epoch/QA/timeout 后调用 `UnoApplyRateFromCwnd()`，把 cwnd 转为 rate：
  - `rate = cwnd * 8 / RTT`

影响：

- 收敛公式和控制方向保持一致。
- 发送行为不是论文/Uno_SC25 的严格 window gate，而是 rate-based approximation。

### 2. epoch 结束条件已改为 ACKed packet timestamp 驱动，但仍不是完整 per-packet send-time 表

论文 Section 4.1.1 说明：sender 存储 `T_epoch` 和每个 packet 的 send/re-send time；当 ACK 的 packet send time `T_pkt >= T_epoch` 时 epoch 结束。

Uno_SC25 也通过 `acked_pkt_ts` 判断 `shouldTriggerEpochEnd()`。

当前 ns-3 实现：

- sender 发数据包时通过已有 `IntHeader::ts` 记录发送时间。
- receiver 生成 ACK 时把该时间戳带回。
- `UnoEpochEnded()` 优先判断 `ackedPktTxTsNs >= m_epochEndTxTsNs`。
- 若当前仿真未启用该 timestamp 通路，则退回 wall-clock fallback。

原因：

- 当前 RDMA ACK 路径能稳定带回“触发该 ACK 的那个数据包”的时间戳，但没有为累计 ACK 暴露完整 packet send-time 列表。
- 发送侧也没有像 Uno_SC25 那样维护严格的 per-packet send/re-send timestamp 表。

影响：

- 已经比原来的 wall-clock 近似更接近论文/Uno_SC25。
- 但它仍不是“每个被 ACKed packet 都可逐一比较”的完整复刻，尤其在 ACK aggregation 或累计确认时仍是近似。

### 3. ECN fraction 通过 ACK interval 计数近似

论文和 Uno_SC25 按 epoch 内 ECN-marked bytes / total ACKed bytes 计算 fraction。

当前实现：

- receiver 端累计本 ACK interval 内 ECN marked packet 数和 total packet 数。
- ACK 携带这两个计数。
- sender 用 packet fraction 乘以 `bytesAcked` 估算 marked bytes。

原因：

- 当前 qbb ACK header 原本只有 CNP bit，不足以表达 ECN fraction。
- 为避免大改 header 格式，复用了 ACK/NACK 已有的 `irnNack` 和 `irnNackSize` 字段。

限制：

- 当 `m_irn == true` 时，这两个字段属于 IRN NACK 语义，UnoCC ECN 计数不会复用它们；此时退回 CNP bit。
- marked bytes 是基于 packet fraction 的估计，不是逐 byte 标记。

### 4. QA period 使用 Uno epoch period

论文 QA 写的是 once every RTT；同时论文又强调 epoch period 对 inter/intra 使用同一 intra-DC RTT granularity。

当前实现：

- QA period 和 epoch period 都使用 `UNO_INTRA_RTT_NS * UNO_EPOCH_RTT_FACTOR`。

影响：

- 匹配论文对统一 granularity 的描述。
- 不完全等同于 Uno_SC25 中 long QA 使用 flow `target_rtt`、short QA 使用 timestamp epoch ratio 的更多模式。

### 5. QA cwnd 下限和 Uno_SC25 的 `0.96` 差异

论文 Algorithm 1 写 `cwnd = bytes_acked_in_qa`。

Uno_SC25 `processQaMeasurementEnd()` 中实际是：

- `_cwnd = bytes_acked_in_qa_period * 0.96`

当前 ns-3 实现：

- `cwnd = max(MTU, qaAckedBytes)`

原因：

- ns-3 RDMA 发送路径中 cwnd/rate 为 0 会产生不可用或极端行为；保留 MTU 下限更稳。
- 论文算法没有 `0.96`，因此没有加入该经验系数。

影响：

- 极端拥塞下不会把 cwnd 降到 0。
- 与 Uno_SC25 精确数值有轻微差异。

### 6. phantom-only 判断使用 5% delay threshold

论文 Algorithm 1 以 `delay == 0` 表示 phantom-only congestion。

Uno_SC25 `aimd_phantom` 中使用近似阈值：

- `rtt > _base_rtt * 1.055` 时认为存在 physical queue delay。

当前实现：

- `physicalQueueDelay = lastRtt > baseRtt * (1 + UNO_DELAY_THRESHOLD)`
- 默认 `UNO_DELAY_THRESHOLD = 0.05`

原因：

- 仿真 timestamp、ACK aggregation、rate mapping 下，严格 `RTT - RTTbase == 0` 过于脆弱。
- 该处理接近 Uno_SC25 的 1.055 判定。

### 7. phantom queue drain 是 lazy update

Uno_SC25 `CompositeQueue` 通过事件调度定期 decrease phantom queue。

当前 ns-3 实现：

- 不额外调度 periodic event。
- 在增加 phantom bytes 或检查 ECN marking 时，根据 elapsed time 计算应 drain 的 bytes。

影响：

- 对 ECN 判定时的 occupancy 是按当前时间更新后的值。
- 不会生成独立的 phantom queue drain 事件或连续日志。

### 8. phantom queue size 默认没有论文统一值，只能做语义上更接近的自动派生

论文 Table 2 没有给 phantom queue size 的统一默认值；Uno_SC25 脚本按实验场景传 `phantom_size`。

当前实现：

- `UNO_PHANTOM_SIZE_KB = 0` 表示自动 fallback。
- fallback 使用 `lineRate * UNO_INTER_RTT_NS / 8` 自动派生。

影响：

- 这比旧的“直接拿物理 ECN `kmax` 当 phantom size”更符合论文里 phantom queue 应显著长于物理队列、并与跨 DC 带宽时延积相关的语义。
- 但它仍不是论文脚本中的精确值；若要严格复现实验，需要在配置中显式给出 `UNO_PHANTOM_SIZE_KB`。

### 9. `UNO_INTER_RTT_NS` 只是 phantom size fallback 的实验默认值

论文 Table 2 的 `Inter-DC RTT = 2ms` 是实验默认参数。

当前实现：

- 新增 `UNO_INTER_RTT_NS = 2000000` / `UNO_INTER_RTT_US`。
- 该值只用于 `UNO_PHANTOM_SIZE_KB = 0` 时的自动派生。
- `qp->m_baseRtt`、链路 delay、topology 文件仍决定实际 flow RTT。

影响：

- 如果你的实验 inter-DC RTT 不是 2ms，应同时覆盖 `UNO_INTER_RTT_NS` 或直接显式设置 `UNO_PHANTOM_SIZE_KB`。

## 当前对齐结论

已对齐论文和/或开源实现的点：

- UnoCC 独立 `CC_MODE_UNOCC`。
- per-flow cwnd/epoch/QA/RTTbase/ECN EWMA 状态。
- ACK 未 ECN marked 时 AI。
- epoch 级 ECN fraction MD。
- `MD_ECN = 4K / (K + BDP)`，并乘 ECN EWMA。
- phantom-only gentle reduction。
- QA bytes threshold 和 cooldown。
- phantom queue occupancy、drain 和 RED-style ECN marking。
- Table 2 默认参数。
- 论文 evaluation 段的物理 ECN threshold 25/75。
- Uno 论文脚本常用 `ECN alpha = 0.65`、`phantom_kmin/kmax = 2/60`、`phantom_size = 22400515/89602060` 这组运行参数。
- `CompositeQueue` 的 phantom marking 概率在 `kmax` 处等价升到 1。

仍属于迁移近似的点：

- window-based UnoCC 映射到 rate-based RDMA pacing。
- epoch 边界虽然已改为 ACKed packet send timestamp 驱动，但仍不是完整 per-packet send-time 复刻。
- ECN fraction 使用 ACK interval packet fraction 估算 bytes fraction。
- IRN 与 UnoCC 精确 ECN count 复用字段冲突，IRN 开启时退回 CNP bit。
- QA 不使用 Uno_SC25 的 `0.96` 系数，并保留 MTU cwnd 下限。
- phantom queue drain 使用 lazy update，而不是独立 periodic event。
- phantom queue size 需要实验配置显式指定才能精确复现论文场景。

## 验证

已执行：

- `./waf build`
- `git diff --check`

结果：

- build 成功。
- `git diff --check` 无 whitespace/error 输出。
- build 中仍有 ns-3 原有 deprecated warning，不是 UnoCC 迁移引入的错误。
