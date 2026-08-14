# IRN 重传状态机说明

本文整理当前代码中的 IRN 重传状态机，重点解释发送端、接收端、SACK/NACK 语义，以及为什么在 `416` 这类实验中可能出现少数尾流恢复很慢的问题。

相关主文件：

- `src/point-to-point/model/rdma-hw.cc`
- `src/point-to-point/model/rdma-queue-pair.h`
- `src/point-to-point/model/rdma-queue-pair.cc`

## 1. 关键状态变量

发送端 `RdmaQueuePair` 中的主要状态：

| 状态 | 含义 |
| --- | --- |
| `snd_una` | 最小未确认字节序号，等价于 cumulative ACK 边界 |
| `snd_nxt` | 下一个将要发送的字节序号 |
| `irn.m_sack` | 发送端记录的 SACK 表，表示接收端已经收到的乱序块 |
| `irn.m_recovery` | 是否处于 IRN recovery |
| `irn.m_recovery_seq` | 进入 recovery 时的 `snd_nxt` 高水位，用于判断何时退出 recovery |
| `m_retransmit` | 发送端重传 timeout 事件 |
| `m_timeout` | `GetRto()` 实际返回的 RTO |

接收端 `RdmaRxQueuePair` 中的主要状态：

| 状态 | 含义 |
| --- | --- |
| `ReceiverNextExpectedSeq` | 接收端当前期待的下一个连续字节序号 |
| `m_irn_sack_` | 接收端记录的已收到乱序块 |
| `m_nackTimer` | 重复 SACK/NACK 的冷却定时器 |
| `m_lastNACK` | 非 IRN 路径使用的上次 NACK 序号 |

注意：接收端和发送端各有一个 SACK 表。

- 接收端 `m_irn_sack_` 记录本端已经收到但还不能累计确认的乱序块。
- 发送端 `irn.m_sack` 记录接收端通过 NACK/SACK 告诉它已经收到的乱序块，用于跳过这些块。

## 2. 接收端状态机

接收端入口是 `RdmaHw::ReceiveUdp()`，它会调用 `ReceiverCheckSeq()` 检查数据包序号。

### 2.1 正常顺序到达

条件：

```cpp
seq == ReceiverNextExpectedSeq
```

行为：

1. `ReceiverNextExpectedSeq` 向前推进一个 `payload_size`。
2. 如果 IRN 开启，尝试查看 `m_irn_sack_` 的第一个 SACK block。
3. 如果第一个 SACK block 正好紧贴新的 `ReceiverNextExpectedSeq`，则继续推进 `ReceiverNextExpectedSeq`。
4. 调用 `discardUpTo(ReceiverNextExpectedSeq)` 删除已经被累计确认覆盖的 SACK block。
5. 如果接收端 SACK 表已经为空，返回 `6`。当前代码注释称其为“NACK but functionality is ACK”。
6. 如果接收端 SACK 表不为空，返回 `2`，表示仍在 IRN loss recovery 中。

代码位置：

- `rdma-hw.cc:712`
- `rdma-hw.cc:714`
- `rdma-hw.cc:720`
- `rdma-hw.cc:726`
- `rdma-hw.cc:727`

一个重要细节：IRN 下 `x == 6` 也会生成反馈包，而且协议号仍是 NACK 协议 `0xFD`，只是 `irnNackSize = 0`，功能上类似 ACK。

### 2.2 乱序到达

条件：

```cpp
seq > ReceiverNextExpectedSeq
```

行为：

1. 如果开启 IRN，接收端把这个乱序包加入 `m_irn_sack_`。
2. 如果这个乱序 block 已经在 SACK 表里，并且还没有过 `m_nackTimer`，返回 `4`，不再发送 NACK/SACK。
3. 否则设置 `m_nackTimer = Now + NACKGenerationInterval`。
4. 设置 `cnp = true`，表示 out-of-order 也会触发随 NACK 携带的 CNP bit。
5. 返回 `2`，要求生成 NACK/SACK。

代码位置：

- `rdma-hw.cc:746`
- `rdma-hw.cc:748`
- `rdma-hw.cc:752`
- `rdma-hw.cc:755`
- `rdma-hw.cc:756`
- `rdma-hw.cc:759`

默认 `NACKGenerationInterval` 是 `20000us`，即 `20ms`：

- `rdma-hw.cc:81`

