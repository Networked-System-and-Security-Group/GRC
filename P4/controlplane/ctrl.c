#include "headers.h"
#include <pthread.h>
#include <time.h>
#include <math.h>
#include <unistd.h>
#include <stdlib.h> // For calloc, free
#include <string.h> // For memset, strdup
#include <stdio.h>  // For fprintf, stderr
#include <bf_rt/bf_rt_common.h>
#include <bf_rt/bf_rt_table.h>
#include <bf_rt/bf_rt_info.h>
#include <bf_rt/bf_rt_session.h>

// ================ GSCC控制平面全局变量 ================
bf_switchd_context_t *switchd_ctx;
bf_rt_target_t *dev_tgt;
const bf_rt_info_hdl *bfrt_info = NULL;
bf_rt_session_hdl *session = NULL;

// ================ GSCC Rate Control相关常量 ================
#define MAX_DC_COUNT 16
#define GSCC_EPOCH_DURATION_US 1000U
#define GSCC_LINK_RATE_BPS 100000000000ULL
#define GSCC_BASE_RATE_BPS (GSCC_LINK_RATE_BPS / 4)
#define GSCC_WEIGHT 1.0L
#define GSCC_INV_DELTA_BYTES 6000000.0L
#define GSCC_BETA 0.3L
#define GSCC_RATE_LIMIT_FACTOR 1.2L
#define GSCC_UPPER_DECAY_FACTOR 0.8L
#define BITS_PER_BYTE 8ULL
#define BITS_PER_SECOND 1000000ULL
#define REF_BYTES_DENOMINATOR (BITS_PER_BYTE * BITS_PER_SECOND)
#define RATE_NUMERATOR_BPS_US (GSCC_INV_DELTA_BYTES * BITS_PER_BYTE * BITS_PER_SECOND)

// ================ 每个DC的统计信息 ================
typedef struct {
    uint32_t dc_id;
    uint32_t min_rtt_us;
    uint32_t current_rtt_us;
    uint32_t real_bytes;
    uint64_t ref_rate_bps;
    uint32_t ref_bytes;
    uint64_t ref_bytes_remainder;
    uint32_t last_real_bytes;
    uint64_t actual_rate_bps;
    uint32_t last_pkt_count;
    uint32_t last_cnp_count;
    uint32_t packet_count_epoch;
    uint32_t cnp_count_epoch;
    uint64_t direction_duration_us;
    int8_t rate_direction;
    uint8_t velocity;
    uint64_t last_update_time_us;
} dc_stats_t;

// ================ 全局状态 ================
static dc_stats_t dc_stats[MAX_DC_COUNT];
static pthread_t control_thread;
static bool control_running = false;
static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;

// ================ P4寄存器表句柄和信息结构体 ================
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
static const bf_rt_table_hdl *cnp_count_reg_table = NULL;
static register_info_t cnp_count_reg_info;

/*
 * @brief 设置一个寄存器，获取其表句柄、key/data句柄和字段ID (增强错误处理)
 */
static void register_setup(const bf_rt_info_hdl *bfrt_info_hdl,
                    const char *reg_name,
                    const char *value_field_name,
                    const bf_rt_table_hdl **reg_table_hdl_ptr,
                    register_info_t *reg_info_ptr) {
    bf_status_t bf_status;
    char reg_value_full_name[128];

    bf_status = bf_rt_table_from_name_get(bfrt_info_hdl, reg_name, reg_table_hdl_ptr);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to get table handle for '%s' (status: %d). This register may not exist in the P4 program.\n", reg_name, bf_status);
        exit(1);
    }
    if (*reg_table_hdl_ptr == NULL) {
        fprintf(stderr, "ERROR: Got a NULL table handle for '%s'. This indicates a severe issue with the BFRT context.\n", reg_name);
        exit(1);
    }

    bf_status = bf_rt_table_key_allocate(*reg_table_hdl_ptr, &reg_info_ptr->key);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to allocate key for '%s'\n", reg_name);
        exit(1);
    }
    bf_status = bf_rt_table_data_allocate(*reg_table_hdl_ptr, &reg_info_ptr->data);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to allocate data for '%s'\n", reg_name);
        exit(1);
    }

    bf_status = bf_rt_key_field_id_get(*reg_table_hdl_ptr, "$REGISTER_INDEX", &reg_info_ptr->kid_register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to get key field ID for '%s'\n", reg_name);
        exit(1);
    }

    snprintf(reg_value_full_name, sizeof(reg_value_full_name), "%s.%s", 
             reg_name, (value_field_name == NULL) ? "f1" : value_field_name);
    bf_status = bf_rt_data_field_id_get(*reg_table_hdl_ptr, reg_value_full_name, &reg_info_ptr->did_value);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to get data field ID for '%s'. The field name might be incorrect.\n", reg_value_full_name);
        exit(1);
    }

    printf("Successfully setup register: %s\n", reg_name);
}

