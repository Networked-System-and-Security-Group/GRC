/* P4_16 - Corrected Version */

#include <core.p4>
#include <t2na.p4>

// Assuming these files contain the necessary header and constant definitions
#include "header.p4"
#include "testbed.p4"
#include "util.p4"

#define REGISTER_SIZE 1024

/*************************************************************************
 ************** I N G R E S S  P R O C E S S I N G *******************
 *************************************************************************/

/******** G L O B A L  M E T A D A T A *********/
struct gs_probe_pair_t { bit<32> psn; bit<32> scratch; }
struct gs_control_pair_t { bit<32> sum; bit<32> count; }
struct gs_sum64_t { bit<32> lo; bit<32> hi; }

struct gs_my_ingress_metadata_t {
    bit<1> gs_probe_valid;
    bit<3> gs_packet_kind;
    bit<3> gs_ack_syndrome;
    bit<32> gs_pkt_timestamp; // 新增：记录时间戳
    bit<16> gs_l4_src_port;
    bit<16> gs_l4_dst_port;
    // [P4SORT] 语义已改为 **d = ackreq 存下的 PSN − 当前 ACK 的 PSN**：
    // 减法只能在 stateful ALU（stage 8 的 gs_read_id_action）里做，那个
    // action 的 out 就是这个字段，所以这里装的是差值而不是 PSN 本身。
    bit<32> gs_rtt_stored_id; // [P4SORT] d = ackreq.PSN − ACK.PSN
    bit<32> gs_rtt_send_ts;   // 新增：RTT匹配用
    bit<32> gs_rtt_seq_id_hash; // 新增：RTT匹配用
    // 解释：新增一个元数据字段用于存放哈希计算结果，以绕过编译器内部错误。
    bit<32> gs_flow_index0;
    // FIX: Add a temporary field to break down complex operations and avoid internal compiler errors.
    bit<32> gs_temp_hash_result;
    // 解释：新增一个标志位，在Parser中设置，用于简化apply块中的条件判断，以规避编译器内部错误。
    bit<1> is_ip_tcp_udp;
    bit<1> gs_is_roce;
    // FIX: Add new metadata fields for staged RTT calculation.
    bit<32> gs_rtt_hash_val;
    bit<32> gs_rtt_entry_idx;
    bit<32> gs_rtt_dc_idx;
    bit<32> gs_rtt_tuple_ip_low;
    bit<32> gs_rtt_tuple_ip_high;
    bit<16> gs_rtt_tuple_port_low;
    bit<16> gs_rtt_tuple_port_high;
    // FIX: Add a temporary field to simplify register write actions.
    bit<32> gs_temp_seq_id_hash;
    // FIX: Add fields for pre-calculated RTT values to avoid binary operations in register writes
    bit<32> gs_calculated_rtt;
    bit<32> gs_new_rtt_sum;
    bit<32> gs_new_rtt_count;
    // FIX: Add separate metadata fields for AckReq and Ack to avoid stage conflicts
    bit<32> gs_ackreq_entry_idx;  // AckReq专用的entry索引
    bit<32> gs_ackreq_dc_idx;     // AckReq专用的DC索引
    bit<32> gs_ack_entry_idx;     // Ack专用的entry索引
    bit<32> gs_ack_dc_idx;
    bit<32> gs_psn_m1;   // ACK 的 PSN - 1
    bit<32> gs_psn_now;  // 当前包的 PSN
    bit<1>  gs_is_ackreq;// 是否要求确认
    // [RTT-STAT] ACK 匹配失败原因分类
    bit<1>  gs_rtt_fail_zero;   // 时间戳槽为 0（没存过 / 被清掉 / 不是数据包）
    bit<1>  gs_rtt_fail_psn;    // 时间戳有效但 PSN 对不上
    // [RTT-STAT] RegisterAction 的 out 参数占位（值不用）
    bit<32> gs_dummy_ack_total;
    bit<32> gs_dummy_fail_zero;
    bit<32> gs_dummy_fail_psn;
    bit<32> gs_dummy_rtt_ok;
    bit<32> gs_dummy_ackreq;
    // [P4SORT] PSN 偏移直方图的桶号 / 符号位。
    // 必须落到 metadata 再喂给 RegisterAction.execute()：TNA 要求 stateful
    // ALU 的索引是"简单"表达式（PHV 字段或常量），直接写三元表达式会报
    // "The index is too complex for the primitive to be handled."。
    // 位宽按寄存器大小给（16 桶 -> 4 bit，2 项 -> 1 bit）：
    // PHV 是按 bit 分配的，写 bit<32> 会白占 59 bit 并被 allocator 拒绝。
    bit<8> gs_off_bucket;   // signed intervals; full-width key, no folding
    bit<1> gs_off_sign;
    bit<8>  gs_opcode_md;// BTH opcode 副本

    // 速率控制相关字段
    bit<32> gs_dst_dc_id;        // 目标DC ID
    bit<32> gs_packet_bytes;     // 当前包字节数
    bit<32> gs_real_bytes;       // 实际发送字节数
    bit<32> gs_ref_bytes;        // 参考字节数
    bit<32> gs_bytes_diff;       // 字节差值
    bit<1>  gs_should_send_cnp;  // 是否应该发送CNP
    bit<32> gs_red_sample_hash;
    bit<5> gs_red_threshold5;
    bit<1> gs_red_backlog_negative;
    bit<16> gs_red_backlog_class_hi;
    bit<15> gs_red_backlog_class_lo;
    bit<32> gs_packet_count;
    bit<32> gs_cnp_count;

    // CNP生成需要的mirror字段
    MirrorId_t gs_ing_mir_ses;   // Mirror session ID
    bit<8> gs_pkt_type;          // 包类型
}
// FIX: Struct definitions must end with a semicolon.
;

