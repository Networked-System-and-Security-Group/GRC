# FEC 代码改动清单（面向实现）

## 目的

本文档基于当前代码，明确为了完成 [fec_mn_implementation_plan.md](/home/niuzihan26/gscc/RDMA-WAN-Optimization/instructions/fec_mn_implementation_plan.md) 里的目标，需要增加、修改哪些类的哪些方法和变量。

本次目标是：

- 每组先发 `n` 个冗余包，再发 `m` 个正常包
- `m` 与 ACK 频率一致
- 冗余包和正常包的 `seq` 分离
- `config` 里给一个默认 `n`
- 每条流输入时先绑定这个默认 `n`
- 建流时把每条流最终绑定好的 `n` 传入 `RdmaHw`

## 当前代码现状

当前实现的几个关键事实：

- 发送端只维护一套字节序号：
  - `RdmaQueuePair::snd_nxt`
  - `RdmaQueuePair::snd_una`
- 接收端只维护一套累计期望序号：
  - `RdmaRxQueuePair::ReceiverNextExpectedSeq`
- `GetNxtPacket()` 每次只生成一个普通 UDP 数据包：
  - [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L747)
- `ReceiveUdp()` + `ReceiverCheckSeq()` 默认所有 UDP 数据包都进入同一套累计 ACK / NACK 逻辑：
  - [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L313)
  - [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L589)
- `FlowIDNUMTag` 当前只承载：
  - `flow_stat`
  - `flow_size`
  - `ack_req`
  - [src/network/model/flow-id-num-tag.h](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/network/model/flow-id-num-tag.h)
