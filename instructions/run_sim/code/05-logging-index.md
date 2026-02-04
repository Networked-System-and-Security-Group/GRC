# 日志产出点索引（文件 → 写入代码位置）

目的：让 AI 能快速定位“这个文件是谁写的/在哪写的”。

## 统一初始化

- `src/point-to-point/model/settings.cc::logfile::initialize_log()`
  - 打开文件、写 CSV header（或重定向到 `/dev/null`）

## 结果与核心日志

- `flow_output`
  - 写入：`scratch/remote.cc::output_flow_info()`（JSON array）
- `drop_log`
  - 写入：`src/point-to-point/model/switch-node.cc::DoSwitchSend()`（ingress/egress drop）
- `buffer_monitor`
  - 写入：`src/point-to-point/model/switch-mmu.h::printBufferInfo()`
- `rtt_log` / `rate_monitor` / `accumulated_bytes_log`
  - 写入：`src/point-to-point/model/wan-routing.cc`（控制面/周期任务）
- `qp_rate_log`
  - 写入：`scratch/remote.cc::m_QP_rate_monitoring()`（注意当前可能被定向到 `/dev/null`）

## 分析侧读取（Python）

- 主要集中在 `analysis/deep_analyse.py`：
  - `flow_output`（json.load）
  - 其余多为 `pd.read_csv`，列名依赖 CSV header

