# GSCC P4（数据面 + 控制面）在 Tofino2 上的踩坑记录（bugs.md）

> 范围：仅记录**踩过的坑**（表现 / 根因 / 修法 / 出处）。成功实验的完整命令与输出见 `experiment.md`。
> 事实来源：本会话完整历史；一手记录文件 `/tmp/remote_p4/gscc-tofino2-record.md`（含“踩过的坑”“复现命令”“按日期实验日志”“ACK 聚合结果”）；`/tmp/remote_p4/gscc_vs_original.diff`（原版 vs 修复版，163 行）。
> 重要背景：`P4-fix` 分支上要保留的是**原版 P4 + 修错 + 补实现论文算法**的可用数据面/控制面，**不含任何多余观测表**（25 张表、bfrt 34 个符号，不增删表）。下文凡涉及“观测寄存器/K 直方图/offset 直方图”的坑属于 `P4-expr/expr-p4/ack` 的实验版本，仅作经验记录。

环境：交换机 192.168.5.220（Tofino2，SDE 9.7.1）；流量机 192.168.5.111（两块 CX-7；`mlx5_0=ens7f0np0=10.99.1.1→面板口1/ dev 392/ pipe3`，`mlx5_2=ens10f0np0=10.99.2.1→面板口2/ dev 400/ pipe3`）。

---

## A. 编译期（bf-p4c）踩坑

### A1. `instruction slot 2 used multiple times in gs_update_real_bytes`（报错位置误导）
- 【时间】：约 11 月上旬（2026-11-05～06 首次上板期间）
- 【表现】：往 stage 0 多加字段提取后，编译报 `instruction slot 2 used multiple times in gs_update_real_bytes`。报错指向 real-bytes 的 ALU，但真凶是 stage 0 的 ALU 操作溢出。
- 【如何解决】：把 BTH 字段提取（psn/ack_req/opcode）从 ingress stage 移到 **parser**（parser 不占 ingress stage），再用 metadata 副本。
- 【出处】：`gscc-tofino2-record.md` L83-88、L140-141（“踩过的坑”表）；`gscc_vs_original.diff` L16-25（parser 新增 3 行）。

### A2. `Internal compiler error`（一个 action 里调两个 RegisterAction）
- 【时间】：约 11 月上旬
- 【表现】：一个 action 里调用两个 RegisterAction，触发 `Internal compiler error`。
- 【如何解决】：拆成两张表（拆开成两个 action/table 分别写两个寄存器）。
- 【出处】：`gscc-tofino2-record.md` L142；本会话（±1 窗口实现时把“镜像 PSN”拆成独立 action/table 是同源经验）。

### A3. `action spanning multiple stages`
- 【时间】：约 11 月上旬
- 【表现】：单个 action 内 ALU 操作超限，编译报 `action spanning multiple stages`。
- 【如何解决】：把计算拆到前面的 stage（前置一级算好，后级只做比较/写入）。
- 【出处】：`gscc-tofino2-record.md` L143、L507-508（`add: action spanning multiple stages`）。

### A4. `expression too complex` / `expression too complex for register action`
- 【时间】：约 11 月上旬
- 【表现】：RegisterAction 里直接读 header 字段报 `expression too complex`；尝试 64 位打包被拒 `expression too complex for register action`。
- 【如何解决】：先把 header 字段搬到 metadata 再进 RegisterAction；64 位量拆成两个 32 位寄存器。
- 【出处】：`gscc-tofino2-record.md` L144-145。

### A5. `could not place it until stage N`
- 【时间】：约 11 月上旬（原版就存在的 stage 紧张）
- 【表现】：资源放不下，报 `could not place it until stage N`。
- 【如何解决】：减少该 stage 的 ALU 操作（拆级/合并/精简 metadata）。
- 【出处】：`gscc-tofino2-record.md` L146；原版 `gs_update_rtt_sum_table` 已被从 stage 9 挤到 stage 10（L84-86）。