/*********************** P A R S E R **************************/
parser gs_IngressParser(packet_in gs_pkt,
                        /* User */
                        out gs_my_ingress_headers_t gs_hdr,
                        out gs_my_ingress_metadata_t gs_meta,
                        /* Intrinsic */
                        out ingress_intrinsic_metadata_t gs_ig_intr_md)
{
    gs_TofinoIngressParser() gs_tofino_parser;

    state start {
        // FIX: Initialize all fields of the 'out' parameter to avoid uninitialized warnings.
        gs_meta.gs_psn_now = 0;
        gs_meta.gs_is_ackreq = 0;
        gs_meta.gs_opcode_md = 0;
        gs_meta.gs_dummy_ackreq = 0;
        gs_meta.gs_off_bucket = 0;
        gs_meta.gs_pkt_timestamp = 0;
        gs_meta.gs_l4_src_port = 0;
        gs_meta.gs_l4_dst_port = 0;
        gs_meta.gs_rtt_stored_id = 0;
        gs_meta.gs_rtt_send_ts = 0;
        gs_meta.gs_rtt_seq_id_hash = 0;
        gs_meta.gs_flow_index0 = 0;
        gs_meta.gs_temp_hash_result = 0;
        gs_meta.is_ip_tcp_udp = 0; // Initialize flag
        gs_meta.gs_is_roce = 0;
        gs_meta.gs_probe_valid = 0;
        gs_meta.gs_packet_kind = 4;
        gs_meta.gs_ack_syndrome = 0;
        // FIX: Initialize new RTT metadata fields.
        gs_meta.gs_rtt_hash_val = 0;
        gs_meta.gs_rtt_entry_idx = 0;
        gs_meta.gs_rtt_dc_idx = 0;
        gs_meta.gs_rtt_tuple_ip_low = 0;
        gs_meta.gs_rtt_tuple_ip_high = 0;
        gs_meta.gs_rtt_tuple_port_low = 0;
        gs_meta.gs_rtt_tuple_port_high = 0;
        gs_meta.gs_temp_seq_id_hash = 0;
        gs_meta.gs_calculated_rtt = 0;
        gs_meta.gs_new_rtt_sum = 0;
        gs_meta.gs_new_rtt_count = 0;
        gs_meta.gs_ackreq_entry_idx = 0;
        gs_meta.gs_ackreq_dc_idx = 0;
        gs_meta.gs_ack_entry_idx = 0;
        gs_meta.gs_ack_dc_idx = 0;

        // 初始化速率控制字段
        gs_meta.gs_dst_dc_id = 0;
        gs_meta.gs_packet_bytes = 0;
        gs_meta.gs_real_bytes = 0;
        gs_meta.gs_ref_bytes = 0;
        gs_meta.gs_bytes_diff = 0;
        gs_meta.gs_should_send_cnp = 0;
        gs_meta.gs_red_sample_hash = 0;
        gs_meta.gs_red_threshold5 = 0;
        gs_meta.gs_red_backlog_negative = 0;
        gs_meta.gs_red_backlog_class_hi = 0;
        gs_meta.gs_red_backlog_class_lo = 0;
        gs_meta.gs_packet_count = 0;
        gs_meta.gs_cnp_count = 0;
        gs_meta.gs_ing_mir_ses = (MirrorId_t)0;
        gs_meta.gs_pkt_type = 0;


        gs_tofino_parser.apply(gs_pkt, gs_ig_intr_md);
        transition gs_parse_ethernet;
    }

    state gs_parse_ethernet {
        gs_pkt.extract(gs_hdr.gs_ethernet);
        transition select(gs_hdr.gs_ethernet.gs_ether_type) {
            GS_ETHERTYPE_IPV4:  gs_parse_ipv4;
            GS_ETHERTYPE_ARP:   gs_parse_arp;
            default: accept;
        }
    }

    state gs_parse_ipv4 {
        gs_pkt.extract(gs_hdr.gs_ipv4);
        transition select(gs_hdr.gs_ipv4.gs_protocol) {
            GS_IP_PROTOCOLS_TCP:    gs_parse_tcp;
            GS_IP_PROTOCOLS_UDP:    gs_parse_udp;
            default: accept;
        }
    }

    state gs_parse_arp {
        gs_pkt.extract(gs_hdr.gs_arp);
        transition accept;
    }

    state gs_parse_tcp {
        gs_pkt.extract(gs_hdr.gs_tcp);
        gs_meta.gs_l4_src_port = gs_hdr.gs_tcp.gs_src_port;
        gs_meta.gs_l4_dst_port = gs_hdr.gs_tcp.gs_dst_port;
        gs_meta.is_ip_tcp_udp = 1; // Set flag for valid TCP over IP packet
        transition accept;
    }

    state gs_parse_udp {
        gs_pkt.extract(gs_hdr.gs_udp);
        gs_meta.gs_l4_src_port = gs_hdr.gs_udp.gs_src_port;
        gs_meta.gs_l4_dst_port = gs_hdr.gs_udp.gs_dst_port;
        gs_meta.is_ip_tcp_udp = 1; // Set flag for valid UDP over IP packet
        transition select(gs_hdr.gs_udp.gs_dst_port) {
            GS_UDP_ROCE_DST_PORT: gs_parse_bth;
            default: accept;
        }
    }

    state gs_parse_bth {
        gs_pkt.extract(gs_hdr.gs_bth);
        gs_meta.gs_is_roce = 1;
        // 把 BTH 里后面要用的字段搬到 metadata。放 parser 里做不占用 ingress stage。
        gs_meta.gs_psn_now = 0; // Set by gs_prepare_psn_table, with a real 32-bit mask.

        gs_meta.gs_opcode_md = gs_hdr.gs_bth.gs_opcode;
        transition select(gs_hdr.gs_bth.gs_opcode) {
            6 .. 11: gs_mark_write;
            17: gs_peek_aeth;
            129: gs_mark_cnp;
            default: accept;
        }
    }
    state gs_mark_write { gs_meta.gs_packet_kind = 0; gs_meta.gs_is_ackreq = gs_hdr.gs_bth.gs_psn_word[31:31]; transition accept; }
    state gs_mark_cnp { gs_meta.gs_packet_kind = 3; transition accept; }
    state gs_peek_aeth {
        bit<32> aeth = gs_pkt.lookahead<bit<32>>();
        gs_meta.gs_ack_syndrome = aeth[31:29];
        transition select(aeth[31:29]) { 0: gs_mark_ack; default: gs_mark_nak; }
    }
    state gs_mark_ack { gs_meta.gs_packet_kind = 1; transition accept; }
    state gs_mark_nak {
        gs_meta.gs_packet_kind = 2;
        transition accept;
    }
}