/*
 * @brief 从硬件读取指定的寄存器条目 (增强错误处理和深度调试)
 */
static void register_read(const bf_rt_target_t *dev_tgt_ptr,
                   const bf_rt_session_hdl *session_hdl,
                   const bf_rt_table_hdl *reg,
                   register_info_t *reg_info,
                   register_entry_t *reg_entry) {
    bf_status_t bf_status;
    const uint64_t flags = ENTRY_READ_FROM_HW;

    // Reset key and data handles
    bf_rt_table_key_reset(reg, &reg_info->key);
    bf_rt_table_data_reset(reg, &reg_info->data);
    fprintf(stderr, "[DEBUG/register_read] after reset key=%p data=%p\n", (void*)reg_info->key, (void*)reg_info->data);

    // Set register index key
    bf_status = bf_rt_key_field_set_value(reg_info->key,
                                          reg_info->kid_register_index,
                                          reg_entry->register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: bf_rt_key_field_set_value failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }

    // Perform HW read
    bf_status = bf_rt_table_entry_get(reg, session_hdl, dev_tgt_ptr,
                                      flags, reg_info->key, reg_info->data);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: bf_rt_table_entry_get failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }
    bf_status = bf_rt_session_complete_operations(session_hdl);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: bf_rt_session_complete_operations failed\n");
        exit(1);
    }

    // Retrieve value array (supporting multi-word registers)
    reg_entry->value_array_size = 0;
    bf_status = bf_rt_data_field_get_value_u64_array_size(reg_info->data,
                                                         reg_info->did_value,
                                                         &reg_entry->value_array_size);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: get_value_array_size failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }
    if (reg_entry->value_array) {
        free(reg_entry->value_array);
    }
    reg_entry->value_array = (uint64_t *)calloc(reg_entry->value_array_size, sizeof(uint64_t));
    bf_status = bf_rt_data_field_get_value_u64_array(reg_info->data,
                                                     reg_info->did_value,
                                                     reg_entry->value_array);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_read: get_value_u64_array failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }
    // For convenience, store first element into value (if exists)
    reg_entry->value = (reg_entry->value_array_size > 0) ? reg_entry->value_array[0] : 0;
}


/*
 * @brief 向硬件写入指定的寄存器条目 (增强错误处理和深度调试)
 */
static void register_write(const bf_rt_target_t *dev_tgt_ptr,
                    const bf_rt_session_hdl *session_hdl,
                    const bf_rt_table_hdl *reg,
                    register_info_t *reg_info,
                    register_entry_t *reg_entry) {
    bf_status_t bf_status;
    const uint64_t flags = 0;

    // --- Start of Enhanced Debugging ---
    if (reg == NULL || reg_info == NULL || reg_info->key == NULL || reg_info->data == NULL) {
        fprintf(stderr, "    [FATAL/register_write] Index: %u. A critical handle is NULL. Aborting.\n", reg_entry->register_index);
        exit(1);
    }
    // --- End of Enhanced Debugging ---

    bf_rt_table_key_reset(reg, &reg_info->key);
    bf_rt_table_data_reset(reg, &reg_info->data);

    bf_status = bf_rt_key_field_set_value(reg_info->key, reg_info->kid_register_index, reg_entry->register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: bf_rt_key_field_set_value failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }
    
    bf_status = bf_rt_data_field_set_value(reg_info->data, reg_info->did_value, reg_entry->value);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: bf_rt_data_field_set_value failed (index: %u, value: %" PRIu64 ")\n", reg_entry->register_index, (uint64_t)reg_entry->value);
        exit(1);
    }
    
    bf_status = bf_rt_table_entry_mod(reg, session_hdl, dev_tgt_ptr, flags,
                                      reg_info->key, reg_info->data);
    if (bf_status != BF_SUCCESS) {
        bf_status = bf_rt_table_entry_add(reg, session_hdl, dev_tgt_ptr, flags,
                                          reg_info->key, reg_info->data);
    }
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: bf_rt_table_entry_mod/add failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }

    bf_status = bf_rt_session_complete_operations(session_hdl);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: bf_rt_session_complete_operations failed\n");
        exit(1);
    }
}

