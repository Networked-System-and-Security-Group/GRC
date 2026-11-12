/* GSCC controller and v2 measurement protocol.
 * Scientific snapshots: quiet, nonce-addressed, one pipe, no live counter resets.
 * Live control RTT: atomic sum32/count32 pair with a conservative wrap bound.
 * Full RTT measurement: independent 64-bit cumulative sum and matched count.
 */
#include "headers.h"

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
#include <ctype.h>
#include <sys/stat.h>

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

#define GSCC_OFF_BUCKETS 132u
static bf_rt_id_t rtt_sum_hi_id, rtt_control_count_id;
static uint64_t controller_epochs = 0, ambiguous_control_reads = 0;
static uint64_t controller_max_epoch_us = 0;
static uint64_t controller_boot_us;
static const char *snapshot_dir;
static const char *build_id;

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

#define UINT32_MASK 0xFFFFFFFFULL

/* ================ 每个 DC 的统计信息 ================ */
typedef struct {
    uint32_t dc_id;

    /* --- 本 epoch 的 RTT 样本（论文 Delay Monitor 的输出）--- */
    uint64_t rtt_sum_ns;   /* 本 epoch 累计 RTT，单位 ns */
    uint32_t rtt_count;    /* Matched ACK sample count */
    uint64_t last_rtt_sum;
    uint32_t last_control_sum, last_control_count;
    uint32_t last_rtt_count;

    /* --- 论文 Algorithm 2 的状态 --- */
    double cur_rtt_s;      /* curRTT */
    double min_rtt_s;      /* baseRTT：历史最小值（论文"long time window"） */
    uint32_t rtt_miss_counter;

    double guaranteed_rate; /* baseRate = max_rate * 0.25 */
    double ref_rate;        /* refRate */
    double real_rate;       /* realRate */
    uint32_t ref_bytes;     /* 控制面维护的 refBytes（绝对量，模 2^32） */
    uint32_t last_real_bytes;
    int64_t budget_balance;  /* ref-real at last control read, not a wrapped sign test */
    uint32_t last_pkt_count; /* 上一轮的包计数，用来算每轮增量 */

    /* 累计量：单轮比值受两次 gRPC 读取的 ~0.4 ms 时间偏移影响，
     * 只有累计值才有意义。 */
    uint64_t total_ackmatch;  /* 累计匹配上 ackreq 的 ACK 数 */
    uint64_t total_ack_pkts;  /* 累计 ACK 包数 */
    uint64_t total_data_pkts; /* 累计数据包数 */

    /* 最近 3 个 epoch 的发送字节数（wan-routing.cc 的 send_bytes_history） */
    uint32_t send_bytes_hist[3];
    uint64_t duration_hist[3];
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

static pthread_t control_thread;
static volatile sig_atomic_t control_running = 0;
static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;

/* ================ P4 寄存器表句柄和信息结构体 ================ */
static const bf_rt_table_hdl *rtt_control_reg_table = NULL, *rtt_max_reg_table = NULL;
static register_info_t rtt_control_reg_info, rtt_max_reg_info;
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
/* Generated CNP requests are distinct from ingress CNP packets. */
static const bf_rt_table_hdl *cnp_count_reg_table = NULL;
static register_info_t cnp_count_reg_info;
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
static const bf_rt_table_hdl *off_hist_reg_table = NULL;
static register_info_t off_hist_reg_info;
static const bf_rt_table_hdl *packet_kind_reg_table = NULL;
static register_info_t packet_kind_reg_info;

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

    /* Read exactly the selected pipe. Never sum scalar register state. */
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
        if (n != 1) {
            fprintf(stderr, "Expected one explicitly selected pipe, got %u\n", n);
            exit(1);
        }
        value = values[0];
        free(values);
    } else {
        fprintf(stderr, "Empty hardware register response\n");
        exit(1);
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
    // Register tables use symmetric scope: reads select pipe 3; the common
    // reference budget is written to all pipes as required by this SDE scope.
    bf_rt_target_t write_target = *dev_tgt_ptr;
    write_target.pipe_id = BF_DEV_PIPE_ALL;
    dev_tgt_ptr = &write_target;
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
        fprintf(stderr, "ERROR: register_write: entry_mod/add failed (index: %u, status: %d)\n", reg_entry->register_index, bf_status);
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
                          (double)dc->send_bytes_hist[2]) /
                         ((dc->duration_hist[0] + dc->duration_hist[1] + dc->duration_hist[2]) * 1e-6);

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

