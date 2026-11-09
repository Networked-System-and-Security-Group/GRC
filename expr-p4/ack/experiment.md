# GSCC P4（Tofino2）成功实验记录

> 本文件只记录**做对、跑通的成功实验**：每一步给出【原始命令】+【真实输出】+【实验结果】+【解读】。
> 编译/部署过程中踩过的坑、报错与修复过程 **不在本文件**，统一记录在 `../bugs.md`。

---

## 0. `expr-p4/ack/` 下的两份观测版 P4 说明

本目录 `expr-p4/ack/` 存放本次 ACK 聚合/PSN 观测实验用到的两份**带观测寄存器的最小改动版** P4，
各自分为 `data-plane/` 与 `control-plane/` 两个子目录：

| 子目录 | 数据面 | 控制面 | 说明 |
|---|---|---|---|
| `multi-bucket/` | `data-plane/gscc.p4`（源出 `gscc_stat.p4`） | `control-plane/ctrl.c`(+headers.h, switch_config.h) | **多桶版（仅加观测）**：保留原版 256 桶，表深 65536 = 256 桶 × 256 槽，索引 `bucket<<8 \| psn[7:0]`。仅在原算法上新增观测寄存器，不改算法/CNP。 |
| `single-bucket/` | `data-plane/gscc.p4`（源出 `gscc_stat.p4`，桶掩码清零） | `control-plane/ctrl.c`(+headers.h, switch_config.h) | **归成一个桶、也带观测**：桶掩码清零，索引 = 纯 `psn[15:0]`，表深 65536（1 桶 × 65536 槽），把全部 SRAM 用于覆盖 psn 位。 |

- 两者控制面都是**带观测打印的 `ctrl-switchd` 版**：`ctrl.c` 本身作为 `bf_switchd` 运行，周期性
  打印 `[epoch] ...` 与 `K-HIST` / `ACK : 数据包 ... 聚合=...x` 等观测信息（读取用 `bf_rt register_read`，
  `BF_DEV_PIPE_ALL` 对 4 个 pipe 求和，不改 GSCC 算法逻辑）。
- 表项命名与功能与原版 gscc 一致，新增的只是观测寄存器（`gs_psn_now_reg`、`gs_storedid_reg`、
  `gs_khist_reg`、`gs_ackreq_pending_reg` 等）；核心算法表不改。

---

## 1. 实验环境

```
交换机     192.168.5.220   root   Tofino2   SDE 9.7.1   （bf-p4c, --target tofino2 --arch t2na）
流量机     192.168.5.111   用户 pengbo29   （经 127.0.0.1:1080 SOCKS 代理登录；host xfusion-1）
网卡       mlx5_0 = ens7f0np0 = 10.99.1.1   面板口 1（dev_port 392, pipe 3）—— client
          mlx5_2 = ens10f0np0 = 10.99.2.1   面板口 2（dev_port 400, pipe 3）—— server
工具       /usr/bin/ib_write_bw （perftest）
端口范围   18515 – 20728 （每次 run 用不同 -p，避免 socket 冲突）
```

- 两网卡经交换机面板口 392/400 回环互通，单 host 两卡对打，链路近线速（≈11034 MiB/s ≈ 92.5 Gbps）。
- 登录/执行的包装形式（本会话实测可用）：

```bash
# 交换机
ssh -o StrictHostKeyChecking=no root@192.168.5.220
# 流量机（默认用户即为 pengbo29）
ssh -o StrictHostKeyChecking=no 192.168.5.111
```

---

## 2. 数据面编译（bf-p4c）

原始命令（以 16 位/单桶档为例，`gscc_stat.p4` 为带 ±1 窗口匹配 + 观测寄存器的版本）：

```bash
cd /root/gscc-p4/dataplane
bf-p4c --std p4-16 --target tofino2 --arch t2na \
    --bf-rt-schema /tmp/build_s16/bf-rt.json -o /tmp/build_s16 gscc_stat.p4 \
    > /tmp/build_s16/compile.log 2>&1
echo COMPILE_EXIT=$?
```

真实输出（摘自 `/tmp/matrix_run.log`，每档编译均为 EXIT=0）：

```
VERIFY
356:    const bit<32> GS_RTT_TABLE_SIZE = 4096;
359:    const bit<32> GS_RTT_BUCKET_MASK = 0;
643:            | (bit<32>)gs_hdr.gs_bth.gs_psn[7:0];
663:            | (bit<32>)gs_hdr.gs_bth.gs_psn[7:0];
COMPILE_EXIT=0
```

产物校验（真实 `ls`，`/tmp/build_s8/gs_pipe/`）：

```
-rw-r--r-- 1 root root 2684978 ... context.json
-rw-r--r-- 1 root root  156379 ... gscc_stat.bfa
-rw-r--r-- 1 root root 1878432 ... tofino2.bin
```

补充（来自 `gscc-tofino2-record.md`）：`bf-p4c EXIT=0`，`gs_pipe/tofino2.bin = 1879600 B`，
`manifest.json` 的 `compilation_succeeded` 为 `true`（编译成功判定用该字段）。

