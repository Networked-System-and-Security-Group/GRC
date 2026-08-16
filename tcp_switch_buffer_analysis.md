# TCP 与 RDMA 共存时的交换机 Buffer、队列和发送路径分析

本文基于当前工作树中的实现整理，重点回答四个问题：

1. TCP 流量怎样被加入仿真，以及它和 RDMA 流量是否真的同时存在于同一条发送链路；
2. TCP 在 host 网卡、DC 交换机和其他交换机上分别进入哪个队列；
3. `--buffer`、TCP 的 q1 固定阈值、PFC、ECN 和实际丢包之间是什么关系；
4. 怎样运行和分析 TCP/RDMA 混跑，哪些日志可以支持结论，哪些数值不能直接解释。

本文描述的是“代码实际行为”，不是硬件交换机的一般性规格。当前工作区包含一批尚未提交的代码修改，所以下面的行号以本工作树为准；修改代码后应重新用 `nl -ba <file>` 核对行号。

## 一、结论摘要

### 1. TCP 和 RDMA 共用 host 的物理发送机，但不共用 RDMA QP 状态

TCP 使用 ns-3 标准 `BulkSendApplication` 和 `PacketSink`，通过 `TcpSocketFactory` 进入 IPv4/TCP 协议栈。协议栈调用 `QbbNetDevice::Send()` 后，TCP 包被放入 `BEgressQueue` 的 q1。

RDMA 则由 `RdmaClient`、`RdmaDriver`、`RdmaHw` 和 `RdmaQueuePair` 产生，数据包由 `RdmaEgressQueue` 按 QP 调度。两类包最终都要经过 `QbbNetDevice::DequeueAndTransmit()` 和同一个 `m_txMachineState`，因此共享 NIC 到链路的串行发送机会；但 TCP 不会更新 RDMA QP 的 `m_nextAvail`、发送窗口或 DCQCN 状态。

### 2. TCP 的分类规则可选，RDMA 数据的优先级由 flow 的 PG 决定

| 位置 | TCP | RDMA 数据 | RDMA 控制包 |
|---|---|---|---|
| host `QbbNetDevice::Send()` | `TCP_QUEUE_INDEX`，默认 q1 | 不走这个标准 NetDevice 入口 | ACK/CNP 等进入高优先级队列 |
| host `RdmaEgressQueue` | 通过特殊返回值 `-2` 选择 BEgressQueue | 非负返回值，对应 QP | `-1`，高优先级 ACK/CNP 队列 |
| `SwitchNode` | IPv4 protocol `0x06` -> `TCP_QUEUE_INDEX` | UDP `0x11` -> `ch.udp.pg` | ACK/NACK/CNP/PFC -> q0 |
| ingress MMU | q1 模式走 TCP 固定阈值；q3 模式走普通 PG3 逻辑 | q0 除外走原共享池/headroom逻辑 | q0 不执行普通 admission |

因此“TCP 与 RDMA 共存”不是把两种应用简单放在两个独立交换机里，而是两种包在 host 发送机和交换机 MMU 中都实际竞争资源；区别在于 host 侧 TCP 是 best-effort 队列，RDMA 有独立 QP/CC/PFC 状态。

### 3. 160 MiB 不是默认交换机总 buffer

队列模式由 `TCP_QUEUE_INDEX` 配置：

- `TCP_QUEUE_INDEX=1`（默认）：TCP 使用 q1，RDMA PG3 使用 q3，保持队列隔离；TCP q1 使用固定 160 MiB ingress PG 特殊阈值；
- `TCP_QUEUE_INDEX=3`：TCP 使用 q3，与 RDMA PG3 共用队列编号、PFC 状态和普通 shared-pool/headroom accounting；TCP q1 的 160 MiB 特殊逻辑不启用。

当前至少要区分以下数值：

