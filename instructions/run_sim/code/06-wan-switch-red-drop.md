# WAN 交换机 RED 丢包实现说明

这份说明针对“在 WAN switch 上做随机早期检测（RED）并丢包”。

## 现有链路

当前 WAN 侧数据路径是：

`SwitchNode::SendToDev()` -> `WanRouting::RouteInput()` -> `WanRouting::HandleUdpReceived()` -> `SwitchNode::DoSwitchSend()`

也就是说，WAN 交换机真正的 WAN 逻辑不在 `DoSwitchSend()` 里，而是在 `WanRouting` 里先做路由/统计，再回调到 `SwitchNode` 进入队列和 admission check。

## 推荐插入点

优先把 RED 放在 `src/point-to-point/model/wan-routing.cc::WanRouting::HandleUdpReceived()`。

原因：

- 这里已经知道 `dst_as`、`out_port`、`dc_handler`
- 这里天然只影响 WAN 数据流，不会误伤本地 DC 内转发
- 这里已经有按 epoch 统计的 `epoch_pkt_cnt` / `epoch_cnp_cnt`，适合扩展成 RED 统计

如果你想做“更通用的 egress RED”，也可以放到 `src/point-to-point/model/switch-node.cc::DoSwitchSend()`，但那样要自己区分 WAN 端口和普通端口。

## 需要改的文件

### 1. `src/point-to-point/model/wan-routing.h`

建议新增：

- `WanRouting` 级别的 RED 开关和参数
- `DstDCHandler` 里的 RED 状态

建议新增变量：

- `bool m_red_enabled`
- `uint32_t m_red_kmin`
- `uint32_t m_red_kmax`
- `double m_red_pmax`
- `UniformRandomVariable m_red_rng`

建议新增到 `DstDCHandler`：

- `double red_avg_q`
- `Time red_last_update`
- `uint64_t red_drop_cnt`
- `uint64_t red_pass_cnt`

建议新增方法：

- `void InitRed(...)`
- `void UpdateRedAvg(uint32_t q_bytes)`
- `bool ShouldEarlyDrop(uint32_t pkt_size, uint32_t q_bytes)`
- `void ResetRedStats()`

### 2. `src/point-to-point/model/wan-routing.cc`

这里实现 RED 判定和实际丢包。

建议改动点：

- `DstDCHandler::Init()` 里初始化 RED 统计字段
- `WanRouting::HandleUdpReceived()` 里，在 `m_switchSendCallback(...)` 之前插入 RED 判断
- `WanRouting::controlplane_logic()` 里按 epoch 输出 RED 统计，并清零 epoch 计数

建议丢包方式：

- 直接 `return;`
- 同时写 `logfile::drop_log`
- `type` 字段建议新增一个值，比如 `2` 表示 `WAN_RED`

### 3. `src/point-to-point/model/switch-node.h`

如果你想把 RED 做成可复用的 switch helper，可以加一个小封装方法：

- `bool IsWanSwitch() const`
- `bool ShouldWanEarlyDrop(...)`

如果 RED 全部放在 `WanRouting`，这个文件可以不改。

### 4. `src/point-to-point/model/switch-node.cc`

只有在“做通用 egress RED”时才需要改这里。

建议插入位置：

- `SwitchNode::DoSwitchSend()` 里，`CheckEgressAdmission()` / `CheckIngressAdmission()` 之前

建议新增逻辑：

- 读取当前 egress 队列占用
- 计算 RED 概率
- 命中后直接写 `drop_log` 并返回

### 5. `src/point-to-point/model/switch-mmu.h` / `switch-mmu.cc`

如果 RED 需要看队列长度，而不是只看 `WanRouting` 的 epoch 统计，就需要补 getter。

建议新增方法：

- `uint32_t GetUsedEgressBytes(uint32_t port, uint32_t qIndex) const`
- `uint32_t GetUsedIngressBytes(uint32_t port) const`
- `uint32_t GetUsedTotalBytes() const`

如果只用 `GetUsedBufferTotal()` 也能做，但粒度会更粗。

### 6. `src/point-to-point/model/settings.h` / `settings.cc`

如果你想把 RED 参数做成全局配置，建议加：

- `static bool wan_red_enabled`
- `static uint32_t wan_red_kmin`
- `static uint32_t wan_red_kmax`
- `static double wan_red_pmax`

如果你更想少改代码，也可以不加 typed 成员，直接用 `Settings::GetRawParam("WAN_RED_*")` 读取。

### 7. `scratch/remote.cc`

这里负责把配置写进仿真对象。

两种做法：

- 最小改法：不改 parser，直接让 `wan-routing.cc` 用 `Settings::GetRawParam(...)`
- 显式改法：在解析 config 时增加 `WAN_RED_ENABLE` / `WAN_RED_KMIN` / `WAN_RED_KMAX` / `WAN_RED_PMAX`

如果你要在 CLI 里暴露参数，还要同步改 `run.py`

## 建议的最小实现

1. 在 `WanRouting::HandleUdpReceived()` 里，计算当前目的 `dst_as` 的 RED 概率。
2. 用 `UniformRandomVariable` 抽样，命中就丢包并写 `drop_log`。
3. 默认只对 `ch.l3Prot == 0x11` 的 WAN 数据包生效，ACK/CNP 不丢。
4. 先复用现有 `drop_log`，不要先新建日志文件。

## 额外建议

- RED 参数最好按 `dst_as` 或 `dst_as + out_port` 维度维护
- 如果你用的是字节阈值，建议用 `m_usedEgressBytes[out_port][qIndex]` 或 `GetUsedBufferTotal()`
- 如果你想更像标准 RED，可以加平均队列 `avg_q`，而不是直接用瞬时队列