这个冷却时间当前没有接到 `run.py` 或 `config.txt`，除非在 C++ 默认值处改，或者新增配置 plumbing。

### 2.3 NACK/SACK 的具体内容

`ReceiveUdp()` 根据 `ReceiverCheckSeq()` 的返回值生成反馈包。

对于 IRN：

- 如果 `x == 2`，设置：
  - `seqh.SetSeq(ReceiverNextExpectedSeq)`
  - `seqh.SetIrnNack(ch.udp.seq)`
  - `seqh.SetIrnNackSize(payload_size)`
- 如果 `x != 2`，设置：
  - `seqh.SetIrnNack(0)`
  - `seqh.SetIrnNackSize(0)`

代码位置：

- `rdma-hw.cc:454`
- `rdma-hw.cc:456`
- `rdma-hw.cc:469`

因此当前 IRN NACK 的语义不是“请重传哪个区间”，而是：

- `seq` 字段表示累计 ACK 边界。
- `irnNack, irnNackSize` 表示一个已经收到的乱序块，即 SACK block。

例子：

如果接收端期待 `5000`，但收到了 `10000`，假设包大小为 `1000` 字节，则反馈内容是：

```text
seq = 5000
irnNack = 10000
irnNackSize = 1000
```

含义是：

```text
5000 之前连续收到；
[10000, 11000) 已收到；
[5000, 10000) 中存在缺口，需要发送端自行推断。
```

## 3. 发送端状态机

发送端入口是 `RdmaHw::ReceiveAck()`，IRN 的 ACK/NACK 统一在这里处理。

### 3.1 收到反馈后更新累计 ACK

发送端首先调用：

```cpp
qp->Acknowledge(seq)
```

其中 `seq` 是接收端反馈包中的 cumulative ACK 边界。

代码位置：

- `rdma-hw.cc:566`

如果接收端仍期待 `5000`，发送端的 `snd_una` 就仍然停在 `5000`。

### 3.2 记录 SACK block

如果 `irnNackSize != 0`，发送端把 `[irnNack, irnNack + irnNackSize)` 加入 `qp->irn.m_sack`：

```cpp
qp->irn.m_sack.sack(ch.ack.irnNack, ch.ack.irnNackSize)
```

代码位置：

- `rdma-hw.cc:579`

`IrnSackManager::sack()` 会把相邻或重叠的 block 合并。SACK block 的含义是“接收端已收到”，不是“需要重传”。

代码位置：

- `rdma-queue-pair.cc:288`
- `rdma-queue-pair.cc:348`

### 3.3 通过 SACK 推进 `snd_una`

发送端查看 `irn.m_sack` 的第一个 block：

```cpp
if (qp->snd_una == sack_seq) {
    qp->snd_una += sack_len;
}
```

这表示如果当前累计 ACK 边界正好落在一个已知已收到 block 的开头，可以跳过这个 block。

代码位置：

- `rdma-hw.cc:584`
- `rdma-hw.cc:591`

### 3.4 进入 IRN recovery

当前代码只有在收到带 `irnNackSize != 0` 的反馈，并且还没有处于 recovery 时，才会进入 recovery：

```cpp
if (!qp->irn.m_recovery) {
    qp->irn.m_recovery_seq = qp->snd_nxt;
    RecoverQueue(qp);
    qp->irn.m_recovery = true;
}
```

其中 `RecoverQueue(qp)` 只是：

```cpp
qp->snd_nxt = qp->snd_una;
```

代码位置：

- `rdma-hw.cc:629`
- `rdma-hw.cc:823`

这意味着第一次发现缺口时，发送端会把 `snd_nxt` 拉回 `snd_una`，从最小未确认字节开始重传。

### 3.5 SACK 跳过已收到块

发送端发送数据前会调用 `GetBytesLeft()`。IRN 开启时，如果 `snd_nxt` 正好等于 SACK 表中第一个 block 的起点，就跳过整个 block：

```cpp
if (snd_nxt == sack_seq) {
    snd_nxt += sack_sz;
    irn.m_sack.discardUpTo(snd_nxt);
}
```

代码位置：

- `rdma-queue-pair.cc:129`

因此当前实现不是严格的“只重传缺失块队列”，而是：

```text
从 snd_una 开始顺序重传；
遇到 SACK 表里确认已收到的 block 时跳过。
```