// ================ 工具函数 ================
static uint64_t get_timestamp_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000 + (uint64_t)ts.tv_nsec / 1000;
}

static void update_rtt_stats(dc_stats_t *dc, uint32_t rtt_sum, uint32_t rtt_count) {
    if (rtt_count == 0) {
        return;
    }
    uint64_t avg_rtt_ns = rtt_sum / rtt_count;
    uint32_t current_avg_rtt_us = (uint32_t)((avg_rtt_ns + 500) / 1000);
    dc->current_rtt_us = current_avg_rtt_us;
    if (dc->min_rtt_us == 0 || current_avg_rtt_us < dc->min_rtt_us) {
        dc->min_rtt_us = current_avg_rtt_us;
    }
    printf("[DC %u] RTT: avg=%u us, base=%u us\n",
           dc->dc_id, dc->current_rtt_us, dc->min_rtt_us);
}

static uint64_t rate_to_u64(long double rate_bps) {
    if (!(rate_bps > 0.0L)) {
        return 0;
    }
    if (rate_bps >= (long double)UINT64_MAX) {
        return UINT64_MAX;
    }
    return (uint64_t)rate_bps;
}

static uint32_t counter_delta_u32(uint32_t current, uint32_t previous) {
    return current - previous;
}

static uint8_t update_rate_velocity(dc_stats_t *dc, int direction,
                                    uint64_t base_rtt_us, uint64_t epoch_duration_us) {
    if (direction == 0 || base_rtt_us == 0) {
        dc->rate_direction = 0;
        dc->direction_duration_us = 0;
        dc->velocity = 1;
        return 1;
    }
    if (dc->rate_direction != direction) {
        dc->rate_direction = (int8_t)direction;
        dc->direction_duration_us = epoch_duration_us;
    } else if (dc->direction_duration_us < base_rtt_us * 10) {
        dc->direction_duration_us += epoch_duration_us;
        if (dc->direction_duration_us > base_rtt_us * 10) {
            dc->direction_duration_us = base_rtt_us * 10;
        }
    }
    if (dc->direction_duration_us >= base_rtt_us * 10) {
        dc->velocity = 4;
    } else if (dc->direction_duration_us >= base_rtt_us * 5) {
        dc->velocity = 2;
    } else {
        dc->velocity = 1;
    }
    return dc->velocity;
}

