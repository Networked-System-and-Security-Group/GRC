#include "headers.h"
#include "switch_config.h"
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
#define GSCC_EPOCH_DURATION_US 100
#define GSCC_RTT_THRESHOLD_US 20
#define GSCC_AI_STEP_FACTOR 0.1
#define GSCC_MD_FACTOR 0.5
#define GSCC_RATE_LIMIT_FACTOR 1.2
#define GSCC_DECAY_FACTOR 0.9
#define GSCC_EWMA_ALPHA 0.8

// ================ 每个DC的统计信息 ================
typedef struct {
    uint32_t dc_id;
    uint32_t rtt_sum;
    uint32_t rtt_count;
    uint32_t min_rtt_us;
    uint32_t current_rtt_us;
    uint32_t predicted_rtt_us;
    double rtt_diff_ewma;
    uint32_t real_bytes;
    uint32_t ref_rate_bps;
    uint32_t ref_bytes;
    uint32_t last_real_bytes;
    uint32_t actual_rate_bps;
    bool is_congested;
    bool was_congested;
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

/*
 * @brief 设置一个寄存器，获取其表句柄、key/data句柄和字段ID (增强错误处理)
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
void register_read(const bf_rt_target_t *dev_tgt_ptr,
                   const bf_rt_session_hdl *session_hdl,
                   const bf_rt_table_hdl *reg,
                   register_info_t *reg_info,
                   register_entry_t *reg_entry) {
    bf_status_t bf_status;
    bf_rt_entry_read_flag_e read_flag = ENTRY_READ_FROM_HW;

    // Reset key and data handles
    bf_rt_table_key_reset(reg, reg_info->key);
    bf_rt_table_data_reset(reg, reg_info->data);
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
                                      reg_info->key,
                                      reg_info->data,   /* 单层指针 */
                                      read_flag);
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
void register_write(const bf_rt_target_t *dev_tgt_ptr,
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

    bf_rt_table_key_reset(reg, reg_info->key);
    bf_rt_table_data_reset(reg, reg_info->data);

    bf_status = bf_rt_key_field_set_value(reg_info->key, reg_info->kid_register_index, reg_entry->register_index);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: bf_rt_key_field_set_value failed (index: %u)\n", reg_entry->register_index);
        exit(1);
    }
    
    bf_status = bf_rt_data_field_set_value(reg_info->data, reg_info->did_value, reg_entry->value);
    if (bf_status != BF_SUCCESS) {
        fprintf(stderr, "ERROR: register_write: bf_rt_data_field_set_value failed (index: %u, value: %lu)\n", reg_entry->register_index, reg_entry->value);
        exit(1);
    }
    
    bf_status = bf_rt_table_entry_mod(reg, session_hdl, dev_tgt_ptr, reg_info->key, reg_info->data);
    if (bf_status != BF_SUCCESS) {
        bf_status = bf_rt_table_entry_add(reg, session_hdl, dev_tgt_ptr, flags, reg_info->key, reg_info->data);
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
    uint32_t current_avg_rtt = rtt_sum / rtt_count;
    dc->current_rtt_us = current_avg_rtt;
    if (dc->min_rtt_us == 0 || current_avg_rtt < dc->min_rtt_us) {
        dc->min_rtt_us = current_avg_rtt;
    }
    int32_t rtt_diff = (int32_t)current_avg_rtt - (int32_t)dc->min_rtt_us;
    dc->rtt_diff_ewma = GSCC_EWMA_ALPHA * rtt_diff + (1.0 - GSCC_EWMA_ALPHA) * dc->rtt_diff_ewma;
    dc->predicted_rtt_us = dc->min_rtt_us + (uint32_t)dc->rtt_diff_ewma;
    dc->was_congested = dc->is_congested;
    dc->is_congested = (current_avg_rtt > dc->min_rtt_us + GSCC_RTT_THRESHOLD_US);
    printf("[DC %u] RTT: curr=%u, min=%u, diff_ewma=%.2f, congested=%s\n",
           dc->dc_id, dc->current_rtt_us, dc->min_rtt_us, dc->rtt_diff_ewma,
           dc->is_congested ? "YES" : "NO");
}

