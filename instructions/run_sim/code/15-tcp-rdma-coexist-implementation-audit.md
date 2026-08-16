# TCP 与 RDMA 共存实现审计：错误、实验解释边界与修复建议

## 1. 文档目的与审计范围

本文审计当前工作树中 TCP/RDMA 共存的实现，回答以下问题：

1. TCP/RDMA 混跑的数据面是否真正闭环；
2. q1（TCP 隔离模式）与 q3（TCP/RDMA 共用模式）的实现是否符合实验名称；
3. buffer、PFC、ECN、丢包和统计路径中是否存在会扭曲实验结论的错误；
4. 对已完成的 337/338 实验，哪些指标仍可使用，哪些结论必须撤回或保留限制；
5. 应以什么顺序修复并重新验证。

本文是对 `14-tcp-rdma-coexist-buffer-analysis.md` 的实现正确性补充，不替代其关于正常发送路径和队列路径的机制说明。代码中的行号以审计时的当前工作树为准。

## 2. 执行结论

当前实现已经具备 TCP/RDMA 混跑的最小数据面闭环，但不能可靠地支撑“按协议归因丢包”“比较 q1/q3 egress buffer”“验证 PFC 分队列行为”或“证明 TCP 获得 ECN/DCTCP 反馈”等结论。

TCP 与 RDMA 的基本路径是工作的：

- TCP 使用 `BulkSendApplication` 和 `PacketSink`，通过 `TcpSocketFactory` 进入标准 TCP/IP 协议栈；
- host 收到 TCP/ICMP 时，`QbbNetDevice::Receive()` 会把它交给 IPv4 协议栈，而不是送入 RDMA hardware；
- TCP 在 host 与交换机都依据 `TCP_QUEUE_INDEX` 选择 q1 或 q3；
- TCP 和 RDMA 最终共享 host NIC 的物理 TX machine，但不是一个统一 FIFO，而是在 TCP 候选与 RDMA QP 候选之间按包交替仲裁。

不过，以下高优先级错误会直接改变 q1/q3 共存实验的解释：

| 严重度 | 问题 | 对实验的核心影响 |
|---|---|---|
| 高 | TCP fallback flow ID 的 PPP 协议号判断错误 | TCP 丢包记录没有有效 flow ID，无法拆分 TCP/RDMA 丢包 |
| 高 | TCP drop 的 `seq_num` 错误使用 `ch.udp.seq` | 不能将 TCP 丢包与 TCP sequence/retransmission 对齐 |
| 高 | 交换机 egress 队列入队失败被忽略 | 队列满时会静默丢包，并造成 MMU buffer accounting 泄漏 |
| 高 | 动态 PFC pause 计算混用 `i` 和 `qIndex` | 可能误 pause 或漏 pause 队列，q1/q3 的 PFC 行为不可信 |
| 高 | TCP ECN/DCTCP 没有形成端到端反馈闭环 | TCP 不能被解释为响应交换机 CE 标记 |
| 中 | q1 的 160 MiB 特殊阈值与默认 9 MiB 全局 buffer 冲突 | q1 不是 160 MiB 物理隔离 buffer，仍受 9 MiB 全局容量限制 |
| 中 | 实际停止时间为 `FLOWGEN_STOP_TIME + 3s` | TCP 未完成 flow 被提前截断，完成流 FCT 不是完整样本 |
| 中 | `run.py` 默认启用 TCP，复用 config 时空参数不清旧 TCP 配置 | RDMA-only/TCP-only 对照可能被静默污染 |
| 中 | egress monitor 只统计 q0+q3 | q1 与 q3 实验的 egress peak 口径不同，不能直接比较 |
| 中 | egress admission 被关闭 | 现有 egress bytes 是 occupancy accounting，不是 egress admission/drop 模型 |
| 低 | TCP flow 输入依赖按启动时间排序 | 无序输入可能出现错误调度或漏调度 |

## 3. 已确认正常的共存路径

