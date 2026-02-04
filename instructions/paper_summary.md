# GSCC（Gateway Sensing Congestion Control）论文总结

> 主题：将 RoCEv2 / RDMA 扩展到公网/运营商 WAN（跨数据中心）场景的拥塞控制。  
> 核心思想：不要依赖 WAN 内部网络设备提供拥塞信号，而是在 **数据中心边界网关交换机**侧“感知 RTT + 计算聚合速率 + 通过 CNP 控制源端 RNIC”。

---

## 1. 面临的问题（Why RDMA over WAN is hard）

将数据中心内成熟的 RDMA（如 RoCEv2）用于跨数据中心的 WAN，会遇到一组系统性挑战，导致吞吐下降、尾延迟恶化，甚至出现“卡死/极慢流”。

### 1.1 拥塞信号缺失或不可控
- DC 内可以依赖 PFC、ECN、甚至 INT 等机制，RNIC 端能收到相对及时、稳定的拥塞反馈（如 CNP）。
- WAN 中间网络属于 ISP/公网设备，租户通常 **无法要求开启或统一配置** PFC/ECN/INT，传统 RDMA CC 失去可靠信号源。

### 1.2 RTT 大且异构，参数难以统一
- DC 内 RTT 为微秒级；跨 DC WAN RTT 为毫秒级、且不同目的地差异巨大。
- 许多拥塞控制算法隐含“RTT 相近/可预设阈值”的假设，跨域后很难调参同时兼顾多目的地与多类型流。

### 1.3 高 BDP + 线速起步带来的突发与丢包
- WAN 的带宽时延积（BDP）可能非常大（可达数百 MB 量级）。
- RDMA 常见做法“线速起步”会在收到任何反馈之前就产生强突发，容易打爆队列导致丢包。

### 1.4 RNIC 重传代价高（Go-Back-N 放大损失）
- RNIC 常用 Go-Back-N 重传，WAN 一旦丢包会触发大幅回退重传，吞吐和尾延迟急剧变差。
- 选择性重传需要更大的状态与缓存，难以在 RNIC 资源约束下规模化。

---

## 2. 整体设计（GSCC Architecture & Key Idea）

### 2.1 核心洞察
跨 DC 流量都会经过 **网关交换机（gateway）**。与其让每台主机的 RNIC 在长 RTT、弱信号的 WAN 上“单兵作战”，不如将 **WAN 段拥塞控制的关键环节集中在网关侧**：
- 网关可共享信息、按目的地聚合决策；
- 控制回路从“跨 WAN 的毫秒级”缩短为“主机到网关的微秒级”。

### 2.2 目标与原则
- **WAN Independence**：不依赖 WAN 中间设备的特殊功能。
- **DC Compatibility**：尽量不改 RNIC，不改 DC 内其它交换机/协议（如 DCQCN 仍可存在）。
- **High Performance**：尽量避免丢包，保持高吞吐并改善尾延迟。

### 2.3 模块划分
GSCC 部署在每个数据中心的网关交换机上，包含 3 个模块：

1) **RTT Monitor（数据面）**  
   按目的地（dst-DC）持续测量 RTT，作为“替代拥塞信号”。

2) **Rate Calculation（控制面）**  
   周期性（epoch）读取 RTT 统计，计算每个 dst-DC 的 **聚合目标速率** `refRate`（reference rate）。

3) **Rate Control（数据面）**  
   在网关侧按 dst-DC 维度施加速率约束，并通过向源端发送 **CNP**（Congestion Notification Packet）触发 RNIC 降速/调速，从而实现快速收敛。

---

## 3. 每个模块的设计

## 3.1 RTT Monitor（网关侧 RTT 测量）

### 3.1.1 关键手段：利用 RoCEv2 的 AckReq
- RoCEv2 数据包可以设置 `AckReq` 位以请求对端回 ACK。
- 网关对部分数据包抽样设置/利用 AckReq，并记录发送时间；当 ACK 返回时计算 RTT。
- 高吞吐下 AckReq 采样密度足够，能够捕捉 WAN RTT 的毫秒级波动。

### 3.1.2 两个关键困难
1) **大流霸占状态**：如果按流记录测量状态，大流可能占据大部分表项，导致 RTT 代表“少数流”而非目的地整体。  
2) **重传导致 RTT 误配**：Go-Back-N 下同一序号的包可能多次发送，ACK 只对应最新一次，若仍保留旧时间戳会造成 RTT 错误。