### A6. bf-p4c `EXIT=3`（条件过复杂 / 跨级 / PHV 预算）
- 【时间】：会话中（±1 窗口实现期，约 11 月上旬）
- 【表现】：写“PSN 匹配窗口”时多次 `EXIT=3`，典型报 `condition too complex, limit 4 bytes+12 bits PHV input`、`condition expression too complex` 等。
- 【如何解决】：改成 **Stateful-ALU 单 PHV 形态**——一个操作数取内存字（已镜像的 ack_req PSN），另一个只用 1 个 PHV（当前 PSN），配合 `d=stored−psn` 的对称窗口比较。
- 【出处】：本会话历史；`gscc-tofino2-record.md` L502-513（8 种写法全被挡的记录）。

### A7. bf-p4c `EXIT=2`（一个 action 非互斥地写两个寄存器）
- 【时间】：会话中（±1 窗口实现期）
- 【表现】：在一个 action 里同时写两个非互斥寄存器，编译 `EXIT=2`。
- 【如何解决】：把“镜像 PSN”单独拆成自己的 action/table，使单个 action 只写一个寄存器。
- 【出处】：本会话历史；与 `gscc-tofino2-record.md` L142（Internal compiler error）同类根因。

### A8. `condition too complex, limit 4 bytes+12 bits PHV input`
- 【时间】：约 11 月上旬
- 【表现】：拿两个 32bit 量做比较（如 `psn/stored` 双 32bit 比较、或 `[15:0]` 切片 + 范围 &&），报 `condition too complex, limit 4 bytes+12 bits PHV input`。
- 【如何解决】：避免“两个 PHV 操作数”参与同一比较；改为“内存字 − 1 个 PHV”的单边比较，或将比较拆到独立流水级。
- 【出处】：`gscc-tofino2-record.md` L503、L508-510。

### A9. 64-bit 寄存器做算术/写入 → `Internal compiler error`（Intel 官方确认为编译器 bug）
- 【时间】：约 11 月上旬（实现 RTT 计数/累加时）
- 【表现】：对一个 `bit<64>` 寄存器在 `RegisterAction` 里做算术/写回（如 `value = value + 50`），bf-p4c 直接崩：`Internal compiler error. Please submit a bug report with your code.`；把该寄存器改成 `bit<32>` 即可正常编译。
- 【如何解决】：寄存器算术一律用 `bit<32>`；需要 >32 位时拆成两个 32-bit 寄存器（或用含至多 2 个 32-bit 的 struct）；若只做赋值、不做算术，可用至多两个 `bit<64>`。
- 【出处】：Intel 社区官方帖 https://community.intel.com/t/tofino2-64-bit-register-internal-compiler-error/124319 （Vladimir_P4ica 回复，SDE 9.13.3 复现）：明确 “it is definitely a compiler bug”，因 Tofino2 SALUs 虽能读写 `bit<64>`，但内部 ALU 只有 32-bit 宽，`RegisterAction` 不能做 64-bit 加法。本会话同 A4（64 位打包被拒）为同类现象。

---

## B. TNA Stateful-ALU / 硬件结构限制

### B1. 控制 ALU 不能用两个 PHV 相减（gateway ALU 输入 ≤4B+12bit）
- 【时间】：约 11 月上旬
- 【表现】：想写 `psn_now - stored_psn` 两个 PHV 直接相减，被 TNA 限制拒绝（gateway ALU 输入 ≤4 字节 + 12 bit）；退而求其次的 `[15:0]` 切片也触发 PHV 预算报错。
- 【如何解决】：用 **内存字（mirrored ack_req PSN）作为被减数 + 1 个 PHV（当前 PSN）** 的单 PHV 形态。
- 【出处】：本会话历史；`gscc-tofino2-record.md` L503、L505（“arithmetic subtraction cannot be sourced from action data”）。

