# GSCC RTT 表深度 1,024 与 65,536 的 Tofino2 MAU 资源对比

## 1. 结论摘要

在相同的 GSCC P4 源码、Tofino2 目标和 bf-p4c 9.7.1 编译环境下，将两张 32-bit RTT 寄存器的深度从 1,024 增加到 65,536 后，两种配置都可以成功编译和安装。主要资源变化集中在 SRAM 和 Map RAM：

| 核心指标 | 1,024 条 | 65,536 条 | 变化 |
|---|---:|---:|---:|
| 全局 SRAM | 29 | 57 | +28，+96.55% |
| 全局 Map RAM | 14 | 44 | +30，+214.29% |
| `gs_rtt_id_reg` RAM / Map RAM | 2 / 2 | 17 / 17 | 各 +15，8.5x |
| `gs_rtt_timestamp_reg` RAM / Map RAM | 2 / 2 | 17 / 17 | 各 +15，8.5x |
| 全局 Meter ALU | 7 | 7 | 不变 |
| 全局 TCAM | 1 | 1 | 不变 |
| 全局 VLIW 指令 | 22 | 22 | 不变 |
| Logical TableID | 19 | 19 | 不变 |

两张 RTT 寄存器的逻辑容量由 8 KiB 增长到 512 KiB，正好增长 64 倍；但编译器报告的每张寄存器物理 RAM/Map RAM 单元由 2 个增长到 17 个，即 8.5 倍。这说明物理资源按照硬件分块、访问和布局粒度分配，不能用逻辑字节数直接线性推导。

## 2. 测试范围与环境

| 项目 | 配置 |
|---|---|
| 远端主机 | `192.168.5.220` |
| 远端源码 | `/sde/bf-sde-9.7.1/spfc/gscc-dataplane/gscc.p4` |
| SDE | `bf-sde-9.7.1` |
| 编译器 | `bf-p4c 9.7.1`，SHA `4316cda` |
| P4 版本/架构 | `p4_16/t2na` |
| 芯片目标 | Tofino2 |
| 比较参数 | `GS_RTT_TABLE_SIZE = 1024` 和 `65536` |
| 资源日志 | `gs_pipe/logs/mau.resources.log` |
| 测试日期 | 2026-08-15 |

两次编译均使用：

```bash
../p4_build.sh --with-tofino2 gscc-dataplane/gscc.p4 \
  P4_VERSION=p4_16 \
  P4_ARCHITECTURE=t2na
```

两份构建日志均以以下状态结束：

```text
MAKE ... INSTALL ... DONE
```

测试只执行编译和安装，没有启动 `bf_switchd`、control 或数据面程序。先编译 1,024，再编译 65,536，因此测试结束后远端源码和安装产物保持在 65,536 条版本。

## 3. 原始日志身份

| 表深度 | Compiler Run ID | 日志创建时间 | SHA-256 |
|---:|---|---|---|
| 1,024 | `8f47d19197bcd825` | 2026-08-15 18:57:51 | `f6e22a5b6373ec46887677798f9896dfff6b7009813b64dcc62a78d1774d04d3` |
| 65,536 | `beca226969073c8d` | 2026-08-15 18:58:18 | `cd5e066e441ed27cf57a5e0b4a0fe31399d10ebb45ccf9af75a66a91a09e1398` |

远端归档位置：

```text
/sde/bf-sde-9.7.1/spfc/gscc-resource-comparison/1024/mau.resources.log
/sde/bf-sde-9.7.1/spfc/gscc-resource-comparison/65536/mau.resources.log
```

本地原始日志位置：

```text
.planning/tofino2-gscc-rtt-resource-compare/artifacts/1024/mau.resources.log
.planning/tofino2-gscc-rtt-resource-compare/artifacts/65536/mau.resources.log
```

本地重新计算的 SHA-256 与远端归档的校验值完全一致。每个归档目录还保存了 `p4_build.log`、`resources.json`、`table_summary.log` 和编译时的 `source_size.txt`。

## 4. MAU 全局资源 Totals 对比

以下数据直接来自两份 `mau.resources.log` 第一张表的 `Totals` 行。