- `L2_ACK_INTERVAL` 当前在 `remote.cc` 中作为字节数读取，并作为 `RdmaHw::m_ack_interval` 下发：
  - [scratch/remote.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/scratch/remote.cc#L1073)
  - [scratch/remote.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/scratch/remote.cc#L1605)
- `wan-routing.cc` 会读取 `ack_req` 做 RTT 采样过滤：
  - [src/point-to-point/model/wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L182)

因此，要实现 FEC，不能只改一个函数，必须把发送状态、接收状态、tag、配置入口一起改。

另外，当前建流链路已经天然是 per-flow 的：

- `Settings::flowInfos[i]`
- `ScheduleFlowInputs()`
- `RdmaClientHelper`
- `RdmaClient`
- `RdmaDriver::AddQueuePair(...)`
- `RdmaHw::AddQueuePair(...)`

所以 `n` 最合理的落点不是“运行时只存在一个 `RdmaHw` 全局变量”，而是：

- config 提供默认值
- 先绑定到 `FlowInput`
- 再传到 `RdmaQueuePair`

## 文件级改动清单

### 1. `scratch/remote.cc`

职责：

- 读取 `config.txt`
- 保存全局仿真配置
- 创建并配置 `RdmaHw`

当前相关变量：

- `packet_payload_size`
- `l2_chunk_size`
- `l2_ack_interval`
- [scratch/remote.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/scratch/remote.cc#L64)

#### 需要新增的变量

需要新增的变量建议为：

- `uint32_t default_fec_parity_pkts = 0;`

它的语义是：

- config 输入阶段的默认 `n`

不是：

- 运行中所有流共享的唯一 `n`

#### 需要修改的配置解析

要在现有 `while(conf >> key)` 分支中新增：

- `FEC_PARITY_PKTS`

其语义改成：

- 默认 `n`

对应修改位置：

- `main()` 里 config 解析分支
- [scratch/remote.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/scratch/remote.cc#L1020)

#### 需要修改的 `RdmaHw` 属性下发

当前会设置：

- `L2AckInterval`
- `Mtu`
- 其他 CC 参数

这里不再建议设置全局：

- `FecParityPkts`

因为 `n` 已经不是全局常量。

对应修改重点转移到：

- `ReadFlowInput()`
- `ScheduleFlowInputs()`

也就是在建流调用 `RdmaClientHelper` 前，把 flow 自己的 `n` 传下去。

#### 这里的实现注意点

- `m` 不建议作为独立 config 变量传入
- 当前代码中 `m` 应由：
  - `m = l2_ack_interval / packet_payload_size`
- 因此 `remote.cc` 至少要负责：
  - 校验 `l2_ack_interval % packet_payload_size == 0`
  - 如果不能整除，直接报错或拒绝启用 FEC

### 2. `run.py`

职责：

- 生成实验用 `config.txt`

当前相关位置：

- `config_template`
- [run.py](/home/niuzihan26/gscc/RDMA-WAN-Optimization/run.py#L22)

#### 需要新增的配置项

如果 `run.py` 仍然负责生成配置，建议做成：

- config 主体写一个默认 `FEC_PARITY_PKTS`
- flow 文件格式保持不变

#### 需要新增的命令行参数

建议新增：

- `--fec-n`
- 可选：`--enable-fec`

其中：

- `--fec-n` 表示生成 config 时的默认 `n`
- 不是运行时全局唯一 `n`

#### 需要新增的模板变量

- 可选：`enable_fec`

#### 这里的实现注意点

- `run.py` 不需要直接计算组状态
- flow 文件格式不变
- `m` 仍然由 `L2_ACK_INTERVAL` 和 `PACKET_PAYLOAD_SIZE` 间接表达

flow 文件格式继续保持：

```
<src> <dst> <pg> <size_bytes> <start_time_seconds>
```

`remote.cc::ReadFlowInput()` 在读入每条 flow 时，直接把 config 默认 `n` 绑定到该 flow。

### 2.5 `src/point-to-point/model/settings.h`

职责：

- 定义 `FlowInput`

当前 `FlowInput`：

- `src`
- `dst`
- `pg`
- `fsize`
- `port`
- `start_time`
- `idx`
- [src/point-to-point/model/settings.h](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/settings.h#L96)

#### 需要新增的变量

- `uint32_t fec_n = 0;`

这是本次“config 默认值 + per-flow 绑定”模式的关键挂载点。

原因：

- 当前所有 RDMA 流本来就先进入 `Settings::flowInfos`
- 每条流最终生效的 `n` 最自然就是跟着 `FlowInput` 走

### 3. `src/network/model/flow-id-num-tag.h`
### 4. `src/network/model/flow-id-num-tag.cc`

职责：

- 给包附加 flow 级 tag

当前字段：

- `int32_t flow_stat`
- `uint32_t flow_size`
- `uint8_t ack_req`

当前接口：

- `SetId()/GetId()`
- `SetFlowSize()/GetFlowSize()`
- `SetAckReq()/GetAckReq()`

#### 需要新增的字段

建议新增：

- `uint8_t fec_enabled`
- `uint8_t fec_pkt_role`
- `uint32_t fec_group_id`
- `uint16_t fec_group_m`
- `uint16_t fec_group_n`
- `uint32_t fec_group_data_start_seq`
- `uint16_t fec_data_idx`
- `uint16_t fec_repair_idx`
- `uint32_t fec_repair_seq`
- `uint16_t fec_tx_ordinal`

其中最关键的是：

- `fec_pkt_role`
- `fec_group_id`
- `fec_group_data_start_seq`
- `fec_data_idx`
- `fec_repair_idx`

#### 需要新增的方法

建议新增：

- `void SetFecEnabled(uint8_t v);`
- `uint8_t GetFecEnabled() const;`
- `void SetFecPktRole(uint8_t role);`
- `uint8_t GetFecPktRole() const;`
- `void SetFecGroupId(uint32_t id);`
- `uint32_t GetFecGroupId() const;`
- `void SetFecGroupM(uint16_t m);`
- `uint16_t GetFecGroupM() const;`
- `void SetFecGroupN(uint16_t n);`
- `uint16_t GetFecGroupN() const;`
- `void SetFecGroupDataStartSeq(uint32_t seq);`
- `uint32_t GetFecGroupDataStartSeq() const;`
- `void SetFecDataIdx(uint16_t idx);`
- `uint16_t GetFecDataIdx() const;`
- `void SetFecRepairIdx(uint16_t idx);`
- `uint16_t GetFecRepairIdx() const;`
- `void SetFecRepairSeq(uint32_t seq);`
- `uint32_t GetFecRepairSeq() const;`
- `void SetFecTxOrdinal(uint16_t idx);`
- `uint16_t GetFecTxOrdinal() const;`

#### 需要修改的方法

- `GetSerializedSize()`
- `Serialize()`
- `Deserialize()`
- `Print()`

原因：

- 现有 tag 序列化大小只覆盖 `flow_stat + flow_size + ack_req`
- 扩展字段后必须同步修改这四个方法

#### 这里的实现注意点

- `ack_req` 仍然保留，不能删
- 因为 `wan-routing.cc` 目前依赖它
- FEC 第一版不要求交换机理解其他 FEC 字段，但它们要能在 host 侧收发完整传递

### 5. `src/point-to-point/model/rdma-queue-pair.h`
### 6. `src/point-to-point/model/rdma-queue-pair.cc`

职责：

- 保存每个发送 flow 的状态
- 保存每个接收 flow 的状态

当前发送侧关键变量：

- `m_size`
- `snd_nxt`
- `snd_una`
- `m_retransmit`
- `GetBytesLeft()`
- `Acknowledge()`
- `GetOnTheFly()`
- `IsFinished()`

当前接收侧关键变量：

- `ReceiverNextExpectedSeq`
- `m_nackTimer`
- `m_milestone_rx`
- `m_lastNACK`

#### 发送侧 `RdmaQueuePair` 需要新增的变量

建议新增一个 FEC 子结构，例如：

- `struct FecTxState { ... } fec;`

里面至少要有：

- `bool enabled;`
- `uint32_t fec_n;`
- `uint32_t next_group_id;`
- `bool group_active;`
- `uint32_t active_group_id;`
- `uint32_t active_group_data_start_seq;`
- `uint32_t active_group_data_bytes;`
- `uint16_t active_group_m;`
- `uint16_t active_group_n;`
- `uint16_t active_group_tx_cursor;`
- `uint16_t active_group_repair_sent;`
- `uint16_t active_group_data_sent;`
- `uint32_t active_group_repair_seq_base;`
- `uint32_t active_group_repair_seq_next;`
- `uint64_t data_snd_nxt;`
- `uint64_t data_snd_una;`

这里有一个关键决定：

- 现有 `snd_nxt/snd_una` 是否继续表示“正常数据字节”

建议：

- 保留 `snd_nxt/snd_una` 继续只表示正常数据字节
- 不让冗余包推进它们
- FEC 额外在 `fec` 子结构里维护组发送进度和冗余发送进度

#### 接收侧 `RdmaRxQueuePair` 需要新增的变量

建议新增一个 FEC 子结构，例如：

- `struct FecRxState { ... } fec;`

至少需要：

- `bool enabled;`
- `uint32_t fec_n_current;`
- `uint32_t acked_group_id_upto;`
- `std::unordered_map<uint32_t, FecGroupRxState> groups;`

其中 `FecGroupRxState` 建议包含：

- `uint32_t group_id;`
- `uint32_t data_start_seq;`
- `uint16_t m_snapshot;`
- `uint16_t n_snapshot;`
- `uint16_t repair_received;`
- `uint16_t data_received;`
- `uint16_t total_received;`
- `bool recoverable;`
- `bool ack_emitted;`
- `std::vector<uint8_t> data_bitmap;`
- `std::vector<uint8_t> repair_bitmap;`

#### `RdmaQueuePair` 需要新增的方法

建议新增：

- `uint32_t GetAckGroupPkts() const;`
- `bool HasBytesToSend() const;`
- `bool FecGroupActive() const;`
- `void StartNextFecGroup(uint32_t m, uint32_t n, uint32_t mtu);`
- `bool IsFecFinished() const;`

这里不一定都要放在 `RdmaQueuePair` 上，也可以部分放到 `RdmaHw`，但至少要有一个清晰的 per-QP 状态入口。

#### `RdmaQueuePair` 需要修改的方法

- `GetBytesLeft()`
- `GetOnTheFly()`
- `IsFinished()`
- `Acknowledge()`

原因：

- 这些方法现在只理解“纯正常数据字节流”
- 引入 FEC 后，至少要决定：
  - `GetBytesLeft()` 返回是否只看正常数据
  - `GetOnTheFly()` 是否要把冗余包也算进去
  - `IsFinished()` 是否要等当前组冗余也发完

建议：

- `GetBytesLeft()` 仍然只返回正常数据剩余
- `GetOnTheFly()` 需要增加“冗余在途”统计，或者由 `RdmaHw` 单独处理
- `IsFinished()` 要改成：
  - 正常数据已全部 ACK
  - 且无活动 FEC 组待发送/待清理

### 7. `src/point-to-point/model/rdma-hw.h`
### 8. `src/point-to-point/model/rdma-hw.cc`

这是本次改造的主入口。

当前关键接口：

- `AddQueuePair()`
- `ReceiveUdp()`
- `ReceiveAck()`
- `ReceiverCheckSeq()`
- `GetNxtPacket()`
- `RecoverQueue()`
- `HandleTimeout()`

#### `RdmaHw` 需要新增的成员变量

建议新增：

- `bool m_fecEnabled;`

不建议新增：

- `m_fecParityPktsDefault`

因为这会把“运行时生效的 `n`”又做回全局量。

`RdmaHw` 最多只需要：

- 一个全局 FEC 开关

而每条流绑定后的 `n` 应保存在：

- `RdmaQueuePair`

严格来说，`m` 仍然可由：

- `m_ack_interval / m_mtu`

推导出来。

#### `RdmaHw` 需要新增的公共方法

建议新增：

- `uint32_t GetFecDataPktsPerGroup() const;`
- `bool IsFecEnabled() const;`

如果要支持按流运行时修改，也不要设计成：

- `SetFecParityPkts(uint32_t n)`

而应设计成：

- `SetFlowFecParityPkts(Ptr<RdmaQueuePair> qp, uint32_t n)`

或者：

- `SetFlowFecParityPktsByFlowId(int32_t flow_id, uint32_t n)`

#### `RdmaHw` 需要新增的私有辅助方法

建议新增：

- `bool IsFecDataPacket(const FlowIDNUMTag& fit) const;`
- `bool IsFecRepairPacket(const FlowIDNUMTag& fit) const;`
- `uint32_t GetFecGroupM() const;`
- `void InitFecGroupIfNeeded(Ptr<RdmaQueuePair> qp);`
- `Ptr<Packet> BuildFecRepairPacket(Ptr<RdmaQueuePair> qp);`
- `Ptr<Packet> BuildFecDataPacket(Ptr<RdmaQueuePair> qp);`
- `void AttachFecTagForRepair(Ptr<Packet> p, Ptr<RdmaQueuePair> qp);`
- `void AttachFecTagForData(Ptr<Packet> p, Ptr<RdmaQueuePair> qp);`
- `int ReceiveFecRepair(Ptr<Packet> p, CustomHeader& ch, Ptr<RdmaRxQueuePair> rxQp, FlowIDNUMTag& fit);`
- `int ReceiveFecData(Ptr<Packet> p, CustomHeader& ch, Ptr<RdmaRxQueuePair> rxQp, FlowIDNUMTag& fit);`
- `bool TryAdvanceFecAck(Ptr<RdmaRxQueuePair> rxQp, uint32_t& ack_seq_out);`
- `void ResetFecTxStateForRecovery(Ptr<RdmaQueuePair> qp);`
- `uint32_t GetFlowFecParityPkts(const Ptr<RdmaQueuePair>& qp) const;`

#### `GetTypeId()` 需要新增属性

当前 `RdmaHw` 用 attribute 下发配置：

- `L2AckInterval`
- `Mtu`
- 等等

要新增：

- `FecEnable`

对应位置：

- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L32)

不建议把 `FecParityPkts` 做成 `RdmaHw` attribute，因为 attribute 是 host 级，不是 flow 级。

#### `AddQueuePair()` 需要修改

当前只初始化普通 QP 状态：

- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L192)

要新增：

- 初始化 `qp->fec.enabled`
- 初始化 `qp->fec.fec_n`
- 初始化 `qp->fec.next_group_id`
- 初始化发送侧组状态

如果接收侧也想在创建时预热配置，也可以在 `GetRxQp()` 中一并初始化 FEC 默认值。

#### `GetRxQp()` 需要修改

当前只初始化：

- `sip/dip/sport/dport`
- `m_ecn_source.qIndex`
- `m_flow_id`

要新增：

- 初始化 `rxQp->fec.enabled`
- 初始化 `rxQp->fec.groups`
- 初始化 `acked_group_id_upto`

接收侧不需要预先知道 `n` 来自哪里，它只需要从首批到达包的 tag 中拿到该 flow/该组最终生效的 `n_snapshot`。

#### `GetNxtPacket()` 需要修改

这是发送逻辑主入口，必须改。

当前行为：

- 取 `qp->GetBytesLeft()`
- 用 `snd_nxt` 作为 `seq`
- 直接构造普通 UDP 数据包
- `ack_req` 基于 `seq % m_ack_interval == 0`
- 最后 `snd_nxt += payload_size`

当前位置：

- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L747)

要改成：

- 如果 FEC 关闭：
  - 保持原逻辑
- 如果 FEC 开启：
  - 若当前组不存在，创建新组
  - 若当前组还有本 flow 自己的 `repair` 未发，优先发 `repair`
  - 否则发送 `data`
  - `data` 包推进 `snd_nxt`
  - `repair` 包不推进 `snd_nxt`
  - `ack_req` 只在该组最后一个 `data` 包上置位，或者按“该组已满足 ACK 边界”的语义置位

#### `ReceiveUdp()` 需要修改

当前行为：

- 读 `ack_req`
- 统一调用 `ReceiverCheckSeq(ch.udp.seq, ...)`
- 根据返回值决定 ACK / NACK

当前位置：

- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L313)

要改成：

- 先从 `FlowIDNUMTag` 解析 FEC 信息
- FEC 关闭时保持原逻辑
- FEC 开启时按 `fec_pkt_role` 分流：
  - `repair` -> `ReceiveFecRepair()`
  - `data` -> `ReceiveFecData()`
- ACK 生成条件不再只依赖旧 `ReceiverCheckSeq()` 返回值

#### `ReceiverCheckSeq()` 需要修改

当前假设所有包都属于正常累计字节流：

- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L589)

这在 FEC 模式下不再成立。

建议改法：

- 保留原函数用于“非 FEC”路径
- 新增 FEC 专用组判断逻辑，不要强行把 `repair` 包塞进 `ReceiverCheckSeq()`

更具体地说：

- `ReceiverCheckSeq()` 最多只处理 `data` 包的正常累计边界
- `repair` 包只能更新组状态，不能走这条函数的旧累计逻辑

#### `ReceiveAck()` 需要修改

当前行为：

- `seq` 直接当成字节 ACK
- `qp->Acknowledge(seq)`
- 必要时 `RecoverQueue(qp)`

当前位置：

- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L428)