/* Carry excess traffic debt, discard unused credit each epoch, matching
 * WanRouting::Update: start=min(previous_end-current_bytes,0).
 * Keeping unused credit indefinitely makes real-ref wrap past 2^31 and
 * manufactures a positive backlog even at 0.2 Gbps. All values are bytes.
 */
static void update_reference_bytes(dc_stats_t *dc, uint64_t epoch_duration_us,
                                   uint32_t bytes_sent) {
    dc->budget_balance -= bytes_sent;
    if (dc->budget_balance > 0) dc->budget_balance = 0;
    double add = bytes_sent ? dc->ref_rate * (double)epoch_duration_us * 1e-6 : 0;
    if (add >= 1073741824.0 || (bytes_sent && epoch_duration_us > 100000)) {
        fprintf(stderr, "Unsafe control interval/budget; refusing wrapped feedback\n");
        exit(1);
    }
    dc->budget_balance += (int64_t)add;
    if (dc->budget_balance <= -1073741824LL) {
        fprintf(stderr, "Backlog outside safe signed range; refusing wrapped feedback\n");
        exit(1);
    }
    dc->ref_bytes = dc->last_real_bytes + (uint32_t)dc->budget_balance;
}

/* ================ P4 寄存器读写 ================ */
static uint64_t read_rtt_sum(uint32_t dc_id) {
    register_entry_t e = { .register_index = dc_id };
    register_read(dev_tgt, session, rtt_sum_reg_table, &rtt_sum_reg_info, &e);
    uint64_t hi = 0;
    uint32_t n = 0;
    if (bf_rt_data_field_get_value_u64_array_size(rtt_sum_reg_info.data, rtt_sum_hi_id, &n) != BF_SUCCESS || n != 1 ||
        bf_rt_data_field_get_value_u64_array(rtt_sum_reg_info.data, rtt_sum_hi_id, &hi) != BF_SUCCESS) {
        fprintf(stderr, "Invalid RTT high word read\n"); exit(1);
    }
    return (hi << 32) | e.value;
}