/*********************** M A U **************************/
control gs_Ingress(
    /* User */
    inout gs_my_ingress_headers_t gs_hdr,
    inout gs_my_ingress_metadata_t gs_meta,
    /* Intrinsic */
    in    ingress_intrinsic_metadata_t gs_ig_intr_md,
    in    ingress_intrinsic_metadata_from_parser_t gs_ig_prsr_md,
    inout ingress_intrinsic_metadata_for_deparser_t gs_ig_dprsr_md,
    inout ingress_intrinsic_metadata_for_tm_t gs_ig_tm_md) {

    // rixin: 确保可通信
    action gs_forward(PortId_t gs_egress_port) {
        gs_ig_tm_md.ucast_egress_port = gs_egress_port;
    }

    table gs_l3_table {
        key = {
            gs_hdr.gs_ipv4.gs_dst_addr : exact;
        }
        actions = {
            gs_forward;
            @defaultonly NoAction;
        }
        size = GS_HOST_IF_NUM;
        const entries = {
            GSCC_CLIENT_IPV4: gs_forward(GSCC_CLIENT_PORT);
            GSCC_SERVER_IPV4: gs_forward(GSCC_SERVER_PORT);
        }
    }

    table gs_arp_table {
        key = {
            gs_hdr.gs_arp.gs_dstIpv4Addr : exact;
        }
        actions = {
            gs_forward;
            @defaultonly NoAction;
        }
        size = GS_HOST_IF_NUM;
        const entries = {
            GSCC_CLIENT_IPV4: gs_forward(GSCC_CLIENT_PORT);
            GSCC_SERVER_IPV4: gs_forward(GSCC_SERVER_PORT);
        }
    }

    // ====== 定义register，明确指定值和索引类型 ======
    Register<bit<32>, bit<32>>(REGISTER_SIZE, 0) gs_flow_timestamp_reg;

    // ====== 使用Hash（大写H）功能来解决所有编译错误 ======
    Hash<bit<32>>(HashAlgorithm_t.CRC32) gs_flow_hasher;
    // FIX: Add a new hasher for RTT logic.
    Hash<bit<32>>(HashAlgorithm_t.CRC32) gs_rtt_hasher;
    Hash<bit<32>>(HashAlgorithm_t.CRC32) gs_red_sample_hasher;



    // ====== 合并Stage 0-1：时间戳和哈希计算 ======
    @stage(0)
    action gs_set_timestamp_and_calc_hash() {
        gs_meta.gs_pkt_timestamp = gs_ig_intr_md.ingress_mac_tstamp[31:0];
        gs_meta.gs_temp_hash_result = gs_flow_hasher.get({
            gs_hdr.gs_ipv4.gs_src_addr,
            gs_hdr.gs_ipv4.gs_dst_addr,
            (bit<32>)gs_meta.gs_l4_src_port,
            (bit<32>)gs_meta.gs_l4_dst_port
        });

        // 速率控制初始化
        gs_meta.gs_packet_bytes = (bit<32>)gs_hdr.gs_ipv4.gs_total_len;
        gs_meta.gs_dst_dc_id = GS_ACTIVE_DC_ID;
        gs_meta.gs_should_send_cnp = 0;
    }
    @stage(0)
    table gs_set_timestamp_and_calc_hash_table {
        key = {
            gs_hdr.gs_ipv4.isValid(): exact;
        }
        actions = { gs_set_timestamp_and_calc_hash; @defaultonly NoAction; }
        size = 2;
        const entries = {
            true: gs_set_timestamp_and_calc_hash();
        }
        default_action = NoAction();
    }

    @stage(0)
    action gs_set_rtt_tuple_forward() {
        gs_meta.gs_rtt_tuple_ip_low = gs_hdr.gs_ipv4.gs_src_addr;
        gs_meta.gs_rtt_tuple_ip_high = gs_hdr.gs_ipv4.gs_dst_addr;
        gs_meta.gs_rtt_tuple_port_low = gs_meta.gs_l4_src_port;
        gs_meta.gs_rtt_tuple_port_high = gs_meta.gs_l4_dst_port;
    }

    @stage(0)
    action gs_set_rtt_tuple_reverse() {
        gs_meta.gs_rtt_tuple_ip_low = gs_hdr.gs_ipv4.gs_dst_addr;
        gs_meta.gs_rtt_tuple_ip_high = gs_hdr.gs_ipv4.gs_src_addr;
        gs_meta.gs_rtt_tuple_port_low = gs_meta.gs_l4_dst_port;
        gs_meta.gs_rtt_tuple_port_high = gs_meta.gs_l4_src_port;
    }

    @stage(0)
    table gs_canonicalize_rtt_tuple_table {
        key = {
            gs_hdr.gs_ipv4.gs_src_addr: exact;
            gs_hdr.gs_ipv4.gs_dst_addr: exact;
        }
        actions = {
            gs_set_rtt_tuple_forward;
            gs_set_rtt_tuple_reverse;
        }
        size = 4;
        const entries = {
            (GSCC_CLIENT_IPV4, GSCC_SERVER_IPV4): gs_set_rtt_tuple_forward();
            (GSCC_SERVER_IPV4, GSCC_CLIENT_IPV4): gs_set_rtt_tuple_reverse();
        }
        default_action = gs_set_rtt_tuple_forward();
    }

    // ====== Stage 1：只计算索引 ======
    @stage(1)
    action gs_calc_flow_index() {
        gs_meta.gs_flow_index0 = gs_meta.gs_temp_hash_result & (REGISTER_SIZE - 1);
        gs_meta.gs_red_sample_hash = gs_red_sample_hasher.get({
            gs_meta.gs_temp_hash_result,
            gs_meta.gs_pkt_timestamp
        });
    }
    @stage(1)
    table gs_calc_flow_index_table {
        key = { gs_hdr.gs_ipv4.isValid(): exact; }
        actions = { gs_calc_flow_index; @defaultonly NoAction; }
        size = 2;
        const entries = { true: gs_calc_flow_index(); }
        default_action = NoAction();
    }

    // ====== Stage 2：记录时间戳 ======
    @stage(2)
    action gs_record_timestamp() {
        gs_flow_timestamp_reg.write(gs_meta.gs_flow_index0, gs_meta.gs_pkt_timestamp);
    }
    @stage(2)
    table gs_record_timestamp_table {
        key = { gs_meta.is_ip_tcp_udp: exact; }
        actions = { gs_record_timestamp; @defaultonly NoAction; }
        size = 2;
        const entries = {
            1 : gs_record_timestamp();  // 只有当is_ip_tcp_udp为1时才记录时间戳
        }
        default_action = NoAction();
    }


    // ====== 新增：RTT测量相关寄存器和哈希 ======
    const bit<32> GS_RTT_TABLE_SIZE = 65536;
    const bit<32> GS_RTT_INDEX_MASK = GS_RTT_TABLE_SIZE - 1;
    // 论文的桶数 = 表项数 / 16；掩码用于取哈希的低位作为桶号
    const bit<32> GS_RTT_BUCKET_MASK = GS_RTT_TABLE_SIZE / 256 - 1;  // 256 slots/bucket
    const bit<32> GS_MAX_DC = 16;
    const int GS_OFF_SHIFT = 8;
    const bit<32> GS_OFF_BUCKETS = 132;
    Register<bit<32>, bit<32>>(GS_RTT_TABLE_SIZE, 0) gs_rtt_timestamp_reg;
    // 0x7f000000 cannot be a valid 24-bit PSN. Timestamp zero is valid.
    Register<gs_probe_pair_t, bit<32>>(GS_RTT_TABLE_SIZE, {0x7f000000, 0}) gs_rtt_id_reg;
    Register<gs_sum64_t, bit<32>>(GS_MAX_DC, {0, 0}) gs_rtt_sum_reg;
    Register<bit<32>, bit<32>>(GS_MAX_DC, 0) gs_rtt_count_reg;
    Register<gs_control_pair_t, bit<32>>(GS_MAX_DC, {0,0}) gs_rtt_control_reg;
    Register<bit<32>, bit<32>>(GS_MAX_DC, 0) gs_rtt_max_reg;
    RegisterAction<gs_control_pair_t, bit<32>, bit<32>>(gs_rtt_control_reg) gs_control_accumulate = {
        void apply(inout gs_control_pair_t v, out bit<32> result) {
            v.sum = v.sum + gs_meta.gs_calculated_rtt;
            v.count = v.count + 1;
            result = v.sum;
        }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_rtt_max_reg) gs_max_rtt = {
        void apply(inout bit<32> v, out bit<32> result) {
            if (v < gs_meta.gs_calculated_rtt) { v = gs_meta.gs_calculated_rtt; }
            result = v;
        }
    };
    Register<bit<32>, bit<3>>(8, 0) gs_packet_kind_reg;
    RegisterAction<bit<32>, bit<3>, bit<32>>(gs_packet_kind_reg) gs_count_kind = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };

    // ====== 速率控制寄存器 ======
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_real_bytes_reg;    // 实际发送字节数
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_ref_bytes_reg;     // 参考字节数
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_pkt_count_reg;
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_cnp_count_reg;
    // [RTT-STAT] ACK 匹配统计：ok / fail_zero / fail_psn / ack_total
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_rtt_ok_cnt_reg;
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_rtt_fail_zero_reg;
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_rtt_fail_psn_reg;
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_ackreq_cnt_reg;
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_ack_total_reg;
    // [ACK-COALESCING] K 直方图（复用 gs_dummy_ackreq 传 K 值，零新增 metadata）
    Register<bit<32>, bit<32>>(RATE_CONTROL_REG_SIZE, 0) gs_ackreq_pending_reg;
    Register<bit<32>, bit<32>>(64, 0) gs_khist_reg;
    // Histogram contains ALL positive ACKs with a valid resident probe.
    Register<bit<32>, bit<8>>(GS_OFF_BUCKETS, 0) gs_off_hist_reg;


    // ====== 速率控制RegisterAction（紧跟寄存器定义，在action使用前）======
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_real_bytes_reg) gs_update_real_bytes_action = {
        void apply(inout bit<32> stored_bytes, out bit<32> new_bytes) {
            stored_bytes = stored_bytes + gs_meta.gs_packet_bytes;
            new_bytes = stored_bytes;
        }
    };

    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_ref_bytes_reg) gs_read_ref_bytes_action = {
        void apply(inout bit<32> stored_bytes, out bit<32> ref_bytes) {
            ref_bytes = stored_bytes;
        }
    };

    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_pkt_count_reg) gs_update_pkt_count_action = {
        void apply(inout bit<32> stored_count, out bit<32> new_count) {
            stored_count = stored_count + 1;
            new_count = stored_count;
        }
    };

    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_cnp_count_reg) gs_update_cnp_count_action = {
        void apply(inout bit<32> stored_count, out bit<32> new_count) {
            stored_count = stored_count + 1;
            new_count = stored_count;
        }
    };

    // [RTT-STAT] 四个计数器，都只做 +1
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_rtt_ok_cnt_reg) gs_inc_rtt_ok_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_rtt_fail_zero_reg) gs_inc_rtt_fail_zero_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_rtt_fail_psn_reg) gs_inc_rtt_fail_psn_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_ackreq_cnt_reg) gs_inc_ackreq_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_ack_total_reg) gs_inc_ack_total_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_ackreq_pending_reg) gs_inc_pending_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_ackreq_pending_reg) gs_read_reset_pending_action = {
        void apply(inout bit<32> c, out bit<32> n) { n = c; c = 0; }
    };
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_khist_reg) gs_inc_khist_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };
    RegisterAction<bit<32>, bit<8>, bit<32>>(gs_off_hist_reg) gs_inc_off_hist_action = {
        void apply(inout bit<32> c, out bit<32> n) { c = c + 1; n = c; }
    };

    // ====== Stage 2：速率控制 - 更新实际字节数（与记录时间戳共用stage）======
    @stage(2)
    action gs_update_real_bytes() {
        gs_meta.gs_real_bytes = gs_update_real_bytes_action.execute(gs_meta.gs_dst_dc_id);
    }

    @stage(2)
    table gs_update_real_bytes_table {
        key = { gs_meta.gs_is_roce: exact; }
        actions = { gs_update_real_bytes; @defaultonly NoAction; }
        size = 2;
        const entries = {
            1 : gs_update_real_bytes();
        }
        default_action = NoAction();
    }

    @stage(13)
    action gs_update_packet_count() {
        gs_meta.gs_packet_count = gs_update_pkt_count_action.execute(gs_meta.gs_dst_dc_id);
    }

    @stage(13)
    table gs_update_packet_count_table {
        key = { gs_meta.gs_is_roce: exact; }
        actions = { gs_update_packet_count; @defaultonly NoAction; }
        size = 2;
        const entries = { 1: gs_update_packet_count(); }
        default_action = NoAction();
    }

    // ====== Stage 3：读取参考字节预算 ======
    @stage(3)
    action gs_read_ref_bytes() {
        gs_meta.gs_ref_bytes = gs_read_ref_bytes_action.execute(gs_meta.gs_dst_dc_id);
    }

    @stage(3)
    table gs_read_ref_bytes_table {
        key = { gs_meta.gs_is_roce: exact; }
        actions = { gs_read_ref_bytes; @defaultonly NoAction; }
        size = 2;
        const entries = {
            1 : gs_read_ref_bytes();
        }
        default_action = NoAction();
    }

    // ====== Algorithm 3: RED probability and CNP generation ======
    @stage(11)
    action gs_compute_red_probability() {
        bit<32> red_excess = gs_meta.gs_bytes_diff - GS_RED_KMIN_BYTES;
        bit<32> red_scaled = (red_excess << 4) + red_excess;
        gs_meta.gs_red_threshold5 = (bit<5>)(red_scaled >> 23);
    }

    @stage(11)
    action gs_set_red_probability_max() {
        gs_meta.gs_red_threshold5 = GS_RED_PMAX_5BIT;
    }

    @stage(11)
    table gs_red_probability_table {
        key = {
            gs_meta.gs_red_backlog_negative: exact;
            gs_meta.gs_red_backlog_class_hi: range;
            gs_meta.gs_red_backlog_class_lo: range;
        }
        actions = {
            gs_compute_red_probability;
            gs_set_red_probability_max;
            @defaultonly NoAction;
        }
        size = 4;
        const entries = {
            (1w0, 16w3 .. 16w3, 15w1696 .. 15w32767): gs_compute_red_probability();
            (1w0, 16w4 .. 16w243, 15w0 .. 15w32767): gs_compute_red_probability();
            (1w0, 16w244 .. 16w32767, 15w0 .. 15w32767): gs_set_red_probability_max();
        }
        default_action = NoAction();
    }

    @stage(12)
    action gs_generate_cnp() {
        gs_meta.gs_should_send_cnp = 1;
        gs_meta.gs_ing_mir_ses = (MirrorId_t)GS_CNP_SES_ID;
        gs_meta.gs_pkt_type = GS_PKT_TYPE_MIRROR;
        gs_meta.gs_cnp_count = gs_update_cnp_count_action.execute(GS_ACTIVE_DC_ID);
        gs_hdr.gs_ipv4.gs_ecn = 2w0;
    }

    @stage(12)
    table gs_generate_cnp_table {
        key = {
            gs_meta.gs_is_roce: exact;
            gs_hdr.gs_bth.isValid(): exact;
            gs_hdr.gs_bth.gs_opcode: range;
            gs_hdr.gs_ipv4.gs_ecn: range;
            gs_meta.gs_red_threshold5: range;
            gs_meta.gs_red_sample_hash[7:3]: range;
        }
        actions = { gs_generate_cnp; @defaultonly NoAction; }
        size = 32;
        const entries = {
            (1, true, 8w0 .. 8w12, 2w3 .. 2w3, 5w0 .. 5w16, 5w0 .. 5w31): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w1 .. 5w1, 5w0 .. 5w0): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w2 .. 5w2, 5w0 .. 5w1): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w3 .. 5w3, 5w0 .. 5w2): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w4 .. 5w4, 5w0 .. 5w3): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w5 .. 5w5, 5w0 .. 5w4): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w6 .. 5w6, 5w0 .. 5w5): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w7 .. 5w7, 5w0 .. 5w6): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w8 .. 5w8, 5w0 .. 5w7): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w9 .. 5w9, 5w0 .. 5w8): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w10 .. 5w10, 5w0 .. 5w9): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w11 .. 5w11, 5w0 .. 5w10): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w12 .. 5w12, 5w0 .. 5w11): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w13 .. 5w13, 5w0 .. 5w12): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w14 .. 5w14, 5w0 .. 5w13): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w15 .. 5w15, 5w0 .. 5w14): gs_generate_cnp();
            (1, true, 8w0 .. 8w12, 2w0 .. 2w2, 5w16 .. 5w16, 5w0 .. 5w15): gs_generate_cnp();
        }
        default_action = NoAction();
    }

    // Scope the instrument to this testbed; retain IP-pair hashing across QPs.
    action gs_exclude_background() {
        gs_meta.gs_packet_kind = 5;
        gs_meta.gs_is_roce = 0;
    }
    table gs_scope_table {
        key = { gs_meta.gs_packet_kind: exact;
                gs_hdr.gs_ipv4.gs_src_addr: exact;
                gs_hdr.gs_ipv4.gs_dst_addr: exact;
                gs_ig_intr_md.ingress_port: exact; }
        actions = { NoAction; gs_exclude_background; }
        const entries = {
            (0, GSCC_CLIENT_IPV4, GSCC_SERVER_IPV4, GSCC_CLIENT_PORT): NoAction();
            (1, GSCC_SERVER_IPV4, GSCC_CLIENT_IPV4, GSCC_SERVER_PORT): NoAction();
            (2, GSCC_SERVER_IPV4, GSCC_CLIENT_IPV4, GSCC_SERVER_PORT): NoAction();
            (3, GSCC_SERVER_IPV4, GSCC_CLIENT_IPV4, GSCC_SERVER_PORT): NoAction();
            (4, GSCC_CLIENT_IPV4, GSCC_SERVER_IPV4, GSCC_CLIENT_PORT): NoAction();
            (4, GSCC_SERVER_IPV4, GSCC_CLIENT_IPV4, GSCC_SERVER_PORT): NoAction();
        }
        size = 8;
        default_action = gs_exclude_background();
    }

    // Mask a full wire word, rather than casting a 24-bit field whose physical
    // container also holds AckReq. SALU consumes a complete 32-bit PHV word.
    action gs_prepare_psn() {
        gs_meta.gs_psn_now = gs_hdr.gs_bth.gs_psn_word & 32w0x00ffffff;
    }
    table gs_prepare_psn_table {
        actions = { gs_prepare_psn; }
        const default_action = gs_prepare_psn();
        size = 1;
    }

    // Each probe register has ONE access site. Multiple stage-constrained
    // sites were split by SDE 9.7.1 and executed a default write on non-RoCE.
    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_rtt_timestamp_reg) gs_probe_ts_action = {
        void apply(inout bit<32> value, out bit<32> timestamp) {
            if (gs_meta.gs_is_ackreq == 1) { value = gs_meta.gs_pkt_timestamp; }
            timestamp = value;
        }
    };
    RegisterAction<gs_probe_pair_t, bit<32>, bit<32>>(gs_rtt_id_reg) gs_probe_id_action = {
        void apply(inout gs_probe_pair_t value, out bit<32> off_d) {
            if (gs_meta.gs_is_ackreq == 1) { value.psn = gs_meta.gs_psn_now; }
            else { value.scratch = value.psn - gs_meta.gs_psn_now; }
            off_d = value.scratch;
        }
    };
    // Carry is tested on the OLD low word. No control-plane clear during traffic.
    RegisterAction<gs_sum64_t, bit<32>, bit<32>>(gs_rtt_sum_reg) gs_update_sum_action = {
        void apply(inout gs_sum64_t value, out bit<32> result) {
            if (value.lo > (32w0xffffffff - gs_meta.gs_calculated_rtt)) {
                value.hi = value.hi + 1;
            }
            value.lo = value.lo + gs_meta.gs_calculated_rtt;
            result = value.lo;
        }
    };


    RegisterAction<bit<32>, bit<32>, bit<32>>(gs_rtt_count_reg) gs_update_count_action = {
        void apply(inout bit<32> stored_count, out bit<32> new_count) {
            stored_count = stored_count + 1;
            new_count = stored_count;
    }
    };



    // ====== 速率控制逻辑集成到现有stage ======

    // ====== Stage 3：RTT哈希计算 ======
    @stage(3)
    action gs_calc_rtt_hash() {
        // RoCEv2 的 ACK 和数据包不互为反向五元组（两者 dport 都是 4791，
        // sport 是网卡算的哈希），所以只用 IP 对做桶哈希。
        gs_meta.gs_rtt_hash_val = gs_rtt_hasher.get({
            gs_meta.gs_rtt_tuple_ip_low,
            gs_meta.gs_rtt_tuple_ip_high
        });
    }
    @stage(3)
    table gs_calc_rtt_hash_table {
        actions = { gs_calc_rtt_hash; }
        size = 1;
        const default_action = gs_calc_rtt_hash();
    }

    action gs_calc_probe_index() {
        gs_meta.gs_rtt_entry_idx =
            ((gs_meta.gs_rtt_hash_val & GS_RTT_BUCKET_MASK) << 8)
            | (bit<32>)gs_meta.gs_psn_now[7:0];
    }
    table gs_calc_probe_index_table {
        actions = { gs_calc_probe_index; }
        const default_action = gs_calc_probe_index();
        size = 1;
    }
    action gs_probe_timestamp() {
        gs_meta.gs_rtt_send_ts = gs_probe_ts_action.execute(gs_meta.gs_rtt_entry_idx);
    }
    table gs_probe_timestamp_table {
        actions = { gs_probe_timestamp; }
        const default_action = gs_probe_timestamp();
        size = 1;
    }
    action gs_probe_id() {
        gs_meta.gs_rtt_stored_id = gs_probe_id_action.execute(gs_meta.gs_rtt_entry_idx);
    }
    table gs_probe_id_table {
        actions = { gs_probe_id; }
        const default_action = gs_probe_id();
        size = 1;
    }

    // ====== [ACKREQ-STAT] Stage 6：统计 ack_req 包总数 ======
    @stage(6)
    action gs_inc_ackreq() {
        gs_meta.gs_dummy_ackreq = gs_inc_ackreq_action.execute(gs_meta.gs_ackreq_dc_idx);
    }
    @stage(6)
    table gs_inc_ackreq_table {
        key = { gs_meta.gs_is_ackreq: exact; }
        actions = { gs_inc_ackreq; @defaultonly NoAction; }
        size = 2;
        const entries = { 1 : gs_inc_ackreq(); }
        default_action = NoAction();
    }
    @stage(14)
    action gs_inc_pending() {
        gs_inc_pending_action.execute(gs_meta.gs_ackreq_dc_idx);
    }
    @stage(14)
    table gs_inc_pending_table {
        key = { gs_meta.gs_is_ackreq: exact; }
        actions = { gs_inc_pending; @defaultonly NoAction; }
        size = 2;
        const entries = { 1 : gs_inc_pending(); }
        default_action = NoAction();
    }
    @stage(14)
    action gs_read_reset_pending() {
        gs_meta.gs_dummy_ackreq = gs_read_reset_pending_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(14)
    table gs_read_reset_pending_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_read_reset_pending; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_read_reset_pending(); }
        default_action = NoAction();
    }
    @stage(15)
    action gs_inc_khist() {
        gs_inc_khist_action.execute(gs_meta.gs_dummy_ackreq);
    }
    @stage(15)
    table gs_inc_khist_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_inc_khist; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_inc_khist(); }
        default_action = NoAction();
    }

    // ====== [P4SORT] Stage 15：PSN 偏移直方图（只在 fail_psn 分支里调用）======
    //   d = ackreq 存下的 PSN - 当前 ACK 的 PSN   （恒为槽数的整数倍）
    //   bucket = min(|d| >> GS_OFF_SHIFT, 15)     （差了几代槽）
    //   sign   = (d < 0) ? 1 : 0                  （索引 1: ACK 领先, 0: ACK 落后）
    //
    // 两条 TNA 限制决定了这个写法（都踩过）：
    //   1. stateful ALU 的索引只接受"简单"表达式 —— 三元式会报
    //      "The index is too complex for the primitive to be handled."
    //      所以桶号先落到 metadata，再用字段当索引；
    //   2. action 里不允许条件语句 —— 会报
    //      "Conditions in an action must be simple comparisons of an action
    //       data parameter". 所以夹取和下标的计算放在 apply 块里，
    //      action 只做寄存器 +1。
    @stage(13)
    action gs_inc_off_hist() {
        gs_inc_off_hist_action.execute(gs_meta.gs_off_bucket);
    }
    @stage(13)
    table gs_inc_off_hist_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_inc_off_hist; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_inc_off_hist(); }
        default_action = NoAction();
    }


    // Generated full-width signed-modulo-24 classification, including tails.
    action gs_classify_offset(bit<8> bucket, bit<32> hit) {
        gs_meta.gs_off_bucket = bucket;
        gs_meta.gs_rtt_hash_val = hit;
        gs_meta.gs_probe_valid = 1;
    }
    table gs_window_table {
        key = { gs_meta.gs_rtt_stored_id[31:16]: range @name("offset_hi");
                gs_meta.gs_rtt_stored_id[15:0]: range @name("offset_lo"); }
        actions = { gs_classify_offset; @defaultonly NoAction; }
        size = 512;
        const entries = {
            // BEGIN GENERATED OFFSET RANGES
            // END GENERATED OFFSET RANGES
        }
        default_action = NoAction();
    }


    // ====== Stage 9：更新RTT总和 ======
    @stage(9)
    action gs_update_rtt_sum() {
        gs_meta.gs_new_rtt_sum = gs_update_sum_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(9)
    table gs_update_rtt_sum_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_update_rtt_sum; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_update_rtt_sum(); }
        default_action = NoAction();
    }

    // ====== Stage 10：更新RTT计数 ======
    @stage(10)
    action gs_update_rtt_count() {
        gs_meta.gs_new_rtt_count = gs_update_count_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(10)
    table gs_update_rtt_count_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_update_rtt_count; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_update_rtt_count(); }
        default_action = NoAction();
    }

    // ====== [RTT-STAT] Stage 11：ACK 总数 ======
    @stage(11)
    action gs_inc_ack_total() {
        gs_meta.gs_dummy_ack_total = gs_inc_ack_total_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(11)
    table gs_inc_ack_total_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_inc_ack_total; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_inc_ack_total(); }
        default_action = NoAction();
    }

    // ====== [RTT-STAT] Stage 12：时间戳为 0 的失败 ======
    @stage(12)
    action gs_inc_rtt_fail_zero() {
        gs_meta.gs_dummy_fail_zero = gs_inc_rtt_fail_zero_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(12)
    table gs_inc_rtt_fail_zero_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_inc_rtt_fail_zero; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_inc_rtt_fail_zero(); }
        default_action = NoAction();
    }

    // ====== [RTT-STAT] Stage 13：PSN 不等的失败 ======
    @stage(13)
    action gs_inc_rtt_fail_psn() {
        gs_meta.gs_dummy_fail_psn = gs_inc_rtt_fail_psn_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(13)
    table gs_inc_rtt_fail_psn_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_inc_rtt_fail_psn; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_inc_rtt_fail_psn(); }
        default_action = NoAction();
    }



    // ====== [RTT-STAT] Stage 13：成功的 RTT 样本 ======
    @stage(13)
    action gs_inc_rtt_ok() {
        gs_meta.gs_dummy_rtt_ok = gs_inc_rtt_ok_action.execute(gs_meta.gs_ack_dc_idx);
    }
    @stage(13)
    table gs_inc_rtt_ok_table {
        key = { gs_meta.gs_ack_dc_idx: exact; }
        actions = { gs_inc_rtt_ok; @defaultonly NoAction; }
        size = 1;
        const entries = { 32w0: gs_inc_rtt_ok(); }
        default_action = NoAction();
    }

    apply {
        // rixin: 确保可通信
        if (gs_hdr.gs_ipv4.isValid()) {
            gs_l3_table.apply();
        }
        else if (gs_hdr.gs_arp.isValid()) {
            gs_arp_table.apply();
        }

        if (gs_hdr.gs_bth.isValid()) {
            gs_prepare_psn_table.apply();
            gs_scope_table.apply();
            gs_count_kind.execute(gs_meta.gs_packet_kind);
        }
        // Rate and RTT processing are limited to the scoped stream.

        // ====== 记录时间戳、哈希计算和速率控制（Stage 0）======
        gs_set_timestamp_and_calc_hash_table.apply();
        if (gs_hdr.gs_ipv4.isValid()) {
            gs_canonicalize_rtt_tuple_table.apply();
        }

        // ====== 使用在Parser中设置的标志位来简化条件判断，以规避编译器内部错误 ======
        if (gs_meta.is_ip_tcp_udp == 1) {
            // 调用合并后的索引计算和记录表
            gs_calc_flow_index_table.apply();
            // 为了简化，总是调用记录时间戳表
            gs_record_timestamp_table.apply();
            if (gs_meta.gs_is_roce == 1 && gs_meta.gs_packet_kind == 0) {
                // Rate-control counters and CNP decisions are scoped to RoCE traffic.
                gs_update_real_bytes_table.apply();
                gs_read_ref_bytes_table.apply();
                gs_meta.gs_bytes_diff = gs_meta.gs_real_bytes - gs_meta.gs_ref_bytes;
                gs_meta.gs_red_backlog_negative = gs_meta.gs_bytes_diff[31:31];
                gs_meta.gs_red_backlog_class_hi = gs_meta.gs_bytes_diff[30:15];
                gs_meta.gs_red_backlog_class_lo = gs_meta.gs_bytes_diff[14:0];
            }
        }

        // ====== RTT测量逻辑 - 共同预处理 ======
        if (gs_meta.gs_is_roce == 1) {
            // 对所有RoCE包进行哈希计算（总共12个stage：0-11）
            gs_calc_rtt_hash_table.apply();

            if (gs_meta.gs_is_ackreq == 1 || gs_meta.gs_packet_kind == 1) {
                gs_calc_probe_index_table.apply();
                gs_probe_timestamp_table.apply();
                gs_probe_id_table.apply();
            }
            // 根据包类型执行不同的RTT处理逻辑
            if (gs_meta.gs_packet_kind == 0 && gs_hdr.gs_bth.gs_psn_word[31:31] == 1) {
                // AckReq包：计算专用索引，记录发送时间戳和序列号ID
                gs_inc_ackreq_table.apply();
                gs_inc_pending_table.apply();
            } else if (gs_meta.gs_packet_kind == 1) {
                // Ack包：计算专用索引，读取之前存储的发送时间戳，计算RTT，并更新统计信息
                gs_meta.gs_rtt_fail_zero = 0;
                gs_meta.gs_rtt_fail_psn = 0;

                // [RTT-STAT] 只有 ACK opcode(17) 才是"真正的 ACK"，
                // READ 响应、NAK 等不参与统计，否则分母会脏
                if (gs_meta.gs_packet_kind == 1) {
                    gs_inc_ack_total_table.apply();
                    gs_read_reset_pending_table.apply();
                    gs_inc_khist_table.apply();

                    gs_window_table.apply();
                    if (gs_meta.gs_probe_valid == 1) {
                        gs_inc_off_hist_table.apply();
                    }


                    if (gs_meta.gs_probe_valid == 0) {
                        gs_meta.gs_rtt_fail_zero = 1;
                        gs_inc_rtt_fail_zero_table.apply();
                    } else if (gs_meta.gs_rtt_hash_val != 32w1) {  // [WIN2] offset in {0,-16}

                        gs_meta.gs_rtt_fail_psn = 1;
                        gs_inc_rtt_fail_psn_table.apply();
                    } else {
                        gs_meta.gs_calculated_rtt = gs_meta.gs_pkt_timestamp - gs_meta.gs_rtt_send_ts;
                        gs_max_rtt.execute(gs_meta.gs_ack_dc_idx);
                        gs_control_accumulate.execute(gs_meta.gs_ack_dc_idx);
                        gs_update_rtt_sum_table.apply();
                        gs_update_rtt_count_table.apply();
                        gs_inc_rtt_ok_table.apply();
                    }
                }
            }
        }

        // Range matches classify signed backlog intervals without a wide ALU branch.
        gs_red_probability_table.apply();
        gs_generate_cnp_table.apply();
        gs_update_packet_count_table.apply();
    }
}