**解读**：`bf-p4c` 在 SDE 9.7.1、`--target tofino2 --arch t2na` 下无错误，产出可上机的
`tofino2.bin / context.json / gscc_stat.bfa` 三件套与 `bf-rt.json`。`GS_RTT_TABLE_SIZE` 与
`psn` 切片随档位变化，是"槽位数"这一自变量的来源。

---

## 3. 控制面编译（ctrl-switchd，C 版）

`ctrl-switchd/ctrl.c` 本身作为 `bf_switchd` 运行（内部 `bf_switchd_lib_init`）。编译命令：

```bash
cd /root/gscc-p4/ctrl-switchd
gcc -O2 -g -DBFRT_GENERIC_FLAGS -I. -I$SDE_INSTALL/include \
    -o ctrl ctrl.c -L$SDE_INSTALL/lib \
    -ldriver -lbf_switchd_lib -lpthread -lm
```

SDE 里 `libbf_switchd_lib.so` 等只有 `.so`、没有 `.so.0`，需就地建软链（真实命令）：

```bash
mkdir -p lib && cd lib
for b in libbfsys libbfutils libdriver libtofinopdfixed_thrift libbf_switchd_lib; do
  ln -sf $SDE_INSTALL/lib/$b.so $b.so.0
done
```

运行（本身即 `bf_switchd`；`LD_LIBRARY_PATH` 带上本地软链目录）：

```bash
GSCC_CONF=/root/gscc-p4/build-hw2/gscc.conf \
LD_LIBRARY_PATH=./lib:$SDE_INSTALL/lib:/sde/bf-sde-9.7.1/p4studio/dependencies/source/libcli:/sde/bf-sde-9.7.1/spfc/gscc-controlplane/lib-runtime \
./ctrl
```

关键编译开关 `-DBFRT_GENERIC_FLAGS`：`bf_rt_table.h` 用 `#ifdef BFRT_GENERIC_FLAGS` 分了新旧两套 C API，
本版按 9.7.1 的新 API（`entry_get/entry_mod` 均带 flags）编译。

**解读**：控制面编译通过、链接 `-ldriver -lbf_switchd_lib` 成功；`.so.0` 软链是运行时动态库名匹配所必需。
运行后 `ctrl` 常驻控制环，既完成 `bf_switchd` 起板，又跑 GSCC 速率控制与观测打印。

---

## 4. 部署与启动

把一次编译产出的四个二进制就位到运行目录，然后重启控制面（真实命令，摘自矩阵编排脚本）：

```bash
cd /tmp/build-coal
cp /tmp/build_s16/gs_pipe/tofino2.bin  gs_pipe/tofino2.bin
cp /tmp/build_s16/gs_pipe/context.json gs_pipe/context.json
cp /tmp/build_s16/gs_pipe/gscc_stat.bfa gs_pipe/gscc_stat.bfa
cp /tmp/build_s16/bf-rt.json           bf-rt.json

# 重启控制面（ctrl 自身拉起 bf_switchd）
pkill -x ctrl; pkill -x bf_switchd; sleep 6; : > ctrlR.log
nohup bash /tmp/build-coal/start.sh > ctrlR.log 2>&1 &

sleep 52
grep -aE '初始化成功|启动成功|失败' ctrlR.log | tail -3
```

真实输出（每次重启稳定出现）：

```
bf_switchd 初始化成功
GSCC 控制面启动成功
```

`start.sh` 负责设置 SDE 环境并 `exec ./ctrl`；端口 392/400 由控制面 `port_setup`
（`GSCC_PORTS` 默认 `392,400`）用 `bf_pal_port_add` + `bf_pal_port_enable` 以 100G RS 自动 bring-up。

**解读**：`bf_switchd 初始化成功` + `GSCC 控制面启动成功` 是"数据面已加载 + 控制环已起来"的双确认；
等 ~52 s 让 P4 寄存器表全部就绪、控制环进入稳态打印后再打流。

---

## 5. 在 111 上打流（ib_write_bw）

server 先起、client 后打（真实命令，摘自矩阵编排脚本的 `SSH111` 一行；`-p` 端口每次变化）：

```bash
# 在 111 上（server 用 mlx5_2，后台；client 用 mlx5_0 指向 10.99.2.1）
nohup ib_write_bw -d mlx5_2 -F -n 40000 -s 65536 -p 20701 -q 1 > /tmp/srv_20701.log 2>&1 &
SS=$!
sleep 2
ib_write_bw -d mlx5_0 -F -n 40000 -s 65536 -p 20701 -q 1 10.99.2.1 > /tmp/cli_20701.log 2>&1
echo RUN_rc=$?
wait $SS
grep -E '65536' /tmp/cli_20701.log | tail -1
```

真实输出（client 结果行，摘自 `/tmp/matrix_run.log`）：

```
RUN_rc=0
 65536      40000            0.00               11033.87		     0.176542
```

- 列含义：消息大小 65536 B、迭代 40000 次、…、**峰值带宽 11033.87 MiB/s**、消息率 0.176542 Mmsg/s。
- 所有 matrix run（q=1…128）均 `RUN_rc=0`，带宽 ~11034 MiB/s。

