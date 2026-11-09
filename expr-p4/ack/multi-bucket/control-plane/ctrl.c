/*
 * ============================================================================
 *  GSCC / GRC 控制面  ——  作为 bf_switchd 运行
 * ============================================================================
 *
 *  来源：/home/micraow/research/GRC_sort/GRC/P4/controlplane/ctrl.c
 *
 *  本文件相对原版的全部改动（每一处都在注释里标了 [FIX-n]）：
 *
 *   [FIX-1] bf_rt_table_entry_get 的参数顺序     —— SDE 9.7.1 API
 *   [FIX-2] bf_rt_table_entry_mod 增加 flags      —— SDE 9.7.1 API
 *   [FIX-3] bf_rt_table_key_reset  传 &key        —— SDE 9.7.1 API
 *   [FIX-4] bf_rt_table_data_reset 传 &data       —— SDE 9.7.1 API
 *   [FIX-5] 寄存器读值按 pipe 求和（Tofino2 有 4 个 pipe 副本）
 *   [FIX-6] conf 路径不再硬编码 tofino1，改成 GSCC_CONF 或 tofino2
 *   [FIX-7] calculate_reference_rate 换成论文 Algorithm 2
 *   [FIX-8] 控制环从 10 秒改成常驻 + 信号退出
 *   [FIX-9] 增加 CNP mirror session 配置（论文 Algorithm 3 需要）
 *   [FIX-10] 启动时把 ref_bytes 对齐到 real_bytes
 *   [FIX-11] DEBUG 输出改成 GSCC_DEBUG 环境变量控制
 *
 *  为什么需要 [FIX-1..4]：
 *    SDE 9.7.1 的 bf_rt_table.h 用 #ifdef BFRT_GENERIC_FLAGS 分了新旧两套
 *    C API（290-623 行是新的，624-954 行是旧的）。原版 ctrl.c 写于
 *    entry_add 已经带 flags、entry_mod 还没带的那个版本，所以两套都不匹配。
 *    编译时要加 -DBFRT_GENERIC_FLAGS 走新 API。
 *
 *  为什么需要 [FIX-5]：
 *    TNA §12：Tofino2 有 4 个 pipe，每个 pipe 的 stateful 寄存器各有一份
 *    副本。数据面只往自己那个 pipe 写，控制面用 pipe_id=BF_DEV_PIPE_ALL
 *    读回来是 4 个值的数组，必须求和才是全网统计。
 *
 *  算法来源：
 *    论文 Algorithm 2 (Update ref Rate)，
 *    与 NS3 参考实现 src/point-to-point/model/wan-routing.cc:701
 *    WanRouting::DstDCHandler::update_ref_rate() 逐行对应。
 *
 *  编译：
 *    gcc -O2 -DBFRT_GENERIC_FLAGS -I. -I$SDE_INSTALL/include \
 *        -o ctrl ctrl.c -L$SDE_INSTALL/lib \
 *        -ldriver -lbf_switchd_lib -lpipe_mgr -ltraffic_mgr -lpthread -lm
 *
 *  运行：
 *    GSCC_CONF=/root/gscc-p4/build-hw2/gscc.conf \
 *    SDE_INSTALL=/sde/bf-sde-9.7.1/install \
 *    ./ctrl
 * ============================================================================
 */

#include "headers.h"
#include "switch_config.h"

#include <pthread.h>
#include <signal.h>
#include <time.h>
#include <math.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include <errno.h>

#include <bf_rt/bf_rt_common.h>
#include <bf_rt/bf_rt_table.h>
#include <bf_rt/bf_rt_info.h>
#include <bf_rt/bf_rt_session.h>

/* [FIX-9] CNP mirror session：用 pipe_mgr 的 Tofino2 通用接口，
 * 不用 tofino/pdfixed 的 p4_pd_*（那是 Tofino1 专用的）。 */
#include <pipe_mgr/pipe_mgr_mirror_intf.h>
#include <pipe_mgr/pipe_mgr_intf.h>
/* [FIX-13] 端口 bring-up：bf_switchd 自带的是板级默认配置，
 * 我们的面板口需要显式 100G + RS FEC。 */
#include <tofino/bf_pal/bf_pal_port_intf.h>

/* ------------------------------------------------------------------ */
/* [FIX-11] 调试输出开关                                               */
/* ------------------------------------------------------------------ */
static int g_debug = 0;
#define DBG(...)                        \
    do {                                \
        if (g_debug) fprintf(stderr, __VA_ARGS__); \
    } while (0)

/* ================ GSCC 控制平面全局变量 ================ */
bf_switchd_context_t *switchd_ctx;
bf_rt_target_t *dev_tgt;
const bf_rt_info_hdl *bfrt_info = NULL;
bf_rt_session_hdl *session = NULL;

/* ================ GSCC Rate Control 相关常量 ================ */
#define MAX_DC_COUNT 16

/* 控制 epoch。NS3 的 WAN_EPOCH_US 默认是 1000 us。
 * 注意：gRPC/bf_rt 单次寄存器读写约 0.4 ms，每个 DC 每轮 8 次，
 * 所以实际 epoch 会明显大于这个值；process_dc_control 用的是**实测**
 * 的 epoch_duration_us，算法本身自洽。 */
#define GSCC_EPOCH_DURATION_US 1000

/* 论文参数，默认值取自 NS3 参考实现 wan-routing.cc:21-31 */
#define GSCC_INV_DELTA 20971520.0     /* kInvDeltaDefault, delta = 1/INV_DELTA */
#define GSCC_BETA 0.3                /* kBetaDefault */
#define GSCC_W_MAX 4.0               /* kWMaxDefault */
#define GSCC_ENABLE_W 0              /* kEnableWDefault = FALSE -> w = 1 */
#define GSCC_ENABLE_V 1              /* kEnableVDefault = TRUE */
#define GSCC_GUARANTEED_RATE_FACTOR 0.25 /* kGuaranteedRateFactorDefault */

#define GSCC_SATURATION_SLACK 3e9    /* wan-routing.cc:718，3 GB/s */
#define GSCC_QUEUE_DELAY_FLOOR 10e-6 /* wan-routing.cc:770，最小 10 us */
#define GSCC_RATE_FLOOR 1000.0       /* 原版 ctrl.c 的下限保护 */
#define GSCC_LINK_RATE_BPS (100e9 / 8.0) /* 100G 面板口 -> 12.5 GB/s */

#define RATE_INCREASE 1
#define RATE_DECREASE (-1)

/*
 * ACK 聚合观测用的包长常量。
 *
 * gs_pkt_count_reg 统计的是**所有** RoCE 包（数据 + ACK），
 * 而 gs_rtt_count_reg 只统计"匹配上 ackreq 时间戳"的 ACK。
 * 要算聚合比，得先把 ACK 包从总数里减掉：
 *
 *     data_pkts = real_bytes / (MTU + L3 头)
 *     ack_pkts  = pkt_count - data_pkts
 *
 * 本实验床 perftest 默认 MTU = 1024，RoCE 的 IP+UDP+BTH+ICRC = 45 字节。
 * 实测 real_bytes / pkt_count = 1050，与 1024+45 吻合。
 */
#define GSCC_MTU_BYTES 1024
#define GSCC_L3_HDR_BYTES 45
#define GSCC_PKT_WIRE_BYTES (GSCC_MTU_BYTES + GSCC_L3_HDR_BYTES)

#define UINT32_MASK 0xFFFFFFFFULL