| 名称 | 当前来源 | 默认/固定值 | 含义 |
|---|---|---:|---|
| DC switch 静态总 MMU buffer | `run.py --buffer` -> `BUFFER_SIZE` | 9 MiB | 整个交换机 ingress 总量的先决上限 |
| TCP q1 ingress PG 阈值 | `SwitchMmu::m_tcp_pg_min_cell` | 160 MiB | 仅 q1 隔离模式生效 |
| TCP q1 port 阈值变量 | `m_tcp_port_min_cell` | 160 MiB | 当前初始化为同值，但 q1 admission 特判直接使用 PG 阈值 |
| DCI switch 总 buffer | `DCI_BUFFER_SIZE` 或 C++ fallback | 160 MiB | DCI 类型交换机总 MMU 容量 |
| WAN switch 总 buffer | `WAN_BUFFER_SIZE` 或 C++ fallback | 320 MiB | WAN 类型交换机总 MMU 容量 |
| 自动总 buffer | `MaxTotalBufferPerPort * ActivePortCnt` | 375000 bytes/port | 只有静态配置为 0 时使用 |

DC switch 默认总量只有 9 MiB，因此 q1 隔离模式即使有 160 MiB 的专用 admission 门槛，也会先受到全交换机 `m_usedTotalBytes <= m_maxBufferBytes` 的限制。q3 共用模式则直接和 RDMA PG3 竞争普通共享池。160 MiB 不能解释为默认 DC switch 可以为 TCP 保留 160 MiB。

## 二、配置和仿真入口

### 2.1 TCP flow 文件

`run.py` 将 `--tcp_flow` 的值写成输出目录 `config.txt` 中的：

```text
TCP_FLOW_FILE <path>
```

`scratch/remote.cc` 的配置解析循环读取这个键，保存到 `tcp_flow_file`。文件被成功打开后，先读第一行 TCP 流数量 `tcp_flow_num`，再读第一条记录并在仿真时间 0 调度 `ScheduleTcpFlowInputs()`。

TCP flow 文件格式和 RDMA flow 文件相同：

```text
N
src dst pg size_bytes start_time_seconds
...
```

例如：

```text
2
0 7 1 1048576 0.001
1 6 1 4194304 0.003
```

字段含义是：

- `src`、`dst`：host node id；读取时要求两端 node type 都是 host；
- `pg`：TCP 当前只为兼容输入格式而读取，实际 TCP 分类不使用它，建议填写 `1`；
- `size_bytes`：`BulkSendApplication::MaxBytes`，小于 1 byte 时被钳制为 1；
- `start_time_seconds`：该 flow 的应用启动时间。

TCP 目的端口从每个目的 host 的 `50000` 开始递增。RDMA 使用另一套源/目的端口计数器，因此 TCP 与 RDMA 不会因为复用同一目的端口而意外连接到同一个 TCP sink。

### 2.2 `ScheduleTcpFlowInputs()` 的应用安装顺序

对每条记录，当前代码执行以下操作：

1. 在 `dst` 安装 `PacketSink(TcpSocketFactory)`，监听 `dst` 对应的 TCP 目的端口；
2. sink 在当前仿真时间启动；
3. 用 `TcpFlowFinish` 连接 sink 的 `Rx` trace。当累计接收字节达到目标大小时打印 TCP flow 完成时间；
4. 在 `src` 安装 `BulkSendApplication(TcpSocketFactory)`，目的地址为 `nodeInfos[dst].ip` 和分配的目的端口；
5. 设置 `MaxBytes=size_bytes`；sender 比 sink 晚 `1 ns` 启动；
6. 读取下一条 flow，并按下一条 flow 的 start time 继续调度。

sink 提前 1 ns 是事件排序保护：如果 sender 和 sink 在同一个时间戳同时安装/启动，TCP 建连事件可能先于接收端监听，导致 reset 或 ICMP 干扰。这是调度实现细节，不是网络传播延迟。

TCP flow 完成回调会在 `PacketSink::Rx` 累计 payload 达到目标大小时，将对应 `FlowInput::isFinished` 置为 true，并增加独立的 `tcp_finished_flows` 计数器。它不会增加 RDMA 专用的 `Settings::cnt_finished_flows`，因此 `flow_output` 仍主要是 RDMA flow 的完成记录，不能用它完整统计 TCP flow 的 FCT。

### 2.3 默认值的文档差异