**解读**：`-n 40000 -s 65536` 即每 QP 40000 条 64 KB 消息；`-q` 控制 QP 数（流数自变量）。
带宽恒定 ~11034 MiB/s，说明单 host 两网卡经交换机已近线速，加 QP 不增总带宽（只是把同样的
字节摊到更多流上）。

---

## 6. 如何观察计数器正常 + match% / ACK 聚合倍数的计算

### 6.1 控制面状态打印（真实片段，来自 record）

```
[epoch] dc=0 rtt=   1.45 us base=   1.45 us realR=  3970.15 MB/s refR=  6250.00 MB/s
[epoch] dc=0 rtt=   1.87 us base=   1.45 us realR= 11707.50 MB/s refR= 12500.00 MB/s
[epoch] dc=0 rtt=   1.86 us base=   1.45 us realR= 11793.22 MB/s refR= 15000.00 MB/s
[epoch] dc=0 rtt=   1.84 us base=   1.45 us realR= 12059.63 MB/s refR= 15000.00 MB/s
```

寄存器直读（来自 record，`bf_rt register_read`，4 pipe 求和）：

| 寄存器 | 值 | 含义 |
|---|---|---|
| `gs_real_bytes_reg` | 342,096,176 | 实际转发字节（数据面累加） |
| `gs_ref_bytes_reg` | 439,103,750 | 控制面写的预算 |
| `gs_pkt_count_reg` | 325,337 | 所有 RoCE 包 |
| `gs_cnp_count_reg` | 2,037 | CNP 生成次数（0.63%） |

### 6.2 每次打流后读一次观测计数器（真实行，来自 `/tmp/matrix_run.log`）

```
L8 q1: ----- K-HIST(C-HW dc0): ack_req=42511 ack_total=42511 | rtt_ok=42511 fail_zero=0 fail_psn=0 ----- | ACK:数据包=2560000 ACK包=44446 聚合=57.6x 匹配=89.5%
L8 q128: ----- K-HIST(C-HW dc0): ack_req=12743865 ack_total=12744869 | rtt_ok=12493401 fail_zero=0 fail_psn=251468 ----- | ACK:数据包=652886920 ACK包=13010872 聚合=50.2x 匹配=90.0%
```

### 6.3 指标计算方式

- **match%（匹配率）** = `rtt_ok / ack_total`。其中 `rtt_ok` = ACK 的 PSN 与存储的 ack_req PSN
  在 ±1 窗口内匹配成功的次数；`fail_psn` = 不匹配次数；`fail_zero` = 时间戳为 0/空槽次数。
  正常情况下 `ack_req == ack_total`（每个 ack_req 恰好等到 1 个 ACK），且 `rtt_ok + fail_psn + fail_zero = ack_total`。
- **ACK 聚合倍数** = `数据包 / ACK包`，由控制面直接输出 `ACK:数据包=X ACK包=Y 聚合=Zx`。
- 注意：控制面每 ~5 s 打印一次，且计数器是**单调累计**的；做"每档净结果"时，用相邻两次快照**差分**得到该次 run 的增量再算比值（下节表格即此法）。
- `匹配=` 字段是"自启动以来的累计匹配率"，跨多档连续跑时会失真，务必用差分后的每档 `rtt_ok/ack_total`。

**解读**：`ack_req:ack_total = 1:1` 说明计数器真实反映包型（AckReq 数据包 vs ACK opcode 17 是不同 stage 的独立自增），
不是同一分支的恒等式；`fail_zero≈0` 说明时间戳通路正常，失配全部来自 psn 槽位碰撞（`fail_psn`）。

### 6.4 现场快照（多桶观测版实测，含 ACK 聚合的 K 分布）

在 `192.168.5.220` 上运行多桶观测版（256 桶 × 256 槽）+ 观测控制面，跑 `ib_write_bw` 打流后，控制面打印的真实状态块：

```
========== GSCC 控制面状态 ==========
运行中: 是
epoch: 1000 us

--- DC 0 ---
  RTT : cur=2.68 us  base=1.60 us  miss=50525
  速率: real=0.00 MB/s  ref=3125.00 MB/s
  字节: refBytes=2836575000  lastRealBytes=2736760528
  ACK : 数据包=2560000  ACK包=43574  聚合=58.8x  匹配=90.3%
  状态: AI  连续=209
======================================

----- K-HIST(C-HW dc0): ack_req=42511 ack_total=42511 | rtt_ok=42176 fail_zero=0 fail_psn=335 -----
  K=0  : 1924
  K=1  : 38663
  K=2  : 1924
  K total samples=42511  nonempty bins=3

----- OFF-HIST(C-HW dc0): fail-slot samples=1 pos=0 neg=1 mean=-16.00 min=-16 max=0 cand_slots=1 -----
  off |d|16-31   : 1
```

两种指标的**口径不同**，必须分开看：

- **K-HIST（硬件直测）**：统计“相邻两次 ACK 请求之间夹了多少个数据包”，即**每个 ACK 实际合并了几个数据包**。
  本快照 `K=1: 38663、K=2: 1924`（另有 `K=0: 1924` 是空槽/未成对样本的计数），**均值≈1.05**，
  即在本测试床上 **ACK 层面几乎不发生合并（一个 ACK 基本对应 1 个数据包）**。