/********************* D E P A R S E R ************************/
control gs_IngressDeparser(packet_out gs_pkt,
                           /* User */
                           inout gs_my_ingress_headers_t gs_hdr,
                           in    gs_my_ingress_metadata_t gs_meta,
                           /* Intrinsic */
                           in    ingress_intrinsic_metadata_for_deparser_t gs_ig_dprsr_md)
{
    Mirror() gs_mirror;

    apply {
        // 如果需要生成CNP，设置mirror
        if (gs_meta.gs_should_send_cnp == 1) {
            gs_mirror.emit<gs_mirror_h>(gs_meta.gs_ing_mir_ses, {gs_meta.gs_pkt_type});
        }

        // 发出原始包头
        gs_pkt.emit(gs_hdr);
    }
}

/*************************************************************************
 **************** E G R E S S  P R O C E S S I N G *******************
 *************************************************************************/

/******** G L O B A L  E G R E S S  M E T A D A T A *********/
struct gs_my_egress_metadata_t {
    bit<1> gs_is_mirrored; // 用于CNP生成
    bit<8> gs_cnp_dip_hash;
    bit<32> gs_cnp_icrc_raw;
}
// FIX: Struct definitions must end with a semicolon.
;

/*********************** P A R S E R **************************/
parser gs_EgressParser(packet_in gs_pkt,
                       /* User */
                       out gs_my_egress_headers_t gs_hdr,
                       out gs_my_egress_metadata_t gs_meta,
                       /* Intrinsic */
                       out egress_intrinsic_metadata_t gs_eg_intr_md)
{
    gs_TofinoEgressParser() gs_tofino_parser;

    state start {
        // FIX: Initialize all fields of the 'out' parameter to avoid uninitialized warnings.
        gs_meta.gs_is_mirrored = 0;
        gs_meta.gs_cnp_dip_hash = 0;
        gs_meta.gs_cnp_icrc_raw = 0;

        gs_tofino_parser.apply(gs_pkt, gs_eg_intr_md);
        transition gs_parse_metadata;
    }

    state gs_parse_metadata {
        gs_mirror_h gs_mirror_md = gs_pkt.lookahead<gs_mirror_h>();
        transition select(gs_mirror_md.gs_pkt_type) {
            GS_PKT_TYPE_MIRROR : gs_parse_mirror_md;
            GS_PKT_TYPE_NORMAL : gs_parse_bridged_md;
            default : gs_parse_ethernet;   // 普通 RoCE 包没有 shim 头，也要解析以太网
        }
    }

    state gs_parse_bridged_md {
        gs_pkt.extract(gs_hdr.gs_bridged_md);
        transition gs_parse_ethernet;
    }

    state gs_parse_mirror_md {
        gs_pkt.extract(gs_hdr.gs_mirror_md);
        gs_meta.gs_is_mirrored = 1;
        transition gs_parse_ethernet;
    }

    state gs_parse_ethernet {
        gs_pkt.extract(gs_hdr.gs_ethernet);
        transition select(gs_hdr.gs_ethernet.gs_ether_type) {
            GS_ETHERTYPE_IPV4: gs_parse_ipv4;
            default: accept;
        }
    }

    state gs_parse_ipv4 {
        gs_pkt.extract(gs_hdr.gs_ipv4);
        transition select(gs_hdr.gs_ipv4.gs_protocol) {
            GS_IP_PROTOCOLS_UDP: gs_parse_udp;
            default: accept;
        }
    }

    state gs_parse_udp {
        gs_pkt.extract(gs_hdr.gs_udp);
        transition select(gs_hdr.gs_udp.gs_dst_port) {
            GS_UDP_ROCE_DST_PORT: gs_parse_bth;
            default: accept;
        }
    }

    state gs_parse_bth {
        gs_pkt.extract(gs_hdr.gs_bth);
        transition accept;
    }
}

