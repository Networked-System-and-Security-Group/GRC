# WAN RED/FEC 15 组联调模板

用途：
- 基于 `w-dynamic-150-200-1000` 做 15 组 RED/FEC 联调
- 复用已有 baseline `[215]`
- 比较已完成流的 FCT

## 1. 基线

基线使用已完成的：

- `mix/output/[215]-05-10-09:32:20`

## 2. 跑 15 组联调

```bash
python3 analysis/run_joint_red_fec_15.py --flow w-dynamic-150-200-1000 --simul_time 0.01 --skip-build 1
```

默认 15 组为：
- 5 组 RED 配置
- 每组配 3 个 `FEC_PARITY_PKTS`
- 共 15 个组合

## 3. 输出

结果写到：

- `analysis/reports/<timestamp>/results.csv`
- `analysis/reports/<timestamp>/results.md`
- `analysis/reports/<timestamp>/results.json`

每个实验独立写到：

- `mix/output/[id]-.../`

## 4. 回退

删除：

- `analysis/run_joint_red_fec_15.py`
- `instructions/run_sim/code/12-wan-red-fec-15-joint-sweep.md`

## 5. 已完成结果

报告目录：

- `analysis/reports/wan-red-fec-15-joint-200/`

最佳组合：

- `RED kmin=262144, kmax=1048576, pmax=0.05, wq=0.002`
- `fec-n=0`
- avg FCT: `0.001247s`
- p99 FCT: `0.008033s`

阶段性观察：

- `fec-n=0/4` 组整体优于 baseline
- `fec-n=10` 组明显恶化
- 最优点出现在 `kmin=262144`、`pmax=0.05`、`wq=0.002` 附近