### B2. 一个寄存器 = 一个 stateful ALU；输入 = 内存字 + ≤2 PHV reg + ≤4 常量
- 【时间】：会话中
- 【表现】：Stateful ALU（RegisterAction）每个 stage 内 2 个比较 ALU + 4 个算术 ALU；一个寄存器对应一个 stateful ALU，输入端口有限（内存字 + 至多 2 个 PHV 寄存器 + 至多 4 个常量）。超了就编译不过。
- 【如何解决】：严格按“1 寄存器 / 1 stateful ALU”设计 action；把需要的 PHV 控制到 ≤2 个，其余用常量或内存字。
- 【出处】：本会话历史（TNA 手册与实测编译反馈）。

### B3. 一个非互斥 action 不能写两个寄存器
- 【时间】：约 11 月上旬
- 【表现】：同一 action 里两次寄存器写、且互斥条件不成立 → 编译 `EXIT=2` / Internal compiler error。
- 【如何解决】：一个 action 只写一个寄存器，或保证两个写严格互斥；否则拆表。
- 【出处】：本会话历史；`gscc-tofino2-record.md` L142。

### B4. PHV reslice 墙：新增 stateful-op 索引字段必触发全局 PHV 重切
- 【时间】：2026-11-09（offset 直方图尝试期）
- 【表现】：为做“聚合位移直方图”新增一个 index 字段，Tofino 立即触发全局 PHV 重分配，碎片化 `gs_packet_bytes`，打断 stage2 的 real-bytes ALU，报 `instruction slot N used multiple times in action gs_update_real_bytes`。连续试了 4～8 种写法全部被挡。
- 【如何解决】：放弃“新增 index 字段在 P4 内分桶”的方案；改为复用已有活跃字段（`gs_ack_entry_idx`）记录**原始对**，在控制面（C）里计算 offset 并分桶（且该观测版本不属于 P4-fix 的干净版）。
- 【出处】：`gscc-tofino2-record.md` L361-364、L502-513、L411。

---

## C. 数据面逻辑 / 论文算法实现坑

### C1. egress 解析器 `default: accept` → 字节级损坏、吞吐暴跌（2546 倍）
- 【时间】：2026-11-06（吞吐关键修复）
- 【表现】：普通 RoCE 包第一个字节是目的 MAC 高位（0x3A），既非 6 也非 9，落入 `default: accept` 后以太网头没被解析；实测平均吞吐 **4.32 MiB/s**（峰值 10844），收包 1,032,181（大量丢包→重传）。
- 【如何解决】：`default : accept` → `default : gs_parse_ethernet`。对照实验平均吞吐 **11002 MiB/s**、收包 32,532，差 2546 倍。
- 【出处】：`gscc-tofino2-record.md` L40-67；`gscc_vs_original.diff` L155-161。

### C2. 哈希若用端口：ACK 与数据包不互为反向五元组 → 永远不同桶
- 【时间】：2026-11-06
- 【表现】：原版把 UDP 端口放进 RTT 哈希。RoCEv2 的 ACK 与数据包**目的端口都是 4791、源端口是网卡算的哈希**，两者不互为反向五元组，导致两个方向索引永远不同、测不到 RTT。
- 【如何解决】：哈希**只用 IP 对**（`gs_rtt_tuple_ip_low/high`），去掉 port。
- 【出处】：`gscc-tofino2-record.md` L104-115；`gscc_vs_original.diff` L68-80。

### C3. 单级哈希一条流只有一个槽、探针互相覆盖
- 【时间】：2026-11-06
- 【表现】：原版 `index = hash & GS_RTT_INDEX_MASK`（单级），一条流只占 1 个槽；实测平均 RTT 变成 396,720 ns（随机值，已被覆盖污染）。
- 【如何解决】：实现论文 Algorithm 1 第 1 行的两级索引 `index = (bucket << 4) | psn[3:0]`（桶号取哈希低位，槽号取 PSN 低 4 位，连续包刚好铺满 16 槽）；RTT 恢复 1,920 ns。
- 【出处】：`gscc-tofino2-record.md` L117-129；`gscc_vs_original.diff` L88-108。

