# 仿真入口与主流程

## 入口文件

- `run.py`：生成 config + 调起 `scratch/remote`
- `scratch/remote.cc`：仿真主程序（解析 config、建拓扑、装 RDMA、跑仿真、写输出）

## `scratch/remote.cc` 的主流程（高层）

1. 解析 `config.txt`
   - 关键：`OUTPUT_DIR_PATH`、`TOPOLOGY_FILE`、`FLOW_FILE`、`WAN_CC_MODE`、`CC_MODE`、`LB_MODE` 等
2. 设置随机种子，初始化全局 `Settings`，并 `initialize_log()` 打开输出文件
3. 读取拓扑 JSON，初始化 `Settings::nodeInfos` 和链路列表
4. 创建 NodeContainer（Host / DC_SWITCH / DCI_SWITCH / WAN_SWITCH）并安装协议栈
5. 根据拓扑创建链路（QbbHelper），分配 IP，填充 `Settings::nbr2if/if2id/pairDelay/pairBw/...`
6. 计算路由（`CalculateRoutes` / `SetRoutingEntries` / WAN routing init）
   - DCI_SWITCH 上会初始化 `SwitchNode::m_mmu->m_wanRouting`
7. 配置 RDMA 硬件与 driver，并挂载 `QpComplete` 回调
8. 读取 flow 文件并 schedule flows
9. 启动周期性监控（buffer / qp_rate 等）
10. 启动 stop 条件：`stop_simulation_middle()`
11. `Simulator::Run()`
12. 结束：`output_flow_info()` 写 `flow_output`（JSON）

AI 做修改时最常见的落点：
- 新增/解析 config key：在“解析 config.txt 的 while 循环”
- 修改 WAN 行为：`Settings::wan_cc_mode` / `WanRouting` / `SwitchNode` 相关分支
- 新增输出：`Settings::initialize_log()` + 写入点

