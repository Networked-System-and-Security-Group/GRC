# WAN RED/FEC 参数敏感性扫参模板

用途：
- 用 `config/w-dynamic-150-200-5000.txt` 做 5000 流切片
- 系统性扫描更多 `RED` 和 `FEC` 参数
- 只比较已完成流的 FCT
- 输出 `config.log`、`flow_output` 和汇总报告，方便回看和回退

## 1. 先确认 5000 流切片

```bash
python3 config/slice_flow.py config/w-dynamic-150-200.txt config/w-dynamic-150-200-5000.txt --until 2.016738 --count 5000
```

## 2. 跑敏感性 sweep

```bash
python3 analysis/sweep_wan_red_fec.py --flow w-dynamic-150-200-5000 --simul_time 0.02
```

默认会跑：
- baseline
- 多组 `WAN_RED_KMIN`
- 多组 `WAN_RED_KMAX`
- 多组 `WAN_RED_PMAX`
- 多组 `WAN_RED_WQ`
- 多组 `FEC_PARITY_PKTS`

每个实验都会写到自己的 `mix/output/[id]-.../` 下：
- `config.log`
- `config.txt`
- `flow_output`
- 其他现有日志

汇总报告写到：
- `analysis/reports/<timestamp>/results.csv`
- `analysis/reports/<timestamp>/results.md`
- `analysis/reports/<timestamp>/results.json`

## 3. 判定最优

脚本会自动给出：
- baseline 的平均 FCT / P99 FCT
- 每组参数的平均 FCT / P99 FCT
- 相对 baseline 的比值
- 按平均 FCT 排序后的 best observed 结果

## 4. 回退

如果只回退这次扫参模板：
- 删除 `analysis/sweep_wan_red_fec.py`
- 删除 `instructions/run_sim/code/10-wan-red-fec-sensitivity-sweep.md`

如果还要回退 `run.py` 的跳过编译开关：
- 删除 `--skip-build` 参数
- 恢复 `run.py` 里原来的 `./waf` 调用逻辑
