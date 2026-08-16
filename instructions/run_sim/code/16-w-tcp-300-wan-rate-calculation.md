# `w-tcp-300` 的 WAN TCP 速率计算

## 1. 结论

`config/w-tcp-300.txt` 中的 `300` 来自生成器参数 `--wan-rate 300G`，但在当前 `config/large_traffic_gen.py` 的实现和 `config/cernet_topo.txt` 的五个 WAN switch 场景下，它**不等于每对 WAN switch 之间 300 Gbps**。

对当前文件，按 20 ms 生成窗口内 TCP payload 的总字节数计算：

| 指标 | 数值 |
|---|---:|
| 活动 WAN switch 数 | 5（222-226） |
| 每个 WAN switch 下的 source host 数 | 20 |
| 有向 WAN switch 对数 | 20（`5 x 4`） |
| `--wan-rate` 参数 / 文件名数值 | 300 Gbps |
| 当前代码的每 host 目标速率 | 75 Gbps |
| 当前代码的每源 WAN switch 目标总出口 | 1,500 Gbps |
| 当前代码的每个有向 WAN switch 对期望速率 | 375 Gbps |
| `w-tcp-300.txt` 实测总 offered load | 7,580.474 Gbps |
| `w-tcp-300.txt` 实测每个有向 switch 对平均 offered load | **379.024 Gbps** |

这里的 `379.024 Gbps` 是生成的 TCP application payload offered load，不是仿真过程中实际送达的 TCP goodput。TCP 建连、拥塞窗口、队列、PFC、丢包、重传和仿真停止时间都会使实际 goodput 与该值不同。

## 2. 生成器中的参数含义

WAN TCP 文件由：

```bash
python3 config/large_traffic_gen.py --wan-rate 300G ...
```

生成时，文件名由以下代码组成：

```python
wan_rate_lbl = wan_pair_rate_str.replace('G', '').replace('M', '')
wan_saved_path = op.join(
    op.dirname(__file__),
    f'{flow_set}-tcp-{wan_rate_lbl}.txt'
)
```

源文件：`config/large_traffic_gen.py` 第 258-264 行。

所以 `w-tcp-300.txt` 只说明调用生成器时 `wan_pair_rate_str` 为 `300G`；文件名本身不保证每个 switch pair 的实际速率为 300 Gbps。

## 3. 当前代码的速率公式

生成器读取全部有 host 的 WAN switch，并对每个 source switch 将目标 host 池设置为其余所有 switch 的 host：

```python
active_wan_switches = [hosts for hosts in wan_as_list if len(hosts) > 0]
num_wan_switches = len(active_wan_switches)

for i, src_hosts in enumerate(active_wan_switches):
    other_hosts_pool = []
    for j, other_hosts in enumerate(active_wan_switches):
        if i != j:
            other_hosts_pool.extend(other_hosts)
```

随后给每个 source host 设置：

```python
per_host_rate_val = (
    target_pair_bw * num_wan_switches
) / len(src_hosts)
```

源文件：`config/large_traffic_gen.py` 第 208-240 行。

记：

```text
R = --wan-rate 对应的 target_pair_bw
N = 活动 WAN switch 数
H = 一个 source WAN switch 下的 host 数
```

则当前代码的速率关系为：

```text
每 host 目标速率
    r_host = R x N / H

每 source WAN switch 总出口速率
    R_src = H x r_host = R x N

目标均匀分摊到其余 N - 1 个 destination switch 后，
每个有向 WAN switch 对的期望速率
    R_pair_expected = R_src / (N - 1)
                    = R x N / (N - 1)
```

因此，当前代码对“每对 WAN switch 的 `--wan-rate` 目标”实际多乘了：

```text
N / (N - 1)
```

倍数。

## 4. 代入 `cernet_topo + w-tcp-300` 的数值

`config/cernet_topo.txt` 中有五个 WAN switch：222、223、224、225、226；并有 100 个 WAN host。当前默认 `--wan-hosts-num=20`，因此每个 WAN switch 对应 20 个 source host。