static int read_rtt_stats_from_p4(uint32_t dc_id, uint64_t *sum, uint32_t *count) {
    // Read-only cumulative counters. Reject a torn sample, never clear live state.
    register_entry_t a = { .register_index = dc_id }, b = a;
    register_read(dev_tgt, session, rtt_count_reg_table, &rtt_count_reg_info, &a);
    *sum = read_rtt_sum(dc_id);
    register_read(dev_tgt, session, rtt_count_reg_table, &rtt_count_reg_info, &b);
    *count = b.value;
    return a.value == b.value;
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

/* Read one index on pipe 3. Caller holds stats_mutex once threads start. */
static uint32_t read_reg_idx(const bf_rt_table_hdl *tbl, register_info_t *info,
                             uint32_t idx) {
    register_entry_t e = { .register_index = idx };
    register_read(dev_tgt, session, tbl, info, &e);
    return (uint32_t)e.value;
}

/* ================ 核心控制逻辑 ================ */
static void process_dc_control(uint32_t dc_id, uint64_t current_time_us) {
    dc_stats_t *dc = &dc_stats[dc_id];

    uint64_t epoch_duration_us = current_time_us - dc->last_update_time_us;
    if (epoch_duration_us == 0) {
        epoch_duration_us = GSCC_EPOCH_DURATION_US;
    }

    // Both words are one atomic register value; no live reset or cross-read pairing.
    register_entry_t pair = { .register_index = dc_id };
    register_read(dev_tgt, session, rtt_control_reg_table, &rtt_control_reg_info, &pair);
    uint32_t n = 0; uint64_t count = 0;
    if (bf_rt_data_field_get_value_u64_array_size(rtt_control_reg_info.data, rtt_control_count_id, &n) != BF_SUCCESS || n != 1 ||
        bf_rt_data_field_get_value_u64_array(rtt_control_reg_info.data, rtt_control_count_id, &count) != BF_SUCCESS) exit(1);
    uint32_t max_rtt = read_reg_idx(rtt_max_reg_table, &rtt_max_reg_info, dc_id);
    uint32_t samples = (uint32_t)count - dc->last_control_count;
    dc->rtt_sum_ns = (uint32_t)(pair.value - dc->last_control_sum);
    dc->rtt_count = samples;
    // Sufficient bound for unique modulo32 sum unwrapping. Reject instead of inventing a mean.
    if ((uint64_t)samples * max_rtt >= (1ULL << 32)) {
        ambiguous_control_reads++;
        dc->rtt_count = 0;
    }
    dc->last_control_sum = pair.value;
    dc->last_control_count = count;
    controller_epochs++;
    if (epoch_duration_us > controller_max_epoch_us) controller_max_epoch_us = epoch_duration_us;

    /* --- 步骤 4: 读取实际发送字节数（累计量）--- */
    uint32_t current_real_bytes;
    read_real_bytes_from_p4(dc_id, &current_real_bytes);

    /* --- 步骤 5: 计算实际速率 --- */
    current_time_us = get_timestamp_us();
    epoch_duration_us = current_time_us - dc->last_update_time_us;
    if (!epoch_duration_us) epoch_duration_us = 1;
    uint32_t bytes_sent = current_real_bytes - dc->last_real_bytes; /* 32-bit cyclic counter */
    if (bytes_sent && epoch_duration_us > 100000) ambiguous_control_reads++;
    dc->last_real_bytes = current_real_bytes;
    dc->real_rate = (double)bytes_sent * 1e6 / (double)epoch_duration_us;

    /* 维护最近 3 个 epoch 的历史（wan-routing.cc 的 send_bytes_history） */
    dc->duration_hist[0] = dc->duration_hist[1];
    dc->duration_hist[1] = dc->duration_hist[2];
    dc->duration_hist[2] = epoch_duration_us;
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

    dc->last_update_time_us = current_time_us;
    // Scientific RTT statistics come from quiet cumulative snapshots only.
    DBG("[control] seq=%" PRIu64 " epoch_us=%" PRIu64 " samples=%u ref_Bps=%.0f\n",
        controller_epochs, epoch_duration_us, dc->rtt_count, dc->ref_rate);

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
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_control_reg", "sum", &rtt_control_reg_table, &rtt_control_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_max_reg", data_field_name, &rtt_max_reg_table, &rtt_max_reg_info);
    if (bf_rt_data_field_id_get(rtt_control_reg_table, "gs_Ingress.gs_rtt_control_reg.count", &rtt_control_count_id) != BF_SUCCESS) exit(1);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_sum_reg", "lo",
                   &rtt_sum_reg_table, &rtt_sum_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_count_reg", data_field_name,
                   &rtt_count_reg_table, &rtt_count_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_real_bytes_reg", data_field_name,
                   &real_bytes_reg_table, &real_bytes_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_ref_bytes_reg", data_field_name,
                   &ref_bytes_reg_table, &ref_bytes_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_pkt_count_reg", data_field_name,
                   &pkt_count_reg_table, &pkt_count_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_cnp_count_reg", data_field_name,
                   &cnp_count_reg_table, &cnp_count_reg_info);
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
    register_setup(bfrt_info, "gs_Ingress.gs_off_hist_reg", data_field_name,
                   &off_hist_reg_table, &off_hist_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_packet_kind_reg", data_field_name,
                   &packet_kind_reg_table, &packet_kind_reg_info);
    if (bf_rt_data_field_id_get(rtt_sum_reg_table, "gs_Ingress.gs_rtt_sum_reg.hi", &rtt_sum_hi_id) != BF_SUCCESS) {
        fprintf(stderr, "Missing RTT sum high word\n"); exit(1);
    }
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
        /* Initialize from fresh dataplane; never reset live statistics. */
        if (!read_rtt_stats_from_p4(i, &dc_stats[i].last_rtt_sum, &dc_stats[i].last_rtt_count)) {
            fprintf(stderr, "Traffic during initialization\n"); exit(1);
        }
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