要新增处理：

- FEC 开启时，ACK 仍然只确认正常数据字节边界
- 但发送侧还要同步清理：
  - 已经被 ACK 覆盖的组状态
  - 已无意义的冗余发送状态

因此这里需要增加：

- 根据 `ack seq` 推导哪些 FEC 组已完成
- 清理 `qp->fec` 中对应组状态

#### `RecoverQueue()` 需要修改

当前实现过于简单：

- `qp->snd_nxt = qp->snd_una;`
- [src/point-to-point/model/rdma-hw.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-hw.cc#L700)

FEC 开启后不够用，因为还要回退：

- 当前活动组发送游标
- 当前组已发的 `repair/data` 计数
- 当前组重传起点

否则：

- `snd_nxt` 回去了
- 但 `fec` 组内游标没回去
- 后续发送状态会错

#### `HandleTimeout()` 需要修改

虽然这次计划不先重做超时策略，但 timeout 触发后会调用恢复路径。

因此 FEC 开启后，这里至少要保证：

- 恢复后发送状态与组状态一致

### 9. `src/applications/model/rdma-client.h`
### 10. `src/applications/model/rdma-client.cc`

职责：

- Application 层创建一条 RDMA 流

当前相关变量：

- `m_size`
- `m_pg`
- `m_sip/m_dip`
- `m_sport/m_dport`
- `m_baseRtt`
- `m_flow_id`
- [src/applications/model/rdma-client.h](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/applications/model/rdma-client.h)

#### 需要新增的变量

- `uint32_t m_fec_n;`

#### 需要修改的方法

- `GetTypeId()`
  - 新增一个 attribute，例如 `FecParityPkts`
- `StartApplication()`
  - 调用 `rdma->AddQueuePair(...)` 时把 `m_fec_n` 传下去

当前位置：

- [src/applications/model/rdma-client.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/applications/model/rdma-client.cc#L140)

### 11. `src/applications/helper/rdma-client-helper.h`

职责：

- 把 flow 参数写进 `RdmaClient` 对象

#### 需要修改的内容

- 增加设置 `FecParityPkts` attribute 的入口

虽然可以直接沿用 `SetAttribute(...)`，但文档里要明确：

- `ScheduleFlowInputs()` 必须把 `flowInfo.fec_n` 经 `clientHelper.SetAttribute(...)` 写给 `RdmaClient`

### 12. `src/point-to-point/model/rdma-driver.h`
### 13. `src/point-to-point/model/rdma-driver.cc`

职责：

- 把应用层建流请求转发给 `RdmaHw`

当前方法：

- `AddQueuePair(uint64_t size, ..., int32_t flow_id)`
- [src/point-to-point/model/rdma-driver.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/rdma-driver.cc#L64)

#### 需要修改的方法签名

建议改成：

- `AddQueuePair(..., int32_t flow_id, uint32_t fec_n)`

原因：

- 这是 per-flow `n` 从应用层进入 `RdmaHw` 的必经路径

### 14. `src/point-to-point/model/qbb-net-device.h`
### 15. `src/point-to-point/model/qbb-net-device.cc`

这部分本次不改包格式，但有一个恢复接口要同步考虑。

当前相关方法：

- `RdmaEgressQueue::RecoverQueue(uint32_t i)`
- [src/point-to-point/model/qbb-net-device.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/qbb-net-device.cc#L198)

当前行为：

- 直接 `snd_nxt = snd_una`

#### 需要修改的方法

- `RdmaEgressQueue::RecoverQueue(uint32_t i)`

#### 修改原因

如果这个接口在其他路径被调用，而它只回退 `snd_nxt`，不回退 FEC 组状态，就会破坏发送一致性。

建议改法：

- 让它调用 `RdmaHw` 的统一恢复逻辑
- 或者至少补充对 `qp->fec` 状态的回退

### 16. `src/point-to-point/model/wan-routing.cc`

这部分不是 FEC 第一版主战场，但有一个相关点必须注意。

当前相关逻辑：

- 读取 `FlowIDNUMTag::GetAckReq()`
- 仅对 `ack_req` 包做 RTT 追踪
- [src/point-to-point/model/wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L182)

#### 需要修改的方法

- `WanRouting::RouteInput(...)` 中 RTT 过滤相关逻辑

#### 修改原因

FEC 开启后：

- 冗余包不应参与正常 RTT 采样
- 只有 `data` 组末尾或真正 ACK 边界对应的包才应继续带 `ack_req`

因此这里不一定要新增字段判断，但必须保证发送端写 `ack_req` 的方式与新语义一致。

如果后续发现 `repair` 包也被打上了 `ack_req`，这里就需要显式排除：

- `fec_pkt_role == repair`

## 方法级改造摘要

下面是最关键的方法清单。

### 必改

- `scratch/remote.cc`
  - 读取默认 `FEC_PARITY_PKTS`
  - flow 输入解析：给每条流绑定默认 `fec_n`
  - 建流调度：把 flow 绑定好的 `fec_n` 传给 `RdmaClient`
- `run.py`
  - flow 文件生成逻辑
  - 可选默认 `n` 参数
- `Settings::FlowInput`
  - 新增 `fec_n`
- `RdmaClient`
  - 新增 `m_fec_n`
  - `StartApplication()` 改签名传参
- `RdmaDriver::AddQueuePair()`
  - 新增 `fec_n` 参数
- `FlowIDNUMTag`
  - 字段
  - getter/setter
  - `Serialize/Deserialize`
  - `GetSerializedSize`
  - `Print`
- `RdmaHw::GetTypeId()`
- `RdmaHw::AddQueuePair()`
- `RdmaHw::GetRxQp()`
- `RdmaHw::GetNxtPacket()`
- `RdmaHw::ReceiveUdp()`
- `RdmaHw::ReceiveAck()`
- `RdmaHw::RecoverQueue()`
- `RdmaQueuePair::IsFinished()`
- `RdmaEgressQueue::RecoverQueue()`

### 大概率要改

- `RdmaHw::ReceiverCheckSeq()`
- `RdmaQueuePair::GetBytesLeft()`
- `RdmaQueuePair::GetOnTheFly()`
- `RdmaQueuePair::Acknowledge()`
- `WanRouting::RouteInput()` 中 `ack_req` 相关 RTT 过滤

## 变量级改造摘要

### 一定要新增

- `scratch/remote.cc`
  - `fec_parity_pkts`
- `RdmaHw`
  - `m_fecEnabled`
- `FlowIDNUMTag`
  - 全套 FEC 元数据字段
- `FlowInput`
  - `fec_n`
- `RdmaClient`
  - `m_fec_n`
- `RdmaQueuePair`
  - `fec.fec_n`
  - 发送侧 `fec` 子状态
- `RdmaRxQueuePair`
  - 接收侧 `fec` 子状态

### 尽量保留原语义

- `RdmaQueuePair::snd_nxt`
- `RdmaQueuePair::snd_una`
- `RdmaRxQueuePair::ReceiverNextExpectedSeq`

建议保留它们作为：

- 正常数据字节序号空间

不要让冗余包复用这几个变量表达自己。

## 实施顺序建议

1. 扩展 `run.py` / `config` / `ReadFlowInput()`，支持默认 `n`
2. 在 `ReadFlowInput()` 中把默认 `n` 绑定到每条流
3. 打通 `RdmaClient` -> `RdmaDriver` -> `RdmaHw::AddQueuePair(...)` 的 per-flow `n` 传递链
4. 扩展 `FlowIDNUMTag`
5. 在 `RdmaQueuePair` / `RdmaRxQueuePair` 中补 FEC 状态结构
6. 改 `RdmaHw::GetNxtPacket()`，先把“先 repair 后 data”发包跑通
7. 改 `RdmaHw::ReceiveUdp()` 和接收侧组恢复逻辑
8. 改 `ReceiveAck()` / `RecoverQueue()` / `IsFinished()`
9. 最后检查 `wan-routing.cc` 的 `ack_req` 语义是否仍然正确

## 结论

为了完成 FEC 文档里的目标，最少需要改 8 类核心对象：

- `RdmaHw`
- `RdmaQueuePair`
- `RdmaRxQueuePair`
- `FlowIDNUMTag`
- `FlowInput`
- `RdmaClient`
- `RdmaDriver`
- `remote.cc/run.py` 输入入口

其中真正的主改动集中在：

- `RdmaHw::GetNxtPacket()`
- `RdmaHw::ReceiveUdp()`
- `RdmaHw::ReceiveAck()`
- `RdmaHw::RecoverQueue()`

因为当前代码的基本假设是“全程只有一套正常数据字节序号”，而这次 FEC 方案的本质，是在不破坏正常累计 ACK 的前提下，再引入一套独立的冗余发送/接收状态。

另外，这次又新增了一个硬约束：

- config 里可以给默认 `n`
- 运行时生效的 `n` 必须是 per-flow 绑定值

所以实现时必须避免把“生效中的 `n`”做成 `RdmaHw` 的单一全局字段。