代入：

```text
R = 300 Gbps
N = 5
H = 20
```

得到：

```text
每 host 目标速率
    r_host = 300 x 5 / 20
           = 75 Gbps

每 source WAN switch 总出口目标速率
    R_src = 20 x 75
          = 1,500 Gbps

每 source 有四个不同的 destination WAN switch，随机均匀选取目标 host，
因此每个有向 switch 对的期望速率
    R_pair_expected = 1,500 / 4
                    = 375 Gbps
```

也可以直接使用通式：

```text
R_pair_expected = 300 x 5 / (5 - 1)
                = 375 Gbps
```

所以当前实现中：

```text
文件名/输入参数：300 Gbps
代码实际每个有向 WAN switch 对的期望：375 Gbps
```

文件中“参数表示 Switch 对之间速率”的注释和 CLI help 与实际公式不一致。若目标确实是让每个有向 WAN switch 对为 `R`，公式应使用：

```python
per_host_rate_val = (
    target_pair_bw * (num_wan_switches - 1)
) / len(src_hosts)
```

此时：

```text
每 source switch 总出口 = R x (N - 1)
平均分到 N - 1 个目的 switch = R
```

该修正会改变后续生成文件，不能在未重新生成并标记版本的情况下把旧 `w-tcp-300.txt` 解释为每 pair 300 Gbps。

## 5. `w-tcp-300.txt` 的实测 offered load

### 5.1 统计方法

`w-tcp-300.txt` 的格式是：

```text
<flow_count>
src_host dst_host pg size_bytes start_time_seconds
...
```

WAN TCP 生成持续时间固定为：

```python
duration=0.02
base_time=2.0
```

源文件：`config/large_traffic_gen.py` 第 233-240 行。

因此，对一组流量文件的 payload offered load 的计算是：

```text
R_total_offered = sum(size_bytes) x 8 / 0.02
```

对单个有向 WAN switch 对 `s -> d`：

```text
R_s_to_d_offered =
    sum(size_bytes of flows whose source belongs to s
                   and destination belongs to d) x 8 / 0.02
```

对当前拓扑，WAN host ID 连续分组：

| WAN switch | WAN host ID 范围 |
|---:|---|
| 222 | 227-246 |
| 223 | 247-266 |
| 224 | 267-286 |
| 225 | 287-306 |
| 226 | 307-326 |

### 5.2 文件级结果

当前 `config/w-tcp-300.txt` 含有：

```text
flow 数量：10,989
TCP payload 总字节数：18,951,184,930 bytes
生成窗口：20 ms
```

因此：

```text
R_total_offered
  = 18,951,184,930 x 8 / 0.02
  = 7,580.473972 Gbps
```

共有 20 个有向 WAN switch 对，故简单平均：

```text
R_pair_avg_offered
  = 7,580.473972 / 20
  = 379.023699 Gbps
```

这与当前代码的期望值 375 Gbps 接近；约 1.07% 的偏差来自随机抽样的 WebSearch CDF 流大小和泊松到达过程。此 WAN 分支调用 `generate_flows(..., restrict=False)`，短时 20 ms 流量没有被 90%-110% 目标范围重试约束。

### 5.3 各有向 WAN switch 对的实际 offered load

