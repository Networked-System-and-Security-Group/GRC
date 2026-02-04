# WAN 路由 / GSCC 逻辑：`WanRouting`

核心文件：
- `src/point-to-point/model/wan-routing.h/.cc`

## 关键对象与挂载位置

- 每个交换机节点有 `SwitchMmu`
- `SwitchMmu` 内包含 `WanRouting m_wanRouting`
- 在 `scratch/remote.cc` 中，对所有 DCI_SWITCH 调用：
  - `m_wanRouting.SetSwitchInfo(i)`
  - `m_wanRouting.init()`

## 数据平面：`RouteInput()`

- 非 DCI_SWITCH：直接转发
- DCI_SWITCH：按协议分流
  - UDP（0x11）→ `HandleUdpReceived`
  - ACK（0xFC）→ `HandleAckReceived`

### `HandleUdpReceived` 的关键机制

- 先按目的 host 映射到 `dst_as`
- 若 `dst_as == cur_as`：回到 DC 内普通转发
- 否则：
  - 计算 5 元组 hash，选择 `m_rtTable[dst_as]` 的出端口（带 flowlet）
  - 维护 per-(dst_as,out_port) 的 `DstDCHandler`
  - 若 `Settings::wan_cc_mode == WAN_OPT`：可能触发 `send_cnp()`

### `HandleAckReceived` 的关键机制

- 用 ACK 序列与哈希表匹配 RTT entry
- `DstDCHandler::record_rtt()` 更新 RTT 估计与 sensitive RTT

## 控制面：`controlplane_logic()`

- 周期触发（`epoch_duration`），会写：
  - `rtt_log`
  - `rate_monitor`
- 在 `WAN_OPT` 模式下会进行 ref_rate 更新与字节窗口调整

## 与日志的关系（AI 改动风险点）

- `rtt_log` / `rate_monitor` / `accumulated_bytes_log` 的 CSV 头由 `initialize_log()` 定义
- 任何列名/列数变化都必须同步更新 Python 分析脚本

