# WAN RED 实现与回退说明

这份文档只描述这次**已经实际落地**的修改，目的是方便你后续：

- 理解当前 RED 是怎么接进去的
- 快速验证它影响了哪些路径
- 在不误删其他改动的前提下做精确回退

## 改动范围

这次实现只改了两个代码文件：

- `src/point-to-point/model/wan-routing.h`
- `src/point-to-point/model/wan-routing.cc`

没有改：

- `switch-node.cc`
- `switch-mmu.cc`
- `settings.h/.cc`
- `run.py`
- `scratch/remote.cc`

这意味着当前实现是一个**局部实现**：

- RED 只挂在 `WanRouting`
- 只影响进入 `WanRouting::HandleUdpReceived()` 的跨 AS UDP 数据包
- 不影响 ACK、CNP、PFC
- 不影响普通 DC 内转发

## 生效位置

当前 `WanRouting` 只在 DCI switch 上初始化：

- `scratch/remote.cc` 里只对 `NodeType::DCI_SWITCH` 调用
  `m_mmu->m_wanRouting.SetSwitchInfo(i)` 和 `init()`

因此这版 RED 的真实作用范围是：

- **DCI switch 上的 WAN 出口流量**

不是：

- 所有 WAN_SWITCH
- 所有交换机统一 RED

如果以后你要扩展到 `WAN_SWITCH`，要先改 `scratch/remote.cc` 的初始化范围。

## 具体改了什么

### 1. `src/point-to-point/model/wan-routing.h`

新增了 RED 相关头文件：

- `#include "ns3/random-variable-stream.h"`

新增了 `DstDCHandler` 内部状态：

- `double red_avg_q`
- `uint64_t red_drop_cnt`
- `uint64_t red_pass_cnt`

新增了 `DstDCHandler` 方法：

- `UpdateRedAvg(...)`
- `ShouldEarlyDrop(...)`
- `ResetEpochRedStats()`

新增了 `WanRouting` 级别配置和工具：

- `bool m_red_enabled`
- `uint32_t m_red_kmin`
- `uint32_t m_red_kmax`
- `double m_red_pmax`
- `double m_red_wq`
- `UniformRandomVariable m_red_uniform`

新增了 `WanRouting` 方法：

- `LoadRedConfig()`
- `MaybeRedDrop(...)`

对应位置见 [wan-routing.h](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.h#L17) 和 [wan-routing.h](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.h#L71)。

### 2. `src/point-to-point/model/wan-routing.cc`

新增了 RED 默认参数常量：

- `WAN_RED_ENABLE` 默认 `FALSE`
- `WAN_RED_KMIN` 默认 `131072`
- `WAN_RED_KMAX` 默认 `1048576`
- `WAN_RED_PMAX` 默认 `0.1`
- `WAN_RED_WQ` 默认 `0.002`

这些默认值放在文件顶部匿名命名空间里。

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L17)。

### 3. `WanRouting::DstDCHandler::Init()`

初始化时增加了 RED 状态复位：

- `red_avg_q = 0.0`
- `ResetEpochRedStats()`

这样每个 `dst_as` 都有自己独立的 RED 统计状态。

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L44)。

### 4. 新增 RED 平均队列与概率判定

实现了三个函数：

- `UpdateRedAvg(...)`
- `ShouldEarlyDrop(...)`
- `ResetEpochRedStats()`

逻辑是：

1. 用 `red_wq` 做 EWMA：
   `red_avg_q = (1 - wq) * red_avg_q + wq * q_bytes`
2. 若 `red_avg_q <= kmin`，不丢
3. 若 `red_avg_q >= kmax`，必丢
4. 中间区间按线性概率 `pmax * (avg-kmin)/(kmax-kmin)` 抽样丢

这里的队列长度单位是**字节**。

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L126)。

### 5. 新增配置加载 `LoadRedConfig()`

当前没有改 `run.py` 和 `scratch/remote.cc` 的 typed parser。

所以 RED 参数是通过已有的 raw param 通道读取的，也就是：

- 只要 `config.txt` 里出现未被显式解析的键
- `scratch/remote.cc` 会把它们存进 `Settings::SetRawParam(...)`
- `WanRouting::LoadRedConfig()` 再通过 `Settings::GetRawParam(...)` 读取

支持的键：

- `WAN_RED_ENABLE`
- `WAN_RED_KMIN`
- `WAN_RED_KMAX`
- `WAN_RED_PMAX`
- `WAN_RED_WQ`

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L159)。

### 6. `WanRouting::init()` 中加载 RED 配置

在 `init()` 最开始调用了：

- `LoadRedConfig()`

这样每个 DCI switch 的 `WanRouting` 在启动时就会拿到 RED 配置。

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L177)。

### 7. 新增实际丢包入口 `MaybeRedDrop(...)`

这是这次实现最关键的落点。

逻辑：

1. 如果 `m_red_enabled == false`，直接返回
2. 找到当前 `out_port` 对应的 `QbbNetDevice`
3. 读取队列长度：`dev->GetQueue()->GetNBytes(ch.udp.pg)`
4. 调用 `dc_handler.ShouldEarlyDrop(...)`
5. 命中时写 `drop_log` 并直接返回 `true`

这意味着：

- 丢包发生在真正进入 `SwitchNode::DoSwitchSend()` 之前
- 被 RED 丢掉的包不会走后续 egress/ingress admission
- 也不会触发该包对应的后续 `m_switchSendCallback(...)`

