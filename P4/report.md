# GSCC Delay Monitor 在 Tofino2 上的容量验证报告

## 1. 结论

在当前 `gscc.p4` 流水线布局、Tofino2 目标和 Intel/Barefoot SDE 9.7.1 编译器下：

- RTT delay monitor 的最大**已验证可编译的 2 的幂表深度**为 **65,536（2^16）条**。
- **131,072（2^17）条无法完成资源放置**，因此当前实现不能扩到下一个 2 的幂。
- 65,536 与 131,072 之间的非 2 次幂精确上限没有继续测量，不能据此断言 65,536 是所有整数深度中的绝对最大值。
- 本次只进行了 P4 编译和安装产物生成，没有启动 `bf_switchd`、控制平面或运行数据面程序。

本地代码最终保留为 65,536 条：

```p4
const bit<32> GS_RTT_TABLE_SIZE = 65536;
const bit<32> GS_RTT_INDEX_MASK = GS_RTT_TABLE_SIZE - 1;
```

## 2. 验证环境

| 项目 | 配置 |
|---|---|
| 本地源码 | `P4/dataplane/gscc.p4` |
| 远端主机 | `192.168.5.220` |
| 远端隔离源码 | `/sde/bf-sde-9.7.1/spfc/gscc-dataplane/gscc.p4` |
| SDE | `bf-sde-9.7.1` |
| 编译器 | `bf-p4c 9.7.1` |
| P4 架构/目标 | `p4_16/t2na`，Tofino2 |
| 测试日期 | 2026-08-15 |

测试使用隔离的 `gscc-dataplane` 目录，没有覆盖远端其他 P4 工程。每个候选深度只执行 Tofino2 编译流程，没有执行交换机程序。

## 3. Delay Monitor 的字段宽度与表深度

当前 RTT delay monitor 使用两个同深度寄存器：

```p4
Register<bit<32>, bit<32>>(GS_RTT_TABLE_SIZE) gs_rtt_timestamp_reg;
Register<bit<32>, bit<32>>(GS_RTT_TABLE_SIZE) gs_rtt_id_reg;
```

各字段含义如下：

| 项目 | P4 宽度 | 说明 |
|---|---:|---|
| timestamp 寄存器值 | 32 bit | 保存 `ingress_mac_tstamp[31:0]` |
| identifier 寄存器值 | 32 bit | 保存由 24-bit BTH `gs_psn` 转换得到的 32-bit 值 |
| 寄存器索引类型 | 32 bit | 声明为 `bit<32>`；65,536 条时实际使用哈希值低 16 bit |
| RTT 计算值 | 32 bit | 当前时间戳减去已保存的发送时间戳 |

因此，“identifier 是多少位”需要区分来源和存储：RoCE BTH PSN 原始字段是 **24 bit**，`gs_rtt_id_reg` 中的存储槽是 **32 bit**。

32-bit timestamp 只保留硬件 ingress timestamp 的低 32 bit，RTT 差值按 32-bit 算术计算。编译验证只证明该实现能被放入芯片，不验证时间戳回绕、哈希冲突或 RTT 运行时语义。

代码顶部的：

```p4
#define REGISTER_SIZE 1024
```

属于另一张 `gs_flow_timestamp_reg`，不控制本报告验证的 `gs_rtt_timestamp_reg` 和 `gs_rtt_id_reg`，因此本次有意保持为 1,024。

## 4. 源码修改

本地 `P4/dataplane/gscc.p4` 完成了以下同步修改：

1. 将 `GS_RTT_TABLE_SIZE` 从 1,024 改为 65,536。
2. 新增 `GS_RTT_INDEX_MASK = GS_RTT_TABLE_SIZE - 1`。
3. AckReq 写入路径和 Ack 读取路径都改为使用同一个 mask，避免表深度改变后仍硬编码 `0x3FF`。
4. mirror session 元数据和强制转换改用 Tofino2 TNA 定义的 `MirrorId_t`，消除硬编码 `bit<10>` 带来的目标兼容问题。

65,536 是 2 的幂，因此 `hash & (GS_RTT_TABLE_SIZE - 1)` 得到合法的 0 到 65,535 索引。若以后使用非 2 次幂深度，不能继续假设该按位 mask 能均匀覆盖所有条目，需要同时修改索引映射方式。

## 5. 编译结果

| RTT 表深度 | 2 的幂 | 结果 | 说明 |
|---:|---:|---|---|
| 65,536 | 2^16 | 成功 | 编译、make 和 install 全部完成 |
| 131,072 | 2^17 | 失败 | stage 6 和 stage 7 的 stateful register 无法放置 |