| 源 | 目的 | flow 数 | payload offered load（20 ms 平均） |
|---:|---:|---:|---:|
| 222 | 223 | 568 | 367.575 Gbps |
| 222 | 224 | 525 | 367.037 Gbps |
| 222 | 225 | 577 | 415.437 Gbps |
| 222 | 226 | 522 | 334.102 Gbps |
| 223 | 222 | 536 | 362.895 Gbps |
| 223 | 224 | 550 | 427.371 Gbps |
| 223 | 225 | 550 | 395.261 Gbps |
| 223 | 226 | 501 | 332.559 Gbps |
| 224 | 222 | 517 | 351.487 Gbps |
| 224 | 223 | 567 | 370.085 Gbps |
| 224 | 225 | 534 | 343.101 Gbps |
| 224 | 226 | 603 | 450.606 Gbps |
| 225 | 222 | 535 | 339.351 Gbps |
| 225 | 223 | 517 | 358.089 Gbps |
| 225 | 224 | 601 | 428.713 Gbps |
| 225 | 226 | 570 | 359.432 Gbps |
| 226 | 222 | 564 | 385.592 Gbps |
| 226 | 223 | 558 | 406.778 Gbps |
| 226 | 224 | 566 | 394.055 Gbps |
| 226 | 225 | 528 | 390.949 Gbps |

当前文件的实际 pair 值在约 332.559-450.606 Gbps 之间波动。该波动是单次随机流量文件的结果，不应将每一个 pair 都视为稳定的恒定速率。

每个 source WAN switch 的总出口 offered load 为：

| 源 WAN switch | 总出口 offered load |
|---:|---:|
| 222 | 1,484.150 Gbps |
| 223 | 1,518.085 Gbps |
| 224 | 1,515.279 Gbps |
| 225 | 1,485.586 Gbps |
| 226 | 1,577.374 Gbps |

五个 source switch 的平均出口为：

```text
7,580.473972 / 5 = 1,516.094794 Gbps
```

也与目标 `1,500 Gbps` 接近。

## 6. offered load 与仿真 TCP goodput 的区别

本文件中的速率只由输入 flow 文件的 payload bytes 和生成时间窗口定义：

```text
offered load = application payload demand / generation duration
```

它不表示仿真中实际从某个 WAN link 发出的比特率，也不表示 PacketSink 实际接收的 goodput。仿真实际结果会受到以下因素影响：

- TCP 三次握手与初始拥塞窗口；
- TCP ACK、重传和拥塞窗口演化；
- host NIC 与 RDMA 共存时的发送仲裁；
- q1/q3 队列选择、PFC pause 和交换机队列；
- ECN、丢包和路径竞争；
- 流的完成时间与仿真 hard stop。

因此，实验报告中应使用如下措辞：

> `w-tcp-300.txt` 在当前生成器与五个 WAN switch 拓扑下，提供约 379.024 Gbps/有向 WAN switch 对的 20 ms 平均 TCP payload offered load；其 nominal 参数为 300 Gbps，但当前公式使每 pair 的期望值为 375 Gbps。

不应写成“每个 WAN switch 对实际 TCP 吞吐恒为 300 Gbps”。

## 7. 可复现统计命令

以下命令计算当前文件的总 offered load：

```bash
awk 'NR > 1 {
    bytes += $4
} END {
    printf "flows=%d payload_bytes=%d offered_rate=%.6f Gbps\\n", \
        NR - 1, bytes, bytes * 8 / 0.02 / 1e9
}' config/w-tcp-300.txt
```

以下命令按 WAN host 连续分组计算每个有向 switch 对的 offered load。这里 `222 + sw(host)` 对应 WAN switch ID：

```bash
awk '
function sw(host) { return int((host - 227) / 20) }
NR > 1 {
    bytes[sw($1), sw($2)] += $4
    flows[sw($1), sw($2)]++
}
END {
    for (s = 0; s < 5; ++s) {
        for (d = 0; d < 5; ++d) {
            if (s != d) {
                k = s SUBSEP d
                printf "src_wan=%d dst_wan=%d flows=%d rate=%.6f Gbps\\n", \
                    222 + s, 222 + d, flows[k], bytes[k] * 8 / 0.02 / 1e9
            }
        }
    }
}' config/w-tcp-300.txt
```

该命令依赖当前 `cernet_topo.txt` 中 WAN host ID 为 227-326、每个 WAN switch 20 个 host 的具体映射。若拓扑或 `--wan-hosts-num` 改变，必须按新的拓扑 mapping 统计，不能继续复用该 host-to-switch 算法。
