#include "ns3/settings.h"

#include <limits> // for std::numeric_limits
#include <map>
#include <vector>
#include <set>
#include <algorithm> // for std::max
#include <functional>
#include "ns3/simulator.h"
#include <queue>
#include "ns3/flow-id-num-tag.h"
#include <assert.h>



namespace ns3 {
void NodeInfo::basic_config(uint32_t as_id, uint32_t id, NodeType type) {
    this->id = id;
    this->as_id = as_id;
    this->node_type = type;
    this->ip = Settings::node_id_to_ip(as_id, id);
}
/* helper function */
Ipv4Address Settings::node_id_to_ip(uint32_t as_id, uint32_t node_id) {
    return Ipv4Address(0x0b000001 + ((node_id / 256) * 0x00010000) + ((node_id % 256) * 0x00000100));
    //assert(node_id < 127*128);
    //return Ipv4Address(0x0b000001 | ((as_id & 0xff) << 16) | (node_id << 2));
}
uint32_t Settings::ip_to_node_id(Ipv4Address ip) {
    return (ip.Get() >> 8) & 0xffff;
}
uint32_t Settings::get_flowid(Ptr<Packet> p) {
    FlowIDNUMTag fit;
    if (p->PeekPacketTag(fit)) {
        return fit.GetId();
    } else {
        assert(false);
        return 0xFFFFFFFF;
    }
}


/* others */
uint32_t Settings::lb_mode = 0;

std::map<uint32_t, uint32_t> Settings::hostIp2IdMap;
std::map<uint32_t, uint32_t> Settings::hostId2IpMap;
std::unordered_map<uint32_t, uint32_t> Settings::asId2DciId;
std::unordered_map<uint32_t, std::unordered_map<uint32_t, std::vector<int>>> Settings::wan_routing;

/* statistics */
uint32_t Settings::node_num = 0;
uint32_t Settings::host_num = 0;
uint32_t Settings::switch_num = 0;
uint32_t Settings::esw_num = 0;
uint64_t Settings::cnt_finished_flows = 0;
uint32_t Settings::packet_payload = 1000;

uint32_t Settings::dropped_pkt_sw_ingress = 0;
uint32_t Settings::dropped_pkt_sw_egress = 0;
bool Settings::setting_debug = false;
bool Settings::set_fixed_routing = false;    //选择固定的路由


/* for load balancer */
std::vector<std::vector<uint32_t>> Settings::static_paths;

std::vector<NodeInfo> Settings::nodeInfos(1000);
std::vector<FlowInput> Settings::flowInfos;
std::map<uint32_t, std::vector<uint32_t>>Settings::hostId2ToRlist;

std::map<uint32_t, std::vector<uint32_t>>Settings::TorSwitch_nodelist;

NodeContainer Settings::nodeContainer;
std::map<Ptr<Node>, std::map<uint32_t, uint32_t> > Settings::if2id;
std::map<Ptr<Node>, std::map<Ptr<Node>, Interface>> Settings::nbr2if;
std::map<Ptr<Node>, std::map<Ptr<Node>, std::vector<Ptr<Node>>>> Settings::nextHop;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> Settings::pairDelay;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> Settings::pairTxDelay;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> Settings::pairBw;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> Settings::pairBdp;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>> Settings::pairRtt;

std::unordered_map<uint64_t, std::unordered_map<uint32_t, uint32_t>> flowCounter;
void Settings::record_flow_distribution(Ptr<Packet> p, CustomHeader &ch, Ptr<Node> srcNode, uint32_t outDev) {
    if (ch.l3Prot != 0x11) {
        return;
    }
    uint32_t srcId = srcNode->GetId();
    uint32_t dstId = if2id[srcNode][outDev];
    if (dstId == Settings::hostIp2IdMap[ch.dip]) {//最后一跳不进行记录
        return;
    }
    if (srcId != 111 && dstId != 111) {
        return;
    }
    uint32_t flowId = Settings::get_flowid(p);
    flowCounter[(static_cast<uint64_t>(srcId) << 32) | dstId][flowId]+=p->GetSize();
}

uint32_t Settings::dropped_flow_id = -1;


void Settings::print_flow_distribution(Time interval) {
    for (auto it = flowCounter.begin(); it != flowCounter.end(); ++it) {
        uint32_t src = it->first >> 32;
        uint32_t dst = it->first & 0xFFFFFFFF;
        for (auto flowIt = it->second.begin(); flowIt != it->second.end(); ++flowIt) {
            uint32_t flowId = flowIt->first;
            uint32_t size = flowIt->second;
            fprintf(logfile::link_utilization, "%lu,%u,%u,%u,%u\n", Simulator::Now().GetNanoSeconds(), src, dst, flowId, size);
        }
    }
    flowCounter.clear();
    fflush(logfile::link_utilization);
    Simulator::Schedule(interval, &Settings::print_flow_distribution, interval);
}



void Settings::read_static_path(std::string path){
    std::ifstream infile(path);
    if (!infile.is_open()) {
        std::cerr << "Error: Unable to open file " << path << " for reading." << std::endl;
        return;
    }
    std::string line;
    while (std::getline(infile, line)) {
        std::istringstream iss(line);
        std::vector<uint32_t> path;
        uint32_t node;
        while (iss >> node) {
            path.push_back(node);
            if (iss.peek() == ',') {
                iss.ignore();
            }
        }
        // 假设储存路径的数据结构是 std::vector<std::vector<uint32_t>> static_paths;
        static_paths.push_back(path);
    }
    infile.close();
}
namespace logfile {
    std::string output_dir = "mix/output/temp";
    // 定义所有文件指针（初始化为nullptr）
    FILE* pfc_file = nullptr;
    FILE* flow_output = nullptr;
    FILE* cnp_output = nullptr;
    FILE* voq_output = nullptr;
    FILE* voq_detail_output = nullptr;
    FILE* uplink_output = nullptr;
    FILE* downlink_output = nullptr;
    FILE* uplink_rx_output = nullptr;
    FILE* downlink_rx_output = nullptr;
    FILE* flow_rx_output = nullptr;
    FILE* qp_rate_log = nullptr;
    FILE* conn_output = nullptr;
    FILE* global_CE_map_output = nullptr;
    FILE* all_links_output = nullptr;
    FILE* link_utilization = nullptr;
    FILE* ideal_ce_output = nullptr;
    FILE* pathCE_mon_output = nullptr;
    FILE* pathCE_exclude_last_hop_mon_output = nullptr;