### 3.1 TCP host 收发闭环

`QbbNetDevice::Send()` 对标准 TCP/IP 包添加 PPP header 后，将其放入 `Settings::tcp_queue_index` 指定的 `BEgressQueue` 队列：

```cpp
uint32_t qIndex = Settings::tcp_queue_index;
if (!m_queue->Enqueue(packet, qIndex)) {
    ...
}
```

源文件：`src/point-to-point/model/qbb-net-device.cc::QbbNetDevice::Send()`。

host 侧接收时，TCP/ICMP 包通过快速路径被交给标准 NetDevice receive callback：

```cpp
if (proto == 0x0800) {
    Ipv4Header ipv4;
    if (tmp->PeekHeader(ipv4) > 0 &&
        (ipv4.GetProtocol() == 0x06 || ipv4.GetProtocol() == 0x01)) {
        ...
        m_rxCallback(this, packet, upProto, GetRemote());
        return;
    }
}
```

源文件：`src/point-to-point/model/qbb-net-device.cc::QbbNetDevice::Receive()`。

因此，TCP 不会在 host 接收端被 RDMA hardware 当作 RDMA UDP 数据处理。已有实验中大量 TCP flow 完成也说明 `BulkSend -> QbbNetDevice -> switch -> QbbNetDevice -> IPv4/TCP -> PacketSink` 的基本路径成立。

### 3.2 q1/q3 分类与 host 发送仲裁

交换机按 L4 协议进行分类：TCP (`0x06`) 使用 `TCP_QUEUE_INDEX`，RDMA UDP (`0x11`) 使用数据包中的 `ch.udp.pg`：

```cpp
if (ch.l3Prot == 0x06) {
    qIndex = Settings::tcp_queue_index;
} else if (ch.l3Prot == 0x11) {
    qIndex = ch.udp.pg;
}
```

源文件：`src/point-to-point/model/switch-node.cc::SwitchNode::SendToDevContinue()`。

在 host 侧，TCP 在 `BEgressQueue` 中，RDMA 在 `RdmaEgressQueue` 的 QP scheduler 中。二者共享 `QbbNetDevice::DequeueAndTransmit()` 和 `m_txMachineState`，但并不共享一个单一 FIFO：

```text
ACK/CNP 高优先级队列
        ↓
RDMA QP 可发送候选
        ↓
TCP BEgressQueue 可发送候选
        ↓
两者同时就绪时按 hostDequeueIndex 奇偶交替
        ↓
同一条物理 NIC TX machine / 链路
```

源文件：`src/point-to-point/model/qbb-net-device.cc::RdmaEgressQueue::GetNextQindex()` 与 `QbbNetDevice::DequeueAndTransmit()`。

所以，“同队列 q3”应准确理解为：

> TCP 与 RDMA 在交换机侧共用 q3/MMU/PFC priority class；在 host 侧共用物理发送机，TCP/RDMA 候选之间由自定义交替调度器竞争发送机会。

它不是按字节公平、按流公平，也不是把 TCP payload 和 RDMA payload 放入同一个 host FIFO；不能将它解读为固定 50/50 的带宽配额。

## 4. 确定性实现错误

### 4.1 TCP fallback flow ID 的 PPP protocol 判断错误

#### 代码事实

`Settings::get_flowid()` 会尝试为没有 `FlowIDNUMTag` 的 TCP/ICMP 包生成 fallback ID：

```cpp
PppHeader ppp;
if (tmp->PeekHeader(ppp) > 0) {
    const uint16_t pppProto = ppp.GetProtocol();
    if (pppProto == 0x0800) {
        tmp->RemoveHeader(ppp);
    }
}
```

源文件：`src/point-to-point/model/settings.cc::Settings::get_flowid()`。

但是该仓库的点到点封装将 IPv4 EtherType `0x0800` 映射为 PPP protocol `0x0021`：

```cpp
case 0x0800: return 0x0021;   // IPv4
```

