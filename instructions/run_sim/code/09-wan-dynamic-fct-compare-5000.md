# WAN dynamic 5000 流对比模板

用途：
- 从 `config/w-dynamic-150-200.txt` 截取前 5000 条流
- 在同一模拟时间下对比 baseline、`RED`、`RED+FEC`
- 只统计已完成流的 FCT

## 1. 先切 5000 流

```bash
python3 config/slice_flow.py config/w-dynamic-150-200.txt config/w-dynamic-150-200-5000.txt --until 2.016738 --count 5000
```

## 2. 跑 baseline

```bash
python3 run.py --topo cernet_topo --my_flow w-dynamic-150-200-5000 --tcp_flow '' --simul_time 0.02 --wan_cc_mode 1 --fec-n 0 --stdout 1 --msg '5000 baseline'
```

## 3. 跑 RED

推荐先用更保守的一组参数，避免 RED 过早把队列打散：

```bash
python3 run.py --topo cernet_topo --my_flow w-dynamic-150-200-5000 --tcp_flow '' --simul_time 0.02 --wan_cc_mode 1 --fec-n 0 --stdout 1 --extra WAN_RED_ENABLE=TRUE --extra WAN_RED_KMIN=262144 --extra WAN_RED_KMAX=2097152 --extra WAN_RED_PMAX=0.05 --extra WAN_RED_WQ=0.001 --msg '5000 red'
```

## 4. 跑 RED+FEC

FEC 先用较小冗余，避免 repair 包把热点出口再顶满：

```bash
python3 run.py --topo cernet_topo --my_flow w-dynamic-150-200-5000 --tcp_flow '' --simul_time 0.02 --wan_cc_mode 1 --fec-n 2 --stdout 1 --extra WAN_RED_ENABLE=TRUE --extra WAN_RED_KMIN=262144 --extra WAN_RED_KMAX=2097152 --extra WAN_RED_PMAX=0.05 --extra WAN_RED_WQ=0.001 --msg '5000 red fec2'
```

## 5. 自动比较

```bash
python3 analysis/compare_fct.py mix/output/[baseline]-... mix/output/[red]-... mix/output/[fec]-...
```

输出内容：
- 流总数
- 已完成流数量和完成率
- 平均 FCT
- P99 FCT
- 相对 baseline 的平均 FCT / P99 比值

## 6. 回退

只回退这次模板相关内容，删掉：
- `config/w-dynamic-150-200-5000.txt`
- `instructions/run_sim/code/09-wan-dynamic-fct-compare-5000.md`
