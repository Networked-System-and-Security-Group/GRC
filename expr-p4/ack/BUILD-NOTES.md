# expr-p4/ack 编译验证记录

环境：交换机 `192.168.5.220`（root，Tofino2，SDE 9.7.1，`bf-p4c` 在 PATH，arch `t2na`）。

## 1. 数据面（观测版）

### multi-bucket（多桶版，256 桶 × 256 槽）
即本目录 `multi-bucket/data-plane/gscc.p4`（源出 `dataplane/gscc_stat.p4`）。
该版本在之前的实验中已编译并**实际部署运行**（`/tmp/build-coal/gs_pipe/` 为其产物，控制面 UP、计数器正常），编译通过。

```bash
bf-p4c --std p4-16 --target tofino2 --arch t2na --bf-rt-schema <out>/bf-rt.json -o <out> gscc.p4
# => compilation_succeeded = true
```

### single-bucket（单桶版，psn[15:0]）
本目录 `single-bucket/data-plane/gscc.p4`（由 `gscc_stat.p4` 把 `BUCKET_MASK=0`、索引改为 `psn[15:0]` 得到）。重新编译验证：

```bash
bf-p4c --std p4-16 --target tofino2 --arch t2na --bf-rt-schema /tmp/build-obs-single/bf-rt.json -o /tmp/build-obs-single gscc_stat.p4
# compile.log 末尾: EXIT=0 ；manifest.json: "compilation_succeeded": true
# 产物: gs_pipe/tofino2.bin (1.88 MB), gs_pipe/gscc_stat.bfa (153 KB), gs_pipe/context.json, bf-rt.json
```

## 2. 控制面（观测版，`control-plane/`）

`ctrl.c` = 带观测打印的 `ctrl-switchd` 版（直读 K 直方图 / off 直方图 / ack_req / ack_total / rtt_ok / fail 等寄存器）。两个版本共用同一控制面。编译命令（Makefile 已含 `-DBFRT_GENERIC_FLAGS`）：

```bash
export SDE_INSTALL=/sde/bf-sde-9.7.1/install
gcc -O2 -g -DBFRT_GENERIC_FLAGS -I. -I$SDE_INSTALL/include -o ctrl ctrl.c \
    -L$SDE_INSTALL/lib -ldriver -lbf_switchd_lib -lpthread -lm
# => rc=0，生成 ctrl（约 91 KB）
```

> 注意：`ctrl.c` 读取的是观测寄存器（`gs_khist_reg` / `gs_psn_now_reg` / `gs_storedid_reg` / `gs_rtt_ok_cnt_reg` 等），因此**只能与带观测的数据面（本目录两个版本）配套使用**；与“无观测”的 `P4/`（P4-fix）版本配套的控制面见 `P4/controlplane/`。