- **`聚合=58.8x`（派生量）**：由控制面 `数据包 = bytes/GSCC_PKT_WIRE_BYTES`、`ACK包 = pkt_delta − 数据包`，
  再取 `数据包/ACK包` 得到。它受 `GSCC_PKT_WIRE_BYTES` 估算与 RoCE 消息分段（一条 64KB WR 被拆成多个 MTU 包）影响，
  **是“数据包与 ACK 包的数量比”，并不等于“一个 ACK 合并了几个数据包”**。

> ⚠️ **结论性提醒**：若严格以硬件 K-HIST 为准，本测试床**观察不到明显 ACK 聚合（K≈1）**；
> `聚合=58.8x` 是字节/包数派生的比例，不能当作 ACK 合并倍数。回答“能否观察到 ACK 聚合”应据此谨慎表述。

其余计数器均正常且自洽：`ack_req=42511=ack_total`（1:1 成对）、`rtt_ok/ack_total≈99.2%`、`fail_zero=0`、
`fail_psn=335`（≈0.8% 槽碰撞）；`OFF-HIST` 失配样本 `d=-16` 恰是 ±1 窗口外的相邻槽，
说明 **±1 窗口逻辑正确、失配来自槽碰撞而非算法**。

---

## 7. PSN 槽位 bit × 流数 梯度矩阵实验

### 7.1 两种观测版本与索引公式

- **multi-bucket（多桶版，256 桶 × 256 槽，psn[7:0]）**：
  `entry_idx = ((hash(IP对) & 255) << 8) | psn[7:0]`，`GS_RTT_TABLE_SIZE = 65536`。
- **single-bucket（1 桶，psn[slot_bits-1:0]）**：桶掩码清 0，
  `entry_idx = psn[slot_bits-1:0]`，有效槽数 = 2^slot_bits。
  单 IP 对下与多桶版行为等价（多桶里其余 255 桶空置），但把 SRAM 全用来覆盖 psn 位。
  为与控制面读取范围匹配，`GS_RTT_TABLE_SIZE` 取 `max(4096, 2^slot_bits)`（有效索引仍只用 `psn[slot_bits-1:0]`）。

### 7.2 真实编排命令（摘自 `/tmp/gscc_matrix.sh`，逐档循环）

```bash
for S in 8 10 12 14 16; do
  N=$((1<<S)); LOW=$((S-1)); TBL=$N; if [ $TBL -lt 4096 ]; then TBL=4096; fi
  # 1) 改常量 + 编译
  cd /root/gscc-p4/dataplane
  cp /tmp/src_slot256_now.p4 gscc_stat.p4
  sed -i "s/const bit<32> GS_RTT_TABLE_SIZE = [0-9]*;/const bit<32> GS_RTT_TABLE_SIZE = $TBL;/" gscc_stat.p4
  sed -i "s#const bit<32> GS_RTT_BUCKET_MASK = [^;]*;#const bit<32> GS_RTT_BUCKET_MASK = 0;#" gscc_stat.p4
  sed -i "s/<< 8)/<< $S)/g; s/gs_psn\[7:0\]/gs_psn[$LOW:0]/g" gscc_stat.p4
  bf-p4c --std p4-16 --target tofino2 --arch t2na \
      --bf-rt-schema /tmp/build_s$S/bf-rt.json -o /tmp/build_s$S gscc_stat.p4 > /tmp/build_s$S/compile.log 2>&1
  # 2) 部署 + 重启控制面（见 §4）
  # 3) 对 Q in 1 2 4 8 16 32 64 128 逐一打流（见 §5），每次 sleep 8 后读一次计数器快照
  for Q in 1 2 4 8 16 32 64 128; do
    P=$((19000 + S*200 + Q))
    # server 在 mlx5_2 后台、client 在 mlx5_0 打 10.99.2.1（见 §5）
    # sleep 8; 读 K-HIST 与 ACK 行，追加到 /tmp/matrix.csv
  done
done
```

### 7.3 真实原始输出（`/tmp/matrix.csv`，累计快照，节选）

```
S,flow,cum_line,agg
8,1,----- K-HIST(C-HW dc0): ack_req=42511 ack_total=42511 | rtt_ok=42511 fail_zero=0 fail_psn=0 -----,ACK:数据包=2560000ACK包=44446聚合=57.6x匹配=89.5%
8,128,----- K-HIST(C-HW dc0): ack_req=12743865 ack_total=12744869 | rtt_ok=12493401 fail_zero=0 fail_psn=251468 -----,ACK:数据包=652886920ACK包=13010872聚合=50.2x匹配=90.0%
16,128,----- K-HIST(C-HW dc0): ack_req=12766059 ack_total=12767177 | rtt_ok=12764348 fail_zero=1 fail_psn=2828 -----,ACK:数据包=652887690ACK包=13107088聚合=49.8x匹配=91.4%
（全表 40 行，见随附 CSV）
```

