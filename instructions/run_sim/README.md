# 运行 / 改参 / 日志开关（GSCC / ns-3.19 仿真）

本文件是 `instructions/run_sim/` 的唯一“实操指南”：
- 如何运行一次实验
- `run.py` 的主要参数、作用与默认值
- 如何在 ns-3 中开启/关闭（落盘）日志

> 这里聚焦“实验相关代码路径”，不覆盖完整 ns-3。

## 索引（按需加载）
- 论文机制概要：`../paper_summary.md`
- 输入格式与生成脚本（topology/flows）：`../config_inputs.md`
- 分析脚本如何运行：`../run_analysis.md`
- 代码细节（多文件地图）：见 `code/` 目录

## A. 一条命令跑一次实验

推荐：

```bash
python3 run.py --simul_time 0.05 --cdf WebSearch --intra_load 30 --inter_load_all 60 --wan_cc_mode 1
```

它会自动完成：
- 编译：`./waf`（`run.py` 内会先调用一次）
- 生成 flow：当 `config/<flow>.txt` 不存在时，调用 `python3 config/wan_traffic_gen.py ...`
- 创建输出目录：`mix/output/[id]-<timestamp>/`
- 写入 `mix/output/[id]-.../config.txt`
- 后台启动仿真：`./waf --run 'scratch/remote <config>'`，stdout/stderr 默认重定向到 `mix/output/.../config.log`

常用辅助命令：
- 查看最近 N 个实验状态：`python3 check.py state [N]`
- 杀掉实验进程：`python3 check.py kill "1-5"`

## B. `run.py` 主要参数（作用 + 默认值）

下面参数来自 `run.py` 的 `argparse` 默认值；如果你要改“默认实验形态”，优先从这里下手。

- `--cc`（默认 `dcqcn`）：DC 内拥塞控制（映射到 `CC_MODE`）
	- 可选：`dcqcn`/`hpcc`/`timely`/`dctcp`
- `--lb`（默认 `fecmp`）：负载均衡/路由方案（映射到 `LB_MODE`）
- `--pfc`（默认 `1`）：是否启用 PFC
- `--irn`（默认 `0`）：是否启用 IRN
	- 约束：`--irn=1` 时必须 `--pfc=0`；`--irn=0` 时必须 `--pfc=1`（`run.py` 有 sanity check）
- `--simul_time`（默认 `0.05`）：生成流量的持续时间（秒）
	- 约束：必须 ≥ 0.005（`run.py` 有 sanity check）
- `--buffer`（默认 `9`）：交换机 buffer size（MB），写入 `BUFFER_SIZE`
- `--dci_buffer`（默认 `0`）：DCI switch buffer size（MB），写入 `DCI_BUFFER_SIZE`
	- `0` 表示保持 C++ 默认值（当前为 160MB）
- `--wan_buffer`（默认 `0`）：WAN switch buffer size（MB），写入 `WAN_BUFFER_SIZE`
	- `0` 表示保持 C++ 默认值（当前为 320MB）
- `--bw`（默认 `100`）：NIC 带宽（Gbps），用于一些参数映射/阈值计算
- `--topo`（默认 `wan_topo_json`）：拓扑文件名（会写 `TOPOLOGY_FILE config/<topo>.txt`）
- `--cdf`（默认 `WebSearch`）：流大小分布（用于 flow generator）
- `--sw_monitoring_interval`（默认 `10000`）：交换机队列/统计采样间隔（ns）
- `--intra_load`（默认 `30`）：DC 内每 host 的发送速率（Gbps，交给 `wan_traffic_gen.py`）
- `--inter_load_all`（默认 `60`）：DC 间总发送速率（Gbps，交给 `wan_traffic_gen.py`）
- `--wan_cc_mode`（默认 `1`）：DC 间（WAN 段）拥塞控制模式，写入 `WAN_CC_MODE`
	- 对应 `Settings::WanCCMode`：`0 NONE` / `1 WAN_OPT` / `2 WITH_ECN`
- `--my_flow`（默认空字符串）：指定自定义 flow 文件名（不带 `.txt`）；为空则用仓库默认命名规则
- `--config`（默认空字符串）：复用已有的 config.txt（会自动替换新的 `OUTPUT_DIR_PATH` 和 `TIME`）
- `--stdout`（默认 `False`）：不重定向日志，直接前台输出
- `--debug`（默认 `False`）：用 gdb 启动 `scratch/remote`（用于调 C++）
- `--msg`（默认空字符串）：追加记录到 `mix/history.txt`

## C. 如何新增/修改一个“实验参数”（约定流程）

当参数需要影响 ns-3（C++）行为时，按这个链路改：
1) `run.py`：新增 CLI 参数 → 写入 `config_template`（增加一行 `KEY {value}`）
2) `scratch/remote.cc`：在读取 `config.txt` 的循环里解析该 `KEY`
3) 将值写入 `Settings`（`src/point-to-point/model/settings.h/.cc`）或传入对应模块（如 `WanRouting` / `SwitchNode` / `SwitchMmu`）

如果参数只影响流量生成：通常只需要改 `run.py` + `config/*.py` 生成脚本。

## D. 如何开启/关闭（落盘）日志

日志文件是否真正落盘，集中由这里控制：
- `src/point-to-point/model/settings.cc::logfile::initialize_log()`

当前很多日志默认被定向到 `/dev/null`（也就是“关闭”）：
- `pfc_file`
- `qp_rate_log`
- `cnp_log`
- `accumulated_bytes_log`
（以及一些 debug 输出如 `cnp_output`/`voq_output`/`uplink_output` 等）

开启某个日志的做法：
- 将对应的 `OPEN_EMPTY_FILE(xxx)` 改成 `OPEN_FILE(xxx)`
- 保持 CSV header/列顺序不变（否则 `analysis/deep_analyse.py` 的 `pd.read_csv(...)` 可能读崩）

例子：开启 `qp_rate_log`
- 在 `initialize_log()` 把 `OPEN_EMPTY_FILE(qp_rate_log);` 改成 `OPEN_FILE(qp_rate_log);`

> 提醒：日志写得太频繁会极大拖慢仿真；如果要加新日志，优先使用“周期采样”（如 1ms）而不是“每包写”。

## E. 代码细节索引（逐文件）

- 仿真入口与主流程：见 [code/01-simulation-entry.md](code/01-simulation-entry.md)
- 配置系统（config.txt → Settings/模块参数）：见 [code/02-config-and-settings.md](code/02-config-and-settings.md)
- WAN 侧 GSCC/路由逻辑：见 [code/03-wan-routing.md](code/03-wan-routing.md)
- 交换机转发/拥塞点：见 [code/04-switch-pipeline.md](code/04-switch-pipeline.md)
- 日志产出点索引：见 [code/05-logging-index.md](code/05-logging-index.md)