### 3.1.3 两级哈希表（bucket + entry）
- 先按 5-tuple 哈希到 bucket；
- 每个 bucket 固定若干 entry（如 16），再按 seq 哈希到 entry；
- entry 存储压缩的 packet identifier + timestamp，并带超时与覆盖规则：遇到重传时更新为“最新一次”的时间戳，避免误配。

### 3.1.4 聚合输出
- 以 dst-DC 为粒度维护统计：`rtt_sum` / `rtt_cnt`；
- 控制面每个 epoch 拉取并清零，用于计算该 epoch 的平均 RTT。

---

## 3.2 Rate Calculation（从 RTT 推导 refRate）

### 3.2.1 基线与阈值：minRTT + T
- 对每个 dst-DC 维护 `minRTT` 作为传播时延基线；
- 用阈值 \(minRTT + T\) 判定是否进入拥塞区间，避免不同目的地基线 RTT 不可比。

### 3.2.2 AI/MD 调节逻辑
- 若当前 RTT \(< minRTT + T\)：认为不拥塞，执行 **Additive Increase（AI）**；
- 否则：认为拥塞，执行 **Multiplicative Decrease（MD）**。

### 3.2.3 抑制 RTT 抖动引发的震荡（预测与降权）
- 用 EWMA 平滑 RTT 差分（梯度）以降低噪声敏感性；
- 结合“预测下一 RTT”判断是否会跨阈值：
  - 若当前 RTT 与预测 RTT 分处阈值两侧，则将 AI/MD 幅度缩小（例如 1/3），降低震荡。

### 3.2.4 尺度化与上界控制
- 以 `minRTT`、`epochDur` 对增减幅度做尺度化，使不同 RTT 目的地收敛更稳。
- 防止 refRate 在低 RTT 但“真实可达速率”受限时无界增大：
  - 估计 `realRate`（根据近几轮 epoch 的实际发送字节）
  - 对 refRate 施加上界，例如不超过 \(\max(gRate, 1.2 \times realRate)\) 并在超出时回落贴近 realRate。

---

## 3.3 Rate Control（在数据面落实 refRate，并通过 CNP 控制 RNIC）

### 3.3.1 难点
- 网关并不知道 CNP 对源 RNIC 速率的“精确映射”（依赖 DCQCN 状态机与参数）。
- 数据面不宜维护复杂的 per-flow 速率状态。

### 3.3.2 控制目标：逼近累计误差为 0
GSCC 不强求瞬时 `realRate == refRate`，而是约束累计偏差：
\[
\int (realRate - refRate)\,dt \to 0
\]
直观上：允许短时偏离，但要让长期“多发/少发”的误差可控并回归。

### 3.3.3 关键状态：realBytes 与 refBytes（按 dst-DC）
- `realBytes`：本 epoch 实际已发送的字节数（逐包累加）。
- `refBytes`：在 refRate 下理论应发送字节数（线性随时间增长）。
- `refBytes` 的截距会继承上个 epoch 的误差（带“记忆性”），用于推动误差回归。

### 3.3.4 CNP 触发规则
- 当 \(realBytes - refBytes > K\) 时，对当前包所属流发送 CNP。
- 误差越大，允许触发越频繁（负反馈更强），使真实速率向 refRate 收敛。

### 3.3.5 公平性直觉
虽然不显式维护每条流的速率，但更快的流会产生更多包、更频繁触发阈值，因此会收到更多 CNP，被更强抑制，形成近似公平的聚合控制。

### 3.3.6 振荡与空闲误差的修正
- **突发导致过度 CNP**：突发会使 `realBytes` 快速超过 `refBytes`，触发大量 CNP，随后又可能出现低于 ref 的阶段，引发振荡。
- **空闲期误差累积**：某 dst-DC 若多个 epoch 无流量，误差继承可能在恢复流量时造成冲高。
- 解决：当误差较小时周期性将 `realBytes` 向 `refBytes` 指数收敛（轻量的纠偏），抑制振荡并限制误差漂移。

---

## 4. 一句话总结
GSCC 用 **网关侧的 RTT 采样**替代 WAN 不可控的拥塞信号，通过 **控制面按目的地聚合计算 refRate**，再用 **数据面 CNP 触发机制**把源 RNIC 的发送速率快速拉回目标区间，从而在“长 RTT、弱信号、易丢包”的 RDMA over WAN 场景中获得更稳定的吞吐与尾延迟表现。