/* ================ 每个 DC 的统计信息 ================ */
typedef struct {
    uint32_t dc_id;

    /* --- 本 epoch 的 RTT 样本（论文 Delay Monitor 的输出）--- */
    uint32_t rtt_sum_ns;   /* 本 epoch 累计 RTT，单位 ns */
    uint32_t rtt_count;    /* 本 epoch 样本数 */

    /* --- 论文 Algorithm 2 的状态 --- */
    double cur_rtt_s;      /* curRTT */
    double min_rtt_s;      /* baseRTT：历史最小值（论文"long time window"） */
    uint32_t rtt_miss_counter;

    double guaranteed_rate; /* baseRate = max_rate * 0.25 */
    double ref_rate;        /* refRate */
    double real_rate;       /* realRate */
    uint32_t ref_bytes;     /* 控制面维护的 refBytes（绝对量，模 2^32） */
    uint32_t last_real_bytes;
    uint32_t last_pkt_count; /* 上一轮的包计数，用来算每轮增量 */

    /* 累计量：单轮比值受两次 gRPC 读取的 ~0.4 ms 时间偏移影响，
     * 只有累计值才有意义。 */
    uint64_t total_ackmatch;  /* 累计匹配上 ackreq 的 ACK 数 */
    uint64_t total_ack_pkts;  /* 累计 ACK 包数 */
    uint64_t total_data_pkts; /* 累计数据包数 */

    /* 最近 3 个 epoch 的发送字节数（wan-routing.cc 的 send_bytes_history） */
    uint32_t send_bytes_hist[3];
    int send_bytes_hist_n;

    /* 方向状态机，用来决定 v ∈ {1,2,4} （论文 line 4-10） */
    int rate_change_state;
    uint32_t consecutive_state_epochs;

    uint64_t last_update_time_us;
} dc_stats_t;

/* ================ 全局状态 ================ */
static dc_stats_t dc_stats[MAX_DC_COUNT];
/*
 * 哪些 dst-DC 需要控制。P4 里 gs_meta.gs_dst_dc_id = GS_ACTIVE_DC_ID（= 0），
 * 所以默认只控 DC 0。原版无脑轮询 0..15，等于每轮多做 15 份无用 gRPC 读写，
 * epoch 被拉长 16 倍。
 * 用环境变量 GSCC_DC_IDS=0,1 指定。
 */
static uint32_t g_active_dc_mask = 0x1;

/*
 * [FIX-16] 日志聚合：值没变就不刷屏。
 *
 * 空闲时每轮都打一遍一模一样的行（rtt=0 realR=0 refR=3125 ...），
 * 900k 轮下来日志能到几十 MB。这里只在以下任一情况变化时输出：
 *   - realRate 变了（取整到 MB/s）
 *   - refRate 变了（取整到 MB/s）
 *   - rtt 变了（取整到 0.1 us）
 * 不变时只累加 suppressed 计数，下次真正输出时带上 "(xN)"。
 */
static uint32_t g_last_print_realr = 0xFFFFFFFF;
static uint32_t g_last_print_refr = 0xFFFFFFFF;
static uint32_t g_last_print_rtt = 0xFFFFFFFF;
static uint32_t g_suppressed_lines = 0;
static pthread_t control_thread;
static volatile sig_atomic_t control_running = 0;
static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;

/* ================ P4 寄存器表句柄和信息结构体 ================ */
static const bf_rt_table_hdl *rtt_sum_reg_table = NULL;
static register_info_t rtt_sum_reg_info;
static const bf_rt_table_hdl *rtt_count_reg_table = NULL;
static register_info_t rtt_count_reg_info;
static const bf_rt_table_hdl *real_bytes_reg_table = NULL;
static register_info_t real_bytes_reg_info;
static const bf_rt_table_hdl *ref_bytes_reg_table = NULL;
static register_info_t ref_bytes_reg_info;
static const bf_rt_table_hdl *pkt_count_reg_table = NULL;
static register_info_t pkt_count_reg_info;
static const bf_rt_table_hdl *ackreq_cnt_reg_table = NULL;
static register_info_t ackreq_cnt_reg_info;
static const bf_rt_table_hdl *ack_total_reg_table = NULL;
static register_info_t ack_total_reg_info;
static const bf_rt_table_hdl *rtt_ok_cnt_reg_table = NULL;
static register_info_t rtt_ok_cnt_reg_info;
static const bf_rt_table_hdl *rtt_fail_zero_reg_table = NULL;
static register_info_t rtt_fail_zero_reg_info;
static const bf_rt_table_hdl *rtt_fail_psn_reg_table = NULL;
static register_info_t rtt_fail_psn_reg_info;
static const bf_rt_table_hdl *khist_reg_table = NULL;
static register_info_t khist_reg_info;
static const bf_rt_table_hdl *psn_now_reg_table = NULL;
static register_info_t psn_now_reg_info;
static const bf_rt_table_hdl *storedid_reg_table = NULL;
static register_info_t storedid_reg_info;

/*
 * @brief 设置一个寄存器，获取其表句柄、key/data 句柄和字段 ID
 */
void register_setup(const bf_rt_info_hdl *bfrt_info_hdl,
                    const char *reg_name,
                    const char *value_field_name,
                    const bf_rt_table_hdl **reg_table_hdl_ptr,
                    register_info_t *reg_info_ptr) {
    bf_status_t bf_status;
    char reg_value_full_name[128];

    bf_status = bf_rt_table_from_name_get(bfrt_info_hdl, reg_name, reg_table_hdl_ptr);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: 找不到寄存器 '%s' (status: %d)。"
                        "P4 程序里可能没有它。\n", reg_name, bf_status);
        exit(1);
    }
    if (*reg_table_hdl_ptr == NULL) {
        fprintf(stderr, "ERROR: '%s' 的表句柄是 NULL。\n", reg_name);
        exit(1);
    }

    bf_status = bf_rt_table_key_allocate(*reg_table_hdl_ptr, &reg_info_ptr->key);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: 为 '%s' 分配 key 失败\n", reg_name);
        exit(1);
    }
    bf_status = bf_rt_table_data_allocate(*reg_table_hdl_ptr, &reg_info_ptr->data);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: 为 '%s' 分配 data 失败\n", reg_name);
        exit(1);
    }

    bf_status = bf_rt_key_field_id_get(*reg_table_hdl_ptr, "$REGISTER_INDEX",
                                       &reg_info_ptr->kid_register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: 取 '%s' 的 key 字段 ID 失败\n", reg_name);
        exit(1);
    }

    /* bit<32> 的 Register 只有一个数据字段，名字是 "<table>.f1" */
    snprintf(reg_value_full_name, sizeof(reg_value_full_name), "%s.%s",
             reg_name, (value_field_name == NULL) ? "f1" : value_field_name);
    bf_status = bf_rt_data_field_id_get(*reg_table_hdl_ptr, reg_value_full_name,
                                        &reg_info_ptr->did_value);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: 取 '%s' 的数据字段 ID 失败（字段名可能不对）\n",
                reg_value_full_name);
        exit(1);
    }

    printf("寄存器就绪: %s\n", reg_name);
}

/*
 * @brief 从硬件读取指定的寄存器条目
 *
 * [FIX-1] bf_rt_table_entry_get 在 SDE 9.7.1 (BFRT_GENERIC_FLAGS) 里的
 *         签名是 (tbl, session, dev_tgt, flags, key, data)，
 *         原版写的是 (tbl, session, dev_tgt, key, data, read_flag)。
 */
