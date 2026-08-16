# Files And Purpose

## 配置与建流

`scratch/remote.cc`

- 读取 `FEC_PARITY_PKTS`
- 将默认 `n` 绑定到每条 RDMA 流的 `FlowInput`
- 创建 `RdmaHw` 时打开 `FecEnable`
- 增加 FEC 参数合法性检查：
  - `PACKET_PAYLOAD_SIZE > 0`
  - `L2_ACK_INTERVAL > 0`
  - `L2_ACK_INTERVAL % PACKET_PAYLOAD_SIZE == 0`

`src/point-to-point/model/settings.h`

- `FlowInput` 增加 `fec_n`

`src/applications/model/rdma-client.h`
`src/applications/model/rdma-client.cc`

- 新增每流属性 `FecParityPkts`
- 向下传入 `RdmaDriver`

`src/point-to-point/model/rdma-driver.h`
`src/point-to-point/model/rdma-driver.cc`

- `AddQueuePair(...)` 增加 `fec_n` 参数

`run.py`

- 配置模板写入 `FEC_PARITY_PKTS`
- CLI 增加 `--fec-n`

## 报文标签

`src/network/model/flow-id-num-tag.h`
`src/network/model/flow-id-num-tag.cc`

- 为每个包附带 FEC 元数据：
  - 是否 FEC
  - repair/data 角色
  - group id
  - 组内 `m/n`
  - data 起始 seq
  - data idx / repair idx
  - repair seq
  - 发送顺序序号

## QP 状态

`src/point-to-point/model/rdma-queue-pair.h`
`src/point-to-point/model/rdma-queue-pair.cc`

- 发送侧增加每组 FEC 状态
- 接收侧增加每组 FEC 状态
- 发送侧额外记录 repair 在途计数
- 接收侧维护 `groups` 映射并按 `ReceiverNextExpectedSeq` 查找可前推组
- `GetOnTheFly()` 把 repair 在途算进去
- `IsFinished()` 需要等 data ACK 完成且没有残余 FEC 状态

## FEC 主逻辑

`src/point-to-point/model/rdma-hw.h`
`src/point-to-point/model/rdma-hw.cc`

- `RdmaHw` 增加 `FecEnable`
- 每流 `AddQueuePair(...)` 绑定 `fec_n`
- `GetNxtPacket(...)` 改为 repair-first, data-second
- repair 包不推进 `snd_nxt`
- data 包推进正常 seq
- 接收时按 tag 区分 repair/data
- repair/data 分支分别更新组接收状态
- ACK 推进只按连续 `group_id` 前进
- 累计 ACK 的 seq 仍是正常 data seq
- 恢复时清空 FEC 活跃组与在途组状态

## 恢复辅助

`src/point-to-point/model/qbb-net-device.cc`

- `RdmaEgressQueue::RecoverQueue(...)` 也同步清理 FEC 发送态

## 当前状态机

下面描述的是当前代码中的“FEC 模拟状态机”，不是独立真实纠删码解码器。

### 发送端状态机

#### 1. `idle`

条件：

- `qp->fec.active_group_valid == false`
- 没有正在构造的新组

转移：

- `GetNxtPacket()` 调用 `EnsureActiveFecGroup()` 后，如果：
  - `ShouldUseFec(qp) == true`
  - `GetBytesLeft() > 0`
  - `m = L2_ACK_INTERVAL / PACKET_PAYLOAD_SIZE > 0`
  则进入 `repair_sending`

#### 2. `repair_sending`

条件：

- `active_group_valid == true`
- `group.repair_sent < group.n_snapshot`

行为：

- 发送 repair 包
- repair 包不推进 `snd_nxt`
- 仅推进 `group.repair_sent`
- repair 在途计数只在该组第一次发送 repair 时按组一次性计入

转移：

- 当 `group.repair_sent == group.n_snapshot` 时进入 `data_sending`

#### 3. `data_sending`

条件：

- `active_group_valid == true`
- `group.repair_sent == group.n_snapshot`
- `group.data_sent < group.m_snapshot`