    FILE* wan_log = nullptr;
    FILE* rtt_log = nullptr;
    FILE* drop_log = nullptr;
    FILE* buffer_monitor = nullptr;
    FILE* rate_monitor = nullptr;
    
    

    // 初始化函数实现
    void initialize_log() {
        // 通用文件打开宏（减少重复代码）
        #define OPEN_FILE(var) {                                     \
            const std::string path = output_dir + "/" #var;         \
            var = fopen(path.c_str(), "w");                         \
            assert(var != NULL);                                     \
        }
        #define OPEN_EMPTY_FILE(var) {                                     \
            const std::string path = "/dev/null";         \
            var = fopen(path.c_str(), "w");                         \
            assert(var != NULL);                                     \
        }

        // 为所有文件调用宏
        OPEN_FILE(pfc_file);
        OPEN_FILE(flow_output);
        OPEN_FILE(wan_log);
        OPEN_FILE(rtt_log);
        fprintf(rtt_log, "timestamp_ns,switch_id,dst_as,next_hop,rtt1_ms,rtt2_ms,timeout_count\n");
        OPEN_FILE(drop_log);
        fprintf(drop_log, "timestamp_ns,switch_id,next_hop,flow_id,seq_num,type\n");
        OPEN_FILE(link_utilization);
        fprintf(link_utilization, "timestamp_ns,src_id,dst_id,flow_id,bytes\n");
        OPEN_FILE(buffer_monitor);
        fprintf(buffer_monitor, "timestamp_ns,switch_id,next_hop,ingress_bytes,egress_bytes\n");
        OPEN_FILE(rate_monitor);
        fprintf(rate_monitor, "timestamp_ns,src_as,dst_as,real_rate,base_rate\n");
        OPEN_FILE(qp_rate_log);
        fprintf(qp_rate_log, "timestamp_ns,flow_id,rate\n");

        OPEN_EMPTY_FILE(cnp_output);
        OPEN_EMPTY_FILE(voq_output);
        OPEN_EMPTY_FILE(voq_detail_output);
        OPEN_EMPTY_FILE(uplink_output);
        OPEN_EMPTY_FILE(downlink_output);
        OPEN_EMPTY_FILE(uplink_rx_output);
        OPEN_EMPTY_FILE(downlink_rx_output);
        OPEN_EMPTY_FILE(flow_rx_output);
        OPEN_EMPTY_FILE(conn_output);
        OPEN_EMPTY_FILE(global_CE_map_output);
        OPEN_EMPTY_FILE(all_links_output);
        OPEN_EMPTY_FILE(ideal_ce_output);
        OPEN_EMPTY_FILE(pathCE_mon_output);
        OPEN_EMPTY_FILE(pathCE_exclude_last_hop_mon_output);

        #undef OPEN_FILE
        #undef OPEN_EMPTY_FILE
    }
}

}  // namespace ns3
