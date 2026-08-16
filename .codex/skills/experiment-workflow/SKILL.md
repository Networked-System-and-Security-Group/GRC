---
name: experiment-workflow
description: 在本仓库中运行指定实验或小规模参数 sweep，完成启动脚本、结果分析和结论文档归档。适用于用户要求跑实验、比较结果、总结结论、沉淀报告或复现实验的场景。
---

# Experiment Workflow

本 skill 只用于“执行并沉淀实验”。如果用户要求修改仿真器逻辑、路由算法、HWP/SPFC 机制、拓扑格式或分析文件格式，先按代码修改任务处理；只有实际启动实验或整理实验报告时才使用本 skill。

## 必须遵守的归档约束

每完成一项新的实验内容，必须在项目根目录单独创建一个 `expr-xxx/` 目录，不能把新的详细实验结论文档继续放到 `docs/`、`docs/experiments/` 或 `docs/archive/experiments/`。
一般来讲，实验是按照“目的”去划分的。如果用户只是让你在某个实验的基础上进行简单的延伸，那么你应该在该实验的目录内完成。例如：额外扫几组参数、增加几种分析等。

推荐命名：

- `expr-<MMDD>-<short-tag>/`
- 示例：`expr-0324-queue-snapshot/`、`expr-0413-ubflat-rail-sweep/`

每个 `expr-xxx/` 至少包含：

- `run.sh`：实验启动脚本，保存实际运行命令，一般是用作启动仿真实验
- `report.md`：结论文档，写清楚实验目的、配置、实验 ID、分析方法、结果和结论，必须使用中文进行撰写
如果实验分为多段，那么可以有多个report.md。

当你发现一个分析脚本可能需要在多个实验之间进行复用，你应当将其抽取为一个公共脚本并放在analysis目录下

按需增加：

- `analyze.py`：本次实验专用分析脚本。
- `summary.csv`：聚合结果。
- `notes.md`：补充观察或失败记录。

`docs/Experiment_Iteration_Log.zh-CN.md` 只保留项目级索引和简要结论，每条实验摘要必须包含“目的、内容、结论、索引”；详细报告入口应指向对应 `expr-xxx/report.md`。

## 实验前确认

开始前确认最小实验规格：

- 拓扑：常见 `topo256e`、`UB-Flat-Rail1/2/4/8`。
- 流量：常见 `moe256-{0,1,2}{c,d}` 或 `ubflat-moe256-0c/0d`。
- LB：常见 `adaptive`、`ear`、`hwp`。
- 路由：常见 `ub`、`ubflat`、`ft`。
- 额外参数：例如 `--queue_snapshot_interval_ns`、`--setting KEY=VALUE`、`--spfc_*`。
- 实验 tag：写入 `--msg`，便于从 `config.txt` 反查。

用户不希望你带着疑惑开始正式的实验。只有当你完全理解需求之后，才能开始实验。如果你有不确定的地方，先积极地与用户沟通

## 启动实验

常用入口：

```bash
python3 run.py --topo topo256e --my_flow moe256-0d --lb hwp --routing ub --pfc 0 --msg <tag>
```

事实和陷阱：

- `run.py` 会先执行 `./waf`。
- 输出目录位于 `mix/output/[id]-.../`。
- 默认后台执行，stdout/stderr 写入实验目录的 `config.log`。
- `--stdout` 和 `--debug` 是 `type=bool`，不要传 `0/1` 字符串。
- 不要只凭 latest 目录定位并发实验；优先用 `MSG`、`--setting STUDY_TAG=...` 或实验 ID。
- 文档里提到的 `--blocking` 不是当前 `run.py` 的真实参数；等待实验用 `python3 check.py wait`。

常用检查：

```bash
python3 check.py state 5
python3 check.py wait
python3 check.py kill <expr_id>
```

## 常用参数

- `--topo`：拓扑名，不带 `config/` 和 `.txt`。
- `--my_flow`：流量名，不带 `config/` 和 `.txt`。
- `--lb`：负载均衡模式。
- `--routing`：`ub`、`ubflat`、`ft`。
- `--pfc`：常规实验多为 `0`。
- `--queue_snapshot_interval_ns`：AR/adaptive、EAR、HWP 的队列快照刷新间隔；`0` 表示实时读取。
- `--setting KEY=VALUE`：透传临时字符串配置，例如 `UB_RANDOM_PORT_LIMIT=2`。
- `--spfc_kmin`、`--spfc_kmax`、`--spfc_pmax`、`--spfc_detour_trigger`、`--spfc_detour_permit_init`、`--spfc_qlen_quant`、`--spfc_k_decay_factor`、`--spfc_extra_cost_decay`、`--spfc_enablecc`：HWP/SPFC 参数。

注意：

- `BUFFER_SIZE` 当前不真正决定交换机队列长度，不应作为有效实验变量，除非先改 C++。
- `ERROR_RATE_PER_LINK` 当前主路径固定为 0.0，不应作为有效实验变量。
- `run.py --cc hpcc/timely/dctcp` 当前不可靠，常规实验优先使用默认 `none`。

## 分析实验

分析脚本应在项目 Python 环境下运行。常用入口：

```bash
python3 -c "from analysis.deep_analyse import latest; a=latest(); a.show_summary()"
python3 -c "from analysis.deep_analyse import get_analyser; a=get_analyser(123); a.show_summary()"
python3 -c "from analysis.deep_analyse import list_expr_table; list_expr_table('1-24', 'FLOW_FILE', 'QUEUE_LENGTH_SNAPSHOT_INTERVAL_NS', 'CT')"
```

优先汇总：

- 完成时间
- 平均/P99 FCT slowdown
- 平均链路利用率


## 报告要求

`expr-xxx/report.md` 至少包含：

1. 实验目的
2. 实验配置范围
3. 实际启动命令或 `run.sh` 说明
4. 实验目录或实验 ID 映射
5. 分析入口和指标
6. 结果表格或摘要
7. 结论和下一步
8. 失败实验、异常退出或不可信数据说明

完成后更新 `docs/Experiment_Iteration_Log.zh-CN.md` 的简要索引，指向 `expr-xxx/report.md`。除非用户明确要求，不要把新的详细实验报告写入 `docs/`、`docs/experiments/` 或 `docs/archive/experiments/`。

实验报告可读性要求：
1. 数字可读性，正确地截断小数位数。恰当地换算单位，例如使用“1.3MB”而不是“1323243243 bytes”
2. 实验设置。优先使用表格去表达每个实验设置对应的id，而不是使用bullet放一长串

## 相关参考

- `AGENTS.md`
- `run.py`
- `check.py`
- `analysis/deep_analyse.py`
- `docs/Experiment_Iteration_Log.zh-CN.md`
- `docs/tech/Runtime_And_Analysis.zh-CN.md`