void register_read(const bf_rt_target_t *dev_tgt_ptr,
                   const bf_rt_session_hdl *session_hdl,
                   const bf_rt_table_hdl *reg,
                   register_info_t *reg_info,
                   register_entry_t *reg_entry) {
    bf_status_t bf_status;
    bf_rt_entry_read_flag_e read_flag = ENTRY_READ_FROM_HW;

    /* [FIX-3] key_reset 要 bf_rt_table_key_hdl ** */
    bf_status = bf_rt_table_key_reset(reg, &reg_info->key);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: key_reset 失败\n");
        exit(1);
    }
    /* [FIX-4] data_reset 要 bf_rt_table_data_hdl ** */
    bf_status = bf_rt_table_data_reset(reg, &reg_info->data);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: data_reset 失败\n");
        exit(1);
    }

    bf_status = bf_rt_key_field_set_value(reg_info->key,
                                          reg_info->kid_register_index,
                                          reg_entry->register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: 设置 key 失败 (index: %u)\n",
                reg_entry->register_index);
        exit(1);
    }

    /* [FIX-1] flags 挪到第 4 个参数 */
    bf_status = bf_rt_table_entry_get(reg, session_hdl, dev_tgt_ptr,
                                      (const uint64_t)read_flag,
                                      reg_info->key,
                                      reg_info->data);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: entry_get 失败 (index: %u)\n",
                reg_entry->register_index);
        exit(1);
    }
    bf_status = bf_rt_session_complete_operations(session_hdl);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: complete_operations 失败\n");
        exit(1);
    }

    /*
     * [FIX-5] Tofino2 有 4 个 pipe，每个 pipe 的寄存器副本各一份。
     * 数据面只写自己那个 pipe，所以这里必须把 value_array 求和，
     * 否则只能读到 pipe 0 的 0。
     */
    reg_entry->value_array_size = 0;
    bf_status = bf_rt_data_field_get_value_u64_array_size(
        reg_info->data, reg_info->did_value, &reg_entry->value_array_size);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: 取 value_array_size 失败\n");
        exit(1);
    }

    uint64_t value = 0;
    if (reg_entry->value_array_size > 0) {
        /*
         * bf_rt_data_field_get_value_u64_array 的最后一个参数是**调用方
         * 预分配**的数组（bf_rt_table_data.h:357），不是 uint64_t**。
         * 先按 array_size 分配，再逐项求和。
         */
        uint32_t n = reg_entry->value_array_size;
        uint64_t *values = (uint64_t *)calloc(n, sizeof(uint64_t));
        if (values == NULL) {
            fprintf(stderr, "ERROR: register_read: calloc(%u) 失败\n", n);
            exit(1);
        }
        bf_status = bf_rt_data_field_get_value_u64_array(
            reg_info->data, reg_info->did_value, values);
        if (bf_status != BF_SUCCESS) {
            fprintf(stderr, "ERROR: register_read: 取 value_array 失败 (%d)\n", bf_status);
            free(values);
            exit(1);
        }
        for (uint32_t i = 0; i < n; i++) {
            value += values[i];
        }
        free(values);
        /* 32 位寄存器：求和后要截回 32 位（四个 pipe 的和可能超） */
        value &= UINT32_MASK;
    }
    reg_entry->value = value;
    DBG("[read] reg idx=%u value=%" PRIu64 " (pipes=%u)\n",
        reg_entry->register_index, value, reg_entry->value_array_size);
}

/*
 * @brief 写寄存器条目
 *
 * [FIX-2] bf_rt_table_entry_mod 在 9.7.1 里多了 flags 参数。
 */
void register_write(const bf_rt_target_t *dev_tgt_ptr,
                    const bf_rt_session_hdl *session_hdl,
                    const bf_rt_table_hdl *reg,
                    register_info_t *reg_info,
                    register_entry_t *reg_entry) {
    bf_status_t bf_status;
    const uint64_t flags = 0;

    bf_status = bf_rt_table_key_reset(reg, &reg_info->key);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: key_reset 失败\n");
        exit(1);
    }
    bf_status = bf_rt_table_data_reset(reg, &reg_info->data);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: data_reset 失败\n");
        exit(1);
    }

    bf_status = bf_rt_key_field_set_value(reg_info->key,
                                          reg_info->kid_register_index,
                                          reg_entry->register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: 设置 key 失败 (index: %u)\n",
                reg_entry->register_index);
        exit(1);
    }

    bf_status = bf_rt_data_field_set_value(reg_info->data, reg_info->did_value,
                                           reg_entry->value & UINT32_MASK);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: 设置 value 失败 (index: %u)\n",
                reg_entry->register_index);
        exit(1);
    }

    /* [FIX-2] 新 API 需要 flags */
    bf_status = bf_rt_table_entry_mod(reg, session_hdl, dev_tgt_ptr, flags,
                                      reg_info->key, reg_info->data);
    if (bf_status != BF_SUCCESS) {
        bf_status = bf_rt_table_entry_add(reg, session_hdl, dev_tgt_ptr, flags,
                                          reg_info->key, reg_info->data);
    }
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: entry_mod/add 失败 (index: %u)\n",
                reg_entry->register_index);
        exit(1);
    }

    bf_status = bf_rt_session_complete_operations(session_hdl);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: complete_operations 失败\n");
        exit(1);
    }
}

/* ================ 工具函数 ================ */
static uint64_t get_timestamp_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000 + (uint64_t)ts.tv_nsec / 1000;
}

/* ================ 论文 Algorithm 2：Update ref Rate ================ */
/*
 * 逐行对应 NS3 参考实现
 *   src/point-to-point/model/wan-routing.cc:701
 *   WanRouting::DstDCHandler::update_ref_rate()
 *
 * 单位：所有速率都是 **bytes/s**（NS3 里 ref_rate 也是 bytes/s，
 * 打印时除以 1e9 当 GB/s 用）。RTT 是秒。
 */