源文件：`src/point-to-point/model/point-to-point-net-device.cc::PointToPointNetDevice::EtherToPpp()`。

#### 实际后果

TCP 报文 PPP protocol 实际为 `0x0021`，当前代码不会移除 PPP header，后续从 PPP bytes 开始错误解析 IPv4 header，最终回退为：

```cpp
return 0xFFFFFFFF;
```

即 CSV 中的 `flow_id=4294967295`。

337/338 的已生成日志已证实这个问题：

| 实验 | `drop_log` 中 `flow_id=4294967295` 的条目 | `config.log` 中相同 warning 数 |
|---|---:|---:|
| 337，TCP q1 / RDMA q3 | 121,170 | 121,170 |
| 338，TCP q3 / RDMA q3 | 111,979 | 111,979 |

因此，现有 `drop_log` 不能可靠按 `flow_id` 区分 TCP/RDMA，不能做 TCP flow 级别的丢包归因。

#### 修复要求

1. PPP 判断至少改为 `0x0021`，或统一复用 PPP-to-EtherType 转换函数；
2. fallback ID 不能仅用 `srcId * 1000 + dstId`；应包含 TCP `sport/dport`，最好建立稳定的 TCP 5-tuple 到 ID 的映射；
3. 将 TCP flow ID 与 RDMA `Settings::flowInfos` 整数索引隔离，避免 ID 冲突；
4. `drop_log` 应增加协议和 5-tuple 字段，不能只依赖单个整数 flow ID。

### 4.2 TCP 丢包的 `seq_num` 记录错误

交换机 ingress drop 和 egress drop 日志无条件写入：

```cpp
ch.udp.seq
```

源文件：`src/point-to-point/model/switch-node.cc::SwitchNode::DoSwitchSend()`。

但 `CustomHeader` 的 TCP/UDP 共享 union：

```cpp
struct { uint16_t sport, dport; uint32_t seq, ack; ... } tcp;
struct { uint16_t sport, dport; uint16_t payload_size, pg; uint32_t seq; ... } udp;
```

源文件：`src/network/utils/custom-header.h`。

`ch.udp.seq` 对 RDMA UDP 是 RDMA sequence；但对 TCP，字段偏移与 `ch.tcp.ack` 重叠，而不是 `ch.tcp.seq`。因此当前 `drop_log.seq_num` 对 TCP 不是 TCP sequence number。

建议最小修复：

```cpp
const uint32_t seq =
    ch.l3Prot == 0x06 ? ch.tcp.seq :
    ch.l3Prot == 0x11 ? ch.udp.seq :
    0;
```

并将 `protocol,sport,dport,qindex` 写入 drop CSV。修复之前，不得用该列做 TCP sequence、retransmission 或 loss gap 分析。

### 4.3 交换机队列入队失败被静默忽略，MMU accounting 泄漏

交换机的 `DoSwitchSend()` 会先通过 admission，再立即更新 ingress/egress accounting：

```cpp
m_mmu->UpdateIngressAdmission(inDev, qIndex, p->GetSize());
m_mmu->UpdateEgressAdmission(outDev, qIndex, p->GetSize());
...
m_devices[outDev]->SwitchSend(qIndex, p, ch);
```

源文件：`src/point-to-point/model/switch-node.cc::SwitchNode::DoSwitchSend()`。

但 `QbbNetDevice::SwitchSend()` 忽略 `BEgressQueue::Enqueue()` 的返回值：

```cpp
m_queue->Enqueue(packet, qIndex);
DequeueAndTransmit();
return true;
```

源文件：`src/point-to-point/model/qbb-net-device.cc::QbbNetDevice::SwitchSend()`。

而 `BEgressQueue::DoEnqueue()` 在超过 `m_maxBytes` 时确实返回 false：

```cpp
if (m_bytesInQueueTotal + p->GetSize() < m_maxBytes) {
    ...
} else {
    return false;
}
```