static void calculate_reference_rate(dc_stats_t *dc, uint64_t epoch_duration_us) {
    long double ref_rate = dc->ref_rate_bps;
    long double queue_delay_us = 0.0L;
    long double target_rate = 0.0L;
    long double step = 0.0L;
    long double epochs_per_rtt = 1.0L;
    uint8_t velocity = 1;

    if (dc->min_rtt_us != 0 && dc->current_rtt_us != 0) {
        uint64_t base_rtt_us = dc->min_rtt_us;
        queue_delay_us = dc->current_rtt_us > base_rtt_us
            ? (long double)(dc->current_rtt_us - base_rtt_us)
            : 0.0L;
        epochs_per_rtt = (long double)base_rtt_us / (long double)epoch_duration_us;
        if (epochs_per_rtt < 1.0L) {
            epochs_per_rtt = 1.0L;
        }
        if (queue_delay_us == 0.0L) {
            target_rate = HUGE_VALL;
        } else {
            target_rate = GSCC_WEIGHT * RATE_NUMERATOR_BPS_US / queue_delay_us;
        }

        int direction = target_rate > ref_rate ? 1 : (target_rate < ref_rate ? -1 : 0);
        velocity = update_rate_velocity(dc, direction, base_rtt_us, epoch_duration_us);
        step = (long double)velocity * GSCC_WEIGHT * RATE_NUMERATOR_BPS_US /
               (epochs_per_rtt * (long double)base_rtt_us);
        long double beta_epoch = 1.0L - powl(1.0L - GSCC_BETA, 1.0L / epochs_per_rtt);

        if (target_rate > ref_rate) {
            ref_rate += step;
        } else {
            long double minimum_decrease = (ref_rate - target_rate) * beta_epoch;
            if (minimum_decrease > step) {
                step = minimum_decrease;
            }
            ref_rate = step >= ref_rate ? 0.0L : ref_rate - step;
        }

        printf("[DC %u] RateCalc: queue=%" PRIu64 " us target=%.0Lf bps step=%.0Lf bps betaEpoch=%.6Lf v=%u\n",
               dc->dc_id, (uint64_t)queue_delay_us, target_rate, step,
               beta_epoch, velocity);
    } else {
        printf("[DC %u] RateCalc: waiting for a valid RTT sample\n", dc->dc_id);
    }

    long double upper_rate = (long double)dc->actual_rate_bps * GSCC_RATE_LIMIT_FACTOR;
    if (upper_rate < (long double)GSCC_BASE_RATE_BPS) {
        upper_rate = (long double)GSCC_BASE_RATE_BPS;
    }
    if (ref_rate > upper_rate) {
        ref_rate = upper_rate + (ref_rate - upper_rate) * GSCC_UPPER_DECAY_FACTOR;
    }
    dc->ref_rate_bps = rate_to_u64(ref_rate);
    printf("[DC %u] Rate: ref=%" PRIu64 " actual=%" PRIu64 " upper=%.0Lf bps\n",
           dc->dc_id, dc->ref_rate_bps, dc->actual_rate_bps, upper_rate);
}

static void update_reference_bytes(dc_stats_t *dc, uint64_t epoch_duration_us) {
    uint32_t bytes_diff = dc->real_bytes - dc->ref_bytes;
    if ((bytes_diff & 0x80000000U) != 0) {
        dc->ref_bytes = dc->real_bytes;
        dc->ref_bytes_remainder = 0;
        bytes_diff = 0;
    }

    uint64_t byte_numerator = dc->ref_rate_bps * epoch_duration_us + dc->ref_bytes_remainder;
    uint64_t bytes_to_add = byte_numerator / REF_BYTES_DENOMINATOR;
    dc->ref_bytes_remainder = byte_numerator % REF_BYTES_DENOMINATOR;
    dc->ref_bytes += (uint32_t)bytes_to_add;
    printf("[DC %u] Budget: backlog=%u ref=%u (+%" PRIu64 " bytes for %" PRIu64 " us)\n",
           dc->dc_id, bytes_diff, dc->ref_bytes, bytes_to_add, epoch_duration_us);
}