// Called on demand, never periodically while an experiment is transmitting.
// Atomic file publication + nonce + boot identity prevents mixed/stale blocks.
static void service_snapshot(void) {
    char reqpath[512], tmp[512], dest[512], nonce[65];
    snprintf(reqpath, sizeof(reqpath), "%s/request", snapshot_dir);
    FILE *req = fopen(reqpath, "r");
    if (!req) return;
    if (fscanf(req, "%64s", nonce) != 1) { fclose(req); unlink(reqpath); return; }
    fclose(req);
    unlink(reqpath);
    for (unsigned i=0; nonce[i]; ++i) if (!isxdigit((unsigned char)nonce[i])) return;
    snprintf(tmp, sizeof(tmp), "%s/%s.tmp", snapshot_dir, nonce);
    snprintf(dest, sizeof(dest), "%s/%s.json", snapshot_dir, nonce);
    pthread_mutex_lock(&stats_mutex);
    uint64_t start = get_timestamp_us();
    uint32_t first[8], last[8], kh[64], off[GSCC_OFF_BUCKETS];
    for (unsigned i=0; i<8; ++i) first[i] = read_reg_idx(packet_kind_reg_table, &packet_kind_reg_info, i);
    usleep(100000);  // Guard interval: caller must have stopped traffic.
    uint32_t reqs = read_reg_idx(ackreq_cnt_reg_table, &ackreq_cnt_reg_info, 0);
    uint32_t acks = read_reg_idx(ack_total_reg_table, &ack_total_reg_info, 0);
    uint32_t ok = read_reg_idx(rtt_ok_cnt_reg_table, &rtt_ok_cnt_reg_info, 0);
    uint32_t empty = read_reg_idx(rtt_fail_zero_reg_table, &rtt_fail_zero_reg_info, 0);
    uint32_t miss = read_reg_idx(rtt_fail_psn_reg_table, &rtt_fail_psn_reg_info, 0);
    uint32_t pkt = read_reg_idx(pkt_count_reg_table, &pkt_count_reg_info, 0);
    uint32_t cnp = read_reg_idx(cnp_count_reg_table, &cnp_count_reg_info, 0);
    uint64_t sum; uint32_t count;
    int quiet = read_rtt_stats_from_p4(0, &sum, &count);
    for (unsigned i=0; i<64; ++i) kh[i] = read_reg_idx(khist_reg_table, &khist_reg_info, i);
    for (unsigned i=0; i<GSCC_OFF_BUCKETS; ++i) off[i] = read_reg_idx(off_hist_reg_table, &off_hist_reg_info, i);
    for (unsigned i=0; i<8; ++i) {
        last[i] = read_reg_idx(packet_kind_reg_table, &packet_kind_reg_info, i);
        if (first[i] != last[i]) quiet = 0;
    }
    FILE *f = fopen(tmp, "w");
    if (!f) { perror("snapshot"); exit(1); }
    fprintf(f, "{\"schema\":\"gscc.ack-experiment.v1\",\"nonce\":\"%s\",\"build_id\":\"%s\","
               "\"pid\":%d,\"boot_us\":%" PRIu64 ",\"pipe\":%u,\"start_us\":%" PRIu64 ",\"end_us\":%" PRIu64 ","
               "\"quiet\":%s,\"ack_req\":%u,\"ack_total\":%u,\"rtt_ok\":%u,\"fail_empty\":%u,\"fail_psn\":%u,"
               "\"pkt\":%u,\"cnp_generated\":%u,\"rtt_sum_ns_mod32_samples\":%" PRIu64 ",\"rtt_count\":%u,"
               "\"control_epochs\":%" PRIu64 ",\"ambiguous_control_reads\":%" PRIu64 ",\"max_epoch_us\":%" PRIu64 ",\"kind\":[",
               nonce, build_id, getpid(), controller_boot_us, dev_tgt->pipe_id, start, get_timestamp_us(),
               quiet?"true":"false", reqs, acks, ok, empty, miss, pkt, cnp, sum, count,
               controller_epochs, ambiguous_control_reads, controller_max_epoch_us);
    for(unsigned i=0;i<8;++i) fprintf(f,"%s%u",i?",":"",last[i]);
    fprintf(f,"],\"k_hist\":[");
    for(unsigned i=0;i<64;++i) fprintf(f,"%s%u",i?",":"",kh[i]);
    fprintf(f,"],\"off_hist\":[");
    for(unsigned i=0;i<GSCC_OFF_BUCKETS;++i) fprintf(f,"%s%u",i?",":"",off[i]);
    fprintf(f,"],\"rtt_max_ns\":%u,\"ref_Bps\":%.0f,\"base_rtt_us\":%.9f}\n",read_reg_idx(rtt_max_reg_table, &rtt_max_reg_info,0),dc_stats[0].ref_rate,dc_stats[0].min_rtt_s*1e6);
    if (fclose(f) != 0 || rename(tmp, dest) != 0) { perror("publish snapshot"); exit(1); }
    pthread_mutex_unlock(&stats_mutex);
}