### C4. ±1 窗口必须对称 `d ∈ {0, +16, −16}`
- 【时间】：会话中（±1 窗口实现期）
- 【表现】：非对称窗口（只接受 `d ≤ +16` 方向）漏判了另一方向，单流 `fail_psn=335`（约 0.79%）。
- 【如何解决】：改成对称判定 `d<=16 || d>=0xFFFFFFF0`（即 `d ∈ {0,+16,−16}`，因单流 d≡0 mod16，等价取 `{0,±16}`）；改后单流 `fail_psn=0`（100%）。
- 【出处】：本会话历史；`gscc-tofino2-record.md` L384、L400、L407-410（offset 恒 −16 的实测依据）。

### C5. 表项 key 用报文头字段 vs metadata 副本
- 【时间】：2026-11-06
- 【表现】：原版表 key 直接写 `gs_hdr.gs_bth.gs_ack_req` / `gs_hdr.gs_bth.gs_opcode`，占用 stage 且与 parser 提取重复。
- 【如何解决】：改成 `gs_meta.gs_is_ackreq` / `gs_meta.gs_opcode_md`（metadata 副本更省 stage）；`const entries` 里的 `17`/`18` 对应改成 `1`。
- 【出处】：`gscc-tofino2-record.md` L90-102；`gscc_vs_original.diff` L110-145。

### C6. 转发表写错：`0a630102→0a630201`、端口 `408→400`
- 【时间】：2026-11-05～06
- 【表现】：原版 `10.99.1.1→392`、`10.99.1.2→408`，与真实布线不符，流量打不通。
- 【如何解决】：l3/arp/canonicalize 三张表统一改 `10.99.1.1→392`、`10.99.2.1→400`（`0x0a630201: gs_forward(9w400)`）。
- 【出处】：`gscc-tofino2-record.md` L30-38；`gscc_vs_original.diff` L27-53。

### C7. 字段提取必须放 parser（不能塞 stage 0）
- 【时间】：2026-11-06
- 【表现】：原版 stage 0 已装 4 张表（`gs_l3/arp/set_timestamp/canonicalize`），`gs_update_rtt_sum_table` 已被挤到 stage 10，没有余量；再往 stage 0 加 3 个 ALU 操作溢出（表现为 A1 的误导性报错）。
- 【如何解决】：把 psn/ack_req/opcode 的提取放到 **parser 的 `gs_parse_bth`**，随后各表用 metadata。
- 【出处】：`gscc-tofino2-record.md` L83-88；`gscc_vs_original.diff` L16-25。

### C8. `GS_RTT_TABLE_SIZE` 65536 → 4096（SALU 内存吃紧）
- 【时间】：2026-11-06
- 【表现】：原版 65536 也能编过，但 SALU 内存吃紧。
- 【如何解决】：降到 4096（256 桶 × 16 槽）。（注：后续实验证明 256 槽在 ≥64 流时会被覆盖，见 D/观测部分的槽位分析。）
- 【出处】：`gscc-tofino2-record.md` L131-134；`gscc_vs_original.diff` L60-64。

---

## D. 控制面（ctrl.c / bf_rt / SDE）踩坑

### D1. bf_rt C API 与 9.7.1 不匹配（参数顺序 / flags / hdl** / 4 pipe 求和）
- 【时间】：2026-11 月上旬
- 【表现】：原版 ctrl.c 按旧 API 写，9.7.1 下编译/运行报参数不匹配。
- 【如何解决】：按 9.7.1 API 改：`entry_get(tbl,sess,tgt,flags,key,data)` 参数顺序；`entry_mod(...)` 多一个 flags；`key_reset(reg,&reg_info->key)`、`data_reset(reg,&reg_info->data)` 要 `hdl**`；读寄存器要**四个 pipe 的 value_array 求和**（Tofino2 有 4 个 pipe 副本）。共 15 处改动。
- 【出处】：`gscc-tofino2-record.md` L189-213（15 处改动表）。