源文件：`src/network/utils/broadcom-egress-queue.cc::BEgressQueue::DoEnqueue()`。

若 egress queue 满，当前后果是：

1. 包在设备队列处被实际丢弃；
2. 不写 `drop_log`；
3. 不增加 `dropped_pkt_sw_egress`；
4. 先前增加的 ingress/egress accounting 不回滚；
5. 包不可能 dequeue，因而 `SwitchNotifyDequeue()` 也不会扣减计账；
6. 后续 buffer、ECN、PFC 判断会被永久虚高的 occupancy 污染。

修复时应让 `SwitchSend()` 传播入队结果；失败后完整回滚 ingress/egress admission，并按 egress drop 记录日志。PFC 检查也应在确认实际入队成功后再执行，避免对已掉的包产生错误 PFC 副作用。

### 4.4 动态 PFC pause 判断混用了队列索引

`SwitchMmu::GetPauseClasses()` 在动态阈值模式中遍历所有 PG：

```cpp
for (uint32_t i = 0; i < qCnt; i++) {
```

但在普通 PG 分支中，shared pool 与 headroom 判断却使用本次到包的 `qIndex`：

```cpp
m_usedIngressSPBytes[GetIngressSP(port, qIndex)]
m_usedIngressPGHeadroomBytes[port][qIndex]
```

源文件：`src/point-to-point/model/switch-mmu.cc::SwitchMmu::GetPauseClasses()`。

这里应使用循环变量 `i`。当前实际含义变成：

> 用当前到达包的 shared-pool/headroom 状态，决定所有队列是否应被 pause。

`CheckAndSendPfc()` 会把计算出的 `pClasses[]` 真正发给对应队列，因此不是仅影响调试输出：

```cpp
for (int j = 0; j < qCnt; j++) {
    if (pClasses[j]) {
        device->SendPfc(j, 0);
    }
}
```

源文件：`src/point-to-point/model/switch-node.cc::CheckAndSendPfc()`。

在 TCP q1 / RDMA q3 混跑中，这会导致 q1 到包影响 q3 判断，或 q3 到包影响其他队列判断。故现有 PFC event、pause 时间、队列竞争和 drop 改善都不能严谨地解释为“每个 PG 按自身阈值工作”。

修复为将两处 `qIndex` 替换为 `i`，并为每次 pause/resume 输出 `port,qindex,reason,threshold,occupancy` 的结构化日志。

### 4.5 TCP ECN/DCTCP 没有可用的端到端控制闭环

当前 TCP stack 看起来提供了 ECN/DCTCP 属性：

```cpp
.AddAttribute("ECN", ..., BooleanValue(true), ...)
.AddAttribute("DCTCP", ..., BooleanValue(true), ...)
```

源文件：`src/internet/model/tcp-socket.cc` 与 `src/internet/model/tcp-socket-base.cc`。

但实现没有完成 ECN 连接协商和反馈：

1. `m_EcnState` 初始化为 `NO_ECN`；
2. 接收 CE 的代码要求已处于 `ECN_CONN`；
3. 当前源码没有将该状态设置为 `ECN_CONN` 的路径；
4. SYN/SYN-ACK 没有实现 ECN 协商；
5. TCP data/ACK 发送路径没有根据 CE 状态设置 ECE/CWR；
6. `ReceivedAck()` 没有在 ECE 上调用 `HalveCwnd()`。

接收侧的 CE 判断如下：

```cpp
if (m_EcnState & ECN_CONN) {
    if (header.GetEcn() == Ipv4Header::CE) {
        m_EcnState |= ECN_TX_ECHO;
    }
}
```

源文件：`src/internet/model/tcp-socket-base.cc::TcpSocketBase::DoForwardUp()`。

因此，交换机 `SwitchNotifyDequeue()` 即使将 TCP IPv4 ECN bits 改为 CE，也不会构成 TCP 的 DCTCP/ECN 拥塞反馈。当前 TCP 的主要控制反应仍来自传统的丢包、重复 ACK 和 retransmission timeout。