65,536 条构建最终输出包含：

```text
MAKE ... DONE
INSTALL ... DONE
```

在容量测试结束后，又按要求将本地 65,536 条版本的 `gscc.p4`、`header.p4` 和 `util.p4` 重新同步到远端隔离目录。三个文件的远端 SHA-256 均与本地一致，并再次完成 Tofino2 编译和安装，退出码为 0。该过程仍然只编译，没有启动数据面或控制程序。

资源报告显示：

| 寄存器 | 放置 stage | SRAM | MapRAM | Stateful ALU |
|---|---:|---:|---:|---:|
| `gs_rtt_id_reg` | 6 | 17 | 17 | 1 |
| `gs_rtt_timestamp_reg` | 7 | 17 | 17 | 1 |
| 合计 | - | 34 | 34 | 2 |

两张寄存器的逻辑数据量为：

```text
65,536 entries x 32 bit x 2 registers = 4,194,304 bit = 512 KiB
```

物理资源开销不能只按这 512 KiB 推算；编译器还必须满足每个 stage 的 SRAM/MapRAM 组织方式、stateful ALU、访问端口和同 stage 其他表的共同放置约束。

## 6. 131,072 条失败原因

SDE 9.7.1 顶层封装最终只报告：

```text
Internal compiler error. Please submit a bug report with your code.
```

但底层 `table_placement_1.log` 给出了明确的资源放置失败：

- `gs_record_ackreq_id_table` 无法在 stage 6 放置包含 131,072 条目的 `gs_rtt_id_reg`。
- `gs_read_stored_timestamp_table` 无法在 stage 7 放置包含 131,072 条目的 `gs_rtt_timestamp_reg`。
- 两条路径均报告 `allocate_all_swbox_users failed`。

所以这里的根本限制不是 P4 常量宽度或索引表达式，而是当前固定 stage 布局中的 stateful memory 资源及访问资源不足。顶层 ICE 是 SDE 9.7.1 对该放置失败的不理想错误呈现，不代表 131,072 已接近成功编译。

限制表深度继续增加的主要因素是：

1. 两张 32-bit RTT 寄存器都随表深度线性增长。
2. 寄存器访问被当前代码固定到相邻的 pipeline stages，不能自由使用芯片全部 SRAM。
3. 每个 stage 可用的 SRAM、MapRAM、stateful ALU 和访问路径都有独立上限。
4. 同一 stage 内的其他 match-action table 和 stateful object 会共同占用资源。
5. 编译器的实际 packing 和 placement 约束比“全芯片总内存容量”更严格。

## 7. 结果与产物位置

远端构建和日志路径：

```text
/sde/bf-sde-9.7.1/build/p4-build/tofino2/gscc
/sde/bf-sde-9.7.1/logs/p4-build/tofino2/gscc
```

131,072 条测试的归档日志：

```text
/sde/bf-sde-9.7.1/spfc/gscc-capacity-results/power2/131072/p4_build.log
/sde/bf-sde-9.7.1/spfc/gscc-capacity-results/power2/131072/make.log
```

详细 placement 日志：

```text
/sde/bf-sde-9.7.1/build/p4-build/tofino2/gscc/gscc/tofino2/gs_pipe/logs/table_placement_1.log
```

最后一次成功安装的 Tofino2 配置：

```text
/sde/bf-sde-9.7.1/install/share/p4/targets/tofino2/gscc.conf
```

当前本地源码、远端隔离源码和最后一次成功安装的产物均为 65,536 条版本。远端安装文件 `/sde/bf-sde-9.7.1/install/share/p4/targets/tofino2/gscc.conf` 已更新，编译后的进程检查确认没有启动 `bf_switchd`、control 或其他 P4/SDE 程序。

## 8. 范围与后续解释

本次结论严格表述为：**当前 GSCC P4 流水线在 Tofino2/SDE 9.7.1 上，最大已验证可编译的 2 的幂 RTT 表深度是 65,536 条。**

没有继续进行 65,536 到 131,072 之间的二分测试，因此没有得到非 2 次幂的精确容量边界。即使找到更大的非 2 次幂可放置值，也必须同步重新设计或验证哈希到索引的映射，不能直接沿用 `size - 1` mask。

此外，当前代码虽然写入了 `gs_rtt_id_reg` 并定义了读取 action，但 ACK 路径只读取 timestamp，没有调用 ID 读取和匹配逻辑。该行为不影响本报告的编译容量结论，但意味着 identifier 尚未在当前数据面路径中用于排除哈希槽冲突。
