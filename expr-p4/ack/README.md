# expr-p4/ack — ACK 聚合与 PSN 匹配观测实验

本目录包含**两个带观测的 P4 版本**，用于在 Tofino2 上观测计数器、验证 PSN 匹配正确性、并观察 ACK 聚合。两者都实现论文算法（±1 window PSN 匹配 + 两级索引），区别仅在“哈希桶”结构；都**带观测表**（K 直方图、ok/fail 子计数、psn_now/storedid 直读等）。

## 两个版本

| 目录 | 数据面 `gscc.p4` | 桶结构 | 索引 | 表深 |
|---|---|---|---|---|
| `multi-bucket/` | 多桶版（仅加观测） | 256 个桶 × 每桶 256 槽 | `((hash & BUCKET_MASK) << 8) \| psn[7:0]` | 65536 |
| `single-bucket/` | 归并成一个桶，也带观测 | 1 个桶（所有流共用一个桶） | `psn[15:0]` | 65536 |

- `multi-bucket`：对应常规“按五元组哈希分桶”的设计；单 IP 对场景下 255/256 的桶被浪费。
- `single-bucket`：把桶哈希“抹掉”（`BUCKET_MASK=0`），直接用 PSN 低 16 位索引，等价于所有流共享一张按 PSN 索引的大表；单 IP 对场景下覆盖更充分。

## 子目录（每个版本各自拆分）

- `data-plane/`：数据面 `gscc.p4` + `header.p4` + `util.p4`
- `control-plane/`：控制面 `ctrl.c` + `headers.h` + `switch_config.h` + `Makefile`
  （控制面为**带观测打印**的版本：会直读 K 直方图、off 直方图（psn_now/storedid）、ack_req/ack_total、rtt_ok/fail 等寄存器，并打印 ACK 聚合倍数与匹配率。）

## 编译

```bash
# 数据面
bf-p4c --std p4-16 --target tofino2 --arch t2na --bf-rt-schema <out>/bf-rt.json -o <out> gscc.p4
# 控制面（在 control-plane/ 下）
make        # 内含 -DBFRT_GENERIC_FLAGS
```

## 结果

实验结果（计数器正常、match%、ACK 聚合倍数、PSN 槽位 bit × 流数 梯度矩阵）见同目录 `experiment.md`；踩坑过程见 `../bugs.md`。

---

## ±1 窗口（PSN 匹配）的归属与正确性

**归属**：±1 窗口（接受 `d = stored_psn − psn_now ∈ {0, +16, −16}`）是**实验版（本目录）的启发式放宽**。`P4-fix` 干净版用**精确匹配 `stored_id == psn_now`**，不含此放宽。

**实现**：TNA 控制 ALU 不能用两个 PHV 相减，故用独立 Stateful-ALU scratch 寄存器 `gs_rtt_diff_reg`：
ack_req 侧 `gs_mirror_ackreq_psn`(@stage6) 镜像 PSN；ACK 侧 `gs_calc_diff_action`(@stage9) 做「内存字 − 1 个 PHV」差分 + 两次比较（`d<=16 || d>=0xFFFFFFF0`），输出 0/1 命中标志（`gs_calc_rtt_diff`）。

**为什么是 16**：它来自“每桶 16 槽、槽号 = `psn[3:0]`”的索引结构。同一槽内的包 PSN 必然相差 **16 的整数倍**，所以“相邻一个槽代”= ±16。`±1 窗口`即“允许相邻 1 个槽代”，**不是 RTT 阈值**。

**会不会匹配错？——会，存在跨代误匹配风险。** 例：PSN=16 与 PSN=32 的 `psn[3:0]` 同为 0、落同一槽；若该槽已被更新的 PSN=32 覆盖，晚到的 ACK(16) 读到 `stored=32`，`d=32−16=16` → 被 ±16 判“命中”，但二者并非同一次探测，读到的发送时间戳属于 PSN=32 那一代，**算出的 RTT 是错的**（偏小，甚至为负）。所以 ±1 窗口是“用少量 RTT 误差换匹配率”的启发式，**不适合作为论文忠实实现**；`P4-fix` 用精确匹配正是为杜绝这种错配（代价是槽被覆盖时该 ACK 只 miss、不更新）。

**本目录两版的注意点**：`multi-bucket` / `single-bucket` 的槽位宽是 `psn[7:0]` / `psn[15:0]`（每桶 256 / 65536 槽），同槽别名相差 256 / 65536 的倍数，故其中的 `±16` 分支基本**退化**（匹配≈精确匹配）。它们主要用于研究“槽位宽度 × 流数”的碰撞率（fail_psn），**不是真正在 16 槽下跑 ±1 窗口**。真正 16 槽的 ±1 窗口算法见 `win16-pm1-reference/`（纯算法，无观测）。

## 资源占用（bf-p4c 9.7.1 / Tofino2 t2na 实测，`--verbose 2`）

| 指标 | multi-bucket | single-bucket | （对照）P4-fix 精确版 |
|---|---|---|---|
| ingress stage（占用 / 编译器 20 槽 0–19）| **16（0–15）** | **16（0–15）** | 14（0–13） |
| egress stage | 9（0–8） | 9（0–8） | 9（0–8） |
| SRAM 块 | **140** | **139** | 41 |
| 单 stage SRAM 峰值 | 31.25%（stage0）| 31.25%（stage0）| 31.25%（stage0）|
| TCAM 块 / 单 stage 峰值 | 8 / **79.17%** | 8 / **79.17%** | 8 / 8.33% |
| MapRAM 块 | 113 | 113 | 18 |
| 逻辑表数 | 46 | 46 | 35 |
| Action Data Bus | 86 B | 66 B | 78 B |
| ingress 时延 | 326 cycles | 304 cycles | 302 cycles |

> 观测版因新增 K-HIST/off-HIST/fail 等表与寄存器，SRAM（140/139 vs 41）、MapRAM（113 vs 18）、逻辑表（46 vs 35）明显上升，且 **TCAM 峰值达 79.17%**（fail 采样/大表所致），是观测版逼近资源墙的主因；`P4-fix` 干净版仅 41 SRAM、TCAM 峰值 8.33%。