在修复并做端到端 trace 验证之前，实验报告不得声称：

- TCP 使用 DCQCN；
- TCP 已经得到与 RDMA 等价的 ECN 反馈；
- CE 标记是 TCP FCT/吞吐变化的因果机制。

## 5. buffer 与队列语义的关键限制

### 5.1 q1 的 160 MiB 不是默认可用的 TCP 专属容量

q1 隔离模式初始化：

```cpp
m_tcp_pg_min_cell = 160 * 1024 * 1024;
m_tcp_port_min_cell = m_tcp_pg_min_cell;
```

源文件：`src/point-to-point/model/switch-mmu.cc::SwitchMmu::InitSwitch()`。

但 ingress admission 的第一步始终是全局总 buffer：

```cpp
if (m_usedTotalBytes + psize > m_maxBufferBytes) {
    return false;
}
```

源文件：`src/point-to-point/model/switch-mmu.cc::SwitchMmu::CheckIngressAdmission()`。

DC switch 的总容量由：

```cpp
ConfigBufferSize(buffer_size * 1024 * 1024);
```

配置。源文件：`scratch/remote.cc`。

而 337/338 使用 `BUFFER_SIZE=9`，因此实际优先级为：

```text
全局 9 MiB admission/drop
        先发生于
q1 接近 160 MiB 的特殊 PG admission/PFC 阈值
```

q1 模式的真实语义是：q1 不进入普通 shared-pool accounting，但仍消耗 `m_usedTotalBytes`，并非预先从物理总容量切出 160 MiB 的专属池。`m_tcp_port_min_cell` 目前仅被声明和初始化，未真正参与 q1 admission 的独立判断。

### 5.2 egress admission 被关闭

当前：

```cpp
bool SwitchMmu::CheckEgressAdmission(...) {
    return true;
}
```

源文件：`src/point-to-point/model/switch-mmu.cc::SwitchMmu::CheckEgressAdmission()`。

所以交换机有 egress byte accounting，但没有可生效的 egress admission/drop 阈值。现有结果中的 egress bytes 应称为“egress occupancy accounting”，不可称为“egress buffer admission”。

### 5.3 `buffer_monitor.egress_bytes` 的统计口径不一致

`printBufferInfo()` 输出：

```cpp
m_usedEgressBytes[port][0] + m_usedEgressBytes[port][3]
```

源文件：`src/point-to-point/model/switch-mmu.h::SwitchMmu::printBufferInfo()`。

因此：

| 模式 | `buffer_monitor.egress_bytes` 是否包含 TCP 数据 |
|---|---|
| TCP q1 / RDMA q3 | 不包含 TCP q1；只含 q0 + q3 |
| TCP q3 / RDMA q3 | 包含 TCP q3 与 RDMA q3，二者无法区分 |

所以 q1/q3 组的 egress peak 不是同一统计口径。不能由它直接推导“共用队列导致 egress buffer 更高/更低”。

需要按 `port,qindex` 输出 ingress PG、egress queue、总 buffer 和 pause 状态，最低格式建议：

```text
timestamp_ns,switch_id,port,qindex,ingress_pg_bytes,egress_q_bytes,total_bytes,paused
```

## 6. 运行控制与可重复性问题

### 6.1 实际 TCP 截止时间为 `FLOWGEN_STOP_TIME + 3s`

代码默认：

```cpp
double flowgen_start_time = 2.0;
double flowgen_stop_time = 2.5;
double simulator_extra_time = 3.0;
```

并每 100 微秒检查：

```cpp
bool time_over =
    Simulator::Now() > Seconds(flowgen_stop_time + simulator_extra_time);
```

超时即写结果并 `Simulator::Stop(NanoSeconds(1))`。源文件：`scratch/remote.cc::stop_simulation_middle()`。

