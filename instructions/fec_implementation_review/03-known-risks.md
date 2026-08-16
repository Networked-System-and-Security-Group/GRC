# Known Risks

本轮已经把设计目标的主链路打通，但仍有几个风险点，review 时建议重点看：

1. 当前实现主要解决的是发送顺序、seq 空间分离、每组 ACK 一次、每流 `n` 绑定。
真实纠删码内容本身没有实现，repair 包目前更像“占位的冗余传输调度单元”。

2. 当前接收端并没有真实执行 FEC 解码。
`ReceiveFecData()` / `ReceiveFecRepair()` 仅用 `group.total_received >= group.m_snapshot`
来判定 `recoverable`，随后 `TryAdvanceFecAck()` 直接把
`ReceiverNextExpectedSeq` 推到 `group.data_end_seq`。
这意味着当前行为更接近“组级 ACK 跳过模拟”，而不是“恢复缺失 data 后再累计确认”。

3. 发送端在收到 FEC 相关 NACK 时，rewind 现在应只回退 `snd_nxt`，
不能回退 `snd_una`。
这一点已经修正，但后续 review 仍需重点确认 sender 侧累计 ACK 单调不减
这一基本语义不会再次被其他 recovery 路径破坏。

4. `MaybeRestoreFecSendCursor()` 只恢复 `snd_nxt` 而不恢复 `snd_una` 是正确方向，
但不足以修复前一条问题。因为 `snd_una` 已经在 rewind 阶段被错误回退，后续 resume
无法自动恢复 ACK 语义。

5. `outstanding_repair_pkts` 当前已经改为按组一次性记账，而不是按每个 repair 包重复累计。
但后续 review 仍需重点确认：
- repair 首次发送时只计入一次
- 组被 prune 时只回收一次
- timeout / recovery 清理后不会残留脏计数

6. timeout / recovery 路径会整体清空 sender 侧 FEC 状态。
`ResetFecStateForRecovery()` 当前会直接清掉：
- `active_group_valid`
- `outstanding_groups`
- `outstanding_repair_pkts`
这会导致仍在网络中的旧 ACK/NACK 返回时，sender 已经失去对应组状态，后续控制语义失配。

7. receiver 侧 FEC group 状态已经补上按 `ReceiverNextExpectedSeq` 的回收逻辑。
但后续 review 仍需确认：
- 只回收已经被累计 ACK 稳定跨过的组
- 不会过早删除仍可能参与控制反馈的组
- 长时间大流量下 group map 不再无限膨胀

8. `PopulateFecControlTagForExpectedSeq()` 当前按 `expected_seq` 去映射所属 group，
比直接复用旧包 tag 更合理，但仍依赖 `rxQp->fec.groups` 中存在正确且未过期的 group 状态。
在 receiver 组状态不清理的前提下，控制包仍有携带陈旧 group 元数据的风险。

9. `ack_emitted` 字段目前没有形成真正的幂等保护。
`TryAdvanceFecAck()` 虽然会置位 `ack_emitted`，但后续经常立刻通过
`ClearFecAckEmittedFlags()` 全量清零，当前更像观测字段，而不是稳定的控制约束。

10. 当前实验复核表明，log 中会同时出现较多：
- `rx_group_recovered`
- `tx_nack`
- `rx_nack_sender`
- `tx_group_rewind`
- `tx_group_resume`
这说明“组变为 recoverable”与“sender 级回退重传”仍大量并存，状态机没有形成稳定闭环。

11. 在 `cernet_topo + w-dynamic-150-180 + 纯 RDMA` 这组实测中，热点丢包几乎全部集中在
单个 WAN 交换机（当前观察到是 `switch 225`），且 `fec=1` 的 drop 总数一度高于 `fec=0`。
这表明当前实现下，repair 包有可能进一步放大热点拥塞，而恢复收益不足以抵消新增负载。

12. `wan-routing.cc` 没有额外改 RTT 过滤逻辑。
当前依赖“只有 data 组末尾包带 `ack_req`，repair 包不带”的约束来保持原有 RTT 采样语义。

13. IRN 与 FEC 同时打开的场景只做了兼容性保持，没有额外做系统级验证。

## 建议后续验证

- 单流、无丢包、`FEC_PARITY_PKTS > 0`
- 单流、组内丢 1 个 data、依赖 repair 推 ACK
- 多流并发，确认 ACK 频率与 `m` 一致
- `FEC_PARITY_PKTS = 0` 回归非 FEC 基线
- FEC NACK / rewind 触发后，确认 `snd_una` 始终单调不减
- 重复 repair 重传场景下，确认 `outstanding_repair_pkts` 不发生累积漂移
- 长时间大流量场景下，确认 `rxQp->fec.groups` 可以稳定回收，不持续膨胀
