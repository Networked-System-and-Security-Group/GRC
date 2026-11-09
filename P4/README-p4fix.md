# GSCC P4 — P4-fix 分支：可用的论文算法修复版（无观测表）

本目录是 **P4-fix 分支**的交付物：在原版 `gscc.p4` 基础上**最小修改**，修复其中的错误并**实现论文中未实现的算法**，**不含任何仅为观测/统计而新增的表或寄存器**。

- `dataplane/`：数据面 `gscc.p4`（+ `header.p4` / `util.p4`）
- `controlplane/`：控制面 `ctrl.c`（+ `headers.h` / `switch_config.h` / `Makefile`）

> 说明：`P4/report.md` 与 `P4/mau-resources-1024-vs-65536.md` 是早期（8 月）关于 RTT 表深度的容量研究，基于**旧版** `gscc.p4`（表深 65536）；当前数据面以本 README 描述的版本与 `gscc.p4` 源码常量为准。

---

## 一、数据面 `gscc.p4`（相对原版的改动）

在保持原版表项命名与功能的前提下，做了以下修复 / 补全：

1. **转发表修正**：Dst IP 相关条目 `0a630102` → `0a630201`，出口 port `408` → `400`（原版笔误）。
2. **字段提取前移到 parser**：把 ACK 侧要用的 `PSN / ack_req / opcode` 在 parser 里搬进 metadata（不占 ingress stage）。
3. **表 key 改用 metadata 副本**：`gs_record_ackreq_*`、`gs_read_stored_*` 的 key 由报文头字段改为 `gs_meta.gs_is_ackreq / gs_opcode_md`，消除解析器改写头字段后的不一致。
4. **桶 hash 改用 IP 对（原版用五元组含端口）**：RoCEv2 的 ACK 与数据包不互为反向五元组（dport 均为 4791，sport 由网卡哈希），用端口会永远不同桶；故**桶号 = `CRC32(ip_low, ip_high) & GS_RTT_BUCKET_MASK`**，只用 `(src_ip, dst_ip)` 对。
5. **论文 Algorithm 1 的两级索引（桶 = IP 对哈希，槽 = PSN 低位）**：
   `bucket = CRC32(ip_low, ip_high) & GS_RTT_BUCKET_MASK`；`slot = psn[3:0]`（即论文里的 `seq mod 16`）；
   `index = (bucket << 4) | slot`（每桶 16 槽，顺序包刚好铺满 16 槽）。
   `GS_RTT_TABLE_SIZE = 4096`，`GS_RTT_BUCKET_MASK = GS_RTT_TABLE_SIZE/16 - 1`（=255，即 256 桶 × 16 槽）。
6. **★ 论文的 PSN 匹配（精确匹配 `stored_id == psn_now`）**：
   按论文 Algorithm 1，AckReq 包把其 PSN 存入 `(bucket, psn[3:0])` 槽（`gs_record_ackreq_id`）；
   ACK 包用同一 `psn[3:0]` 槽读出 `stored_id`，**只有 `stored_id == psn_now`（同一槽、且序号完全相等）才判命中**并更新 RTT，否则计为 miss、不更新 RTT。
   这样绝不会把“属于另一代（同槽、PSN 相差 16 整数倍的其它包）的槽”误匹配进来，**RTT 不会算错**；代价是槽被覆盖时该 ACK 只 miss、不更新（这属论文原义）。
   > 说明：另有“±1 窗口（接受 `d∈{0,±16}`）”是**实验版（`expr-p4`）里的启发式放宽**（用 `gs_rtt_diff_reg` + Stateful-ALU 差分实现），会带来跨代误匹配、RTT 偏差的风险，故**不放进本修复版**，仅在实验分支保留。
7. **egress 解析器修复（吞吐关键）**：`select` 的 `default: accept` → `default: gs_parse_ethernet`，
   让普通 RoCE 包（无 shim 头）也走以太网解析，消除字节级损坏。
8. **只对真正的 ACK（opcode 17）做 RTT 测量**，避免 READ 响应 / NAK 污染样本。

**不含**任何观测表：`gs_rtt_ok/fail_zero/fail_psn/ack_total/ackreq_cnt/pending`、`gs_khist`、`gs_psn_now_reg`、`gs_storedid_reg` 等一概没有。

### 编译验证

```bash
bf-p4c --std p4-16 --target tofino2 --arch t2na \
       --bf-rt-schema <out>/bf-rt.json -o <out> gscc.p4
# 结果：compilation_succeeded = true（bf-p4c 9.7.1 / Tofino2 / t2na），生成 gs_pipe/{tofino2.bin,context.json,*.bfa}
```

### 资源占用（bf-p4c 9.7.1 / Tofino2 t2na 实测，`--verbose 2` 资源报表）

| 指标 | 数值 |
|---|---|
| **ingress 占用 stage** | **14 个（stage 0–13）**（资源报表按 20 个 stage 槽 0–19 列出） |
| egress 占用 stage | 9 个（stage 0–8） |
| SRAM 块（合计） | 41 |
| 单 stage SRAM 峰值 | **31.25%（stage 0）** |
| TCAM 块 / 单 stage 峰值 | 8 / 8.33% |
| MapRAM 块 | 18 |
| 逻辑表数 | 35 |
| Action Data Bus | 78 B |
| 流水线时延 | ingress 302 cycles / egress 150 cycles |

> 来源：`bf-p4c ... --verbose 2` 生成的 `gs_pipe/logs/{mau.resources.log, metrics.json, table_summary.log}`。

## 二、控制面 `ctrl.c`

原版的 epoch 控制逻辑（AI/MD 速率调整、参考字节数、CNP 生成）保持不变；相对 SDE 9.7.1 做了 **API 适配**（`-DBFRT_GENERIC_FLAGS` 的 flags 变体），并**移除了所有观测打印**（K 直方图、ok/fail 子计数、psn_now/storedid 直读等），使其与「去掉观测表」的数据面匹配。`gscc_print_status` 仍保留原始的 RTT / 速率 / 字节 / ACK 聚合统计打印（这些量由 `pkt_count`、`rtt_count` 等原始寄存器推导，不依赖观测表）。

### 编译验证

```bash
make            # 内含 -DBFRT_GENERIC_FLAGS -I$SDE_INSTALL/include -L$SDE_INSTALL/lib -ldriver -lbf_switchd_lib
# 结果：rc=0，生成 ctrl
```

### 运行要点

`ctrl` 本身即作为 `bf_switchd` 运行，需给 SDE 的运行库建 `.so.0` 软链并设置 `LD_LIBRARY_PATH`（详见 `gscc-tofino2-record` 记录）。