尽管主函数还设置 `Simulator::Stop(Seconds(flowgen_stop_time + 10.0))`，但在正常运行中前者会更早触发。因此 337/338 的：

```text
FLOWGEN_STOP_TIME = 2.05 s
有效截止约为 5.05 s
```

而非 12.05 s。

337 与 338 均完成 `10980 / 10989` TCP flow，各有 9 条未完成。故当前 TCP FCT 只能代表“截止前完成的 TCP flow”，不是完整输入集合的 FCT 分布。

### 6.2 `run.py` 默认和 config 复用可能污染对照

当前 `run.py` 的默认 TCP 输入为：

```python
--tcp_flow config/w-tcp-100.txt
```

但运行说明仍写默认空字符串。没有显式指定 `--tcp_flow` 的运行会带入 TCP，而不是纯 RDMA。

复用已有 config 时，只有非空 `tcp_flow` 才更新 `TCP_FLOW_FILE`：

```python
if tcp_flow:
    existing_config = _upsert_line(
        existing_config, 'TCP_FLOW_FILE', tcp_flow
    )
```

因此：

```bash
python3 run.py --config old-config.txt --tcp_flow ''
```

不能清除旧 config 中已有的 TCP flow 文件。纯 RDMA 对照可能静默变成混跑。

另外，`TCP_FLOW_FILE` 无法打开时仅打印 warning 后继续运行，实验会无声退化为 RDMA-only。应改为 fail-fast。

### 6.3 TCP flow 文件需要按启动时间排序

`ScheduleTcpFlowInputs()` 使用当前 `tcpFlowInfos.back()` 的 start time 调度下一次事件，且不会对输入排序。输入必须按非递减 start time 排列；若乱序，下一次 `Simulator::Schedule()` 可能得到错误的时间差。

建议在读取时验证排序；若输入无序，应排序后再调度或直接报错。

## 7. 对 337/338 已有结果的解释边界

### 7.1 可以继续使用的指标

以下指标可以作为观测结果保留，但报告应同时列出本审计中的限制：

- TCP 与 RDMA 确实同时存在；
- TCP 已完成 flow 的数量和完成时间；
- RDMA `flow_output` 的 FCT/slowdown；
- admission path 已记录的 ingress drop 时间、热点交换机、热点端口；
- ingress buffer 的趋势；
- 配置中 q1/q3 是否实际生效；
- host TX machine 和交换机全局 buffer 的竞争确实存在。

### 7.2 当前不能可靠得出的结论

以下结论不能直接由当前 337/338 数据导出：

- TCP 与 RDMA 分别丢失了多少包；
- 哪些 TCP flow 丢包最多；
- TCP retransmission 与 `drop_log.seq_num` 的对应关系；
- q1/q3 哪个模式的 egress peak buffer 更高；
- PFC 是否按预期针对 q1/q3 正确触发；
- TCP 是否通过 CE/ECN/DCTCP 获得拥塞控制收益；
- 338 相对 337 的 drop 下降主要来自 TCP 还是 RDMA；
- q1 是否实际为 TCP 提供了 160 MiB 独占 buffer；
- q3 共用造成的 FCT 变化是否由正确的 PFC/ECN 机制导致。

特别地，若观察到 338 的 drop 少于 337，这仍可作为“已记录 admission drop 的观测差异”保留；但在修复 flow ID、PFC 索引、device queue 入队失败和 egress 统计口径前，不能进一步做协议归因或机制因果解释。

## 8. 对现有说明文档的修订要求

`instructions/run_sim/code/14-tcp-rdma-coexist-buffer-analysis.md` 的大部分正常路径描述仍可保留，但需要做以下同步：