这是一个简化版 selective recovery，而不是完整的 selective retransmission queue。

### 3.6 退出 recovery

发送端只有在累计 ACK 推进到进入 recovery 时的高水位之后，才退出 recovery：

```cpp
if (qp->irn.m_recovery && qp->snd_una >= qp->irn.m_recovery_seq) {
    qp->irn.m_recovery = false;
}
```

代码位置：

- `rdma-hw.cc:597`

`m_recovery_seq` 是第一次进入 recovery 时的 `snd_nxt`。如果第一次丢包时已经发出了很远的 flight，那么 recovery 会持续到很高的累计 ACK 边界。

## 4. 慢恢复问题的触发路径

以下是当前状态机中最关键的问题场景。

初始状态：

```text
ReceiverNextExpectedSeq = 5000
sender snd_una = 5000
sender snd_nxt 已经发到很后面，例如 50000
```

步骤 1：接收端收到 `10000`

接收端反馈：

```text
seq = 5000
irnNack = 10000
irnNackSize = 1000
```

发送端动作：

```text
记录 SACK [10000, 11000)
m_recovery_seq = 50000
snd_nxt = snd_una = 5000
m_recovery = true
```

步骤 2：发送端开始重传 `5000, 6000, 7000, ...`

如果这些重传包全部成功到达，接收端的 `ReceiverNextExpectedSeq` 会向前推进，并最终跳过 SACK block，恢复结束。

步骤 3：中间重传包又丢了

假设重传的 `6000` 又丢了，但 `7000, 8000, 9000` 到了。

接收端会继续产生新的 SACK/NACK，比如：

```text
seq = 6000
irnNack = 7000
irnNackSize = 1000
```

发送端会记录这些 SACK block，但由于当前已经在 recovery 中：

```cpp
if (!qp->irn.m_recovery) {
    RecoverQueue(qp);
}
```

不会再次 `RecoverQueue(qp)`。

如果此时 `snd_nxt` 已经越过了缺失的 `6000`，发送端不会立即回头重传 `6000`。它会继续依赖后续 ACK 推进；但 `snd_una` 卡在 `6000`，ACK 又无法推进。于是恢复容易退化为等待 timeout。

步骤 4：timeout 触发

发送端 timeout 处理：

```cpp
if (qp->irn.m_enabled) qp->irn.m_recovery = true;
if (m_cc_mode == 1) cnp_received_mlx(qp);
RecoverQueue(qp);
```

代码位置：

- `rdma-hw.cc:979`
- `rdma-hw.cc:993`
- `rdma-hw.cc:995`
- `rdma-hw.cc:1010`

这里有两个效果：

1. `RecoverQueue(qp)` 终于把 `snd_nxt` 拉回 `snd_una`。
2. `cnp_received_mlx(qp)` 把 timeout 当作拥塞反馈处理，触发 DCQCN 降速。

这就是 `416` 里少数 IRN 尾流恢复特别慢的核心原因：新的缺口没有被 NACK 立即驱动重传，而是经常需要等 timeout；每次 timeout 又进一步降速。

## 5. ACK 频率与 NACK 冷却的关系

`L2_ACK_INTERVAL` 影响正常顺序数据包是否请求 ACK。DCQCN 默认由 `run.py` 设置为 `40000` 字节。

但 IRN 的乱序 NACK 不依赖正常 ACK 周期：

```cpp
if ((ack_req && x == 1) || x == 2 || x == 6)
```

只要 `x == 2`，就会生成 NACK/SACK。

代码位置：

- `rdma-hw.cc:454`

因此，当前慢恢复问题的主因不是 `L2_ACK_INTERVAL` 太大，而是：

1. IRN 重复 SACK/NACK 的冷却默认是 `20ms`。
2. recovery 中新的 NACK/SACK 不会再次触发 `RecoverQueue()`。
3. 当前 inter-DC RTO 是固定 `35ms`，而不是使用 `IrnRtoLow/IrnRtoHigh`。
4. timeout 被当成 CNP，导致发送速率继续下降。

## 6. 是否是简单 bug，还是机制设计问题

这是两层问题。

### 6.1 当前实现存在明确的状态机问题

`m_recovery` 的 guard 会让 IRN 在已有 recovery 期间忽略新的 hole 对发送指针的回退需求：

```cpp
if (!qp->irn.m_recovery) {
    RecoverQueue(qp);
}
```