static void calculate_reference_rate(dc_stats_t *dc, uint64_t epoch_duration_us) {
    const double epoch_s = (double)epoch_duration_us * 1e-6;
    /*
     * 硬上限 = 物理链路速率（100G 面板口 = 12.5 GB/s）。
     *
     * 原来写的是 LINK_RATE * 1.2，那是把论文的 upperRate 公式
     * （= max(baseRate, realRate*1.2)）误抄成了硬上限。upperRate 的 1.2 是
     * "允许瞬时超发 20%"的软收敛参考值，不是真的能发到 120%。
     * refRate 超过链路速率没有任何物理意义，只会让 refBytes 预算凭空膨胀。
     */
    const double ai_step_guard = GSCC_LINK_RATE_BPS;

    /* wan-routing.cc:705-707  历史不足 3 个 epoch 不更新 */
    if (dc->send_bytes_hist_n < 3) {
        DBG("[DC %u] warmup (%d/3 epochs)\n", dc->dc_id, dc->send_bytes_hist_n);
        return;
    }

    /* wan-routing.cc:708  rateBefore = 最近 3 个 epoch 的平均发送速率 */
    double rate_before = ((double)dc->send_bytes_hist[0] +
                          (double)dc->send_bytes_hist[1] +
                          (double)dc->send_bytes_hist[2]) / 3.0 / epoch_s;

    /* wan-routing.cc:710-711  upperRate = max(baseRate, realRate * 1.2) */
    double upper_rate = fmax(dc->guaranteed_rate, rate_before * 1.2);
    int flag = (dc->ref_rate > upper_rate);
    double pre_ref_rate = dc->ref_rate;

    /* wan-routing.cc:717-719  saturated = (realRate + 3GB/s >= refRate) */
    int saturated = (rate_before + GSCC_SATURATION_SLACK) >= pre_ref_rate;

    /* wan-routing.cc:721-728  本 epoch 没有 RTT 样本：只做上限衰减后返回 */
    if (dc->rtt_count == 0) {
        dc->rtt_miss_counter++;
        if (dc->ref_rate > upper_rate) {
            dc->ref_rate = upper_rate + (dc->ref_rate - upper_rate) * 0.8;
        }
        DBG("[DC %u] RTT miss #%u, refRate -> %.3f GB/s\n", dc->dc_id,
            dc->rtt_miss_counter, dc->ref_rate / 1e9);
        return;
    }
    dc->rtt_miss_counter = 0;

    /* wan-routing.cc:733-742  curRTT 与 baseRTT
     *   论文的 baseRTT 是"一个长时间窗口内的最小延迟"，
     *   所以这里用历史最小值（单调不增），和 NS3 的 min_element 等价。 */
    dc->cur_rtt_s = ((double)dc->rtt_sum_ns / (double)dc->rtt_count) * 1e-9;
    if (dc->min_rtt_s <= 0.0 || dc->cur_rtt_s < dc->min_rtt_s) {
        dc->min_rtt_s = dc->cur_rtt_s;
    }

    /* wan-routing.cc:746  epochsPerRTT = baseRTT / epochDur
     *
     * 偏差说明（数值保护，不改变算法）：
     *   原式在 baseRTT < epochDur 时会退化成 < 1，把 step 放大成天文数字
     *   （本实验床 baseRTT ≈ 1.4 us、epoch ≈ 7 ms，比值 2e-4）。
     *   论文的物理含义是"速率只在一个 RTT 的时间尺度上缓慢变化"，
     *   因此 epochsPerRTT 不可能小于 1 —— 那意味着一个 epoch 比一个 RTT
     *   还长，此时"每 RTT 一次更新"退化成"每 epoch 一次更新"。 */
    double epochs_per_rtt = dc->min_rtt_s / epoch_s;
    if (epochs_per_rtt < 1.0) {
        epochs_per_rtt = 1.0;
    }

    /* wan-routing.cc:754-766  权重 w（加权公平性，默认恒为 1） */
    double w = 1.0;
    if (GSCC_ENABLE_W) {
        w = GSCC_W_MAX;
        if (w < 1.0) w = 1.0;
        if (w > GSCC_W_MAX) w = GSCC_W_MAX;
    }

    /* wan-routing.cc:769-772  targetRate = w / (delta * queueDelay) */
    const double delta = 1.0 / GSCC_INV_DELTA;
    double queue_delay = dc->cur_rtt_s - dc->min_rtt_s;
    if (queue_delay < GSCC_QUEUE_DELAY_FLOOR) {
        queue_delay = GSCC_QUEUE_DELAY_FLOOR;
    }
    double target_rate = w / delta / queue_delay;

    /* wan-routing.cc:773-787  方向状态机，用来决定 v */
    int target_state = (target_rate > pre_ref_rate) ? RATE_INCREASE : RATE_DECREASE;
    if (dc->rate_change_state == target_state) {
        if (target_state == RATE_INCREASE && !saturated) {
            /* 没饱和的"想增"不算连续，避免 v 被拉高 */
            if (dc->consecutive_state_epochs > 1) {
                dc->consecutive_state_epochs--;
            } else {
                dc->consecutive_state_epochs = 1;
            }
        } else {
            dc->consecutive_state_epochs++;
        }
    } else {
        dc->rate_change_state = target_state;
        dc->consecutive_state_epochs = 1;
    }

    /* wan-routing.cc:790-796  v ∈ {1, 2, 4} */
    int v = 1;
    if (GSCC_ENABLE_V) {
        if ((double)dc->consecutive_state_epochs >= 10.0 * epochs_per_rtt) {
            v = 4;
        } else if ((double)dc->consecutive_state_epochs >= 5.0 * epochs_per_rtt) {
            v = 2;
        }
    }

    /* wan-routing.cc:798  step = w*v / (delta * epochsPerRTT * baseRTT) */
    double step = w * (double)v / (delta * epochs_per_rtt * dc->min_rtt_s);
    const char *why = "?";

    /*
     * [FIX-15] 单 epoch 步长上限（数值保护）。
     *
     * 论文的 step 公式里带 1/baseRTT，是给 WAN 量级 RTT（几十 ms）标定的。
     * 本实验床 baseRTT ≈ 1.5 us，比 WAN 小 4 个数量级，step 会算出
     * 1e13 B/s 这种值 —— 一个 epoch 就把 refRate 顶到链路速率上限，
     * 之后 refRate 恒 > realRate，bytesDiff 永远为负，CNP 一个都发不出来。
     *
     * 这里限制"每 epoch 最多翻倍"，让 refRate 用几个 epoch 爬到链路速率。
     * 只在 step 远大于 refRate 时生效（即 baseRTT ≪ epoch 的退化区间），
     * 在论文的设计区间（baseRTT ≫ epoch）里不会触发。
     */
    if (step > dc->ref_rate) {
        step = dc->ref_rate;
    }

    if (target_state == RATE_INCREASE) {
        /* 论文 line 5-6：加性增长 */
        dc->ref_rate += step;
        why = "AI";
    } else {
        /* 论文 line 8-10：beta^e 快速下降 */
        double gamma = pow(1.0 - GSCC_BETA, 1.0 / epochs_per_rtt);
        double min_step = ceil(pre_ref_rate * (1.0 - gamma));
        double origin_step = step;
        if (min_step > step) step = min_step;
        if (step > pre_ref_rate) step = pre_ref_rate; /* 防止变负 */
        dc->ref_rate -= step;
        why = (step > origin_step) ? "fastMD" : "linMD";
    }

    /* 论文 line 12-14：refRate 向 upperRate 收缩 */
    if (flag && dc->ref_rate > upper_rate) {
        dc->ref_rate = upper_rate + (dc->ref_rate - upper_rate) * 0.8;
    }

    /* 硬上限（数值保护）：refRate 是"参考发送速率"，不可能超过物理链路
     * 速率。原实现只靠上面 20% 的软收敛，在微秒级 RTT 的实验床上会被
     * step 推到 1e16 量级、再花二十多轮才收回来，期间 refBytes 直接溢出。 */
    if (dc->ref_rate > ai_step_guard) {
        dc->ref_rate = ai_step_guard;
    }

    /* 原版 ctrl.c 的下限 */
    if (dc->ref_rate < GSCC_RATE_FLOOR) {
        dc->ref_rate = GSCC_RATE_FLOOR;
    }

    DBG("[DC %u] %-6s v=%d curRTT=%.3f us baseRTT=%.3f us qDelay=%.3f us "
        "target=%.3f GB/s step=%.3f GB/s consec=%u -> refRate=%.3f GB/s\n",
        dc->dc_id, why, v, dc->cur_rtt_s * 1e6, dc->min_rtt_s * 1e6,
        queue_delay * 1e6, target_rate / 1e9, step / 1e9,
        dc->consecutive_state_epochs, dc->ref_rate / 1e9);
}

/* ================ 论文 Algorithm 2 之后：refBytes 累加 ================ */
/*
 * [FIX-14] 空闲 epoch 不累积预算。
 *
 * 论文 line 1-2 的 bytesDiff = realBytes - refBytes 是"实际转发量"和
 * "按 refRate 应该转发多少"的差。refRate 的物理含义是**允许的发送速率**，
 * 只有在真有流量时才消耗这个预算。
 *
 * 原版 ctrl.c 无条件累加：控制面先起来空转 60 秒，refBytes 就跑到
 * realBytes 前面 1.9e9 字节；之后即使满速打流，bytesDiff 也要好几秒
 * 才能转正，这段时间 CNP 一个都发不出来（实测 cnp_count = 0）。
 *
 * 空闲时不累积，等价于"预算只在有流量时消耗"，这不改变算法，
 * 只是把论文的隐式前提写明确。
 */
static void update_reference_bytes(dc_stats_t *dc, uint64_t epoch_duration_us,
                                   uint32_t bytes_sent) {
    if (bytes_sent == 0) {
        return; /* 本 epoch 没有任何 RoCE 流量，预算不累积 */
    }
    double add = dc->ref_rate * (double)epoch_duration_us * 1e-6;
    dc->ref_bytes = (uint32_t)(((uint64_t)dc->ref_bytes +
                                (uint64_t)add) & UINT32_MASK);
}

/* ================ P4 寄存器读写 ================ */
static void read_rtt_stats_from_p4(uint32_t dc_id, uint32_t *rtt_sum,
                                   uint32_t *rtt_count) {
    register_entry_t sum_entry = { .register_index = dc_id };
    register_entry_t count_entry = { .register_index = dc_id };
    register_read(dev_tgt, session, rtt_sum_reg_table, &rtt_sum_reg_info, &sum_entry);
    register_read(dev_tgt, session, rtt_count_reg_table, &rtt_count_reg_info, &count_entry);
    *rtt_sum = (uint32_t)sum_entry.value;
    *rtt_count = (uint32_t)count_entry.value;
}

static void write_ref_bytes_to_p4(uint32_t dc_id, uint32_t ref_bytes) {
    register_entry_t entry = { .register_index = dc_id, .value = (uint64_t)ref_bytes };
    register_write(dev_tgt, session, ref_bytes_reg_table, &ref_bytes_reg_info, &entry);
}

static void read_real_bytes_from_p4(uint32_t dc_id, uint32_t *real_bytes) {
    register_entry_t entry = { .register_index = dc_id };
    register_read(dev_tgt, session, real_bytes_reg_table, &real_bytes_reg_info, &entry);
    *real_bytes = (uint32_t)entry.value;
}