1. 所有“TCP 固定使用 q1”的表述改为 `TCP_QUEUE_INDEX`，以兼容 q1/q3；
2. host 入队步骤中的 `m_queue->Enqueue(packet, 1)` 改为实际的 `m_queue->Enqueue(packet, TCP_QUEUE_INDEX)`；
3. 丢包章节明确 TCP `seq_num` 当前错误地使用 `ch.udp.seq`，而不是“待确认”；
4. 增加 PPP fallback flow ID bug，以及大量 `4294967295` 丢包记录的已验证事实；
5. ECN 章节明确：当前 TCP 的 ECN/DCTCP 反馈闭环未实现，不可作为实验机制解释；
6. 停止章节明确真实优先生效的截止条件是 `FLOWGEN_STOP_TIME + simulator_extra_time`，当前为 `+3s`；
7. egress monitor 章节强调 q1/q3 两组统计口径不同；
8. 运行文档中的 `--tcp_flow` 默认值应与 `run.py` 一致，推荐恢复代码默认空字符串。

## 9. 推荐修复与验证顺序

### 9.1 第一阶段：先修复会使数据不可归因的错误

1. 修复 PPP `0x0021` 解析与 TCP 5-tuple flow ID；
2. 修复 TCP `seq_num`，并扩展 drop CSV 的 protocol/5-tuple/qindex；
3. 让 switch egress queue enqueue 失败可见、可记录、可回滚 MMU accounting；
4. 修复动态 PFC 循环中的 `qIndex`/`i` 混用。

### 9.2 第二阶段：明确模型语义

1. 决定 q1 是否真要拥有独立物理容量；若是，则总 MMU 与保留池必须协调；
2. 若 q1 只是特殊逻辑 PG，应删除“160 MiB 专属物理 buffer”的表述；
3. 决定是否需要真正实现 TCP ECN/DCTCP；若需要，补齐 ECN 协商、CE->ECE、ECE->cwnd reduction 和可观测 trace；
4. 若不实现 TCP ECN，则在实验描述中明确 TCP 仅按 loss/ACK/timeout 控制。

### 9.3 第三阶段：修复可重复性与观测

1. 将 `simulator_extra_time` 暴露为 config/CLI 参数；
2. 将 TCP finish time、完成状态、未完成原因结构化写入 CSV/JSON；
3. `run.py` 默认不带 TCP，混跑必须显式指定；
4. `--tcp_flow ''` 必须从复用 config 中删除 `TCP_FLOW_FILE`；
5. TCP 文件打开失败应非零退出；
6. 增加按 qIndex 的 ingress/egress/PFC 采样。

### 9.4 建议的最小验证矩阵

| 验证 | 流量 | 期望检查 |
|---|---|---|
| TCP-only | 少量单 flow | IPv4/TCP 收发、唯一 TCP flow ID、finish time、无 RDMA 混入 |
| RDMA-only | 少量单 flow | 关闭 TCP 后 config 中不存在 `TCP_FLOW_FILE` |
| TCP q1 + RDMA q3 | 小 buffer、可控 burst | q1/q3 的 accounting、PFC 各自仅由对应队列状态触发 |
| TCP q3 + RDMA q3 | 同一流量 | q3 中 TCP/RDMA 的占用被同时、可拆分地记录 |
| 强制 egress queue 满 | 小 `BEgressQueue` 上限 | egress drop 被记录，MMU accounting 不泄漏 |
| ECN 验证（若实现） | 低阈值 CE | SYN 协商、CE、ECE、cwnd reduction trace 完整闭环 |

## 10. 最终判断

当前 TCP/RDMA 共存代码适合用于验证“TCP 与 RDMA 可以同时运行、共享 host TX machine、并在交换机 q1/q3 路径中竞争”的最小功能性事实。

但它还不适合用于发表或固化以下强结论：协议级 loss attribution、TCP retransmission analysis、PFC correctness、TCP ECN/DCTCP effectiveness、q1 专属 buffer 容量，以及 q1/q3 egress buffer 的量化比较。

应先完成第 9.1 节的四项修复，再使用按 qIndex 的 buffer/PFC/TCP completion 结构化日志重跑 q1/q3 对照实验。届时才能将性能差异与具体竞争机制可靠关联。