如果 recovery 中再次丢了重传包，发送端可能只记录 SACK，却不立即重传新的最小缺口，最终依赖 timeout。

这不是网络拥塞本身导致的必然后果，而是当前状态机的行为。

### 6.2 当前 IRN 是简化机制，不是完整选择性重传

完整的 IRN/selective retransmission 通常需要显式维护 lost/retransmit queue，能够根据 cumulative ACK 和 SACK 信息选择缺失区间并调度重传。

当前实现没有独立的重传队列，而是：

```text
RecoverQueue: snd_nxt = snd_una
发送时通过 SACK block 跳过已收到区间
```

这能处理简单丢包，但遇到 recovery 中再次丢包时，容易退化为 timeout 驱动。因此它既有局部 bug，也有机制简化带来的结构性限制。

## 7. 简单修复方案

### 方案 A：允许 recovery 中的新 NACK 再次触发 `RecoverQueue`

最小改动是放宽 `m_recovery` guard：

```cpp
if (ch.ack.irnNackSize != 0) {
    if (!qp->irn.m_recovery) {
        qp->irn.m_recovery_seq = qp->snd_nxt;
        qp->irn.m_recovery = true;
    }
    RecoverQueue(qp);
}
```

优点：

- 实现简单。
- 可以显著减少 recovery 中再次丢包后等待 timeout 的概率。
- 行为接近当前非 IRN DCQCN 的 NACK 驱动重传。

缺点：

- 不是严格选择性重传，仍然是从 `snd_una` 开始重发，再靠 SACK 跳过。
- 如果 NACK 很频繁，可能产生更多重复重传。
- 可能需要配合较小的 `NACKGenerationInterval`，否则重复 hole 的反馈仍然偏慢。

### 方案 B：把 `NACKGenerationInterval` 接到配置并调小

当前默认 `20ms` 对 RTT 小于 `10ms` 的路径偏大。可以先把它作为实验参数暴露到 `config.txt`，再扫：

```text
NACK_GENERATION_INTERVAL_US = 200, 500, 1000, 2000
```

优点：

- 改动小。
- 能提升重复 hole 的反馈频率。

缺点：

- 只解决反馈太慢，不解决 recovery 中不回退 `snd_nxt` 的核心问题。
- 如果 NACK 伴随 CNP bit，可能增加 DCQCN 降速事件。

### 方案 C：让 IRN RTO 真正使用 `IrnRtoLow/IrnRtoHigh`

当前 `IrnRtoLow/IrnRtoHigh` 被设置了，但 `GetRto()` 只返回 `m_timeout`。inter-DC QP 又被硬编码为 `35ms` timeout。

短期可以改 `GetRto()`，让 IRN 使用更合理的 RTO。

优点：

- timeout 恢复更快。
- 对尾流有效。

缺点：

- 仍然是 timeout 驱动，不是理想的 NACK 驱动。
- RTO 太小可能导致误判和不必要降速。

### 方案 D：timeout 不直接等价于 CNP

当前 timeout 会调用 `cnp_received_mlx(qp)`。如果 timeout 只是 loss recovery 的兜底，而不是拥塞信号，把它直接等价为 CNP 会让尾流越恢复越慢。

可以考虑：

- IRN timeout 只触发 `RecoverQueue()`，不触发 DCQCN 降速。
- 或者只在连续 timeout 超过阈值后才降速。

优点：

- 能避免尾部恢复期间速率被反复砍低。

缺点：

- 如果 timeout 确实由拥塞造成，完全不降速可能加剧丢包。
- 需要和 ECN/CNP 语义区分清楚。

## 8. 建议优先级

建议先做低风险验证：

1. 暴露 `NACKGenerationInterval`，把默认 `20ms` 降到 `200us-2ms` 区间扫一遍。
2. 放宽 IRN recovery 内新 NACK 的 `RecoverQueue()` 限制，观察 `416` 的少数长尾是否消失。
3. 把 IRN RTO 接入 `GetRto()`，替代 inter-DC 固定 `35ms`。
4. 最后再考虑更完整的 selective retransmission queue。

如果目标是快速修复当前 `416` 的异常长尾，方案 A 和方案 B 是最直接的。如果目标是实现更接近真实 IRN 的机制，需要方案 C 之外再补完整的缺口重传队列。