### 7.4 结果：每流 match%（对累计值做差分，`match% = Δrtt_ok / Δack_total`）

| 有效槽 (bits) | q1 | q2 | q4 | q8 | q16 | q32 | q64 | q128 |
|---|---|---|---|---|---|---|---|---|
| 256 (8b)   | 100 | 100 | 100 | 99.99 | 99.96 | 99.81 | 99.68 | **96.73** |
| 1024 (10b) | 100 | 100 | 100 | 100 | 99.99 | 99.85 | 99.98 | 99.47 |
| 4096 (12b) | 100 | 100 | 100 | 100 | 100 | 99.99 | 99.44 | 99.86 |
| 16384 (14b)| 100 | 100 | 100 | 100 | 100 | 100 | 100 | **99.97** |
| 65536 (16b)| 100 | 100 | 100 | 100 | 100 | 99.86 | 100 | 99.99 |

> ⚠️ 口径注：本表为 **±16 窗口版**（允许近似匹配）。若改用 Fix/论文的 **精确匹配**（`d==0`），256 槽时 q64≈92.6%、q128≈89–94%（实测见 **§11.4**）——match% 高不等于 RTT 准。

每流 `fail_psn`（psn 槽碰撞次数，差分）：

| 有效槽 | q32 | q64 | q128 |
|---|---|---|---|
| 256  | 2574 | 8699 | 239923 |
| 1024 | 2074 | 535  | 38956  |
| 4096 | 150  | 15301| 10442  |
| 16384| 5    | 118  | 2539   |
| 65536| 1920 | 62   | 846    |

### 7.5 派生的“数据包/ACK 包”比值（`聚合=Zx`，注意口径）

| 流数 | q1 | q8 | q16 | q32 | q64 | q128 |
|---|---|---|---|---|---|---|
| 派生比值 | ~57.6x | ~58.8x | ~58.6x | ~58.3x | ~58.0x | ~49–50x |

> ⚠️ 上表是控制面 `数据包/ACK包` 的**派生比值**（受 `GSCC_PKT_WIRE_BYTES` 与消息分段影响），**不是**“一个 ACK 合并了几个数据包”。
> 真正的 ACK 合并倍数看硬件 **K-HIST：K≈1**（见 §6.4），即本测试床 ACK 层几乎无合并。

### 7.6 解读

1. **PSN 位宽 = 24 bit**（`header.p4`: `bit<24> gs_psn;`）。"全覆盖"= psn[23:0] → 2^24 = 16,777,216 槽/桶；
   每表项约 5 个 32-bit 寄存器，2^24 表项 ≈ 335 MB，**物理不可行**；且数据表明 14 bit 已饱和，无需 24 bit。
2. **q≤32 时 256 槽(8 bit) 已 ≥99.8%**：流数少时，单 IP 对总包率固定，psn 槽碰撞概率 ~ 总在途/槽数，很小。
3. **q128 是分水岭**：256 槽 → 96.73%（fail 24 万），随槽位单调恢复：1024→99.47%、4096→99.86%、
   16384→**99.97%**、65536→99.99%。即 **128 流需 ≥14 bit（16384 槽）才逼近 100%**，16 bit 仅边际提升。
4. **fail_zero≈0**（个别档仅 1）→ 时间戳/±1 窗口逻辑正确；失配几乎全部是 `fail_psn`（psn 槽碰撞覆盖），
   证明**瓶颈是槽数而非算法**，也说明"桶数"不是瓶颈（单 IP 对永远落 1 个桶）。
5. **ACK 聚合**：派生的“数据包/ACK包”比值 q≤64 稳定 ~57–59x、q128 降到 ~49–50x；但硬件 K-HIST 显示每 ACK 实际合并 **K≈1**（几乎无合并）。两者口径不同（见 §6.4/§7.5），谈“聚合倍数”应以 K-HIST 为准。所有 run `rc=0`、线速 ~11034 MiB/s。

---

## 8. 结论小结

1. 数据面 `bf-p4c` 编译成功（EXIT=0，`compilation_succeeded=true`），控制面 `ctrl-switchd` 编译运行成功；
   部署后 `bf_switchd 初始化成功 / GSCC 控制面启动成功`，111 两卡经交换机回环稳定 ~11034 MiB/s。
2. 计数器在真机全部正常：`ack_req/ack_total/rtt_ok/fail_zero/fail_psn`、`gs_real_bytes/ref_bytes/pkt/cnp`、
   `[epoch]` 的 `rtt/realR/refR` 均可读且自洽，`ack_req:ack_total = 1:1`，`fail_zero≈0`。
3. PSN 槽位梯度：**256 槽足以支撑 ≤32 流（≥99.8%）**；**128 流需 ≥14 bit（16384 槽）才 99.97%**；
   24 bit 既不可行也无必要；瓶颈是槽数、不是桶数；剩余失配全为 psn 槽碰撞。
4. ACK 聚合：派生“数据包/ACK包”比值 **~57–59x（q≤64）/ ~49–50x（q128）**；但硬件 **K-HIST 显示每个 ACK 实际合并 K≈1**（几乎无合并）。两者口径不同（见 §6.4），回答“能否观察到 ACK 聚合”应以 K-HIST 为准——**本测试床未观察到显著 ACK 合并**，58.8x 仅为字节/包数派生比值。