drop log 里新增使用了：

- `type = 2`

约定：

- `0` 仍表示 ingress drop
- `1` 仍表示 egress drop
- `2` 表示 `WanRouting` 里的 RED early drop

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L201)。

### 8. 在 `HandleUdpReceived()` 插入 RED 判定

插入点放在：

- 更新完 `cur_rate`
- 发送 CNP 判断之前
- `m_switchSendCallback(...)` 之前

即：

1. 先做 RTT/速率统计
2. 再做 RED 丢包
3. 没丢的话再继续原有 CNP/WAN-OPT 逻辑

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L243)。

### 9. 在 `controlplane_logic()` 增加 RED 统计输出

每个 epoch 都会往 `wan_log` 追加一行：

- `timestamp`
- `switch_id`
- `as_id`
- `red_enabled`
- `red_avg_q`
- `red_drop_cnt`
- `red_pass_cnt`

注意：

- 这里复用了已有 `wan_log`
- 没有新开日志文件
- 每个 epoch 结束后会 `ResetEpochRedStats()`

对应位置见 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc#L372)。

## 这版实现的行为边界

当前实现有几个你需要明确知道的限制：

### 1. 只对 DCI switch 生效

原因不是 RED 写死了 DCI，而是 `WanRouting` 当前只在 DCI 上初始化。

### 2. 只对跨 AS 的 UDP 数据包生效

`HandleUdpReceived()` 里先判断：

- 如果 `dst_as == cur_as`，直接回 DC 内路径，不做 RED

### 3. 只看瞬时 per-queue 字节数，再做 EWMA

当前队列输入是：

- `dev->GetQueue()->GetNBytes(ch.udp.pg)`

也就是当前优先级队列的瞬时字节数。

不是：

- MMU egress shared bytes
- 端口总队列长度
- ingress/egress admission 使用的内部统计值

### 4. RED 丢包不会增加 `Settings::dropped_pkt_sw_ingress/egress`

因为它不经过 `SwitchNode::DoSwitchSend()` 的那两个分支。

所以如果你只看 `my_periodic_monitoring()` 打印的这两个计数器，RED 丢包不会反映进去。
真正的依据应该看：

- `mix/output/[id]-.../config.log`
- `drop_log`
- `wan_log`

## 回退点

如果要回退这次实现，优先检查并撤销以下两处：

- `src/point-to-point/model/wan-routing.h`
- `src/point-to-point/model/wan-routing.cc`

如果只想回退实验输出重定向，再撤销：

- `run.py`
- `instructions/run_sim/code/01-simulation-entry.md`

- `drop_log` 里的 `type=2`
- `wan_log` 里的 `red_drop_cnt`

## 如何开启

当前不需要再改 C++ parser。

只要让生成出来的 `config.txt` 里带上这些键即可：

```txt
WAN_RED_ENABLE TRUE
WAN_RED_KMIN 131072
WAN_RED_KMAX 1048576
WAN_RED_PMAX 0.1
WAN_RED_WQ 0.002
```

如果你用 `run.py`，最方便的是用已有的 `--extra`：

```bash
python3 run.py \
  --extra WAN_RED_ENABLE=TRUE \
  --extra WAN_RED_KMIN=131072 \
  --extra WAN_RED_KMAX=1048576 \
  --extra WAN_RED_PMAX=0.1 \
  --extra WAN_RED_WQ=0.002
```

## 如何验证

建议看三处：

1. `drop_log`
   重点看 `type == 2`
2. `wan_log`
   看每个 epoch 的 `red_drop_cnt` / `red_pass_cnt`
3. 仿真行为
   看 flow 完成时间、重传、吞吐是否发生变化

## 回退步骤

如果你只想回退这次 RED，实现最小回退就是把 `wan-routing.*` 里的新增内容删掉。

### 方案 A：精确回退

回退 [wan-routing.h](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.h)：

- 删除 `random-variable-stream.h` 头文件
- 删除 `DstDCHandler` 的 RED 字段和方法声明
- 删除 `WanRouting` 的 RED 配置字段
- 删除 `LoadRedConfig()` / `MaybeRedDrop(...)` 声明

回退 [wan-routing.cc](/home/niuzihan26/gscc/RDMA-WAN-Optimization/src/point-to-point/model/wan-routing.cc)：

- 删除 RED 默认参数常量
- 删除构造函数里的 `m_red_uniform.SetStream(0);`
- 删除 `Init()` 里的 `red_avg_q` 初始化
- 删除 `UpdateRedAvg(...)`
- 删除 `ShouldEarlyDrop(...)`
- 删除 `ResetEpochRedStats()`
- 删除 `LoadRedConfig()`
- 删除 `MaybeRedDrop(...)`
- 删除 `init()` 里的 `LoadRedConfig()`
- 删除 `HandleUdpReceived()` 里的 `if (MaybeRedDrop(...)) return;`
- 删除 `controlplane_logic()` 里的 RED 日志输出和 `ResetEpochRedStats()`

### 方案 B：逻辑关闭，不删代码

如果你只是想暂时禁用：

```txt
WAN_RED_ENABLE FALSE
```

这样代码还在，但不会生效。

## 编译结果

这次实现后我执行了：

```bash
./waf build
```

结果：

- 编译成功
- 只出现了一个与这次改动无关的已有 warning：
  `scratch/remote.cc` 里 `printf("TCP flow num: %lu\n", tcp_flow_num);`