static void read_pkt_count_from_p4(uint32_t dc_id, uint32_t *pkt_count) {
    register_entry_t entry = { .register_index = dc_id };
    register_read(dev_tgt, session, pkt_count_reg_table, &pkt_count_reg_info, &entry);
    *pkt_count = (uint32_t)entry.value;
}

/* [ACK-COALESCING] generic single-index register read (C direct HW, sum 4 pipes) */
static uint32_t read_reg_idx(const bf_rt_table_hdl *tbl, register_info_t *info,
                             uint32_t idx) {
    register_entry_t e = { .register_index = idx };
    register_read(dev_tgt, session, tbl, info, &e);
    return (uint32_t)e.value;
}

/* [ACK-COALESCING] read one (pipe, index) — per-pipe, NOT summed across replicas.
 * Needed because per-slot VALUE registers must not be summed across the 4 pipe copies. */
static uint32_t read_reg_idx_pipe(const bf_rt_table_hdl *tbl, register_info_t *info,
                                  uint32_t idx, uint32_t pipe) {
    bf_rt_target_t t = *dev_tgt;
    t.pipe_id = (bf_dev_pipe_t)pipe;
    register_entry_t e = { .register_index = idx };
    register_read(&t, session, tbl, info, &e);
    return (uint32_t)e.value;
}

static void reset_rtt_registers_for_dc(uint32_t dc_id) {
    register_entry_t entry = { .register_index = dc_id, .value = 0 };
    register_write(dev_tgt, session, rtt_sum_reg_table, &rtt_sum_reg_info, &entry);
    register_write(dev_tgt, session, rtt_count_reg_table, &rtt_count_reg_info, &entry);
}

/* ================ 核心控制逻辑 ================ */
static void process_dc_control(uint32_t dc_id, uint64_t current_time_us) {
    dc_stats_t *dc = &dc_stats[dc_id];

    uint64_t epoch_duration_us = current_time_us - dc->last_update_time_us;
    if (epoch_duration_us == 0) {
        epoch_duration_us = GSCC_EPOCH_DURATION_US;
    }

    /* --- 步骤 1: 从 P4 读取本 epoch 的 RTT 统计 --- */
    uint32_t rtt_sum, rtt_count;
    read_rtt_stats_from_p4(dc_id, &rtt_sum, &rtt_count);
    dc->rtt_sum_ns = rtt_sum;
    dc->rtt_count = rtt_count;

    /* --- 步骤 3: 清零 P4 里的 RTT 累加器（per-epoch 语义）--- */
    reset_rtt_registers_for_dc(dc_id);

    /* --- 步骤 4: 读取实际发送字节数（累计量）--- */
    uint32_t current_real_bytes;
    read_real_bytes_from_p4(dc_id, &current_real_bytes);

    /* --- 步骤 5: 计算实际速率 --- */
    uint32_t bytes_sent = current_real_bytes - dc->last_real_bytes; /* 32 位回绕 */
    dc->last_real_bytes = current_real_bytes;
    dc->real_rate = (double)bytes_sent * 1e6 / (double)epoch_duration_us;

    /* 维护最近 3 个 epoch 的历史（wan-routing.cc 的 send_bytes_history） */
    dc->send_bytes_hist[0] = dc->send_bytes_hist[1];
    dc->send_bytes_hist[1] = dc->send_bytes_hist[2];
    dc->send_bytes_hist[2] = bytes_sent;
    if (dc->send_bytes_hist_n < 3) {
        dc->send_bytes_hist_n++;
    }

    /* --- 步骤 6-7: 论文 Algorithm 2 --- */
    calculate_reference_rate(dc, epoch_duration_us);
    update_reference_bytes(dc, epoch_duration_us, bytes_sent);

    /* --- 步骤 8: 把 refBytes 写回 P4 --- */
    write_ref_bytes_to_p4(dc_id, dc->ref_bytes);

    /*
     * --- 步骤 9: 观测 ACK 聚合 ---
     *
     * gs_pkt_count_reg 是数据面所有 RoCE 包（数据 + ACK）的累计计数，
     * gs_rtt_count_reg 的每轮增量是"匹配上 outstanding ackreq 的 ACK"
     * 个数。两者相除就是本轮的 ACK 聚合率。
     *
     * 注意 rtt_count 在步骤 3 已经被清零了，所以这里用的是本函数开头
     * 读到的值（dc->rtt_count），不是再次读硬件。
     */
    uint32_t pkt_now = 0;
    read_pkt_count_from_p4(dc_id, &pkt_now);
    uint32_t pkt_delta = pkt_now - dc->last_pkt_count;
    dc->last_pkt_count = pkt_now;

    dc->last_update_time_us = current_time_us;

    /*
     * ACK 聚合观测：
     *   data_pkts  本 epoch 的数据包（由字节数反推）
     *   ack_pkts   本 epoch 的 ACK 包
     *   coalesce   每个 ACK 合了几个数据包（越大说明聚合越狠）
     *   match      ACK 中能在 gs_rtt_timestamp_reg 找到时间戳的比例
     *              = GRC 的 ackreq 匹配率，RTT 采样的有效率
     */
    uint32_t data_pkts = (uint32_t)(bytes_sent / GSCC_PKT_WIRE_BYTES);
    uint32_t ack_pkts = (pkt_delta > data_pkts) ? (pkt_delta - data_pkts) : 0;
    double coalesce = (ack_pkts > 0) ? (double)data_pkts / (double)ack_pkts : 0.0;
    double match_pct = (ack_pkts > 0)
                           ? (100.0 * (double)dc->rtt_count / (double)ack_pkts)
                           : 0.0;

    dc->total_ackmatch += dc->rtt_count;
    dc->total_ack_pkts += ack_pkts;
    dc->total_data_pkts += data_pkts;

    /* [FIX-16] 只在关键量变化时输出，否则累加 suppressed */
    uint32_t cur_realr = (uint32_t)(dc->real_rate / 1e6);
    uint32_t cur_refr = (uint32_t)(dc->ref_rate / 1e6);
    uint32_t cur_rtt = (uint32_t)(dc->cur_rtt_s * 1e7);
    if (cur_realr == g_last_print_realr && cur_refr == g_last_print_refr &&
        cur_rtt == g_last_print_rtt) {
        g_suppressed_lines++;
        return;
    }
    char sup[32] = "";
    if (g_suppressed_lines > 0) {
        snprintf(sup, sizeof(sup), " (+%u same)", g_suppressed_lines);
    }
    g_suppressed_lines = 0;
    g_last_print_realr = cur_realr;
    g_last_print_refr = cur_refr;
    g_last_print_rtt = cur_rtt;

    printf("[epoch] dc=%u rtt=%7.2f us base=%7.2f us realR=%9.2f MB/s "
           "refR=%9.2f MB/s refBytes=%u | pkt=%u ack=%u coalesce=%5.1fx "
           "match=%5.1f%%%s\n",
           dc_id, dc->cur_rtt_s * 1e6, dc->min_rtt_s * 1e6,
           dc->real_rate / 1e6, dc->ref_rate / 1e6, dc->ref_bytes,
           pkt_delta, ack_pkts, coalesce, match_pct, sup);
}

/* ================ 控制线程主函数 ================ */
static void* control_loop(void* arg) {
    (void)arg;
    printf("GSCC 控制环启动 (epoch = %d us)\n", GSCC_EPOCH_DURATION_US);
    while (control_running) {
        uint64_t start_time = get_timestamp_us();
        pthread_mutex_lock(&stats_mutex);
        for (uint32_t dc_id = 0; dc_id < MAX_DC_COUNT; dc_id++) {
            if ((g_active_dc_mask & (1u << dc_id)) != 0) {
                process_dc_control(dc_id, start_time);
            }
        }
        pthread_mutex_unlock(&stats_mutex);

        uint64_t elapsed_us = get_timestamp_us() - start_time;
        if (elapsed_us < GSCC_EPOCH_DURATION_US) {
            usleep(GSCC_EPOCH_DURATION_US - elapsed_us);
        }
    }
    printf("GSCC 控制环停止\n");
    return NULL;
}