static void calculate_reference_rate(dc_stats_t *dc, uint64_t epoch_duration_us) {
    uint32_t old_ref_rate = dc->ref_rate_bps;
    if (!dc->is_congested) {
        uint32_t ai_step = (uint32_t)(GSCC_AI_STEP_FACTOR * dc->min_rtt_us * 1000000.0 / epoch_duration_us);
        dc->ref_rate_bps += ai_step;
        printf("[DC %u] AI: +%u bps\n", dc->dc_id, ai_step);
    } else {
        dc->ref_rate_bps = (uint32_t)(dc->ref_rate_bps * GSCC_MD_FACTOR);
        printf("[DC %u] MD: x%.2f -> %u bps\n", dc->dc_id, GSCC_MD_FACTOR, dc->ref_rate_bps);
    }
    uint32_t max_allowed_rate = (uint32_t)(dc->actual_rate_bps * GSCC_RATE_LIMIT_FACTOR);
    if (dc->ref_rate_bps > max_allowed_rate && dc->actual_rate_bps > 0) {
        dc->ref_rate_bps = (uint32_t)(dc->ref_rate_bps * GSCC_DECAY_FACTOR);
        printf("[DC %u] Rate limiting: decay to %u bps (max_allowed=%u)\n", 
               dc->dc_id, dc->ref_rate_bps, max_allowed_rate);
    }
    if (dc->ref_rate_bps < 1000) {
        dc->ref_rate_bps = 1000;
    }
    printf("[DC %u] Reference rate: %u -> %u bps\n", dc->dc_id, old_ref_rate, dc->ref_rate_bps);
}

static void update_reference_bytes(dc_stats_t *dc, uint64_t epoch_duration_us) {
    dc->ref_bytes += (uint32_t)(dc->ref_rate_bps * epoch_duration_us / 1000000.0);
    printf("[DC %u] Reference bytes updated: %u (+%u for %lu us)\n",
           dc->dc_id, dc->ref_bytes, 
           (uint32_t)(dc->ref_rate_bps * epoch_duration_us / 1000000.0),
           epoch_duration_us);
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
    printf("\n=== Processing DC %u (epoch: %lu us) ===\n", dc_id, epoch_duration_us);

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

    // --- 步骤 5: 计算实际速率 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 5 - Calculating actual rate (last_real_bytes = %u)...\n", dc_id, dc->last_real_bytes);
    uint32_t bytes_sent = current_real_bytes - dc->last_real_bytes;
    dc->actual_rate_bps = (uint32_t)(bytes_sent * 1000000.0 / epoch_duration_us);
    dc->last_real_bytes = current_real_bytes;
    printf("[DC %u] Actual rate: %u bps (%u bytes in %lu us)\n",
           dc_id, dc->actual_rate_bps, bytes_sent, epoch_duration_us);

    // --- 步骤 6: 计算新的参考速率 ---
    fprintf(stderr, "[DEBUG] DC %u: Step 6 - Calculating new reference rate...\n", dc_id);
    calculate_reference_rate(dc, epoch_duration_us);
    fprintf(stderr, "[DEBUG] DC %u: New reference rate calculated: %u bps.\n", dc_id, dc->ref_rate_bps);

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
        dc_stats[i].ref_rate_bps = 1000000;
    }
    bf_status_t status = setup_p4_register_tables();
    if (status != BF_SUCCESS) {
        fprintf(stderr, "Failed to setup P4 register tables\n");
        return status;
    }
    
    // 增加额外的检查，确保所有表句柄都有效
    if (rtt_sum_reg_table == NULL || rtt_count_reg_table == NULL ||
        real_bytes_reg_table == NULL || ref_bytes_reg_table == NULL) {
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
    printf("Epoch duration: %d us\n", GSCC_EPOCH_DURATION_US);
    printf("RTT threshold: %d us\n", GSCC_RTT_THRESHOLD_US);
    pthread_mutex_lock(&stats_mutex);
    for (int i = 0; i < MAX_DC_COUNT; i++) {
        dc_stats_t *dc = &dc_stats[i];
        if (dc->last_update_time_us > 0) {
            printf("\n--- DC %d ---\n", i);
            printf("  RTT: curr=%u, min=%u, diff_ewma=%.2f\n", 
                   dc->current_rtt_us, dc->min_rtt_us, dc->rtt_diff_ewma);
            printf("  Rate: ref=%u, actual=%u bps\n", 
                   dc->ref_rate_bps, dc->actual_rate_bps);
            printf("  Bytes: ref=%u, real=%u\n", 
                   dc->ref_bytes, dc->real_bytes);
            printf("  Congested: %s\n", dc->is_congested ? "YES" : "NO");
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
    snprintf(conf_file, sizeof(conf_file), "%s/share/p4/targets/tofino/%s.conf",
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
