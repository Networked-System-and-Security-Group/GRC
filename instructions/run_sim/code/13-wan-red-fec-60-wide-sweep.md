# WAN RED/FEC 60 组宽间隔联调模板

用途：
- 用 `w-dynamic-150-200-200` 做 60 组宽间隔 RED/FEC 联调
- 参数跨度比前面更大
- 统计已完成流 FCT

## 1. 流量切片

```bash
python3 config/slice_flow.py config/w-dynamic-150-200.txt config/w-dynamic-150-200-200.txt --until 2.01 --count 200
```

## 2. 跑 60 组

```bash
python3 analysis/run_joint_red_fec_60.py --flow w-dynamic-150-200-200 --simul_time 0.01 --skip-build 1
```

## 3. 输出

- `analysis/reports/<timestamp>/results.csv`
- `analysis/reports/<timestamp>/results.md`
- `analysis/reports/<timestamp>/results.json`

## 4. 回退

- 删除 `analysis/run_joint_red_fec_60.py`
- 删除 `instructions/run_sim/code/13-wan-red-fec-60-wide-sweep.md`