/* ================ P4 表设置函数 ================ */
static bf_status_t setup_p4_register_tables(void) {
    const char *data_field_name = "f1";
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_sum_reg", data_field_name,
                   &rtt_sum_reg_table, &rtt_sum_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_count_reg", data_field_name,
                   &rtt_count_reg_table, &rtt_count_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_real_bytes_reg", data_field_name,
                   &real_bytes_reg_table, &real_bytes_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_ref_bytes_reg", data_field_name,
                   &ref_bytes_reg_table, &ref_bytes_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_pkt_count_reg", data_field_name,
                   &pkt_count_reg_table, &pkt_count_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_ackreq_cnt_reg", data_field_name,
                   &ackreq_cnt_reg_table, &ackreq_cnt_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_ack_total_reg", data_field_name,
                   &ack_total_reg_table, &ack_total_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_ok_cnt_reg", data_field_name,
                   &rtt_ok_cnt_reg_table, &rtt_ok_cnt_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_fail_zero_reg", data_field_name,
                   &rtt_fail_zero_reg_table, &rtt_fail_zero_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_fail_psn_reg", data_field_name,
                   &rtt_fail_psn_reg_table, &rtt_fail_psn_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_khist_reg", data_field_name,
                   &khist_reg_table, &khist_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_psn_now_reg", data_field_name,
                   &psn_now_reg_table, &psn_now_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_storedid_reg", data_field_name,
                   &storedid_reg_table, &storedid_reg_info);
    printf("P4 寄存器表全部就绪\n");
    return BF_SUCCESS;
}

/* ================ 公共接口函数 ================ */
bf_status_t gscc_control_init(bf_rt_target_t *target,
                              const bf_rt_info_hdl *info,
                              bf_rt_session_hdl *sess) {
    dev_tgt = target;
    bfrt_info = info;
    session = sess;
    memset(dc_stats, 0, sizeof(dc_stats));

    for (int i = 0; i < MAX_DC_COUNT; i++) {
        dc_stats[i].dc_id = i;
        dc_stats[i].guaranteed_rate = GSCC_LINK_RATE_BPS * GSCC_GUARANTEED_RATE_FACTOR;
        dc_stats[i].ref_rate = dc_stats[i].guaranteed_rate;
        dc_stats[i].rate_change_state = 0;
    }

    bf_status_t status = setup_p4_register_tables();
    if (status != BF_SUCCESS) {
        fprintf(stderr, "P4 寄存器表设置失败\n");
        return status;
    }

    if (rtt_sum_reg_table == NULL || rtt_count_reg_table == NULL ||
        real_bytes_reg_table == NULL || ref_bytes_reg_table == NULL) {
        fprintf(stderr, "ERROR: 有寄存器表句柄是 NULL，P4 程序和 ctrl 不匹配\n");
        return BF_UNEXPECTED;
    }

    /*
     * [FIX-10] 启动对齐
     *
     * 原版从 0 开始累加 ref_bytes。如果控制面先空转一段（比如先起控制面
     * 再打流），refBytes 会跑到 realBytes 前面，之后
     * bytesDiff = realBytes - refBytes 长时间为负，CNP 一个也发不出来。
     * 这里做一次对齐，保证 bytesDiff 从 0 起步。
     */
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        if ((g_active_dc_mask & (1u << i)) == 0) {
            continue;
        }
        uint32_t real_now = 0;
        read_real_bytes_from_p4((uint32_t)i, &real_now);
        dc_stats[i].ref_bytes = real_now;
        dc_stats[i].last_real_bytes = real_now;
        {
            uint32_t pkt_now = 0;
            read_pkt_count_from_p4((uint32_t)i, &pkt_now);
            dc_stats[i].last_pkt_count = pkt_now;
        }
        /* 清掉上一轮残留的 RTT 累加器 */
        reset_rtt_registers_for_dc((uint32_t)i);
        if (real_now != 0) {
            printf("dc=%d 对齐: realBytes = refBytes = %u\n", i, real_now);
        }
    }

    printf("GSCC 控制面初始化完成\n");
    return BF_SUCCESS;
}

bf_status_t gscc_control_start(void) {
    if (control_running) {
        printf("GSCC 控制面已经在跑了\n");
        return BF_ALREADY_EXISTS;
    }
    control_running = 1;
    uint64_t current_time = get_timestamp_us();
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        if ((g_active_dc_mask & (1u << i)) != 0) {
            dc_stats[i].last_update_time_us = current_time;
        }
    }
    if (pthread_create(&control_thread, NULL, control_loop, NULL) != 0) {
        control_running = 0;
        perror("创建控制线程失败");
        return BF_NO_SYS_RESOURCES;
    }
    printf("GSCC 控制面启动成功\n");
    return BF_SUCCESS;
}

bf_status_t gscc_control_stop(void) {
    if (!control_running) {
        printf("GSCC 控制面没在跑\n");
        return BF_INVALID_ARG;
    }
    control_running = 0;
    pthread_join(control_thread, NULL);
    printf("GSCC 控制面停止成功\n");
    return BF_SUCCESS;
}

bf_status_t gscc_get_dc_stats(uint32_t dc_id, dc_stats_t *stats_out) {
    if (dc_id >= MAX_DC_COUNT || stats_out == NULL) {
        return BF_INVALID_ARG;
    }
    pthread_mutex_lock(&stats_mutex);
    memcpy(stats_out, &dc_stats[dc_id], sizeof(dc_stats_t));
    pthread_mutex_unlock(&stats_mutex);
    return BF_SUCCESS;
}

bf_status_t gscc_set_dc_rate(uint32_t dc_id, uint32_t rate_bps) {
    if (dc_id >= MAX_DC_COUNT) {
        return BF_INVALID_ARG;
    }
    pthread_mutex_lock(&stats_mutex);
    dc_stats[dc_id].ref_rate = (double)rate_bps;
    pthread_mutex_unlock(&stats_mutex);
    printf("DC %u 参考速率设为 %u B/s\n", dc_id, rate_bps);
    return BF_SUCCESS;
}