`instructions/run_sim/README.md` 仍把 `--tcp_flow` 描述为“默认空字符串”，但当前 `run.py` 的 argparse 默认值是 `config/w-tcp-100.txt`。因此运行前必须检查：

```bash
python3 run.py --help | rg 'tcp_flow'
```

若需要纯 RDMA，显式传入空字符串：

```bash
python3 run.py --tcp_flow '' ...
```

若需要混跑，显式指定 TCP 文件并在 `config.txt` 中确认：

```bash
python3 run.py --tcp_flow config/w-tcp-100.txt ...
rg '^FLOW_FILE|^TCP_FLOW_FILE|^BUFFER_SIZE|^DCI_BUFFER_SIZE|^WAN_BUFFER_SIZE' mix/output/*/config.txt
```

不要根据旧 README 推断当前命令是否包含 TCP。

## 三、host 侧：TCP 和 RDMA 如何共享发送机会

### 3.1 两套队列对象

每个 `QbbNetDevice` 同时持有：

- `m_queue`：`BEgressQueue`，承载标准 NetDevice 入口的 TCP/IP 包，也承载交换机设备的按 qIndex 队列；
- `m_rdmaEQ`：`RdmaEgressQueue`，持有 RDMA QP group 和最高优先级 `m_ackQ`。

`RdmaEgressQueue::qCnt` 和 `QbbNetDevice::qCnt` 均为 8。q0 是控制/高优先级路径，TCP 固定使用 q1。RDMA flow 的 `pg` 可为其他优先级，常规 RDMA 数据不应被误写成 TCP q1。

### 3.2 TCP 入队

`QbbNetDevice::Send(packet, dest, protocolNumber)` 是 TCP 从 IPv4 协议栈进入 Qbb 设备的关键闭环。它使用 `Settings::tcp_queue_index`（由 `TCP_QUEUE_INDEX` 配置）选择队列：

1. 链路 down 时立即失败并触发 MAC TX drop；
2. 添加 PPP header；
3. 不解析 TCP flow 的 `pg`，使用 `qIndex=TCP_QUEUE_INDEX`；
4. 写入 enqueue trace；
5. 调用 `m_queue->Enqueue(packet, 1)`；
6. 若队列入队失败，写 drop trace 并返回 false；
7. 入队成功后调用 `DequeueAndTransmit()`。

这意味着 TCP 的 host egress queue 选择由 `protocolNumber` 所代表的标准网络入口和代码中的固定分类决定，不是由 TCP socket 端口或 TCP 拥塞窗口决定。

### 3.3 共享 TX machine 和调度优先级

`QbbNetDevice::DequeueAndTransmit()` 先检查链路状态、`m_txMachineState` 和各队列 pause 状态。设备忙时直接返回；传输完成后 `TransmitComplete()` 将状态恢复为 READY 并再次调用发送函数。

host 侧 `GetNextQindex()` 返回值：

| 返回值 | 含义 |
|---:|---|
| `-1` | 从 `m_ackQ` 取 ACK/CNP 等最高优先级包 |
| `-2` | 从 `BEgressQueue` 取 TCP/IP 包 |
| `0` 及以上 | 从对应 RDMA QP 取包 |
| `-1024` | 没有当前可发送的包 |

实际仲裁顺序是：

```text
ACK/CNP 高优先级
        |
        v
扫描可发送的 RDMA QP ---- RDMA candidate
        |                         |
        +---- TCP q1 ready -------+
                       |
          hostDequeueIndex 奇偶交替
                       |
               选择 TCP 或 RDMA
```

TCP ready 的判断是 `m_queue` 非空、`TCP_QUEUE_INDEX` 未被 pause、`m_queue->GetNBytes(TCP_QUEUE_INDEX)>0`。当 RDMA 没有可发送候选时直接服务 TCP；当两者都有候选时，`hostDequeueIndex` 的奇偶值决定本次选择。q3 共用模式下，TCP 与 PG3 RDMA 仍由 host TX scheduler 按 TCP/RDMA 候选交替仲裁，而不是由两个独立的队列轮询。该策略是最小化的交替策略，不是带权公平队列，也没有按字节数、flow 数、TCP cwnd 或 RDMA rate 做比例控制。