// ================ P4寄存器读写函数 ================
static void read_rtt_stats_from_p4(uint32_t dc_id, uint32_t *rtt_sum, uint32_t *rtt_count) {
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

static void read_rate_counters_from_p4(uint32_t dc_id,
                                       uint32_t *packet_count,
                                       uint32_t *cnp_count) {
    register_entry_t packet_entry = { .register_index = dc_id };
    register_entry_t cnp_entry = { .register_index = dc_id };
    register_read(dev_tgt, session, pkt_count_reg_table, &pkt_count_reg_info, &packet_entry);
    register_read(dev_tgt, session, cnp_count_reg_table, &cnp_count_reg_info, &cnp_entry);
    *packet_count = (uint32_t)packet_entry.value;
    *cnp_count = (uint32_t)cnp_entry.value;
}

static void reset_rtt_registers_for_dc(uint32_t dc_id) {
    register_entry_t entry = { .register_index = dc_id, .value = 0 };
    register_write(dev_tgt, session, rtt_sum_reg_table, &rtt_sum_reg_info, &entry);
    register_write(dev_tgt, session, rtt_count_reg_table, &rtt_count_reg_info, &entry);
}

// ================ 核心控制逻辑 (已添加调试信息) ================
static void process_dc_control(uint32_t dc_id, uint64_t current_time_us) {
    // 检查指针和句柄是否有效，防止段错误
    if (dev_tgt == NULL || session == NULL) {
        fprintf(stderr, "[FATAL] Global dev_tgt or session is NULL!\n");
        exit(1);
    }
    dc_stats_t *dc = &dc_stats[dc_id];

    // 计算epoch持续时间
    uint64_t epoch_duration_us = current_time_us - dc->last_update_time_us;
    if (epoch_duration_us == 0) epoch_duration_us = GSCC_EPOCH_DURATION_US;
    
    // 这是您看到的最后一条打印信息
    printf("\n=== Processing DC %u (epoch: %" PRIu64 " us) ===\n", dc_id, epoch_duration_us);

    // --- 步骤 1: 从P4读取RTT统计信息 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 1 - Reading RTT stats from P4...\n", dc_id);
    uint32_t rtt_sum, rtt_count;
    if (rtt_sum_reg_table == NULL || rtt_count_reg_table == NULL) {
        fprintf(stderr, "[FATAL] DC %u: RTT register table handles are NULL. Cannot read stats.\n", dc_id);
        exit(1);
    }
    read_rtt_stats_from_p4(dc_id, &rtt_sum, &rtt_count);
    fprintf(stderr, "[DEBUG] DC %u: P4 Read Complete. rtt_sum = %u, rtt_count = %u\n", dc_id, rtt_sum, rtt_count);

    // --- 步骤 2: 更新本地RTT统计信息 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 2 - Updating local RTT statistics...\n", dc_id);
    update_rtt_stats(dc, rtt_sum, rtt_count);
    fprintf(stderr, "[DEBUG] DC %u: Local RTT stats updated.\n", dc_id);

    // --- 步骤 3: 重置P4中的RTT寄存器 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 3 - Resetting RTT registers in P4...\n", dc_id);
    reset_rtt_registers_for_dc(dc_id);
    fprintf(stderr, "[DEBUG] DC %u: P4 RTT registers reset.\n", dc_id);

    // --- 步骤 4: 从P4读取实际发送字节数 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 4 - Reading real bytes from P4...\n", dc_id);
    uint32_t current_real_bytes;
    if (real_bytes_reg_table == NULL) {
        fprintf(stderr, "[FATAL] DC %u: real_bytes_reg_table handle is NULL. Cannot read bytes.\n", dc_id);
        exit(1);
    }
    read_real_bytes_from_p4(dc_id, &current_real_bytes);
    fprintf(stderr, "[DEBUG] DC %u: P4 Read Complete. current_real_bytes = %u\n", dc_id, current_real_bytes);
    dc->real_bytes = current_real_bytes;

    uint32_t current_packet_count, current_cnp_count;
    read_rate_counters_from_p4(dc_id, &current_packet_count, &current_cnp_count);
    dc->packet_count_epoch = counter_delta_u32(current_packet_count, dc->last_pkt_count);
    dc->cnp_count_epoch = counter_delta_u32(current_cnp_count, dc->last_cnp_count);
    dc->last_pkt_count = current_packet_count;
    dc->last_cnp_count = current_cnp_count;

    // --- 步骤 5: 计算实际速率 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 5 - Calculating actual rate (last_real_bytes = %u)...\n", dc_id, dc->last_real_bytes);
    uint32_t bytes_sent = current_real_bytes - dc->last_real_bytes;
    uint64_t measured_rate_bps = (uint64_t)bytes_sent * REF_BYTES_DENOMINATOR / epoch_duration_us;
    dc->actual_rate_bps = measured_rate_bps;
    dc->last_real_bytes = current_real_bytes;
    printf("[DC %u] Actual rate: %" PRIu64 " bps (%u bytes in %" PRIu64 " us)\n",
           dc_id, dc->actual_rate_bps, bytes_sent, epoch_duration_us);
    printf("[DC %u] Feedback counters: packets=%u CNPs=%u\n",
           dc_id, dc->packet_count_epoch, dc->cnp_count_epoch);

    // --- 步骤 6: 计算新的参考速率 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 6 - Calculating new reference rate...\n", dc_id);
    calculate_reference_rate(dc, epoch_duration_us);
    fprintf(stderr, "[DEBUG] DC %u: New reference rate calculated: %" PRIu64 " bps.\n", dc_id, dc->ref_rate_bps);

    // --- 步骤 7: 更新参考字节数 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 7 - Updating reference bytes...\n", dc_id);
    update_reference_bytes(dc, epoch_duration_us);
    fprintf(stderr, "[DEBUG] DC %u: Reference bytes updated to %u.\n", dc_id, dc->ref_bytes);

    // --- 步骤 8: 将参考字节数写入P4 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 8 - Writing reference bytes to P4...\n", dc_id);
     if (ref_bytes_reg_table == NULL) {
        fprintf(stderr, "[FATAL] DC %u: ref_bytes_reg_table handle is NULL. Cannot write bytes.\n", dc_id);
        exit(1);
    }
    write_ref_bytes_to_p4(dc_id, dc->ref_bytes);
    fprintf(stderr, "[DEBUG] DC %u: P4 write complete.\n", dc_id);

    // --- 步骤 9: 更新时间戳并结束 ---
    dc->last_update_time_us = current_time_us;
    printf("=== DC %u processing complete ===\n", dc_id);
}


// ================ 控制线程主函数 ================
static void* control_loop(void* arg) {
    printf("GSCC Control Loop started\n");
    while (control_running) {
        uint64_t start_time = get_timestamp_us();
        pthread_mutex_lock(&stats_mutex);
        for (uint32_t dc_id = 0; dc_id < MAX_DC_COUNT; dc_id++) {
            if (dc_stats[dc_id].last_update_time_us > 0) {
                process_dc_control(dc_id, start_time);
            }
        }
        pthread_mutex_unlock(&stats_mutex);
        uint64_t elapsed_us = get_timestamp_us() - start_time;
        if (elapsed_us < GSCC_EPOCH_DURATION_US) {
            usleep(GSCC_EPOCH_DURATION_US - elapsed_us);
        }
    }
    printf("GSCC Control Loop stopped\n");
    return NULL;
}

// ================ P4表设置函数 ================
static bf_status_t setup_p4_register_tables(void) {
    const char *data_field_name = "f1";
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_sum_reg", data_field_name, &rtt_sum_reg_table, &rtt_sum_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_rtt_count_reg", data_field_name, &rtt_count_reg_table, &rtt_count_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_real_bytes_reg", data_field_name, &real_bytes_reg_table, &real_bytes_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_ref_bytes_reg", data_field_name, &ref_bytes_reg_table, &ref_bytes_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_pkt_count_reg", data_field_name, &pkt_count_reg_table, &pkt_count_reg_info);
    register_setup(bfrt_info, "gs_Ingress.gs_cnp_count_reg", data_field_name, &cnp_count_reg_table, &cnp_count_reg_info);
    printf("P4 register tables setup successfully\n");
    return BF_SUCCESS;
}

// ================ 公共接口函数 ================
bf_status_t gscc_control_init(bf_rt_target_t *target, const bf_rt_info_hdl *info, bf_rt_session_hdl *sess) {
    dev_tgt = target;
    bfrt_info = info;
    session = sess;
    memset(dc_stats, 0, sizeof(dc_stats));
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        dc_stats[i].dc_id = i;
        dc_stats[i].ref_rate_bps = GSCC_BASE_RATE_BPS;
    }
    bf_status_t status = setup_p4_register_tables();
    if (status != BF_SUCCESS) {
        fprintf(stderr, "Failed to setup P4 register tables\n");
        return status;
    }
    
    // 增加额外的检查，确保所有表句柄都有效
    if (rtt_sum_reg_table == NULL || rtt_count_reg_table == NULL ||
        real_bytes_reg_table == NULL || ref_bytes_reg_table == NULL ||
        pkt_count_reg_table == NULL || cnp_count_reg_table == NULL) {
        fprintf(stderr, "ERROR: One or more register table handles are NULL after setup. This confirms a mismatch with the loaded P4 program.\n");
        return BF_UNEXPECTED;
    }

    printf("GSCC Control initialized successfully\n");
    return BF_SUCCESS;
}