void gscc_print_status(void) {
    printf("\n========== GSCC 控制面状态 ==========\n");
    printf("运行中: %s\n", control_running ? "是" : "否");
    printf("epoch: %d us\n", GSCC_EPOCH_DURATION_US);
    pthread_mutex_lock(&stats_mutex);
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        dc_stats_t *dc = &dc_stats[i];
        if (dc->last_update_time_us > 0 && (dc->real_rate > 0.0 || dc->ref_rate > 0.0)) {
            printf("\n--- DC %d ---\n", i);
            printf("  RTT : cur=%.2f us  base=%.2f us  miss=%u\n",
                   dc->cur_rtt_s * 1e6, dc->min_rtt_s * 1e6, dc->rtt_miss_counter);
            printf("  速率: real=%.2f MB/s  ref=%.2f MB/s\n",
                   dc->real_rate / 1e6, dc->ref_rate / 1e6);
            printf("  字节: refBytes=%u  lastRealBytes=%u\n",
                   dc->ref_bytes, dc->last_real_bytes);
            if (dc->total_ack_pkts > 0) {
                printf("  ACK : 数据包=%" PRIu64 "  ACK包=%" PRIu64
                       "  聚合=%.1fx  匹配=%.1f%%\n",
                       dc->total_data_pkts, dc->total_ack_pkts,
                       (double)dc->total_data_pkts / (double)dc->total_ack_pkts,
                       100.0 * (double)dc->total_ackmatch /
                           (double)dc->total_ack_pkts);
            }
            printf("  状态: %s  连续=%u\n",
                   dc->rate_change_state == RATE_INCREASE ? "AI" : "MD",
                   dc->consecutive_state_epochs);
        }
    }
    pthread_mutex_unlock(&stats_mutex);
    printf("======================================\n");
    /* ===== [ACK-COALESCING] C reads HW directly: K histogram + RTT subcounters ===== */
    {
        uint32_t ackreq = read_reg_idx(ackreq_cnt_reg_table, &ackreq_cnt_reg_info, 0);
        uint32_t ackall = read_reg_idx(ack_total_reg_table, &ack_total_reg_info, 0);
        uint32_t ok     = read_reg_idx(rtt_ok_cnt_reg_table, &rtt_ok_cnt_reg_info, 0);
        uint32_t fz     = read_reg_idx(rtt_fail_zero_reg_table, &rtt_fail_zero_reg_info, 0);
        uint32_t fp     = read_reg_idx(rtt_fail_psn_reg_table, &rtt_fail_psn_reg_info, 0);
        printf("\n----- K-HIST(C-HW dc0): ack_req=%u ack_total=%u | rtt_ok=%u fail_zero=%u fail_psn=%u -----\n",
               ackreq, ackall, ok, fz, fp);
        uint64_t tot = 0; int nb = 0;
        for (uint32_t k = 0; k < 64; k++) {
            uint32_t v = read_reg_idx(khist_reg_table, &khist_reg_info, k);
            if (v) { printf("  K=%-2u : %u\n", k, v); tot += v; nb++; }
        }
        printf("  K total samples=%" PRIu64 "  nonempty bins=%d\n", tot, nb);
    }
    /* ===== [ACK-COALESCING] C reads HW: offset = ACK.PSN - matched ackreq PSN, bucketed histogram ===== */
    {
        uint32_t bins[15]; for (int i=0;i<15;i++) bins[i]=0;
        uint32_t nz=0, posc=0, negc=0, adjc=0, farc=0; int32_t mn=0, mx=0; double sm=0.0;
        /* pass1: find non-empty slot indices via the (summed) read */
        static uint32_t cand[4096]; int nc=0;
        for (uint32_t idx=0; idx<4096u; idx++) {
            uint32_t s1 = read_reg_idx(psn_now_reg_table, &psn_now_reg_info, idx);
            uint32_t s2 = read_reg_idx(storedid_reg_table, &storedid_reg_info, idx);
            if (s1||s2) cand[nc++]=(uint32_t)idx;
        }
        /* pass2: read both registers per-pipe (no cross-replica sum) */
        for (uint32_t pp=0; pp<4u; pp++) {
            for (int ci=0; ci<nc; ci++) {
                uint32_t idx=cand[ci];
                uint32_t psn = read_reg_idx_pipe(psn_now_reg_table,&psn_now_reg_info,idx,pp);
                uint32_t st  = read_reg_idx_pipe(storedid_reg_table,&storedid_reg_info,idx,pp);
                if (psn==0u && st==0u) continue;
                int32_t d = (int32_t)psn - (int32_t)st;
                if (d==0) continue;
                nz++; sm += d; if(d>mx)mx=d; if(d<mn)mn=d;
                uint32_t mag = (d<0)? (uint32_t)(-(int64_t)d) : (uint32_t)d;
                if (d<0) negc++; else posc++;
                if (mag <= 256u) adjc++; else farc++;
                if (ci<18) { const char* ppc=(psn>st)?"ahead":"behind"; (void)ppc; printf("    raw pp=%u slot=%u psn=%u stored=%u d=%d\n", pp, idx, psn, st, d); }
                int bb;
                if (mag<8u) bb=0; else if(mag<16u) bb=1; else if(mag<32u) bb=2;
                else if(mag<64u) bb=3; else if(mag<128u) bb=4; else if(mag<256u) bb=5;
                else if(mag<512u) bb=6; else if(mag<1024u) bb=7; else if(mag<2048u) bb=8;
                else if(mag<4096u) bb=9; else if(mag<8192u) bb=10; else if(mag<16384u) bb=11;
                else if(mag<32768u) bb=12; else if(mag<65536u) bb=13; else bb=14;
                bins[bb]++;
            }
        }
        printf("\n----- OFF-HIST(C-HW dc0): fail-slot samples=%u pos=%u neg=%u mean=%.2f min=%d max=%d cand_slots=%d -----\n",
               nz, posc, negc, nz?(sm/(double)nz):0.0, nz?mn:0, nz?mx:0, nc);
        printf("  off-class: adj(|d|<=256)=%u  far(|d|>256)=%u\n", adjc, farc);
        const char *lbl[15]={"|d|0-7","|d|8-15","|d|16-31","|d|32-63","|d|64-127","|d|128-255","|d|256-511","|d|512-1k","|d|1k-2k","|d|2k-4k","|d|4k-8k","|d|8k-16k","|d|16k-32k","|d|32k-64k","|d|>=64k"};
        for (int bb=0;bb<15;bb++) if (bins[bb]) printf("  off %-10s : %u\n", lbl[bb], bins[bb]);
    }
}

/* ================ [FIX-13] 端口 bring-up ================ */
/*
 * bf_switchd 的板级自动 port-add 用的是平台默认的速度/FEC，
 * 我们的 100G 面板口（dev_port 392 / 400，都在 pipe 3）需要
 * 100G + RS FEC 才能起来。
 *
 * 端口列表用环境变量 GSCC_PORTS 覆盖，默认 "392,400"。
 */
static void port_setup(void) {
    const char *env = getenv("GSCC_PORTS");
    const char *ports_str = (env != NULL && env[0] != '\0') ? env : "392,400";
    char *dup = strdup(ports_str);
    char *tok = strtok(dup, ",");

    while (tok != NULL) {
        long dp = strtol(tok, NULL, 10);
        if (dp <= 0) {
            tok = strtok(NULL, ",");
            continue;
        }
        bf_status_t sts = bf_pal_port_add(dev_tgt->dev_id, (bf_dev_port_t)dp,
                                          BF_SPEED_100G,
                                          BF_FEC_TYP_REED_SOLOMON);
        if (sts != BF_SUCCESS) {
            fprintf(stderr, "WARN: port_add %ld 失败 (%d)\n", dp, sts);
        } else {
            printf("port_add %ld = 100G RS 成功\n", dp);
        }
        sts = bf_pal_port_enable(dev_tgt->dev_id, (bf_dev_port_t)dp);
        if (sts != BF_SUCCESS && sts != BF_ALREADY_EXISTS) {
            fprintf(stderr, "WARN: port_enable %ld 失败 (%d)\n", dp, sts);
        } else {
            printf("port_enable %ld 成功\n", dp);
        }
        tok = strtok(NULL, ",");
    }
    free(dup);
}

/* ================ [FIX-9] CNP mirror session ================ */
/*
 * 论文 Algorithm 3 的 sendCNP() 在数据面是
 *     gs_mirror.emit<gs_mirror_h>(gs_meta.gs_ing_mir_ses, {gs_meta.gs_pkt_type});
 * 这条语句要求 mirror session 已经被创建，否则是空操作。
 *
 * 这里用 pipe_mgr 的 Tofino2 通用接口（pipe_mgr_mirror_intf.h），
 * 不用原版 baseline 里的 tofino/pdfixed 的 p4_pd_mirror_session_create
 * ——那是 Tofino1 专用的，Tofino2 上根本没有这个头文件。
 */
static void configure_cnp_mirror(uint16_t session_id, uint32_t egress_dev_port,
                                  uint16_t max_pkt_len) {
    pipe_sess_hdl_t pipe_sess;
    pipe_status_t sts = pipe_mgr_client_init(&pipe_sess);
    if (sts != PIPE_SUCCESS) {
        fprintf(stderr, "WARN: pipe_mgr_client_init 失败 (%d)，跳过 mirror 配置\n", sts);
        return;
    }

    dev_target_t dev_target = {0};
    dev_target.device_id = dev_tgt->dev_id;
    dev_target.dev_pipe_id = BF_DEV_PIPE_ALL;

    bf_mirror_session_info_t s_info;
    memset(&s_info, 0, sizeof(s_info));
    s_info.mirror_type = BF_MIRROR_TYPE_NORM;
    s_info.dir = BF_DIR_INGRESS;
    s_info.ucast_egress_port = egress_dev_port;
    s_info.ucast_egress_port_v = true;
    s_info.egress_port_queue = 0;
    s_info.ingress_cos = 0;
    s_info.packet_color = 0;
    s_info.max_pkt_len = max_pkt_len;

    sts = bf_mirror_session_set(pipe_sess, dev_target, session_id, &s_info, true);
    if (sts != PIPE_SUCCESS) {
        fprintf(stderr, "WARN: bf_mirror_session_set 失败 (%d)，CNP 发不出去\n", sts);
        pipe_mgr_client_cleanup(&pipe_sess);
        return;
    }

    printf("CNP mirror session %u 已配置 -> dev_port %u (max %u B)\n",
           session_id, egress_dev_port, max_pkt_len);
    pipe_mgr_client_cleanup(&pipe_sess);
}