### 3.4 PFC 对 host TCP 的含义

TCP 使用和 RDMA 队列一样的 `m_paused[TCP_QUEUE_INDEX]` 状态。因此收到针对 TCP 队列的 PFC pause 时，host scheduler 不会从该队列取 TCP 包；收到 resume 后才恢复调度。q3 模式下这个状态与 RDMA PG3 完全相同。

但是 ACK/CNP 在 q0，q0 pause 状态独立于 q1。RDMA 控制反馈可能继续发送，而 TCP 数据被 q1 pause；反过来，q1 上 TCP 的积压不会自动修改 TCP 的拥塞窗口，除非 TCP 协议栈通过丢包/ACK/RTT 自己观察到影响。

## 四、接收侧和交换机侧协议识别

### 4.1 host `Receive()` 分流

接收包先检查 PFC (`l3Prot=0xFE`)。PFC 由 Qbb 设备处理并更新 `m_paused[]`，不交给普通 IPv4/TCP 协议栈。

对非 PFC 包：

- 交换机 node type：加上设备/接口相关 tag，调用 `SwitchReceiveFromDevice()`；
- host node type：调用 `m_rdmaReceiveCb(packet, ch)`，RDMA 数据、ACK、NACK、CNP 等由 RDMA 硬件模型处理；若返回值表示非 RDMA/普通 MPI 接收，则进入对应的 MPI 路径。

TCP 包要交给标准 IPv4/TCP 协议栈，当前改动在 `Receive()` 前部识别 PPP + IPv4 + TCP，并调用 `m_rxCallback`。这一步是 TCP 混跑能够成立的必要补丁；没有它，TCP 包会被当作不带 RDMA `CustomHeader` 语义的包，无法进入 `TcpL4Protocol`。

### 4.2 switch 侧 qIndex 规则

`SwitchNode::SendToDevContinue()` 的分类顺序是：

1. `0xFF` CNP、`0xFE` PFC，以及启用高优先级时的 `0xFD` NACK 和 `0xFC` ACK，统一进入 q0；
2. IPv4 TCP `0x06` 进入 `TCP_QUEUE_INDEX`；
3. UDP `0x11` 被当作 RDMA，进入包头 `ch.udp.pg` 指定的队列；
4. 其他 L4 协议回退到 q1，避免读取未初始化的 UDP PG。

ECMP 选择也区分协议：TCP 使用源/目的 IP 与 TCP 源/目的端口构造 hash，RDMA 使用 UDP 源/目的端口。故 TCP 和 RDMA 可以共享交换机路径选择框架，但它们的 queue index 仍由上述分类规则独立决定。

## 五、交换机 MMU：总容量、TCP q1 和 admission

### 5.1 总 buffer 的配置链路

配置链路为：

```text
run.py --buffer / --dci_buffer / --wan_buffer
        -> config.txt 的 BUFFER_SIZE / DCI_BUFFER_SIZE / WAN_BUFFER_SIZE
        -> scratch/remote.cc 解析
        -> SwitchMmu::ConfigBufferSize(bytes)
        -> SwitchMmu::InitSwitch()
        -> m_maxBufferBytes
```

当前交换机初始化行为：

- `DC_SWITCH`：直接使用 `buffer_size * 1024 * 1024`；`run.py` 默认 `buffer_size=9`，所以是 9 MiB；
- `DCI_SWITCH`：若 `DCI_BUFFER_SIZE>0` 使用显式值，否则 C++ 写入 160 MiB；
- `WAN_SWITCH`：若 `WAN_BUFFER_SIZE>0` 使用显式值，否则 C++ 写入 320 MiB；WAN 设备还设置 `QbbEnabled=false`，因此不能把 WAN switch 的行为等同于 DC 内启用 PFC 的交换机。

`ConfigBufferSize()` 只设置 `m_staticMaxBufferBytes`。`InitSwitch()` 中如果该值非零就直接使用；如果为零，才使用：

```text
m_maxBufferBytes = m_maxBufferBytesPerPort * m_activePortCnt
```

