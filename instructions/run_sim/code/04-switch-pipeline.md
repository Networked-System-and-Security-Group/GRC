# 交换机转发/拥塞点：`SwitchNode` + `SwitchMmu`

## 关键文件

- `src/point-to-point/model/switch-node.cc`
- `src/point-to-point/model/switch-mmu.h`

## 交换机发送路径（高层）

`SwitchNode::DoSwitchSend()` 做：
- Admission control（ingress/egress）
- 触发 drop（并写 `drop_log`）
- 触发/检查 PFC
- 最终调用设备发送

## ECN 标记点

`SwitchNode::SwitchNotifyDequeue()`：
- 若 `m_ecnEnabled` 且 `m_mmu->ShouldSendCN(...)`，则给 IP header 打 ECN mark

## Buffer 监控写入点

`SwitchMmu::printBufferInfo()`：
- 写 `buffer_monitor`（含 ingress/egress bytes）

AI 新增 buffer 指标的建议：
- 尽量复用 `printBufferInfo()` 的模式
- 控制写频率（比如 1ms 一次），避免每包写日志