> 单元测试/踩坑与修复过程见 `../bugs.md`；两份观测版 P4 源码见本目录 `multi-bucket/` 与 `single-bucket/`。

---

## 9. 资源占用（bf-p4c 9.7.1 / Tofino2 t2na，`--verbose 2` 资源报表）

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

> 观测版因新增 K-HIST / off-HIST / fail 等表与寄存器，SRAM（140/139 vs 41）、MapRAM（113 vs 18）、逻辑表（46 vs 35）明显上升，且 **TCAM 峰值达 79.17%**（fail 采样 / 大表所致），是观测版逼近资源墙的主因；P4-fix 干净版仅 41 SRAM、TCAM 峰值 8.33%、14 个 ingress stage。原始报表：交换机 `/tmp/res-fix2`（fix）、`/tmp/res-multi`、`/tmp/res-single` 的 `gs_pipe/logs/{mau.resources.log,metrics.json,table_summary.log}`。
>
> ±1 窗口的 16 槽纯算法参考实现见 `win16-pm1-reference/`（无观测，控制面用 P4-fix 去观测版 ctrl）。

---

## 10. S（每桶槽数）放大对 RTT 测量影响的计算

记号：`S` = 每桶槽数（槽号 = PSN 的低 `log2(S)` 位，即 `psn & (S-1)`）；`L` = 包长（字节，下面取 L=1024B）；`R` = 线速（bps）；`RTT` = 往返时延（s）；每包串行化时间 `t_pkt = 8L/R`。**同一槽内的包，PSN 必然相差 `S` 的整数倍。**

### 10.1 若把“窗口”也放大到 ±S（跨一代容错）—— RTT 偏差 ∝ S
一次“命中相邻一代”的错配，用到的发送时间戳属于相隔 `S` 个包的另一个包，RTT 偏差：
**Δrtt ≈ S · t_pkt = S · (8L / R)**（对 S 线性）。L=1KB：

| 线速＼S | S=16 | S=256 | S=65536 |
|---|---|---|---|
| 25G  | 5.24 µs | 83.9 µs | **21.5 ms** |
| 100G | 1.31 µs | 21.0 µs | **5.37 ms** |
| 400G | 0.33 µs | 5.24 µs | **1.34 ms** |

→ S=16 时错配代价（~µs）相对 WAN RTT 可忽略；但 S 到 256/65536 后，一次错配的代价升到几十 µs 甚至 ms 级（可 ≥1 个 RTT），**完全不可接受**。所以“±S 窗口”不能随 S 放大。（包长变大则同比例放大：换 4KB 包，表内数值 ×4。）

### 10.2 扩大 S 的正确目的：让 S ≥ 在飞包数 B（消除覆盖）
单流在飞包数（BDP，以包计）`B = RTT · R / (8L) = RTT / t_pkt`。**只有当 `S ≥ B` 时，同一流在飞的包才不会在同一槽互相覆盖**；否则第 S 个包会盖掉前面同槽的包 → 该 ACK 只能 miss（精确匹配）或被错配（窗口放大时）。L=1KB：

| 线速＼RTT | 0.1 ms | 1 ms |
|---|---|---|
| 25G  | B≈305 → 9 bit (512)   | B≈3052 → 12 bit (4096) |
| 100G | B≈1221 → 11 bit (2048) | B≈12207 → **14 bit (16384)** |
| 400G | B≈4883 → 13 bit (8192) | B≈48828 → **16 bit (65536)** |

### 10.3 结论
1. **精确匹配（窗口=0）下，放大 S 不给 RTT 引入任何偏差**，只把“覆盖→miss”变少（命中率↑）——这才是 S 的正确收益。
2. **只有把窗口也放大到 ±S 才会有 RTT 偏差，且偏差 ∝ S**（10.1）；到 S=256/65536 一次错配≈几十 µs~ms、甚至超过 WAN RTT，故**绝不这么做**。
3. 现设计窗口写死 **±16**：S=16 时等价“跨一代容错”（偏差≤~µs，可接受）；S=256/65536 时**±16 匹配不到任何异代**（同槽差值只能是 S 的倍数），退化为精确匹配——**窗口失效但无害**。
4. **Fix 版 16 槽的局限**：高 BDP 单流下 `S=16 ≪ B`（如 100G/1ms/1KB 时 B≈12207），会大量覆盖→命中率低；这正是观测实验要把槽位扩到 8/16 位的原因（§3/§4 实测“128 流需 ≥14 bit/16384 槽”，与上表 100G/1ms 的 14 bit 一致）。**扩槽位是为了覆盖 BDP，不是为了放宽窗口。**

### 10.4 中间档 S（16→32→64→128→256）逐档 RTT 偏差
沿用 10.1 的“窗口=±S”口径，把 S 在 16 与 256 之间逐档列出（L=1KB，Δrtt = S·8L/R）：