默认 `m_maxBufferBytesPerPort=375000` bytes。比如 12 个 active port 时约为 4.5 MB，32 个 active port 时约为 12 MB。这里的 MB 是代码中的十进制乘法，而 `--buffer` 转换使用 `1024*1024`，写报告时要说明单位口径。

### 5.2 TCP q1 隔离模式的固定 ingress 阈值

`InitSwitch()` 设置：

```cpp
m_tcp_pg_min_cell = 160 * 1024 * 1024;
m_tcp_port_min_cell = m_tcp_pg_min_cell;
```

只有 `TCP_QUEUE_INDEX=1` 时，`CheckIngressAdmission(port, qIndex, psize)` 才对 q1 使用以下特殊顺序：

1. 先检查全局总量：`m_usedTotalBytes + psize > m_maxBufferBytes`；失败则丢包；
2. 如果 `qIndex==1`，检查 `m_usedIngressPGBytes[port][1] + psize > m_tcp_pg_min_cell`；失败则丢包；
3. q1 成功时直接返回，不走普通 PG 的 shared pool/headroom 分支。

成功入队后 `UpdateIngressAdmission()` 会增加：

- `m_usedTotalBytes`；
- `m_usedIngressPortBytes[port]`；
- `m_usedIngressPGBytes[port][1]`。

q1 隔离模式不增加 `m_usedIngressSPBytes`，出队时也不从 shared pool 扣减。也就是说，160 MiB 是当前代码中的 q1 ingress PG 计数上限，不是一个从总容量中预先切出的、自动隔离的物理池。全局总量仍由所有被 admission 记账的流量共同消耗。`TCP_QUEUE_INDEX=3` 时，q3 不走该特判，TCP 与 RDMA PG3 一起更新和扣减普通 shared-pool accounting。

### 5.3 egress admission 当前不构成独立丢包门槛

`SwitchNode::DoSwitchSend()` 对 q0 之外的包依次调用 egress admission 和 ingress admission。但当前 `SwitchMmu::CheckEgressAdmission()` 直接 `return true`，因此 TCP q1 和 RDMA 数据在交换机侧没有实际生效的独立 egress admission 阈值。

这不代表 egress 没有队列字节统计：`UpdateEgressAdmission()` 仍会增加 `m_usedEgressBytes[outDev][qIndex]`，出队时 `RemoveFromEgressAdmission()` 会扣减；只是这个统计目前不负责拒绝入队。任何报告都应把“egress bytes 监控”和“egress admission drop”分开。

### 5.4 q1 隔离模式的 PFC pause/resume

只有 q1 隔离模式启用以下 TCP 特殊 pause threshold：

```text
pause_threshold = max(160 MiB - m_pg_hdrm_limit[port], 0)
resume_threshold = max(pause_threshold - 2*MTU, 0)
```

`GetPauseClasses()` 在静态和动态阈值路径中都对 q1 做这项特殊检查；q1 使用量超过 pause threshold 时将 q1 标记为 pause class。`GetResumeClasses()` 只有在 q1 已经 paused 且使用量低于 resume threshold 时才恢复，形成 2 MTU 的滞回区间。q3 共用模式不使用 160 MiB 特殊 pause/resume 阈值，而沿用普通 PG3 逻辑。

这套逻辑的含义是：

- PFC 的触发点低于 q1 的固定物理上限，为链路传播和接收处理预留 headroom；
- q1 pause 会同时影响 host 上发出的 TCP q1 和交换机向下一跳发出的 q1；
- PFC 本身不改变 TCP cwnd，也不调用 RDMA CC；它只是阻止相应 qIndex 的设备发送，直到 resume；
- 如果 PFC 被禁用，pause/resume 不会提供无损保证，队列超过 admission 条件时仍可能丢包。

### 5.5 ECN 标记

交换机出队时 `SwitchNotifyDequeue()` 对 q0 之外的包执行 ingress/egress accounting，并在 `m_ecnEnabled` 且 `ShouldSendCN(ifIndex,qIndex)` 为真时修改 IPv4 ECN bits 为 CE (`0x03`)。