/***************** M A T C H - A C T I O N *********************/
control gs_Egress(
    /* User */
    inout gs_my_egress_headers_t gs_hdr,
    inout gs_my_egress_metadata_t gs_meta,
    /* Intrinsic */
    in    egress_intrinsic_metadata_t gs_eg_intr_md,
    in    egress_intrinsic_metadata_from_parser_t gs_eg_prsr_md,
    inout egress_intrinsic_metadata_for_deparser_t gs_eg_dprsr_md,
    inout egress_intrinsic_metadata_for_output_port_t gs_eg_oport_md)
{
    Hash<bit<8>>(HashAlgorithm_t.CRC8) gs_cnp_dip_hash_calc;
    Hash<bit<32>>(HashAlgorithm_t.CRC32) gs_cnp_icrc_hash_calc;

    @stage(0)
    action gs_calculate_cnp_dip_hash() {
        gs_meta.gs_cnp_dip_hash = gs_cnp_dip_hash_calc.get({gs_hdr.gs_ipv4.gs_dst_addr});
    }
    @stage(0)
    table gs_calculate_cnp_dip_hash_table {
        key = {
            gs_meta.gs_is_mirrored: exact;
            gs_hdr.gs_bth.isValid(): exact;
        }
        actions = { gs_calculate_cnp_dip_hash; @defaultonly NoAction; }
        size = 4;
        const entries = { (1, true): gs_calculate_cnp_dip_hash(); }
        default_action = NoAction();
    }

    @stage(1)
    action gs_swap_cnp_ethernet_addresses() {
        gs_mac_addr_t gs_tmp_mac = gs_hdr.gs_ethernet.gs_dst_addr;
        gs_hdr.gs_ethernet.gs_dst_addr = gs_hdr.gs_ethernet.gs_src_addr;
        gs_hdr.gs_ethernet.gs_src_addr = gs_tmp_mac;
    }
    @stage(1)
    table gs_swap_cnp_ethernet_addresses_table {
        key = {
            gs_meta.gs_is_mirrored: exact;
            gs_hdr.gs_bth.isValid(): exact;
        }
        actions = { gs_swap_cnp_ethernet_addresses; @defaultonly NoAction; }
        size = 4;
        const entries = { (1, true): gs_swap_cnp_ethernet_addresses(); }
        default_action = NoAction();
    }

    @stage(2)
    action gs_swap_cnp_ipv4_addresses() {
        gs_ipv4_addr_t gs_tmp_ip = gs_hdr.gs_ipv4.gs_dst_addr;
        gs_hdr.gs_ipv4.gs_dst_addr = gs_hdr.gs_ipv4.gs_src_addr;
        gs_hdr.gs_ipv4.gs_src_addr = gs_tmp_ip;
    }
    @stage(2)
    table gs_swap_cnp_ipv4_addresses_table {
        key = {
            gs_meta.gs_is_mirrored: exact;
            gs_hdr.gs_bth.isValid(): exact;
        }
        actions = { gs_swap_cnp_ipv4_addresses; @defaultonly NoAction; }
        size = 4;
        const entries = { (1, true): gs_swap_cnp_ipv4_addresses(); }
        default_action = NoAction();
    }

    @stage(3)
    action gs_set_cnp_constant_fields() {
        gs_hdr.gs_ipv4.gs_version = 4w4;
        gs_hdr.gs_ipv4.gs_ihl = 4w5;
        gs_hdr.gs_ipv4.gs_ecn = 2w0;
        gs_hdr.gs_ipv4.gs_total_len = GS_CNP_IPV4_TOTAL_LEN;
        gs_hdr.gs_ipv4.gs_flags = 3w0;
        gs_hdr.gs_ipv4.gs_frag_offset = 13w0;
        gs_hdr.gs_ipv4.gs_ttl = 8w64;
        gs_hdr.gs_ipv4.gs_protocol = GS_IP_PROTOCOLS_UDP;
        gs_hdr.gs_udp.gs_dst_port = GS_UDP_ROCE_DST_PORT;
        gs_hdr.gs_udp.gs_hdr_length = GS_CNP_UDP_LENGTH;
        gs_hdr.gs_udp.gs_checksum = 16w0;

        gs_hdr.gs_bth.gs_opcode = ROCE_V2_CNP_OPCODE;
        gs_hdr.gs_bth.gs_solicited_event = 1w0;
        gs_hdr.gs_bth.gs_mig_req = 1w0;
        gs_hdr.gs_bth.gs_pad_count = 2w0;
        gs_hdr.gs_bth.gs_header_v = 4w0;
        gs_hdr.gs_bth.gs_reserved1 = GS_CNP_BECN;
        gs_hdr.gs_bth.gs_psn_word = 32w0x80000000;

        gs_hdr.gs_cnp_padding.setValid();
        gs_hdr.gs_cnp_padding.gs_reserved1 = 64w0;
        gs_hdr.gs_cnp_padding.gs_reserved2 = 64w0;
        gs_hdr.gs_icrc.setValid();
    }
    @stage(3)
    table gs_set_cnp_constant_fields_table {
        key = {
            gs_meta.gs_is_mirrored: exact;
            gs_hdr.gs_bth.isValid(): exact;
        }
        actions = { gs_set_cnp_constant_fields; @defaultonly NoAction; }
        size = 4;
        const entries = { (1, true): gs_set_cnp_constant_fields(); }
        default_action = NoAction();
    }

    @stage(4)
    action gs_set_cnp_qpn(bit<24> sender_qpn) {
        gs_hdr.gs_bth.gs_dst_qpn = sender_qpn;
    }
    action gs_drop_unmapped_cnp() {
        gs_eg_dprsr_md.drop_ctl = 1;
    }
    @stage(4)
    table gs_set_cnp_qpn_table {
        key = {
            gs_hdr.gs_ipv4.gs_dst_addr: exact;
            gs_hdr.gs_bth.gs_dst_qpn: exact;
        }
        actions = { gs_set_cnp_qpn; gs_drop_unmapped_cnp; }
        size = 128;
        default_action = gs_drop_unmapped_cnp();
    }

    apply {
        gs_calculate_cnp_dip_hash_table.apply();
        gs_swap_cnp_ethernet_addresses_table.apply();
        gs_swap_cnp_ipv4_addresses_table.apply();
        gs_set_cnp_constant_fields_table.apply();
        if (gs_meta.gs_is_mirrored == 1) { gs_set_cnp_qpn_table.apply(); }
        if (gs_hdr.gs_icrc.isValid()) {
            gs_meta.gs_cnp_icrc_raw = gs_cnp_icrc_hash_calc.get({
                64w0xffffffffffffffff,
                gs_hdr.gs_ipv4.gs_version,
                gs_hdr.gs_ipv4.gs_ihl,
                8w0xff,
                gs_hdr.gs_ipv4.gs_total_len,
                gs_hdr.gs_ipv4.gs_identification,
                gs_hdr.gs_ipv4.gs_flags,
                gs_hdr.gs_ipv4.gs_frag_offset,
                8w0xff,
                gs_hdr.gs_ipv4.gs_protocol,
                16w0xffff,
                gs_hdr.gs_ipv4.gs_src_addr,
                gs_hdr.gs_ipv4.gs_dst_addr,
                gs_hdr.gs_udp.gs_src_port,
                gs_hdr.gs_udp.gs_dst_port,
                gs_hdr.gs_udp.gs_hdr_length,
                16w0xffff,
                gs_hdr.gs_bth.gs_opcode,
                gs_hdr.gs_bth.gs_solicited_event,
                gs_hdr.gs_bth.gs_mig_req,
                gs_hdr.gs_bth.gs_pad_count,
                gs_hdr.gs_bth.gs_header_v,
                gs_hdr.gs_bth.gs_parti_key,
                8w0xff,
                gs_hdr.gs_bth.gs_dst_qpn,
                gs_hdr.gs_bth.gs_psn_word,
                gs_hdr.gs_cnp_padding.gs_reserved1,
                gs_hdr.gs_cnp_padding.gs_reserved2
            });
            gs_hdr.gs_icrc.gs_value[31:24] = gs_meta.gs_cnp_icrc_raw[7:0];
            gs_hdr.gs_icrc.gs_value[23:16] = gs_meta.gs_cnp_icrc_raw[15:8];
            gs_hdr.gs_icrc.gs_value[15:8] = gs_meta.gs_cnp_icrc_raw[23:16];
            gs_hdr.gs_icrc.gs_value[7:0] = gs_meta.gs_cnp_icrc_raw[31:24];
        }
    }
}

