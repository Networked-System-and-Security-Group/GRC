# FEC Implementation Summary

本目录记录这次 FEC 代码改动，目标是方便 review、差异核对和局部回退。

本轮代码当前“试图实现”的核心行为：

- `config.txt` 新增/使用默认 `FEC_PARITY_PKTS`
- 每条 RDMA 流在建流时绑定自己的 `fec_n`
- FEC 发送顺序改为每组先发 `n` 个 repair，再发 `m` 个 data
- `m = L2_ACK_INTERVAL / PACKET_PAYLOAD_SIZE`
- repair 包不占用正常 data 的 seq 空间
- ACK 只围绕正常 data seq 累计推进
- 接收端按连续 `group_id` 推进 cumulative ACK，每组最多触发一次 ACK
- 当某组已经 `recoverable` 时，后续属于该组的 `data` 包不再触发普通 NACK，而是直接走 ACK 推进语义

当前需要特别注意：

- 当前实现没有真实的 FEC 编码/解码内容，repair 包仍然只是调度与控制语义上的冗余单元
- 当前 `recoverable` 判定本质上是“组内累计收到包数达到 `m` 后允许 ACK 前推”
- 当前 sender / receiver 状态机经过实验和代码复核，仍存在若干语义风险
- sender 在 FEC NACK rewind 时错误回退 `snd_una` 的问题已修正
- repair 在途计数重复累计的问题已修正为按组一次性记账
- receiver 侧 FEC group 无回收的问题已补上按 ACK 前推后的组回收
- 因此本实现目前不能视为“逻辑已完全正确的 FEC”

本轮没有改：

- `flow` 文件格式
- 独立的真实 FEC 编码/解码内容，当前仍是调度与 ACK 语义改造

建议 review 顺序：

1. `scratch/remote.cc`
2. `src/applications/model/rdma-client.cc`
3. `src/point-to-point/model/rdma-driver.cc`
4. `src/point-to-point/model/rdma-queue-pair.h`
5. `src/point-to-point/model/rdma-queue-pair.cc`
6. `src/network/model/flow-id-num-tag.h`
7. `src/network/model/flow-id-num-tag.cc`
8. `src/point-to-point/model/rdma-hw.h`
9. `src/point-to-point/model/rdma-hw.cc`
10. `src/point-to-point/model/qbb-net-device.cc`

验证结果：

- `./waf build` 通过
- 仿真可运行，但当前代码复核与实验复核表明，FEC 状态机仍有未修复的逻辑问题
- 具体问题清单见 [03-known-risks.md](/home/niuzihan26/gscc/RDMA-WAN-Optimization/instructions/fec_implementation_review/03-known-risks.md)