/* ================ 驱动初始化 ================ */
/*
 * [FIX-6] 不再硬编码 tofino1。
 *
 * 原版：
 *   snprintf(conf_file, ..., "%s/share/p4/targets/tofino/%s.conf", ...)
 * 这个路径在 Tofino2 的 SDE 里不存在（只有 tofino2/）。
 *
 * 现在按优先级：
 *   1) 环境变量 GSCC_CONF 指向的绝对路径
 *   2) $SDE_INSTALL/share/p4/targets/tofino2/<prog>.conf
 */
static void switchd_setup(bf_switchd_context_t *ctx, const char *prog) {
    bf_status_t bf_status;
    char conf_file[512];
    const char *env_conf = getenv("GSCC_CONF");
    const char *install_dir = getenv("SDE_INSTALL");

    if (install_dir == NULL) {
        fprintf(stderr, "ERROR: 环境变量 SDE_INSTALL 没设\n");
        exit(1);
    }

    if (env_conf != NULL && env_conf[0] != '\0') {
        snprintf(conf_file, sizeof(conf_file), "%s", env_conf);
    } else {
        /* Tofino2 的 targets 目录是 tofino2，不是 tofino */
        snprintf(conf_file, sizeof(conf_file),
                 "%s/share/p4/targets/tofino2/%s.conf", install_dir, prog);
    }

    if (access(conf_file, R_OK) != 0) {
        fprintf(stderr, "ERROR: conf 文件不可读: %s (%s)\n"
                        "  用 GSCC_CONF=/path/to/gscc.conf 指定\n",
                conf_file, strerror(errno));
        exit(1);
    }

    printf("conf 文件: %s\n", conf_file);
    ctx->install_dir = strdup(install_dir);
    ctx->conf_file = strdup(conf_file);
    ctx->running_in_background = true;
    ctx->dev_sts_thread = true;
    ctx->dev_sts_port = 7777;

    bf_status = bf_switchd_lib_init(ctx);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: bf_switchd_lib_init 失败 (%d)\n", bf_status);
        exit(1);
    }
    printf("bf_switchd 初始化成功\n");
}

static void bfrt_setup(bf_rt_target_t *dev_tgt_ptr,
                        const bf_rt_info_hdl **bfrt_info_hdl,
                        const char *prog,
                        bf_rt_session_hdl **session_hdl_ptr) {
    bf_status_t bf_status = BF_UNEXPECTED;
    int retry_cnt = 10;

    while (retry_cnt-- > 0) {
        bf_status = bf_rt_info_get(dev_tgt_ptr->dev_id, prog, bfrt_info_hdl);
        if (bf_status == BF_SUCCESS) break;
        bf_status = bf_rt_info_get(dev_tgt_ptr->dev_id, "gs_pipe", bfrt_info_hdl);
        if (bf_status == BF_SUCCESS) break;
        fprintf(stderr, "WARN: bf_rt_info_get 失败（还剩 %d 次），等 pipeline 就绪...\n",
                retry_cnt);
        sleep(1);
    }
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: 重试后仍然拿不到 bf_rt_info (dev=%d, prog=%s)\n",
                dev_tgt_ptr->dev_id, prog ? prog : "<NULL>");
        exit(1);
    }

    bf_status = bf_rt_session_create(session_hdl_ptr);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: bf_rt_session_create 失败\n");
        exit(1);
    }
    printf("bfrt_info + session 就绪\n");
}

static void on_signal(int signum) {
    (void)signum;
    control_running = 0;
}

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;

    setvbuf(stdout, NULL, _IOLBF, 0);   /* 重定向到文件时也按行刷 */
    setvbuf(stderr, NULL, _IOLBF, 0);

    if (getenv("GSCC_DEBUG") != NULL) {
        g_debug = 1;
    }

    /* [FIX-12] 只控制真正在用的 dst-DC，默认 0（= P4 里的 GS_ACTIVE_DC_ID） */
    {
        const char *dc_env = getenv("GSCC_DC_IDS");
        if (dc_env != NULL && dc_env[0] != '\0') {
            char *dup = strdup(dc_env);
            char *tok = strtok(dup, ",");
            g_active_dc_mask = 0;
            while (tok != NULL) {
                long v = strtol(tok, NULL, 10);
                if (v >= 0 && v < MAX_DC_COUNT) {
                    g_active_dc_mask |= (1u << v);
                } else {
                    fprintf(stderr, "WARN: 忽略非法 DC id '%s'\n", tok);
                }
                tok = strtok(NULL, ",");
            }
            free(dup);
            if (g_active_dc_mask == 0) {
                g_active_dc_mask = 0x1;
            }
        }
        printf("受控 dst-DC 掩码: 0x%x\n", g_active_dc_mask);
    }

    printf("GSCC 控制面启动（作为 bf_switchd）\n");

    dev_tgt = (bf_rt_target_t *)calloc(1, sizeof(bf_rt_target_t));
    if (dev_tgt == NULL) { perror("calloc dev_tgt"); return -1; }
    dev_tgt->dev_id = 0;
    dev_tgt->pipe_id = BF_DEV_PIPE_ALL;   /* [FIX-5] 四个 pipe 全读 */

    switchd_ctx = (bf_switchd_context_t *)calloc(1, sizeof(bf_switchd_context_t));
    if (switchd_ctx == NULL) { perror("calloc switchd_ctx"); free(dev_tgt); return -1; }

    /* 程序名可用 GSCC_PROG 覆盖（换 P4 程序时不改代码） */
    const char *prog_name = "gscc";
    {
        const char *e = getenv("GSCC_PROG");
        if (e != NULL && e[0] != '\0') prog_name = e;
    }
    switchd_setup(switchd_ctx, prog_name);

    printf("等待交换机就绪...\n");
    sleep(2);

    bfrt_setup(dev_tgt, &bfrt_info, prog_name, &session);

    if (gscc_control_init(dev_tgt, bfrt_info, session) != BF_SUCCESS) {
        fprintf(stderr, "GSCC 控制面初始化失败\n");
        return -1;
    }

    /* [FIX-13] 显式 bring-up 面板口 */
    port_setup();

    /* [FIX-9] 配 CNP mirror session（端口用环境变量覆盖） */
    {
        const char *mp = getenv("GSCC_MIRROR_PORT");
        if (mp != NULL && mp[0] != '\0') {
            configure_cnp_mirror(1 /* GS_CNP_SES_ID */, (uint32_t)atoi(mp),
                                 64 /* CNP 很短，64 字节够 */);
        }
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    if (gscc_control_start() != BF_SUCCESS) {
        fprintf(stderr, "GSCC 控制面启动失败\n");
        return -1;
    }

    /* [FIX-8] 原版是 for (i = 0; i < 10; i++) sleep(1)，只跑 10 秒。
     * 现在常驻，Ctrl-C / SIGTERM 退出。 */
    printf("\nGSCC 控制环常驻中（Ctrl-C 退出）...\n");
    while (control_running) {
        sleep(5);
        gscc_print_status();
    }

    gscc_control_stop();

    bf_rt_session_destroy(session);
    free((void *)switchd_ctx->install_dir);
    free((void *)switchd_ctx->conf_file);
    free(switchd_ctx);
    free(dev_tgt);

    printf("\nGSCC 控制面退出\n");
    return 0;
}