| 资源 | 1,024 条 | 65,536 条 | 绝对变化 | 说明 |
|---|---:|---:|---:|---|
| Exact Match Input xbar | 126 | 126 | 0 | 不变 |
| Ternary Match Input xbar | 4 | 4 | 0 | 不变 |
| Hash Bit | 388 | 390 | +2 | 编译器对索引相关逻辑重新布局 |
| Hash Dist Unit | 15 | 15 | 0 | 不变 |
| Gateway | 16 | 17 | +1 | stage 4 增加 1 个 |
| SRAM | 29 | 57 | +28 | +96.55%，约 1.97x |
| Map RAM | 14 | 44 | +30 | +214.29%，约 3.14x |
| TCAM | 1 | 1 | 0 | 不变 |
| VLIW Instr | 22 | 22 | 0 | 不变 |
| Meter ALU | 7 | 7 | 0 | 不变 |
| Stats ALU | 0 | 0 | 0 | 不变 |
| Stash | 0 | 0 | 0 | 不变 |
| Exact Match Search Bus | 17 | 18 | +1 | stage 4 增加 1 个 |
| Exact Match Result Bus | 17 | 17 | 0 | 不变 |
| Tind Result Bus | 12 | 12 | 0 | 不变 |
| Action Data Bus Bytes | 46 | 42 | -4 | stage 4 的布局变化 |
| 8-bit Action Slots | 0 | 0 | 0 | 不变 |
| 16-bit Action Slots | 0 | 0 | 0 | 不变 |
| 32-bit Action Slots | 0 | 0 | 0 | 不变 |
| Logical TableID | 19 | 19 | 0 | 不变 |

这里最重要的是：表深度增加没有增加 Meter ALU、VLIW 指令或逻辑表数量，说明处理动作和流水线逻辑规模没有随表深度扩张；增长主要体现在保存更多寄存器元素所需的 SRAM/Map RAM。

## 5. `Average` 利用率对比

`mau.resources.log` 第二张表给出了编译器计算的平均利用率。仅列出发生变化的字段：

| 资源 | 1,024 条 | 65,536 条 | 变化 |
|---|---:|---:|---:|
| Hash Bit | 8.48% | 8.52% | +0.04 个百分点 |
| Gateway | 9.09% | 9.66% | +0.57 个百分点 |
| SRAM | 3.30% | 6.48% | +3.18 个百分点 |
| Map RAM | 2.65% | 8.33% | +5.68 个百分点 |
| Exact Match Search Bus | 9.66% | 10.23% | +0.57 个百分点 |
| Action Data Bus Bytes | 3.27% | 2.98% | -0.29 个百分点 |

其余平均利用率均不变。全局平均值仍不高，但不能把该平均值直接解释为寄存器还能按同样比例扩容；stateful object 的放置受特定 stage、内存分块、访问路径和 swbox 约束，而不是只受全局平均容量约束。

## 6. 逐 Stage 变化

逐行比较绝对资源表后，只有 stage 4、5、6、7 发生变化；stage 0-3 和 8-19 完全一致。

| Stage | 资源 | 1,024 条 | 65,536 条 | 变化 |
|---:|---|---:|---:|---:|
| 4 | Hash Bit | 20 | 10 | -10 |
| 4 | Gateway | 2 | 3 | +1 |
| 4 | SRAM | 4 | 2 | -2 |
| 4 | Exact Match Search Bus | 2 | 3 | +1 |
| 4 | Action Data Bus Bytes | 8 | 4 | -4 |
| 5 | Hash Bit | 43 | 49 | +6 |
| 6 | SRAM | 2 | 17 | +15 |
| 6 | Map RAM | 2 | 17 | +15 |
| 7 | Hash Bit | 33 | 39 | +6 |
| 7 | SRAM | 2 | 17 | +15 |
| 7 | Map RAM | 2 | 17 | +15 |

Hash Bit 的全局净变化为 `-10 + 6 + 6 = +2`。全局 SRAM 的净变化为 `-2 + 15 + 15 = +28`。Map RAM 只在 stage 6 和 7 增长，因此全局变化为 `+15 + 15 = +30`。

## 7. RTT 寄存器对象级对比

`Allocated Resource Usage` 表显示两张 RTT 寄存器始终位于原来的 stage，没有因为表深度变化而迁移：

| P4 对象 | Stage | 资源 | 1,024 条 | 65,536 条 | 变化 |
|---|---:|---|---:|---:|---:|
| `gs_Ingress.gs_rtt_id_reg` | 6 | RAMs | 2 | 17 | +15 |
| `gs_Ingress.gs_rtt_id_reg` | 6 | Map RAMs | 2 | 17 | +15 |
| `gs_Ingress.gs_rtt_timestamp_reg` | 7 | RAMs | 2 | 17 | +15 |
| `gs_Ingress.gs_rtt_timestamp_reg` | 7 | Map RAMs | 2 | 17 | +15 |

两张 RTT 寄存器合计：

