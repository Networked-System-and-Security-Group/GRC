# WAN dynamic 小窗口对比模板

用途：
- 从 `config/w-dynamic-150-200.txt` 截取前一段流量
- 跑 baseline 和 `RED+FEC`
- 自动比较已完成流量的 FCT

## 1. 先切一个前缀流量集

```bash
python3 config/slice_flow.py config/w-dynamic-150-200.txt config/w-dynamic-150-200-5ms.txt --until 2.005 --count 500
```

## 2. 跑 baseline

```bash
python3 run.py --topo cernet_topo --my_flow w-dynamic-150-200-5ms --tcp_flow '' --simul_time 0.005 --wan_cc_mode 1 --fec-n 0 --stdout 1 --msg 'baseline 5ms'
```

## 3. 跑 RED+FEC

```bash
python3 run.py --topo cernet_topo --my_flow w-dynamic-150-200-5ms --tcp_flow '' --simul_time 0.005 --wan_cc_mode 1 --fec-n 1 --stdout 1 --extra WAN_RED_ENABLE=TRUE --extra WAN_RED_KMIN=131072 --extra WAN_RED_KMAX=1048576 --extra WAN_RED_PMAX=0.1 --extra WAN_RED_WQ=0.002 --msg 'red fec 5ms'
```

## 4. 自动比较 FCT

```bash
python3 analysis/compare_fct.py mix/output/[id1]-... mix/output/[id2]-...
```

输出内容：
- 流总数
- 已完成流数量和完成率
- 平均 FCT
- P99 FCT
- 两组平均 FCT 比值
- 已完成流数量差值

## 5. 回退

如果只回退模板相关修改，删掉：
- `config/slice_flow.py`
- `analysis/compare_fct.py`
- `instructions/run_sim/code/08-wan-dynamic-fct-compare-template.md`