bf_status_t gscc_control_start(void) {
    if (control_running) {
        printf("GSCC Control already running\n");
        return BF_ALREADY_EXISTS;
    }
    control_running = true;
    uint64_t current_time = get_timestamp_us();
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        if (i == 0) {
            dc_stats[i].last_update_time_us = current_time;
        }
    }
    if (pthread_create(&control_thread, NULL, control_loop, NULL) != 0) {
        control_running = false;
        perror("Failed to create control thread");
        return BF_NO_SYS_RESOURCES;
    }
    printf("GSCC Control started successfully\n");
    return BF_SUCCESS;
}

bf_status_t gscc_control_stop(void) {
    if (!control_running) {
        printf("GSCC Control not running\n");
        return BF_INVALID_ARG;
    }
    control_running = false;
    pthread_join(control_thread, NULL);
    printf("GSCC Control stopped successfully\n");
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
    dc_stats[dc_id].ref_rate_bps = rate_bps;
    pthread_mutex_unlock(&stats_mutex);
    printf("DC %u reference rate set to %u bps\n", dc_id, rate_bps);
    return BF_SUCCESS;
}

void gscc_print_status(void) {
    printf("\n========== GSCC Control Status ==========\n");
    printf("Control running: %s\n", control_running ? "YES" : "NO");
    printf("Epoch duration: %u us\n", GSCC_EPOCH_DURATION_US);
    printf("Link/base rate: %" PRIu64 "/%" PRIu64 " bps\n",
           GSCC_LINK_RATE_BPS, (uint64_t)GSCC_BASE_RATE_BPS);
    pthread_mutex_lock(&stats_mutex);
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        dc_stats_t *dc = &dc_stats[i];
        if (dc->last_update_time_us > 0) {
            printf("\n--- DC %d ---\n", i);
            printf("  RTT: curr=%u us, base=%u us\n",
                   dc->current_rtt_us, dc->min_rtt_us);
            printf("  Rate: ref=%" PRIu64 ", actual=%" PRIu64 " bps\n",
                   dc->ref_rate_bps, dc->actual_rate_bps);
            printf("  Bytes: ref=%u, real=%u\n", 
                   dc->ref_bytes, dc->real_bytes);
            printf("  Epoch feedback: packets=%u CNPs=%u, velocity=%u\n",
                   dc->packet_count_epoch, dc->cnp_count_epoch, dc->velocity);
        }
    }
    pthread_mutex_unlock(&stats_mutex);
    printf("==========================================\n");
}