/********************* D E P A R S E R ************************/
control gs_EgressDeparser(packet_out gs_pkt,
                          /* User */
                          inout gs_my_egress_headers_t gs_hdr,
                          in    gs_my_egress_metadata_t gs_meta,
                          /* Intrinsic */
                          in    egress_intrinsic_metadata_for_deparser_t gs_eg_dprsr_md)
{
    Checksum() gs_ipv4_csum;

    apply {
        if (gs_hdr.gs_ipv4.isValid()) {
            gs_hdr.gs_ipv4.gs_hdr_checksum = gs_ipv4_csum.update({
                gs_hdr.gs_ipv4.gs_version,
                gs_hdr.gs_ipv4.gs_ihl,
                gs_hdr.gs_ipv4.gs_diffserv,
                gs_hdr.gs_ipv4.gs_ecn,
                gs_hdr.gs_ipv4.gs_total_len,
                gs_hdr.gs_ipv4.gs_identification,
                gs_hdr.gs_ipv4.gs_flags,
                gs_hdr.gs_ipv4.gs_frag_offset,
                gs_hdr.gs_ipv4.gs_ttl,
                gs_hdr.gs_ipv4.gs_protocol,
                gs_hdr.gs_ipv4.gs_src_addr,
                gs_hdr.gs_ipv4.gs_dst_addr
            });
        }
        gs_pkt.emit(gs_hdr.gs_ethernet);
        gs_pkt.emit(gs_hdr.gs_ipv4);
        gs_pkt.emit(gs_hdr.gs_arp);
        gs_pkt.emit(gs_hdr.gs_tcp);
        gs_pkt.emit(gs_hdr.gs_udp);
        gs_pkt.emit(gs_hdr.gs_bth);
        gs_pkt.emit(gs_hdr.gs_cnp_padding);
        gs_pkt.emit(gs_hdr.gs_icrc);
    }
}


/************ F I N A L  P A C K A G E ******************************/
Pipeline(
    gs_IngressParser(),
    gs_Ingress(),
    gs_IngressDeparser(),
    gs_EgressParser(),
    gs_Egress(),
    gs_EgressDeparser()
) gs_pipe;

Switch(gs_pipe) main;