### D2. 编译控制面需 `-DBFRT_GENERIC_FLAGS`（否则 “too many arguments”）
- 【时间】：2026-11 月上旬
- 【表现】：`bf_rt_table.h` 用 `#ifdef BFRT_GENERIC_FLAGS` 分了新旧两套 C API；原版 ctrl.c 写于 `entry_add` 已带 flags、`entry_mod` 还没带的版本，两套都不匹配，编译报 `entry_add/mod` “too many arguments”。
- 【如何解决】：gcc 加 `-DBFRT_GENERIC_FLAGS`。
- 【出处】：`gscc-tofino2-record.md` L214-218。

### D3. SDE 9.7.1 缺 `.so.0` 软链
- 【时间】：2026-11 月上旬
- 【表现】：运行 `./ctrl` 时动态库找不到（`libbf_switchd_lib.so.0` 等缺失）。
- 【如何解决】：手动建软链：对 `libbfsys/libbfutils/libdriver/libtofinopdfixed_thrift/libbf_switchd_lib` 逐个 `ln -sf $SDE_INSTALL/lib/<b>.so <b>.so.0`。
- 【出处】：`gscc-tofino2-record.md` L304-308。

### D4. refBytes 无条件累积 → bytesDiff 长期为负、`cnp_count=0`
- 【时间】：2026-11-06
- 【表现】：控制面空转 60 s 后 refBytes 跑到 realBytes 前 1.9e9 字节，满速打流也要好几秒才转正，实测不发 CNP。
- 【如何解决】：[FIX-14] **空闲 epoch 不累积** refBytes（只有真有流量才消耗预算，符合论文 line 1-2）。
- 【出处】：`gscc-tofino2-record.md` L259-264。

### D5. Algorithm 2 的 step 公式在 1.5us 实验床发散 → refRate 顶上限、CNP 发不出
- 【时间】：2026-11-06
- 【表现】：`step = w*v/(delta*epochsPerRTT*baseRTT)` 带 `1/baseRTT`，本床 baseRTT≈1.5us 比 WAN 小 4 个数量级，step 算出 ~1e13 B/s，一个 epoch 就把 refRate 顶到上限，之后 refRate 恒 > realRate、bytesDiff 恒负、`cnp_count=0`。另 `epochsPerRTT=baseRTT/epoch` 在 epoch>RTT 时退化成 <1，把 step 放大成天文数字。
- 【如何解决】：[FIX-15] 限制单 epoch 步长 `step ≤ refRate`（每 epoch 最多翻倍，3 个 epoch 爬到上限，爬升期 CNP 正常触发）；`epochsPerRTT = max(baseRTT/epoch, 1.0)`。
- 【出处】：`gscc-tofino2-record.md` L265-273。

### D6. `bf_rt` 一次寄存器读写约 0.4ms → epoch 做不到 100us
- 【时间】：2026-11-06
- 【表现】：论文想 100us epoch，但 `bf_rt` 单次寄存器读写约 0.4ms，每 DC 每轮 8 次，实测约 3.3ms/轮，无法达到 100us。
- 【如何解决】：`epoch_duration_us` 用**实测值**（如 1000us），让算法自洽；接受控制面轮询粒度受 bf_rt 限制。
- 【出处】：`gscc-tofino2-record.md` L326-330（“已知限制”第 1 条）。

### D7. `BF_DEV_PIPE_ALL` 会把 4 个 pipe 副本**求和** → 读数偏大
- 【时间】：2026-11-09
- 【表现】：控制面用 `BF_DEV_PIPE_ALL` 读 per-slot 寄存器，把 Tofino2 的 4 个 pipe 副本加总，得到错误值（offset 样本被污染）。
- 【如何解决】：改为**逐 pipe 读**（`read_reg_idx_pipe`），C 端再按 pipe 处理。（对全局计数器求和无妨，但对 per-slot/直方图必须逐 pipe。）
- 【出处】：`gscc-tofino2-record.md` L371-374、L383。