| S（槽数） | 槽位 bits | 25G | 100G | 400G |
|---|---|---|---|---|
| 16  | 4 | 5.24 µs | 1.31 µs | 0.33 µs |
| 32  | 5 | 10.49 µs | 2.62 µs | 0.66 µs |
| 64  | 6 | 20.97 µs | 5.24 µs | 1.31 µs |
| 128 | 7 | 41.94 µs | 10.49 µs | 2.62 µs |
| 256 | 8 | 83.89 µs | 20.97 µs | 5.24 µs |

结论：在“窗口随 S 放大”这一（错误）假设下，S 从 16 每翻一倍，一次错配的 RTT 偏差就线性翻倍；到 S=256 已达 21 µs（100G）/84 µs（25G），是 S=16 的 16 倍。**这正是不能把窗口做成 ±S 的量化依据**——S 越大越不能用跨代窗口。真正要放大 S 的理由见 10.2（覆盖在飞包，避免覆盖→miss），见 §11 的实测 ok/total。

## 11. 中间档 S（16→32→64→128→256）实测 ok/total（220+111 实跑，exact-match）

> 与 §7.4 的关键区别：**§7.4 用的是 ±16 窗口版（会“近似匹配”）；本节用精确匹配 `stored_id==psn_now`（与 Fix/论文一致）**，所以大 S 下 match% 更低但 RTT 更准（见 11.4、§12）。两者都 single-bucket。

### 11.1 方法（真实脚本 `/tmp/gscc_sweep.sh`、`/tmp/build_one.sh`、`/tmp/deploy_one.sh`）
- 版本：single-bucket（`GS_RTT_BUCKET_MASK=0`，同 IP 对的所有流落 **1 个桶**），`index = psn[S-1:0]`，`GS_RTT_TABLE_SIZE = max(4096, 2^S)`；把 WIN2 判定由 `d∈{0,±16..}` 改为 **`d==0`（精确）**。
- 档位：S = 16/32/64/128/256（slot bits 4/5/6/7/8）。
- 每档：编译→cp 到 `/tmp/build-coal`→重启 `ctrl`（内部拉起 bf_switchd，日志 `bf_switchd 初始化成功` / `GSCC 控制面启动成功`）→ Q=1/2/4/8/16/32/64/128 依次 `ib_write_bw -d mlx5_0 -F -n 40000 -s 65536 10.99.2.1`（server `mlx5_2` 后台）。
- 计数：每次打流后 sleep 6，读 `K-HIST(C-HW dc0)`；对累计值做 **Δ 差分**，`match% = Δrtt_ok / Δack_total`。所有 run `rc=0`、线速 ~11034 MiB/s、`fail_zero=0`（时间戳通路正常，失配全部是 `fail_psn` 槽碰撞）。

### 11.2 实测 match%（ok/total），exact-match，单桶

| S（槽） | bits | q1 | q2 | q4 | q8 | q16 | q32 | q64 | q128 |
|---|---|---|---|---|---|---|---|---|---|
| 16  | 4 | 98.42 | 99.78 | 99.61 | 90.81 | 91.90 | 90.83 | 83.89 | 37.84 |
| 32  | 5 | 100 | 99.57 | 99.80 | 99.57 | 94.00 | 92.71 | 75.63 | 49.32 |
| 64  | 6 | 100 | 100 | 99.87 | 99.70 | 98.27 | 98.81 | 81.87 | 40.61 |
| 128 | 7 | 100 | 100 | 99.99 | 99.84 | 98.94 | 99.19 | 96.95 | 66.94 |
| 256 | 8 | 100 | 100 | 99.99 | 100 | 99.88 | 98.23 | 92.58 | 88.59 |

（Δack_total 各档量级一致：q1≈42.5k、q128≈7.3M；恒有 `rtt_ok + fail_psn = ack_total`、`fail_zero≈0`。原始逐点 `S,Q,ack,ok,fail_psn,fail_zero,rc,bw` 见 `expr-p4/ack/sweep_s16_256.csv`。）

### 11.3 解读
1. **q1**：16 槽 98.42%（≈1.6% 被覆盖丢失），≥32 槽 100% → 本床单流在飞的“采样包”只需十几槽，**≥32 槽即可全覆盖**。
2. **q≤4**：各档 ≥99.6%；**q≤32** 时 128/256 槽仍 ≥99%。
3. **分水岭在 q≥64**：q64 时 128 槽 96.95%、256 槽 92.6%；q128 急剧下滑：16 槽 37.8%、32 槽 49.3%、64 槽 40.6%、128 槽 66.9%、256 槽 ~89%。
4. **q128 对 QP 起动相位极敏感**（128 条 QP 同时建立→PSN 同步→最坏碰撞）：256 槽实测 4 次为 88.6 / 90.0 / 89.2 / 93.6%，故 q128 应读作 **~89–94% 区间**，不是单点；q64 在 256 槽很稳（92.6/92.7/92.8%）。个别 q8/q64 点（如 S=16 q64=83.9 反而 > S=32 q64=75.6）也是相位/别名抖动，趋势以 q≤32 与 q128 下包络为准。
5. **结论**：单桶（IP 对哈希）下 **S 越大 ok/total 越高**；≤32 流 128 槽已够；**128 流要 ~90% 需 256 槽（8bit），要 ~100% 仍需 ≥14bit（16384 槽）**（与 §7.6 一致）。

