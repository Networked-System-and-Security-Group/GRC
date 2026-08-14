#ifndef __SETINGS_H__
#define __SETINGS_H__

#include <stdbool.h>
#include <stdint.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <list>
#include <map>
#include <numeric>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <tuple>

#include "ns3/callback.h"
#include "ns3/custom-header.h"
#include "ns3/double.h"
#include "ns3/ipv4-address.h"
#include "ns3/net-device.h"
#include "ns3/nstime.h"
#include "ns3/object.h"
#include "ns3/packet.h"
#include "ns3/ptr.h"
#include "ns3/string.h"
#include "ns3/tag.h"
#include "ns3/uinteger.h"
#include "ns3/node.h"
#include "ns3/node-container.h"

namespace ns3 {

#define SLB_DEBUG (false)

#define PARSE_FIVE_TUPLE(ch)                                                    \
    DEPARSE_FIVE_TUPLE(std::to_string(Settings::hostIp2IdMap[ch.sip]),          \
                       std::to_string(ch.udp.sport),                            \
                       std::to_string(Settings::hostIp2IdMap[ch.dip]),          \
                       std::to_string(ch.udp.dport), std::to_string(ch.l3Prot), \
                       std::to_string(ch.udp.seq), std::to_string(ch.GetIpv4EcnBits()))
#define PARSE_REVERSE_FIVE_TUPLE(ch)                                            \
    DEPARSE_FIVE_TUPLE(std::to_string(Settings::hostIp2IdMap[ch.dip]),          \
                       std::to_string(ch.udp.dport),                            \
                       std::to_string(Settings::hostIp2IdMap[ch.sip]),          \
                       std::to_string(ch.udp.sport), std::to_string(ch.l3Prot), \
                       std::to_string(ch.udp.seq), std::to_string(ch.GetIpv4EcnBits()))
#define DEPARSE_FIVE_TUPLE(sip, sport, dip, dport, protocol, seq, ecn)                        \
    sip << "(" << sport << ")," << dip << "(" << dport << ")[" << protocol << "],SEQ:" << seq \
        << ",ECN:" << ecn << ","

#if (SLB_DEBUG == true)
#define SLB_LOG(msg) \
    std::cout << __FILE__ << "(" << __LINE__ << "):" << Simulator::Now() << "," << msg << std::endl
#else
#define SLB_LOG(msg) \
    do {             \
    } while (0)
#endif

/**
 * @brief For flowlet-routing
 */
struct Flowlet {
    Time _activeTime;     // to check creating a new flowlet储存的是上一次到达包的时间
    Time _activatedTime;  // start time of new flowlet
    uint32_t _PathId;     // current pathId
    uint32_t _nPackets;   // for debugging
};

struct Caver_Flowlet{
    Time _activeTime;     // to check creating a new flowlet储存的是上一次到达包的时间
    Time _activatedTime;  // start time of new flowlet
    uint32_t _PathId;
    uint32_t _nPackets;
    bool _SrcRoute_ENABLE;
    uint32_t _outPort; // 对于使用ECMP路由的包，需要记录在Src ToR上出发的端口
};


struct Interface {
    uint32_t idx;
    bool up;
    uint64_t delay;
    uint64_t bw;

    Interface() : idx(0), up(false) {} //initial 
};

struct FlowInput {
    uint32_t src, dst, pg, fsize, port;
    double start_time, finish_time = 0;
    uint32_t idx;
    uint32_t srcTor=0xFFFFFFFF, dstTor=0xFFFFFFFF;//记录源tor和目的tor。流第一次进入交换机的时候被初始化
    bool isFinished = false;
    std::vector<uint32_t> passed_nodes;
    inline void record_switch_node(uint32_t switch_id) {
        for (uint32_t id : passed_nodes) {
            if (id == switch_id) {
                return;
            }
        }
        passed_nodes.push_back(switch_id);
    }
    void print(FILE* file) const {
        fprintf(file, "FlowInput { src: %d, dst: %d, fsize: %u, start_time: %.9f, idx: %d, isFinished: %s, passed_nodes: ",
                src, dst, fsize, start_time, idx, (isFinished ? "true" : "false"));
        for (const auto& node : passed_nodes) {
            fprintf(file, "%d ", node);
        }
        fprintf(file, "}\n");
    }
};

/**
 * @brief Tag for monitoring last data sending time per flow
 */
class LastSendTimeTag : public Tag {
   public:
    LastSendTimeTag() : Tag() {}
    static TypeId GetTypeId(void) {
        static TypeId tid =
            TypeId("ns3::LastSendTimeTag").SetParent<Tag>().AddConstructor<LastSendTimeTag>();
        return tid;
    }
    virtual TypeId GetInstanceTypeId(void) const { return GetTypeId(); }
    virtual void Print(std::ostream &os) const {}
    virtual uint32_t GetSerializedSize(void) const { return sizeof(m_pktType); }
    virtual void Serialize(TagBuffer i) const { i.WriteU8(m_pktType); }
    virtual void Deserialize(TagBuffer i) { m_pktType = i.ReadU8(); }
    void SetPktType(uint8_t type) { m_pktType = type; }
    uint8_t GetPktType() { return m_pktType; }

    enum pktType {
        PACKET_NULL = 0,
        PACKET_FIRST = 1,
        PACKET_LAST = 2,
        PACKET_SINGLE = 3,
    };