### D8. `GSCC_CONF` 原版硬编码 `tofino/`（Tofino1 路径）
- 【时间】：2026-11 月上旬
- 【表现】：原版硬编码 `tofino/` 配置目录，在 Tofino2 上找不到。
- 【如何解决】：改用 `GSCC_CONF` 环境变量 / 默认 `tofino2/`。
- 【出处】：`gscc-tofino2-record.md` L203。

### D9. 原版 `calculate_reference_rate` 是简化版
- 【时间】：2026-11-06
- 【表现】：原版控制算法是简化版，与论文 Algorithm 2 不一致。
- 【如何解决】：按论文 Algorithm 2 重写 `calculate_reference_rate()`，并与 NS3 参考实现 `src/point-to-point/model/wan-routing.cc:701 update_ref_rate()` 逐行对应。
- 【出处】：`gscc-tofino2-record.md` L204、L220-256。

### D10. 原版 `main` 只跑 10 秒
- 【时间】：2026-11 月上旬
- 【表现】：原版控制环跑 10 秒就退出，无法持续控制。
- 【如何解决】：改常驻控制环 + 信号退出。
- 【出处】：`gscc-tofino2-record.md` L205。

### D11. 控制环无脑轮询 0..15 → 慢 16 倍
- 【时间】：2026-11 月上旬
- 【表现】：原版轮询全部 16 个 DC，实际只用 0，浪费 16 倍时间。
- 【如何解决】：只遍历 `GSCC_DC_IDS`（默认 0）。
- 【出处】：`gscc-tofino2-record.md` L209。

### D12. 缺 mirror session / port-add（100G RS）
- 【时间】：2026-11 月上旬
- 【表现】：论文 Algorithm 3 需要 mirror session 才发得出 CNP；板级自动 port-add 不带 100G RS。
- 【如何解决】：新增 `configure_cnp_mirror()`（`bf_mirror_session_set`）与 `port_setup()`（`bf_pal_port_add` + `bf_pal_port_enable`，100G RS）。
- 【出处】：`gscc-tofino2-record.md` L206、L210。

### D13. 启动时 refBytes/realBytes 未对齐 → bytesDiff 长时间为负
- 【时间】：2026-11-06
- 【表现】：启动时 refBytes 与 realBytes 不对齐，bytesDiff 长时间为负。
- 【如何解决】：`gscc_control_init` 启动时把 refBytes 对齐到 realBytes。
- 【出处】：`gscc-tofino2-record.md` L207。

---

## E. 观测表相关坑（仅 expr 实验版本；P4-fix 干净版不含这些）

### E1. offset 直方图被 PHV reslice 墙阻断（同 B4）
- 【时间】：2026-11-09
- 【表现】：试了 4 种实现（stage11 算 delta / 单独表 / 去掩码 / stage13→14 最短存活）均触发 `instruction slot N used multiple times in action gs_update_real_bytes`。
- 【如何解决】：放弃 P4 内 offset 分桶；改为记录原始对（复用 `gs_ack_entry_idx`，仅 copy 两个已活跃字段），C 端分桶。且该方案受 slot 复用污染（见 F3）。
- 【出处】：`gscc-tofino2-record.md` L361-364、L502-513。

### E2. `fail_psn` 曾被误读为“ACK 聚合位移”，实为表别名/跨流覆盖
- 【时间】：2026-11-09
- 【表现】：把 `fail_psn` 当作“聚合位移”来解读，结论错误。
- 【如何解决】：认清 `fail_psn` 来自 RTT 表按 `psn[3:0]` 建索引导致的**同流窗口滑移（offset=±16k 小倍数）**和**跨流同桶覆盖（offset 巨大、仍是 16 的倍数）**；聚合应以 K 直方图为准，不是 fail_psn。
- 【出处】：`gscc-tofino2-record.md` L383-390、L452-484。

### E3. `cand_slots` 随流数饱和到 16 → 证明所有流挤在同一桶
- 【时间】：2026-11-09
- 【表现】：`cand_slots` 随流数 1→2→5→11→16 单调上升并**饱和在 16**（=单桶槽数），说明 IP-对哈希让所有 QP 共用一组 16 槽。
- 【如何解决】：若要匹配率与流数解耦，需桶哈希含 QP/端口（5 元组）或增大桶数——但那属于改 GSCC 算法，超出最小改动范围，故在干净版不做。
- 【出处】：`gscc-tofino2-record.md` L458-484。