对于 RDMA UDP，CE/CNP 反馈可以进入 RDMA hardware/DCQCN 逻辑；对于 TCP，当前代码路径只明确完成了 IPv4/TCP 上交和 q1 分类，不能据此声称已经实现了 DCTCP 端到端反馈。是否由 TCP socket 读取 CE、使用何种 TCP congestion control、以及 `CC_MODE` 对 TCP 是否生效，都应通过专门实验和协议栈代码继续验证。

## 六、丢包、统计与可观测性

### 6.1 交换机丢包

`SwitchNode::DoSwitchSend()` 中：

- ingress admission 失败：增加 `Settings::dropped_pkt_sw_ingress`，写 `drop_log`，`type=0`；
- egress admission 失败：增加 `Settings::dropped_pkt_sw_egress`，写 `drop_log` 的逻辑只对 UDP/RDMA 分支打印额外信息，`type=1`；
- 当前 egress admission 恒真，所以当前工作树中主要应关注 global buffer 或 q1 ingress admission 导致的丢包。

`drop_log` header 是：

```text
timestamp_ns,switch_id,next_hop,flow_id,seq_num,type
```

TCP 的 `seq_num` 仍来自 `CustomHeader` 读取结果，但 TCP 并不是 RDMA UDP 序号；对 TCP drop 做逐包 TCP 序号语义分析前，必须确认该 header 字段是否已正确填入，否则只能可靠使用时间、交换机、下一跳、协议/flow fallback 等信息。

### 6.2 buffer_monitor 的实际列含义

`SwitchMmu::printBufferInfo()` 写：

```text
timestamp_ns,switch_id,next_hop,ingress_bytes,egress_bytes
```

其中：

- `ingress_bytes` 是该 ingress port 的累计 ingress accounting；
- `egress_bytes` 当前实现是 `m_usedEgressBytes[port][0] + m_usedEgressBytes[port][3]`。

因此 `buffer_monitor.egress_bytes` 不是所有 qIndex 的总和，特别不是 TCP q1 的专用队列长度。仅使用现有 `buffer_monitor` 无法直接回答“TCP q1 的 egress peak buffer 是多少”。若要回答，需新增按 qIndex 记录，或直接从 `BEgressQueue::GetNBytes(1)` 周期采样；新增 CSV 时必须同步更新分析脚本和 header。

### 6.3 flow_output 和 TCP FCT

`flow_output` 由 `scratch/remote.cc::output_flow_info()` 写出，主要来自 RDMA flow 完成回调。TCP 目前通过 `TcpFlowFinish` 在标准输出打印完成时间，并在仿真结束前把输入元数据写入：

```text
<output_dir>/tcp_flows.txt
```

该文件包含 `idx src dst start_time_s size_bytes`，但不包含完成时间。因此 TCP FCT 目前不能像 RDMA 那样直接从 `flow_output` 得到；要计算 TCP FCT，需要保存回调中的 finish time，或者从应用 trace/log 采集并与 `tcp_flows.txt` 对齐。

### 6.4 推荐的最小诊断集合

每个混跑实验至少保存并检查：

| 文件/来源 | 能回答的问题 | 主要限制 |
|---|---|---|
| `config.txt` | 实际拓扑、RDMA flow、TCP flow、buffer、PFC、CC 配置 | 只说明配置，不说明运行时是否成功发包 |
| `tcp_flows.txt` | TCP 输入 flow 的 src/dst/大小/启动时间 | 当前没有完成时间 |
| `buffer_monitor` | 周期性的 ingress 和部分 egress 占用 | egress 只汇总 q0+q3；q3 共用模式下会包含 TCP q3，但仍无法单独拆分 TCP/RDMA |
| `drop_log` | 交换机 ingress/egress drop 时间和位置 | TCP 的 seq 字段未必有 RDMA 语义 |
| `link_utilization` | 链路、flow fallback 和字节记录 | TCP flow id 可能使用合成 fallback |
| `flow_output` | RDMA 完成/FCT 等结果 | 不应当当作完整 TCP 完成表 |
| stdout/config.log | TCP flow finish print、启动异常和 warning | 文本日志不适合无损聚合 |