// ================ 测试主函数 (增强错误处理) ================
static void switchd_setup(bf_switchd_context_t *ctx, const char *prog) {
    bf_status_t bf_status;
    char conf_file[256];
    
    ctx->install_dir = strdup(getenv("SDE_INSTALL"));
    snprintf(conf_file, sizeof(conf_file), "%s/share/p4/targets/tofino2/%s.conf",
             ctx->install_dir, prog);
    ctx->conf_file = strdup(conf_file);
    ctx->running_in_background = true;
    ctx->dev_sts_thread = true;
    ctx->dev_sts_port = 7777;
    
    bf_status = bf_switchd_lib_init(ctx);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: bf_switchd_lib_init failed\n");
        exit(1);
    }
    printf("bf_switchd initialized successfully!\n");
}

static void configure_cnp_mirror(const bf_rt_target_t *target) {
    const uint16_t mirror_session_id = 1;
    const bf_dev_port_t mirror_dev_port = 392;
    p4_pd_sess_hdl_t pd_session;
    p4_pd_dev_target_t pd_target = {target->dev_id, target->pipe_id};
    p4_pd_mirror_session_info_t mirror_info = {
        .type = PD_MIRROR_TYPE_NORM,
        .dir = PD_DIR_INGRESS,
        .id = mirror_session_id,
        .egr_port = mirror_dev_port,
        .egr_port_v = true,
        .max_pkt_len = 55
    };
    p4_pd_status_t status = p4_pd_client_init(&pd_session);
    if (status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: p4_pd_client_init failed: %d\n", status);
        exit(EXIT_FAILURE);
    }

    status = p4_pd_mirror_session_create(pd_session, pd_target, &mirror_info);
    if (status != BF_SUCCESS) {
        status = p4_pd_mirror_session_update(pd_session, pd_target, &mirror_info, true);
    }
    if (status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: failed to configure CNP mirror session %u on dev port %u: %d\n",
                mirror_session_id, mirror_dev_port, status);
        exit(EXIT_FAILURE);
    }
    printf("Configured ingress CNP mirror session %u to dev port %u (max packet length %u)\n",
           mirror_session_id, mirror_dev_port, 55);
}