### 11.4 与 §7.4 的口径差异（重要：match% 高≠RTT 准）
§7.4 的 256 槽行（q64=99.68、q128=96.73）是 **±16 窗口版**；本表是 **精确匹配**。同一 256 槽、同一 `-n 40000 -s 65536`，直接对比（均为本次新跑）：

| S=256 配置 | q64 | q128 |
|---|---|---|
| 精确 `d==0`（本表 / Fix / 论文） | **92.6–92.8%** | **88.6–93.6%** |
| ±16 窗口（复跑复现 §7.4） | **96.5–99.9%** | **96.5–98.6%** |

窗口把 match 拉高 **4–8 个百分点**，代价是“多出来的匹配”其偏差 `d∈[±1..16]` **并非零偏差**（把近似/聚合/相邻的 ACK 当原始包）→ RTT 被污染（100G 下 16 包≈1.3 µs；S 越大跨代误差越大，见 §10）。**这正是 §12 的“匹配 vs 丢弃”命题：论文选择丢弃。**
## 12. “差一点的 ACK 要不要硬匹配？”——论文（GRC, ICNP'26）的答案

问题：当 ACK 的 PSN 与槽里存的值不是精确相等、只“差一点”（例如同槽的相邻一代），我们该尝试把它匹配上（估一个 RTT），还是直接丢弃？

论文的做法（Algorithm 1 "Update Delay Entry" + §III/§V）明确：**宁可丢弃，也不误配**。三条依据：

**1) 写入侧：槽被“不同 packet”占用时不覆盖、不刷新（新采样直接放弃）**

Algorithm 1（论文原文）：
```
1: index ← hash(newPkt.5Tuple)×16 + hash(newPkt.seq) mod 16
2: if now − table[index].ts > Timeout then
3:     table[index].ts ← now
4:     table[index].identifier ← hash(newPkt)
5: else if table[index].identifier = hash(newPkt) then
6:     table[index].ts ← now        // 同一 packet 的重传副本：刷新时间戳
7: end if                           // 不同 packet 且未超时：什么都不做（丢弃新包）
```
即：只有“空/超时”才写入；“同一 packet（identifier 相同，重传副本）”才刷新；**遇到不同 packet 就放弃这个新采样、绝不覆盖**。这样旧 packet 的 ACK 之后回来仍能对上自己的 identifier，不会被顶掉而同槽误配。

**2) 读出侧：ACK 到达时用 compact identifier 核对，不符即丢弃该样本**

论文：“Each sampled packet is hashed to an entry containing a timestamp and a **compact identifier derived from its 5-tuple and sequence number**, which **distinguishes different packets mapped to the same entry**. Upon ACK arrival, the monitor retrieves the corresponding entry to compute RTT …” —— identifier 不符（槽已被别的包占用）就不算样本、不更新 RTT。

§V：“While entry collisions can be frequent, **packet identifiers prevent erroneous matches**. With the 24-bit identifier …, the probability of an erroneous match is **below 0.03% per epoch** … further mitigated by **averaging RTT samples within each epoch**.”

**3) 即便已算出 RTT，异常小的也丢弃**

“A rarer case is spurious retransmission … This may produce an unrealistically small RTT sample. To avoid this, GRC **discards RTT samples that are more than one RTO below the current RTT estimate**.”

**为什么是“丢弃”而不是“硬匹配”？** RTT 直接喂给速率环：Algorithm 2 `queueDelay ← newRTT − baseRTT`、`targetRate ← w/(δ·queueDelay)`。一个被误配（偏小）的 RTT 会让 queueDelay→0、targetRate 爆炸 → refRate 冲高 → 反而制造丢包；而丢一个样本只是少一个平均点。论文靠“采样量（1024 表项/6-DC 即每 epoch 数十个样本）+ epoch 内平均”保覆盖，不靠“抢救每个 ACK”。结论：**精度优先，模糊即丢**。

**对两条实现路线的判决**
- **Fix（精确匹配 `stored_id == psn_now`，不同即 miss、不更新）＝ 与论文完全一致。** ✅
- **实验版 ±1/±16 窗口“接受 d∈{0,±16}”＝ 恰好是论文反对的方向**（把不同 packet 当同一个），会引入跨代误配；与“宁可丢也不误配”相反。❌ 这也是 §10 的结论：窗口只能停留在 S=16 的“一代容错”，S 放大后必须退回精确匹配。

**保真度提醒（建议改）**：论文 identifier = `hash(5-tuple + seq)`（含流标识）；我们 P4 的 `stored_id` 只存了 **PSN**。当多条 QP 共用同一 IP-对桶（sport 不同但被忽略）且 PSN 相同时，PSN-only identifier 仍可能跨 QP 误配——且这种误配会计入 `rtt_ok`、**不被计为 fail，属“静默错误”**。要完全对齐论文，identifier 应并入流标识（如 sport 低位 / QP 号）；否则在“多 QP 同 IP 对”场景下需把这部分当已知近似。