分析入口可使用 `analysis/deep_analyse.py` 读取 `flow_output`、`drop_log`、`buffer_monitor` 和 `link_utilization`。`analysis/tcp.py` 当前主要是一个 TCP bandwidth 与示例 FCT 曲线绘图脚本，内含示例数组，不能把它当作自动读取当前实验结果的分析器。

## 七、运行建议和实验设计

本节只给出复现实操，不启动实验。典型命令形态为：

```bash
python3 run.py \
  --my_flow <rdma_flow_stem> \
  --tcp_flow config/<tcp_flow>.txt \
  --buffer 9 \
  --pfc 1 \
  --msg tcp-rdma-coexist-buffer
```

运行后先定位带有 message/tag 的输出目录，再检查 `config.txt`，不要只依赖 `latest` 目录。纯 RDMA 对照应显式使用 `--tcp_flow ''`；TCP-only 或 RDMA-only 对照也应明确关闭另一类输入，避免默认值造成误判。

建议至少设置以下对照：

| 对照 | RDMA flow | TCP flow | 目的 |
|---|---|---|---|
| A | 有 | 空 | RDMA 基线及纯 RDMA buffer/drop |
| B | 空/最小 | 有 | TCP 单独运行，检查 TCP 协议栈闭环 |
| C | 有 | 有 | 观察 host TX 仲裁、共享 MMU 和相互影响 |
| D | 有 | 有，改变 TCP 总字节或启动时间 | 区分持续 TCP 背景负载和启动突发 |
| E | 有 | 有，改变 `--buffer` | 验证总 buffer 先决上限，而不是只观察 160 MiB 阈值 |

每组都应核对：

1. `config.txt` 是否包含预期的 `TCP_FLOW_FILE`；
2. `tcp_flows.txt` 是否生成且 flow 数量与输入一致；
3. 日志中是否出现每条 TCP flow 的 finish 输出；
4. RDMA `flow_output` 是否完成，是否因提前停止或硬停止而截断；
5. `drop_log` 的热点交换机和 drop type；
6. `buffer_monitor` 的 ingress 趋势，但不要将其 egress 列误称为 TCP q1；
7. 对 TCP FCT 采用独立 finish-time 记录，而不是直接从 RDMA `flow_output` 推断。

## 八、当前实现的边界和风险

### 8.1 不能直接声称“TCP 获得了 RDMA 的拥塞控制”

TCP 只复用了 Qbb 设备、交换机队列、PFC/ECN 可能产生的网络信号和共享链路。TCP 的可靠传输、重传、拥塞窗口、ACK 和 cwnd 更新仍由 ns-3 TCP 栈负责。RDMA 的 DCQCN/CNP、QP rate 和 PFC 记录不会自动成为 TCP 的控制状态。

### 8.2 q1 不是严格的 TCP 隔离 buffer，q3 是显式共用模式

`TCP_QUEUE_INDEX=1` 时，q1 在计数和 admission 上有独立的 160 MiB 特判，但所有通过 admission 的 q1 包仍增加全局 `m_usedTotalBytes`。在默认 DC 总 buffer 9 MiB 时，总量先到上限；在大 buffer 配置下，q1 的 per-port/per-PG 上限才可能成为实际控制因素。`TCP_QUEUE_INDEX=3` 时，TCP 与 RDMA PG3 使用相同的普通 shared-pool/headroom 逻辑，不存在 TCP 专用 160 MiB 阈值。

### 8.3 host 侧调度不是带宽配额

交替策略只能说明当 TCP 和 RDMA 都 ready 时大致按发送机会交替。包大小、RDMA QP 的 rate gate、TCP socket 的 cwnd、PFC pause、链路速率都会让最终字节带宽比例偏离 50/50。不要把 `hostDequeueIndex` 的奇偶逻辑解释为“TCP 得到 50% 链路带宽”。

### 8.4 TCP 输入调度依赖 flow 文件按 start time 排序

`ScheduleTcpFlowInputs()` 只检查 `tcpFlowInfos.back().start_time`，然后按下一条记录继续调度。因此输入记录应按非递减启动时间排列；若乱序，后面的 flow 可能被延迟或调度时间表达式异常。