### E4. 单流 offset 恒 −16 = 同流窗口滑移（非聚合）
- 【时间】：2026-11-09
- 【表现】：单流 OFF 样本恒 `offset=−16`（`|d|` 在 16-31），对应“聚合窗口数 = |off|/16 − 1 = 0”。
- 【如何解决】：纳入解读：单流无 ACK 聚合；方向是 `stored = psn_now + 16`（应查“窗口 与 窗口+1”，牛说的 x/16−1 方向相反）。
- 【出处】：`gscc-tofino2-record.md` L400、L408-410、L487-494。

### E5. `ack_req == ack_total` 是独立计数器的 1:1，不是恒等式
- 【时间】：2026-11-09
- 【表现】：担心 `ack_req==ack_total` 是同一分支恒等（假象）。
- 【如何解决】：核实 P4 源码：`gs_inc_ackreq` 在 AckReq 数据包分支（`gs_is_ackreq==1`，stage6）自增；`gs_inc_ack_total` 仅在 ACK opcode==17 分支（stage11）自增——不同包型、不同 stage 的独立计数器，故 1:1 是真实观测、说明无净聚合。
- 【出处】：`gscc-tofino2-record.md` L423-425、L440。

---

## F. 其它零散坑

### F1. 必须保持 25 张表 / 34 符号，不增删表
- 【时间】：全程
- 【表现】：一旦增删表或改动表结构过多，偏离“最小改动”并可能引入 stage/PHV 问题。
- 【如何解决】：原版 25 张表全部保留、命名一致，只改逻辑；观测寄存器用最小增量、且只放在实验分支。
- 【出处】：`gscc-tofino2-record.md` L15、L28；本会话约束（“只在原版 gscc.p4 上做最小修改”“不要多余观测表”）。

### F2. 读寄存器忘记 `from_hw=True` 会读到缓存旧值
- 【时间】：2026-11-06
- 【表现】：脚本读寄存器不带 `from_hw=True` 时读到的是软件缓存而非硬件真值。
- 【如何解决】：`reg.get(0, from_hw=True).data[b"...f1"]`。
- 【出处】：`gscc-tofino2-record.md` L173-179（复现命令里的注释“别忘了 from_hw=True”）。

### F3. `gs_psn_m1` 等 metadata 字段需在 parser 初始化为 0
- 【时间】：2026-11-06
- 【表现】：未初始化的 metadata 字段可能触发未初始化告警/不确定值。
- 【如何解决】：parser `start` 里把所有 out 参数（含 `gs_psn_now`、`gs_rtt_stored_id` 等）初始化为 0。
- 【出处】：`gscc-tofino2-record.md` L76-80（parser 提取）；会话中 parser 初始化段（`gs_meta.gs_psn_now = 0; ...`）。

---

## 附：论文算法落地对照（坑的“正解”索引）

| 论文要点 | 落地实现 | 关联坑 |
|---|---|---|
| Algorithm 1 第1行：`index = hash(5tuple)*16 + hash(seq) mod 16` | `(bucket<<4) | psn[3:0]`，桶哈希只用 IP 对 | C2/C3/C5 |
| RTT 匹配（ACK 与 ack_req PSN 对齐） | 对称 ±1 窗口 `d∈{0,±16}` | C4/A6/B1 |
| Algorithm 2：refRate 调整 | `calculate_reference_rate()` ↔ `wan-routing.cc:701` | D9/D4/D5 |
| Algorithm 3：CNP 生成 + bytes 预算 | mirror session + refBytes 预算 | D12/D4 |
| 高性能转发 | egress `default: gs_parse_ethernet` | C1 |
| 控制面 | ctrl.c 15 处 API/移植改动 | D1/D2/D3/D6/D7 |
