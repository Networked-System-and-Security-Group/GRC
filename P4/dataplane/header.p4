#ifndef _HEADERS_
#define _HEADERS_

/*************************************************************************
 ************* C O N S T A N T S   A N D  T Y P E S  *******************
 *************************************************************************/

typedef bit<48> gs_mac_addr_t;
typedef bit<32> gs_ipv4_addr_t;
typedef bit<16> gs_l4_port_t;

typedef bit<16> gs_ether_type_t;
const gs_ether_type_t GS_ETHERTYPE_IPV4 = 16w0x0800;
const bit<16> GS_ETHERTYPE_ARP = 16w0x0806;

typedef bit<8> gs_ip_protocol_t;
const gs_ip_protocol_t GS_IP_PROTOCOLS_TCP = 6;
const gs_ip_protocol_t GS_IP_PROTOCOLS_UDP = 17;

const gs_l4_port_t GS_UDP_ROCE_DST_PORT = 4791;

// rixin: 由于使用了mirror，所以需要区分
typedef bit<8>  gs_pkt_type_t;
const gs_pkt_type_t GS_PKT_TYPE_NORMAL = 6;
const gs_pkt_type_t GS_PKT_TYPE_MIRROR = 9;

typedef bit<3> gs_mirror_type_t;


const gs_mirror_type_t GS_MIRROR_TYPE_I2E = 1;
const gs_mirror_type_t GS_MIRROR_TYPE_E2E = 2;

// rixin: the num of host interfaces, real num at ACT is 12.
const int GS_HOST_IF_NUM = 32;
// rixin: session id 0被保留了，使用1
const int GS_CNP_SES_ID = 1;
// rixin: 造成拥塞的跨DC流的最大个数(concurrent)
const int GS_MAX_NUM_CONGESTION_FLOW = 10000;// 修正: 添加所有缺失的常量定义
const bit<8> ROCE_V2_ACK_OPCODE = 17;   // 0x11
const bit<8> ROCE_V2_CNP_OPCODE = 129;  // 0x81

// 自定义数据包类型常量
const gs_pkt_type_t PKT_TYPE_NORMAL_DATA = 0;
const gs_pkt_type_t PKT_TYPE_ACK         = 1;
const gs_pkt_type_t PKT_TYPE_ACKREQ      = 2;

// 寄存器和表大小
const bit<32> RTT_TABLE_SIZE = 1024;
const bit<16> MAX_DST_DCS    = 16;

// GSCC 算法参数
const bit<48> CNP_THRESHOLD_K    = 400000; // 400KB
const bit<32> MIN_CNP_INTERVAL   = 50;     // 50us, 假设时间戳单位是微秒
const PortId_t RECIRC_PORT       = 68;     // Tofino上一个常用的循环端口

// 速率控制参数
const bit<32> RATE_CONTROL_REG_SIZE = 16;  // 速率控制寄存器大小
const bit<32> BYTES_DIFF_THRESHOLD = 400000; // 字节差值阈值 (400KB)

/*************************************************************************
 *********************** H E A D E R S  *********************************
 *************************************************************************/

header gs_ethernet_h {
    gs_mac_addr_t gs_dst_addr;
    gs_mac_addr_t gs_src_addr;
    bit<16> gs_ether_type;
}

header gs_ipv4_h {
    bit<4> gs_version;
    bit<4> gs_ihl;
    bit<6> gs_diffserv;
    bit<2> gs_ecn;
    bit<16> gs_total_len;
    bit<16> gs_identification;
    bit<3> gs_flags;
    bit<13> gs_frag_offset;
    bit<8> gs_ttl;
    bit<8> gs_protocol;
    bit<16> gs_hdr_checksum;
    gs_ipv4_addr_t gs_src_addr;
    gs_ipv4_addr_t gs_dst_addr;
}

header gs_tcp_h {
    gs_l4_port_t gs_src_port;
    gs_l4_port_t gs_dst_port;
    bit<32> gs_seq_no;
    bit<32> gs_ack_no;
    bit<4> gs_data_offset;
    bit<4> gs_res;
    bit<8> gs_flags;
    bit<16> gs_window;
    bit<16> gs_checksum;
    bit<16> gs_urgent_ptr;
    bit<96> gs_options;
}

header gs_udp_h {
    gs_l4_port_t gs_src_port;
    gs_l4_port_t gs_dst_port;
    bit<16> gs_hdr_length;
    bit<16> gs_checksum;
}

header gs_bth_h {
    bit<8> gs_opcode;
    bit<1> gs_solicited_event;
    bit<1> gs_mig_req;
    bit<2> gs_pad_count;
    bit<4> gs_header_v;
    bit<16> gs_parti_key;
    bit<8> gs_reserved1;
    bit<24> gs_dst_qpn;
    bit<1> gs_ack_req;
    bit<7> gs_reserved2;
    bit<24> gs_psn;
}

header gs_arp_h {
    bit<16> gs_hw_type;
    bit<16> gs_proto_type;
    bit<8> gs_hw_sz;
    bit<8> gs_proto_sz;
    bit<16> gs_opcode;
    gs_mac_addr_t gs_srcMacAddr;
    bit<32> gs_srcIpv4Addr;
    gs_mac_addr_t gs_dstMacAddr;
    bit<32> gs_dstIpv4Addr;
}

header gs_mirror_bridged_metadata_h {
    gs_pkt_type_t gs_pkt_type;
}

header gs_mirror_h {
    gs_pkt_type_t  gs_pkt_type;
    bit<8> gs_is_last_recir_pkt;
}

struct gs_my_ingress_headers_t {
    gs_mirror_bridged_metadata_h gs_bridged_md;
    gs_ethernet_h gs_ethernet;
    gs_ipv4_h gs_ipv4;
    gs_arp_h gs_arp;
    gs_tcp_h gs_tcp;
    gs_udp_h gs_udp;
    gs_bth_h gs_bth; // 确保有BTH头
}

struct gs_my_egress_headers_t {
    gs_mirror_bridged_metadata_h gs_bridged_md;
    gs_mirror_h gs_mirror_md;
    gs_ethernet_h gs_ethernet;
    gs_ipv4_h gs_ipv4;
    gs_tcp_h gs_tcp;
    gs_udp_h gs_udp;
    gs_bth_h gs_bth;
}

struct gs_empty_header_t {}

struct gs_empty_metadata_t {}

#endif /* _HEADERS_ */