### 8.5 硬停止可能截断 TCP

混跑时的提前停止条件现在是 RDMA 和 TCP 两类 flow 都完成；除此之外仍有 `Simulator::Stop(Seconds(flowgen_stop_time + 10.0))` 的硬停止兜底。长 RTT、大 TCP flow 或发生大量丢包/重传时，必须检查是否在兜底硬停止前完成；否则 finish 输出和 FCT 结论不完整。停止日志会同时打印 `RDMA finished/total` 和 `TCP finished/total`。

### 8.6 当前日志不足以精确分离 TCP q1

如果研究问题是“TCP q1/q3 在交换机上的峰值占用、TCP 与 RDMA PG 的精确竞争比例”，现有日志不够。建议新增以下周期采样字段，而不是每包写日志：

```text
timestamp_ns,switch_id,port,qindex,ingress_pg_bytes,egress_q_bytes,total_bytes,paused
```

同时在 host 侧按设备记录：

```text
timestamp_ns,host_id,if_index,tcp_q1_bytes,rdma_bytes_left,paused_q1,tx_state
```

修改日志后必须同步更新 `analysis/deep_analyse.py` 或新增独立分析脚本，并保持 CSV header 与列顺序稳定。

## 九、源码索引

| 机制 | 文件和函数 |
|---|---|
| TCP 参数写入 | `run.py` argparse、生成 `TCP_FLOW_FILE` 和 `TCP_QUEUE_INDEX` |
| TCP flow 解析 | `scratch/remote.cc::ReadTcpFlowInput()` |
| TCP 应用安装 | `scratch/remote.cc::ScheduleTcpFlowInputs()` |
| TCP 完成打印 | `scratch/remote.cc::TcpFlowFinish()` |
| 混跑 stop 保护 | `scratch/remote.cc::stop_simulation_middle()` |
| TCP host 入队 | `src/point-to-point/model/qbb-net-device.cc::QbbNetDevice::Send()` |
| host TCP/RDMA 仲裁 | `RdmaEgressQueue::GetNextQindex()`、`QbbNetDevice::DequeueAndTransmit()` |
| host TCP 接收分流 | `QbbNetDevice::Receive()` |
| switch 协议分类 | `src/point-to-point/model/switch-node.cc::SendToDevContinue()` |
| switch admission/drop | `SwitchNode::DoSwitchSend()` |
| 出队 ECN/PFC 处理 | `SwitchNode::SwitchNotifyDequeue()` |
| 总 MMU 初始化 | `src/point-to-point/model/switch-mmu.cc::ConfigBufferSize()`、`InitSwitch()` |
| q1 隔离阈值 | `SwitchMmu::m_tcp_pg_min_cell`、`CheckIngressAdmission()`（仅 `TCP_QUEUE_INDEX=1`） |
| q1 pause/resume | `SwitchMmu::GetPauseClasses()`、`GetResumeClasses()` |
| buffer 监控 | `SwitchMmu::printBufferInfo()` |
| flow id fallback | `src/point-to-point/model/settings.cc::Settings::get_flowid()` |
| 日志初始化 | `settings.cc::logfile::initialize_log()` |
| Python 分析 | `analysis/deep_analyse.py`；TCP 示例绘图为 `analysis/tcp.py` |

## 十、最终判断

当前实现已经形成了 TCP/RDMA 混跑的最小闭环：TCP 应用可以启动，TCP 包可以经 QbbNetDevice 进入可配置的 q1/q3，TCP 与 RDMA 可以共用 host TX machine，交换机可以按协议分类并在 MMU/PFC/ECN 路径中处理；停止逻辑也会分别跟踪两类 flow，只有两类都完成才提前结束。

但它还不是一个完整的“TCP 与 RDMA 统一拥塞控制模型”：TCP 不计入 RDMA flow 完成统计，TCP q1 的交换机 egress admission 没有实际门槛，现有 `buffer_monitor` 不能直接观测 q1 egress，TCP FCT 也没有结构化写入结果文件。后续任何性能结论都应以显式的 TCP finish-time、按 qIndex 的 buffer 采样和 `config.txt` 实际配置为依据。