/* ================ [FIX-13] 端口 bring-up ================ */
/*
 * Add the operator-specified ports using the experiment's 100G RS-FEC setup.
 */
static void port_setup(void) {
    const char *ports_str = getenv("GSCC_PORTS");
    if (ports_str == NULL || ports_str[0] == '\0') {
        fprintf(stderr, "Set GSCC_PORTS to the comma-separated Tofino device ports\n");
        exit(1);
    }
    char *dup = strdup(ports_str);
    char *tok = strtok(dup, ",");

    while (tok != NULL) {
        char *end;
        long dp = strtol(tok, &end, 10);
        if (end == tok || *end != '\0' || dp < 0 || dp >= 512) {
            fprintf(stderr, "Invalid Tofino device port: %s\n", tok);
            free(dup);
            exit(1);
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
        pipe_mgr_client_cleanup(pipe_sess);
        return;
    }

    printf("CNP mirror session %u 已配置 -> dev_port %u (max %u B)\n",
           session_id, egress_dev_port, max_pkt_len);
    pipe_mgr_client_cleanup(pipe_sess);
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
    /* Let SDE identify every device through platform configuration.
     * Setting only the global is_sw_model bypasses per-device initialization. */
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

    controller_boot_us = get_timestamp_us();
    snapshot_dir = getenv("P4SORT_SNAPSHOT_DIR");
    build_id = getenv("P4SORT_BUILD_ID");
    if (!snapshot_dir || !build_id) { fprintf(stderr,"Missing measurement deployment identity\n"); return 1; }
    for (const char *c=build_id; *c; ++c) if (!isxdigit((unsigned char)*c)) return 1;

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
    const char *pipe_env = getenv("GSCC_PIPE");
    if (pipe_env == NULL || strspn(pipe_env, "0123") != 1 || pipe_env[1] != '\0') {
        fprintf(stderr, "Set GSCC_PIPE to the Tofino2 pipe of both ports (0-3)\n");
        return 1;
    }
    dev_tgt->pipe_id = (bf_dev_pipe_t)(pipe_env[0] - '0');

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
        usleep(100000);
        service_snapshot();
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
