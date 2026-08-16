# WAN RED/FEC 扫参修改记录

时间：2026-05-10

## 本轮修改目标

把 WAN 侧 `RED` 和 `FEC` 的参数敏感性实验做成可批量执行、可汇总、可回退的流程。

## 实际改动

### 1. `run.py`

- 新增 `--fec-n`，把 `FEC_PARITY_PKTS` 透传进 `config.txt`
- 新增 `--skip-build`，方便批量实验时跳过重复 `./waf`
- 继续保留 `--extra KEY=VALUE`，用于传 `WAN_RED_*`
- 输出仍落到 `mix/output/[id]-.../config.log`

### 2. `analysis/sweep_wan_red_fec.py`

- 新增批量扫参脚本
- 自动跑：
  - baseline
  - RED 的多组 `WAN_RED_KMIN`
  - RED 的多组 `WAN_RED_KMAX`
  - RED 的多组 `WAN_RED_PMAX`
  - RED 的多组 `WAN_RED_WQ`
  - 多组 `FEC_PARITY_PKTS`
- 自动统计：
  - total flows
  - completed flows
  - completion rate
  - avg FCT
  - p99 FCT
  - relative ratio vs baseline
- 自动生成：
  - `analysis/reports/<timestamp>/results.csv`
  - `analysis/reports/<timestamp>/results.md`
  - `analysis/reports/<timestamp>/results.json`

### 3. 文档

- 新增扫参模板：`instructions/run_sim/code/10-wan-red-fec-sensitivity-sweep.md`
- 更新 `instructions/run_sim/code/README.md` 索引

## 回退方式

### 只回退实验工具

- 删除 `analysis/sweep_wan_red_fec.py`
- 删除 `instructions/run_sim/code/10-wan-red-fec-sensitivity-sweep.md`
- 删除 `instructions/run_sim/code/11-wan-red-fec-sweep-change-log.md`

### 回退 `run.py`

- 删除 `--skip-build`
- 删除 `--fec-n`
- 恢复原来的 `./waf` 启动逻辑

### 风险说明

- 当前扫参脚本是单变量敏感性，不是全量二维/三维网格
- `RED` 和 `FEC` 的最佳点还需要靠实验结果确认，不应直接默认

## 已执行的参数敏感性实验

### 实验输入

- 流量切片：`config/w-dynamic-150-200-1000.txt`
- 模拟时间：`0.01s`
- 运行命令：

```bash
python3 analysis/sweep_wan_red_fec.py --flow w-dynamic-150-200-1000 --simul_time 0.01 --skip-build 1 --report-name wan-red-fec-sweep-1000
```

### 已完成的阶段性结果

当前已经完成：

- baseline：`mix/output/[215]-05-10-09:32:20`
- `RED kmin=131072`：`mix/output/[216]-05-10-09:33:36`
- `RED kmin=262144`：`mix/output/[217]-05-10-09:34:53`

对应结果：

- baseline
  - avg FCT: `0.001727s`
  - p99 FCT: `0.008280s`
- `kmin=131072`
  - avg FCT: `0.001765s`
  - p99 FCT: `0.009298s`
  - avg ratio vs baseline: `1.0221`
  - p99 ratio vs baseline: `1.1229`
- `kmin=262144`
  - avg FCT: `0.001752s`
  - p99 FCT: `0.008750s`
  - avg ratio vs baseline: `1.0143`
  - p99 ratio vs baseline: `1.0567`

### 阶段性观察

- 在这组 1000-flow 小切片上，当前已完成的 `RED kmin` 扫描都没有优于 baseline
- `kmin=262144` 比 `kmin=131072` 更接近 baseline，说明过早 RED 更容易恶化 tail
- 当前更像是：
  - 较小 `kmin` 更敏感，尾延迟更差
  - 适当放宽 `kmin` 能减轻伤害，但还没有观察到正收益

### 说明

- 完整 sweep 仍在继续，会继续补充 `kmax` / `pmax` / `wq` / `fec-n` 的结果
- 若只看目前已完成结果，baseline 仍是最优