| 指标 | 1,024 条 | 65,536 条 | 变化 |
|---|---:|---:|---:|
| RTT 寄存器 RAMs | 4 | 34 | +30 |
| RTT 寄存器 Map RAMs | 4 | 34 | +30 |

对象级 RAMs 增加 30，而全局 SRAM 只增加 28，是因为编译器在 65,536 版本中重新组织了 stage 4，使该 stage 的 SRAM 从 4 降到 2。由此可见，全局 Totals 是完整流水线重新放置后的净结果，不能简单地把单个对象差值直接当成全局差值。

## 8. Stage 6 和 Stage 7 的局部压力

| Stage | 对应 RTT 对象 | 资源 | 1,024 条 | 65,536 条 | 变化 |
|---:|---|---|---:|---:|---:|
| 6 | `gs_rtt_id_reg` | SRAM 利用率 | 2.50% | 21.25% | +18.75 个百分点 |
| 6 | `gs_rtt_id_reg` | Map RAM 利用率 | 4.17% | 35.42% | +31.25 个百分点 |
| 7 | `gs_rtt_timestamp_reg` | SRAM 利用率 | 2.50% | 21.25% | +18.75 个百分点 |
| 7 | `gs_rtt_timestamp_reg` | Map RAM 利用率 | 4.17% | 35.42% | +31.25 个百分点 |
| 6 | `gs_rtt_id_reg` | Meter ALU | 1 | 1 | 0 |
| 7 | `gs_rtt_timestamp_reg` | Meter ALU | 1 | 1 | 0 |

表深度只增加寄存器存储容量，不会增加每个包执行的寄存器操作数量，因此 stage 6 和 7 的 Meter ALU 使用量保持为 1。局部瓶颈主要转向 Map RAM 和 SRAM，而不是 ALU 数量。

## 9. 逻辑容量与物理分配

每张 RTT 寄存器的元素和值宽均为 32 bit，两张寄存器的逻辑数据量如下：

```text
1,024  x 32 bit x 2 =     65,536 bit =   8 KiB
65,536 x 32 bit x 2 =  4,194,304 bit = 512 KiB
```

逻辑容量增长 64x，但 `mau.resources.log` 中每张寄存器的 RAM/Map RAM 计数只从 2 增至 17，即 8.5x。原因是日志中的 RAM 数量是 Tofino2 物理分配单元数量，不是逻辑字节数：1,024 条版本已经需要最小分配、索引映射和 stateful 访问相关资源，后续容量按照硬件块粒度扩展。

这一结果还说明，不能只用“逻辑数据量 / 芯片总 SRAM”估算最大表深度。此前 131,072 条版本即使从平均利用率看仍有余量，也会因为 stage 6/7 的 stateful register 和 swbox 访问布局无法满足而编译失败。

## 10. 编译器布局的附带变化

除两张 RTT 寄存器外，编译器还对索引计算相关对象做了重新布局：

- stage 4 的 `gs_calc_ack_indices_table` 在两个版本中的 action/gateway 组织不同。
- stage 5 的 `gs_record_ackreq_timestamp_table` Hash Bits 从 43 增至 49。
- stage 7 的同名 timestamp 记录对象 Hash Bits 从 10 增至 16。
- 这些变化使全局 Hash Bit 增加 2、Gateway 增加 1、Exact Match Search Bus 增加 1，同时 Action Data Bus Bytes 减少 4。

这些是 bf-p4c 对完整流水线重新放置的结果，不代表 P4 源码新增了逻辑表或动作；两种配置的 Logical TableID 和 VLIW 指令数量都保持不变。

## 11. 最终结论

从 `mau.resources.log` 看，RTT 表深度从 1,024 增加到 65,536 的代价主要是：

1. 两张 RTT 寄存器各多占用 15 个 RAM 和 15 个 Map RAM。
2. stage 6 和 stage 7 的 SRAM 利用率分别提高到 21.25%，Map RAM 利用率分别提高到 35.42%。
3. 全局 SRAM 从 29 增至 57，Map RAM 从 14 增至 44。
4. Meter ALU、TCAM、VLIW 指令和逻辑表数量不变，说明计算逻辑复杂度基本不变。
5. 编译器重新打包 stage 4/5/7，产生少量 hash、gateway、bus 资源变化。

因此，65,536 条版本的主要成本是特定 stage 上的 stateful memory 压力，而不是新增 match-action 逻辑或 ALU 操作。两种配置均已在同一台 Tofino2 主机上成功编译；最终远端状态保留为 65,536 条版本，未运行 P4 程序。