   private:
    uint8_t m_pktType;
};

struct NodeInfo {
    uint32_t id;
    uint32_t as_id;
    enum NodeType {
       HOST,
       DC_SWITCH,
       DCI_SWITCH,
       WAN_SWITCH,
       UNCONFIGURED, 
    }node_type = UNCONFIGURED;
    Ipv4Address ip;
    void basic_config(uint32_t as_id, uint32_t id, NodeType type);
};
/**
 * @brief Global setting parameters
 */
class Settings {
   public:
    Settings() {}
    virtual ~Settings() {}

    /* helper function */
    static Ipv4Address node_id_to_ip(uint32_t as_id, uint32_t node_id);  // node_id -> ip
    static uint32_t ip_to_node_id(Ipv4Address ip);  // ip -> node_id
    static uint32_t get_flowid(Ptr<Packet> p);


    /* conweave params */
    static const uint32_t CONWEAVE_CTRL_DUMMY_INDEV = 88888888;  // just arbitrary

    /* load balancer */
    // 0: flow ECMP, 2: DRILL, 3: Conga, 4: ConWeave
    static uint32_t lb_mode;
    static enum WanCCMode{
        NONE = 0,
        WAN_OPT = 1,
        WITH_ECN = 2,
    } wan_cc_mode;
    // Switch-side Themis baseline.  When enabled, every DCI switch runs PNP
    // and TRP through its ThemisRouting module.
    static bool themis_enabled;

    // for common setting
    static uint32_t packet_payload;

    // for statistic
    static uint32_t node_num;
    static uint32_t host_num;
    static uint32_t switch_num;
    static uint32_t esw_num;
    static uint64_t cnt_finished_flows;  // number of finished flows (in qp_finish())

    /* The map between hosts' IP and ID, initial when build topology */
    static std::unordered_map<uint32_t, uint32_t> asId2DciId;
    static std::unordered_map<uint32_t, std::unordered_map<uint32_t, std::vector<int>>> wan_routing;//从某一节点，前往对应as，需要走的下一跳的dev_id候选
    static std::map<uint32_t, uint32_t> hostIp2IdMap;
    static std::map<uint32_t, uint32_t> hostId2IpMap;
    static std::map<uint32_t, std::vector<uint32_t>>TorSwitch_nodelist; //记录每个ToR交换机下的节点 ip列表
    static std::map<uint32_t, std::vector<uint32_t>>hostId2ToRlist; //记录每个节点相连的ToR交换机id的vector

    // 一个2维数组，每个位置存放一个uint32_t，数组的大小为node_num*node_num
    //dive into related:计算最优所需要的信息
    // static std::map<uint32_t, std::map<uint32_t, std::vector<uint32_t>>> nextHop;


    static std::vector<FlowInput> flowInfos;
    static std::vector<NodeInfo> nodeInfos;
    
    static NodeContainer nodeContainer;
    static std::map<Ptr<Node>, std::map<uint32_t, uint32_t> > if2id;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, Interface>> nbr2if;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, std::vector<Ptr<Node>>>> nextHop;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> pairDelay;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> pairTxDelay;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> pairBw;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> pairBdp;
    static std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> pairRtt;

    static uint32_t dropped_pkt_sw_ingress;
    static uint32_t dropped_pkt_sw_egress;

    static bool setting_debug;

    static bool set_fixed_routing;//选择固定的路由；
    static void read_static_path(std::string path);//读取固定的路由表
    static std::vector<std::vector<uint32_t>> static_paths;
    
    static void record_flow_distribution(Ptr<Packet> p, CustomHeader &ch, Ptr<Node> srcNode, uint32_t outDev);
    static void print_flow_distribution(Time interval);

    static uint32_t dropped_flow_id;

    // Temporary parameter passthrough: unknown config keys are stored here
    // as raw string values for easy access during experimentation.
    static inline void SetRawParam(const std::string& key, const std::string& value) {
        raw_params[key] = value;
    }
    static inline bool HasRawParam(const std::string& key) {
        return raw_params.find(key) != raw_params.end();
    }
    static inline std::string GetRawParam(const std::string& key,
                                          const std::string& defaultValue = "") {
        auto it = raw_params.find(key);
        if (it == raw_params.end()) {
            return defaultValue;
        }
        return it->second;
    }
    static inline const std::unordered_map<std::string, std::string>& GetRawParams() {
        return raw_params;
    }
    static inline void ClearRawParams() {
        raw_params.clear();
    }

   private:
    static std::unordered_map<std::string, std::string> raw_params;


};

namespace logfile {
    extern std::string output_dir;
    // 声明所有文件指针
    extern FILE* pfc_file;
    extern FILE* wan_log;
    extern FILE* rtt_log;
    extern FILE* flow_output;
    extern FILE* drop_log;
    extern FILE* link_utilization;
    extern FILE* buffer_monitor;
    extern FILE* rate_monitor;
    extern FILE* cnp_log;
    extern FILE* cnp_trigger_prob_log;
    extern FILE* accumulated_bytes_log;
    extern FILE* flow_debug_log;

    extern FILE* cnp_output;
    extern FILE* voq_output;
    extern FILE* voq_detail_output;
    extern FILE* uplink_output;
    extern FILE* downlink_output;
    extern FILE* uplink_rx_output;
    extern FILE* downlink_rx_output;
    extern FILE* flow_rx_output;
    extern FILE* qp_rate_log;
    extern FILE* uno_cwnd_log;
    extern FILE* conn_output;
    extern FILE* global_CE_map_output;
    extern FILE* all_links_output;
    extern FILE* ideal_ce_output;
    extern FILE* pathCE_mon_output;
    extern FILE* pathCE_exclude_last_hop_mon_output;

    // 初始化函数声明
    void initialize_log();
}

}  // namespace ns3

#endif