static void bfrt_setup(bf_rt_target_t *dev_tgt_ptr,
                           const bf_rt_info_hdl **bfrt_info_hdl,
                           const char *prog,
                           bf_rt_session_hdl **session_hdl_ptr) {
    bf_status_t bf_status;
    int retry_cnt = 10; // total ~10 seconds wait

    // Try to obtain BF-RT info, retrying because the pipeline may still be loading
    while (retry_cnt-- > 0) {
        bf_status = bf_rt_info_get(dev_tgt_ptr->dev_id, prog, bfrt_info_hdl);
        if (bf_status == BF_SUCCESS) break;
        // Fallback: try with the default pipeline name "gs_pipe"
        bf_status = bf_rt_info_get(dev_tgt_ptr->dev_id, "gs_pipe", bfrt_info_hdl);
        if (bf_status == BF_SUCCESS) break;
        fprintf(stderr, "WARN: bf_rt_info_get failed (attempts left: %d). Waiting for pipeline to be ready...\n", retry_cnt);
        sleep(1);
    }
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to get bf_rt_info for device %d (prog=%s) after multiple retries.\n",
                dev_tgt_ptr->dev_id, prog ? prog : "<NULL>");
        fprintf(stderr, "Make sure:\n");
        fprintf(stderr, "1. Tofino driver is loaded\n");
        fprintf(stderr, "2. P4 program '%s' is compiled and loaded\n", prog);
        fprintf(stderr, "3. bf_switchd is running properly\n");
        exit(1);
    }

    bf_status = bf_rt_session_create(session_hdl_ptr);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: Failed to create BFRT session\n");
        exit(1);
    }

    printf("bfrt_info and session created successfully!\n");
}

int main(void) {
    printf("Starting GSCC Control Plane Test\n");
    
    dev_tgt = (bf_rt_target_t *)calloc(1, sizeof(bf_rt_target_t));
    if (dev_tgt == NULL) {
        perror("Cannot allocate dev_tgt");
        return -1;
    }
    dev_tgt->dev_id = 0;
    dev_tgt->pipe_id = BF_DEV_PIPE_ALL;
    
    switchd_ctx = (bf_switchd_context_t *)calloc(1, sizeof(bf_switchd_context_t));
    if (switchd_ctx == NULL) {
        perror("Cannot allocate switchd context");
        free(dev_tgt);
        return -1;
    }
    
    const char* prog_name = "gscc";
    switchd_setup(switchd_ctx, prog_name); 

    printf("Waiting for switch to be ready...\n");
    sleep(2);
    
    bfrt_setup(dev_tgt, &bfrt_info, prog_name, &session);
    configure_cnp_mirror(dev_tgt);
    
    if (gscc_control_init(dev_tgt, bfrt_info, session) != BF_SUCCESS) {
        fprintf(stderr, "Failed to initialize GSCC control. Please check P4 program and compilation.\n");
        return -1;
    }
    
    if (gscc_control_start() != BF_SUCCESS) {
        fprintf(stderr, "Failed to start GSCC control\n");
        return -1;
    }
    
    printf("\nRunning GSCC control loop for 10 seconds...\n");
    for (int i = 0; i < 10; i++) {
        sleep(1);
        gscc_print_status();
    }
    
    gscc_control_stop();
    
    bf_rt_session_destroy(session);
    free((void*)switchd_ctx->install_dir);
    free((void*)switchd_ctx->conf_file);
    free(switchd_ctx);
    free(dev_tgt);
    
    printf("\nGSCC Control Plane Test completed\n");
    return 0;
}