行为：

- 发送 data 包
- data 包推进正常 `snd_nxt`
- 最后一包 data 或流尾 data 可以带 `ack_req`

转移：

- 当 `group.data_sent == group.m_snapshot` 时进入 `waiting_ack`

#### 4. `waiting_ack`

条件：

- 当前组全部 data 已发完
- 组被放入 `outstanding_groups`
- `active_group_valid` 置回 `false`

行为：

- 等待累计 ACK 把 `snd_una` 推过 `group.data_end_seq`
- `PruneAckedFecGroups()` 在 sender 侧做组回收

转移：

- 若仍有未发送字节，则回到 `idle` 并准备下一组
- 若收到与该组关联的 FEC NACK，则进入 `rewind_retransmit`
- 若整流完成，则结束

#### 5. `rewind_retransmit`

条件：

- 收到携带 FEC metadata 的 NACK
- sender 侧仍能找到该组的 `active_group` 或 `outstanding_group`

行为：

- 仅回退发送游标 `snd_nxt` 到组起点
- 不允许回退累计确认边界 `snd_una`
- 重置该组 `repair_sent/data_sent/repair_seq_next`
- 记录 `retransmit_resume_*`

转移：

- 重新进入 `repair_sending`
- 该组重发完毕后，在 `tx_group_close` 处尝试 `MaybeRestoreFecSendCursor()`
- 恢复到 rewind 之前更靠后的 `snd_nxt`

#### 6. `timeout_recovery`

条件：

- sender 常规超时恢复触发 `RecoverQueue()`

行为：

- 清空 sender 侧 FEC 活跃组 / outstanding 组 / repair 在途计数
- 清空 retransmit resume 状态

说明：

- 这是当前实现与普通 RDMA recovery 对齐的“整体回退”
- 它仍可能导致在网络中飞行的旧 FEC ACK/NACK 返回时无法匹配原组状态

### 接收端状态机

#### 1. `group_absent`

条件：

- `rxQp->fec.groups` 中还没有该 `group_id`

转移：

- 收到带 FEC tag 的 repair/data 包时，`GetOrCreateFecRxGroup()` 创建组状态

#### 2. `group_tracking`

条件：

- 组已存在
- 正在接收 repair/data

行为：

- 对 data：更新 `data_bitmap/data_received/total_received`
- 对 repair：更新 `repair_bitmap/repair_received/total_received`
- 组内 bitmap 只做“是否已见过”判重

#### 3. `group_recoverable`

条件：

- `group.total_received >= group.m_snapshot`

说明：

- 当前代码用这个条件模拟“该组足够恢复”
- 这里没有真实解码，只是组级可前推 ACK 的近似条件

#### 4. `ack_advance`

入口：

- `ReceiveFecData()` 或 `ReceiveFecRepair()` 在组变为 `recoverable` 后调用 `TryAdvanceFecAck()`

行为：

- 查找覆盖 `ReceiverNextExpectedSeq` 的 recoverable 组
- 若找到，则把 `ReceiverNextExpectedSeq` 直接推进到该组 `data_end_seq`
- 可连续跨过多个 recoverable 组

说明：

- 当前 ACK 前推按“覆盖当前 expected seq 的 recoverable 组”工作
- 不再依赖旧的连续 `group_id` 假设

#### 5. `control_feedback`

行为：

- 如果组已 recoverable，后续同组 data 不再走普通缺口 NACK 判定
- 若 ACK 因组前推而产生，会立即发控制 ACK
- 若仍存在缺口且组不可 recoverable，则继续可能触发普通 NACK

#### 6. `group_pruned`

行为：

- 在 ACK 已经因为组前推而发出后，调用 `PruneAckedFecRxGroups()`
- 删除所有 `data_end_seq <= ReceiverNextExpectedSeq` 的旧 group

目的：

- 防止 receiver 侧 group map 无限膨胀
- 降低旧 group 干扰后续控制 tag 查找的风险
