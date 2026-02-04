#include <ns3/assert.h>
#include <ns3/rdma-client-helper.h>
#include <ns3/rdma-client.h>
#include <ns3/rdma-driver.h>
#include <ns3/rdma.h>
#include <ns3/sim-setting.h>
#include <ns3/switch-node.h>
#include <time.h>

#include <fstream>
#include <iostream>
#include <unordered_map>
#include <filesystem>
#include <cctype>

#include "ns3/applications-module.h"
#include "ns3/broadcom-node.h"
#include "ns3/conga-routing.h"
#include "ns3/conweave-voq.h"
#include "ns3/hula-routing.h"
#include "ns3/core-module.h"
#include "ns3/error-model.h"
#include "ns3/global-route-manager.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-static-routing-helper.h"
#include "ns3/letflow-routing.h"
#include "ns3/packet.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/qbb-helper.h"
#include "ns3/qbb-net-device.h"
#include "ns3/rdma-hw.h"
#include "ns3/settings.h"
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"

#include "json.hpp"

using namespace ns3;
using namespace std;

static inline std::string _TrimWs(std::string s) {
    auto notSpace = [](unsigned char ch) { return !std::isspace(ch); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), notSpace));
    s.erase(std::find_if(s.rbegin(), s.rend(), notSpace).base(), s.end());
    return s;
}

NS_LOG_COMPONENT_DEFINE("GENERIC_SIMULATION");

/*------Load balancing parameters-----*/
// mode for load balancer, 0: flow ECMP, 2: DRILL, 3: Conga, 6: Letflow, 9: ConWeave 12:Hula
uint32_t lb_mode = 0;

bool caver_useEWMA = true;
bool init_log = false;
uint32_t global_ce_mon_interval = 20; //us

/*------------------------ simulation variables -----------------------------*/
uint32_t cc_mode = 1;           // mode for congestion control, 1: DCQCN
bool enable_qcn = true, enable_pfc = true, use_dynamic_pfc_threshold = true;
uint32_t packet_payload_size = 1000, l2_chunk_size = 0, l2_ack_interval = 0;
double pause_time = 5;  // PFC pause, microseconds
double flowgen_start_time = 2.0, flowgen_stop_time = 2.5, simulator_extra_time = 3.0;//0.15;
// queue length monitoring time is not used in this simulator
// uint32_t qlen_dump_interval = 100000000, qlen_mon_interval = 1000;  // ns
uint32_t switch_mon_interval = 10000;  // ns
uint32_t server_rtt_mon_interval = 100000;  //ns
uint64_t cnp_mon_start;                // ns
uint64_t cnp_monitor_bucket = 100000;  // ns
uint64_t irn_mon_start;                // ns
uint64_t irn_monitor_bucket = 100000;  // ns

using namespace logfile;

std::string data_rate, link_delay, topology_file, flow_file;

// CC params
double alpha_resume_interval = 55, rp_timer = 300, ewma_gain = 1 / 16;
double rate_decrease_interval = 4;
uint32_t fast_recovery_times = 1;
std::string rate_ai, rate_hai, min_rate = "100Mb/s";
std::string dctcp_rate_ai = "1000Mb/s";

bool clamp_target_rate = false, l2_back_to_zero = false;
double error_rate_per_link = 0.0;
uint32_t has_win = 1;
uint32_t global_t = 0;
uint32_t mi_thresh = 5;
bool var_win = false, fast_react = true;
bool multi_rate = true;
bool sample_feedback = false;
double u_target = 0.95;
uint32_t int_multi = 1;
bool rate_bound = true;
unordered_map<uint64_t, uint32_t> rate2kmax, rate2kmin;
unordered_map<uint64_t, double> rate2pmax;

// config of link-down scenario, ACK priority, and buffer
uint32_t buffer_size = 0;  // 0 to set buffer size automatically
uint32_t dci_buffer_size = 0;  // MB, 0 keeps default
uint32_t wan_buffer_size = 0;  // MB, 0 keeps default

// Added from Here
double load = 10.0;
int enable_irn = 0;
int random_seed = 1;  // change this randomly if you want random expt

uint64_t maxRtt, maxBdp;

std::map<Ptr<Node>, std::map<uint32_t, uint32_t>>& if2id = Settings::if2id;
std::map<Ptr<Node>, std::map<Ptr<Node>, Interface>>& nbr2if = Settings::nbr2if;
std::map<Ptr<Node>, std::map<Ptr<Node>, std::vector<Ptr<Node>>>>& nextHop = Settings::nextHop;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>>& pairDelay = Settings::pairDelay;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>>& pairTxDelay = Settings::pairTxDelay;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>>& pairBw = Settings::pairBw;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>>& pairBdp = Settings::pairBdp;
std::map<Ptr<Node>, std::map<Ptr<Node>, uint64_t>>& pairRtt = Settings::pairRtt;
auto &nodeInfos = Settings::nodeInfos;

// for uplink/Downlink monitoring at TOR switches (load balance performance)
std::map<uint32_t, std::vector<uint32_t>> torId2UplinkIf;
std::map<uint32_t, std::vector<uint32_t>> torId2DownlinkIf;

// input files
NodeContainer& n = Settings::nodeContainer;                         // node container
//place to store the server ip address

//flow input global variable
std::ifstream flowf;
std::ifstream tcp_flowf;
uint32_t flow_num;
uint32_t tcp_flow_num = 0;
std::unordered_map<uint32_t, uint16_t> sportNumber;
std::unordered_map<uint32_t, uint16_t> dportNumber;
std::unordered_map<uint32_t, uint16_t> tcpDportNumber;

std::string tcp_flow_file;
std::vector<FlowInput> tcpFlowInfos;

using json = nlohmann::json;
json topo_json;

/**
 * Read flow input from file "flowf"
 */
bool ReadFlowInput() {
    if (Settings::flowInfos.size() < flow_num) {
        uint32_t flow_id = Settings::flowInfos.size();
        Settings::flowInfos.emplace_back();
        auto& flow_input = Settings::flowInfos.back();
        flowf >> flow_input.src >> flow_input.dst >> flow_input.pg >> flow_input.fsize >> flow_input.start_time;
        flow_input.idx = flow_id;
        flow_input.fsize = std::max(1u, flow_input.fsize);
        //printf("flow %u: %u -> %u, pg: %u, fsize: %u, start_time: %.2f\n", flow_id,
        //       flow_input.src, flow_input.dst, flow_input.pg, flow_input.fsize, flow_input.start_time);
        fflush(stdout);
        assert(n.Get(flow_input.src)->GetNodeType() == 0 &&
               n.Get(flow_input.dst)->GetNodeType() == 0);
        return true;
    } else {
        std::cout << "*** input flow is over the prefixed number -- flow number : " << flow_num
                  << std::endl;
        std::cout << "*** THIS IS THE LAST FLOW TO SEND :) " << std::endl;
        return false;
    }
}

/**
 * Read TCP flow input from file "tcp_flowf".
 * Format is identical to RDMA flow file: N then <src> <dst> <pg> <size_bytes> <start_time_seconds>
 */
bool ReadTcpFlowInput() {
    if (tcpFlowInfos.size() < tcp_flow_num) {
        uint32_t flow_id = tcpFlowInfos.size();
        tcpFlowInfos.emplace_back();
        auto& flow_input = tcpFlowInfos.back();
        tcp_flowf >> flow_input.src >> flow_input.dst >> flow_input.pg >> flow_input.fsize >> flow_input.start_time;
        flow_input.idx = flow_id;
        flow_input.fsize = std::max(1u, flow_input.fsize);
        fflush(stdout);
        assert(n.Get(flow_input.src)->GetNodeType() == 0 &&
               n.Get(flow_input.dst)->GetNodeType() == 0);
        return true;
    }
    return false;
}

/**
 * Scheduling flows given in /config/L_XX....txt file
 */
void ScheduleFlowInputs() {
    NS_LOG_DEBUG("ScheduleFlowInputs at " << Simulator::Now());
    //printf("Scheduled!Now:%lu\n", Simulator::Now().GetNanoSeconds());
    while (std::abs(Settings::flowInfos.back().start_time - Simulator::Now().GetSeconds()) < 1e-8) {
        auto& flowInfo = Settings::flowInfos.back();
        if (flowInfo.idx % 1000 == 0) {
            std::time_t t = std::time(nullptr);
            std::cout << std::put_time(std::localtime(&t), "%H:%M:%S") << " [" << Simulator::Now() << "]"
                << flowInfo.idx << "条流已导入" << std::endl;
        }
        uint32_t pg, src, dst, sport, dport, fsize;
        pg = flowInfo.pg;
        src = flowInfo.src;
        dst = flowInfo.dst;
        sport = sportNumber[src]++;
        dport = dportNumber[dst]++;
        fsize = flowInfo.fsize;
        assert(n.Get(src)->GetNodeType() == 0 && n.Get(dst)->GetNodeType() == 0);
 
        if (pairRtt.find(n.Get(src)) == pairRtt.end() ||
            pairRtt[n.Get(src)].find(n.Get(dst)) == pairRtt[n.Get(src)].end()) {
            std::cerr << "pairRtt src: " << src << " -> dst: " << dst
                      << " ==> cannot be found from database" << std::endl;
            assert(false);
        }

        RdmaClientHelper clientHelper(
            pg, nodeInfos[src].ip, nodeInfos[dst].ip, sport, dport, fsize,
            has_win ? (global_t == 1 ? maxBdp : pairBdp.at(n.Get(src)).at(n.Get(dst))) : 0,
            global_t == 1 ? maxRtt : pairRtt.at(n.Get(src)).at(n.Get(dst)));
        clientHelper.SetAttribute("StatFlowID", IntegerValue(flowInfo.idx));

        ApplicationContainer appCon = clientHelper.Install(n.Get(src));  // SRC
        appCon.Start(Seconds(Time(0)));
        appCon.Stop(Seconds(100.0));
        
        if (!ReadFlowInput()) {
            flowf.close();
            return;
        }
    }
    Simulator::Schedule(Seconds(Settings::flowInfos.back().start_time) - Simulator::Now(), &ScheduleFlowInputs);
}

/**
 * Scheduling TCP flows from TCP_FLOW_FILE using ns-3 standard applications:
 * - Sender: BulkSendApplication (TcpSocketFactory)
 * - Receiver: PacketSink (TcpSocketFactory)
 */
void ScheduleTcpFlowInputs() {
    NS_LOG_DEBUG("ScheduleTcpFlowInputs at " << Simulator::Now());
    while (!tcpFlowInfos.empty() &&
           std::abs(tcpFlowInfos.back().start_time - Simulator::Now().GetSeconds()) < 1e-8) {
        auto& flowInfo = tcpFlowInfos.back();
        if (flowInfo.idx % 1000 == 0) {
            std::time_t t = std::time(nullptr);
            std::cout << std::put_time(std::localtime(&t), "%H:%M:%S") << " [" << Simulator::Now() << "]"
                      << " TCP " << flowInfo.idx << "条流已导入" << std::endl;
        }

        uint32_t src = flowInfo.src;
        uint32_t dst = flowInfo.dst;
        uint32_t fsize = flowInfo.fsize;
        uint16_t dport = tcpDportNumber[dst]++;

        // Install apps at the scheduled time, and start the sink slightly earlier than the sender
        // to avoid spurious resets/ICMP due to event ordering.
        Time start = Simulator::Now();
        Time sinkStart = start;
        Time senderStart = start + NanoSeconds(1);

        PacketSinkHelper sinkHelper("ns3::TcpSocketFactory",
                                   Address(InetSocketAddress(Ipv4Address::GetAny(), dport)));
        ApplicationContainer sinkApps = sinkHelper.Install(n.Get(dst));
        sinkApps.Start(sinkStart);
        sinkApps.Stop(Seconds(100.0));

        BulkSendHelper senderHelper("ns3::TcpSocketFactory",
                                   Address(InetSocketAddress(nodeInfos[dst].ip, dport)));
        senderHelper.SetAttribute("MaxBytes", UintegerValue(fsize));
        ApplicationContainer senderApps = senderHelper.Install(n.Get(src));
        senderApps.Start(senderStart);
        senderApps.Stop(Seconds(100.0));

        if (!ReadTcpFlowInput()) {
            tcp_flowf.close();
            return;
        }
    }

    if (!tcpFlowInfos.empty()) {
        Simulator::Schedule(Seconds(tcpFlowInfos.back().start_time) - Simulator::Now(), &ScheduleTcpFlowInputs);
    }
}

/**
 * @brief CNP frequency monitoring (timestamp nodeId ECN OoO Total)
 */
void cnp_freq_monitoring(FILE *fout, Ptr<RdmaHw> rdmahw) {
    if (rdmahw->cnp_total > 0) {
        // flush
        fprintf(fout, "%lu %u %u %u %u\n", Simulator::Now().GetNanoSeconds(),
                rdmahw->m_node->GetId(), rdmahw->cnp_by_ecn, rdmahw->cnp_by_ooo, rdmahw->cnp_total);
        fflush(fout);

        // initialize
        rdmahw->cnp_by_ecn = 0;
        rdmahw->cnp_by_ooo = 0;
        rdmahw->cnp_total = 0;
    }

    // recursive callback
    Simulator::Schedule(NanoSeconds(cnp_monitor_bucket), &cnp_freq_monitoring, fout, rdmahw);
}

void m_QP_rate_monitoring()
{
    uint64_t now = Simulator::Now().GetNanoSeconds();
    for (uint32_t i = 0; i < Settings::node_num; i++) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            //printf("Got server %u\n", i);
            Ptr<Node> server = n.Get(i);
            Ptr<RdmaDriver> rdmaDriver = server->GetObject<RdmaDriver>();
            Ptr<RdmaHw> rdmaHw = rdmaDriver->m_rdma;
            // monitor total/active QP number <time, serverId, #ExistingQP, #ActiveQP>
            for (auto qp : rdmaHw->m_qpMap) {
                uint32_t flowid = qp.second->m_flow_id;
                DataRate m_rate = qp.second->m_rate;
                uint64_t m_bps = m_rate.GetBitRate();
                auto& flowInfo = Settings::flowInfos[flowid];
                if (Settings::nodeInfos[flowInfo.src].as_id != Settings::nodeInfos[flowInfo.dst].as_id) {
                    fprintf(qp_rate_log, "%lu,%u,%lu,%lf,%lu\n", now, flowid, m_bps / 8, qp.second->mlx.m_alpha, qp.second->mlx.m_targetRate.GetBitRate() / 8);
                }
                // std::cout << "bps: " << now << flowid << m_bps << std::endl;
            }
        }
    }
    Simulator::Schedule(MicroSeconds(50), &m_QP_rate_monitoring);  // every 10us
    return;
}

void my_periodic_monitoring(Time interval) {
    printf("Periodic monitoring at %lu, %lu flows finished, %ld flows activing\n", 
        Simulator::Now().GetNanoSeconds(), Settings::cnt_finished_flows, Settings::flowInfos.size() - Settings::cnt_finished_flows);
    printf("DropInfo: %u %u\n", Settings::dropped_pkt_sw_ingress, Settings::dropped_pkt_sw_egress);
    Settings::dropped_pkt_sw_ingress = 0;
    Settings::dropped_pkt_sw_egress = 0;
    //对于所有的DCI交换机，打印一些内容
    for (const auto& node_info : Settings::nodeInfos) {
        if (node_info.node_type == NodeInfo::NodeType::DCI_SWITCH) {
            Ptr<Node> node = n.Get(node_info.id);
            auto sw_node = DynamicCast<SwitchNode>(node);
            //sw_node->m_mmu->m_wanRouting.print_status();
        } 
        if (node_info.node_type == NodeInfo::NodeType::WAN_SWITCH
                    || node_info.node_type == NodeInfo::NodeType::DCI_SWITCH) {
            DynamicCast<SwitchNode>(n.Get(node_info.id))->m_mmu->printBufferInfo();
        }
    }
    fflush(logfile::buffer_monitor);
    Simulator::Schedule(interval, &my_periodic_monitoring, interval);
}

/**
 * @brief When one RDMA is finished, so does (1) QP, (2) RxQP, (3) write it on file fct.txt.
 */
void qp_finish(FILE *fout, Ptr<RdmaQueuePair> q) {
    Settings::flowInfos[q->m_flow_id].finish_time = Simulator::Now().GetSeconds();
    uint32_t sid = Settings::ip_to_node_id(q->sip), did = Settings::ip_to_node_id(q->dip);
    uint64_t base_rtt = pairRtt[n.Get(sid)][n.Get(did)];
    uint64_t b = 100000000000lu;// pairBw[n.Get(sid)][n.Get(did)];
    uint32_t total_bytes =
        q->m_size + ((q->m_size - 1) / packet_payload_size + 1) *
                        (CustomHeader::GetStaticWholeHeaderSize() -
                         IntHeader::GetStaticSize());  // translate to the minimum bytes required
                                                       // (with header but no INT)
    uint64_t standalone_fct = base_rtt + total_bytes * 8000000000lu / b;

    //remove rxQP from the receiver 
    Ptr<Node> dstNode = n.Get(did);
    Ptr<RdmaDriver> rdma = dstNode->GetObject<RdmaDriver>();
    rdma->m_rdma->DeleteRxQp(q->sip.Get(), q->sport, q->dport, q->m_pg);
    //printf("Flow %u Finished!\n", q->m_flow_id);
    // fprintf(fout, "%lu QP complete\n", Simulator::Now().GetTimeStep());
    //fprintf(fout, "%u %u %u %lu %lu %lu %lu\n", q->m_flow_id, Settings::ip_to_node_id(q->sip),
    //        Settings::ip_to_node_id(q->dip), q->m_size,
    //        q->startTime.GetTimeStep(), (Simulator::Now() - q->startTime).GetTimeStep(),
    //        standalone_fct);

    // for debugging
    // NS_LOG_DEBUG("%u %u %u %u %lu %lu %lu %lu\n" %
    //              (Settings::ip_to_node_id(q->sip), Settings::ip_to_node_id(q->dip), q->sport,
    //               q->dport, q->m_size, q->startTime.GetTimeStep(),
    //               (Simulator::Now() - q->startTime).GetTimeStep(), standalone_fct));
    Settings::cnt_finished_flows++;
    fflush(fout);
    fflush(stdin);
}

/**
 * @brief PFC event logging
 */
void get_pfc(FILE *fout, Ptr<QbbNetDevice> dev, uint32_t type) {
    // time, nodeID, nodeType, Interface's Idx, 0:resume, 1:pause
    //std::cout << "PFC event: " << Simulator::Now().GetTimeStep() << " " << dev->GetNode()->GetId()
    //          << " " << dev->GetNode()->GetNodeType() << " " << dev->GetIfIndex() << " " << type
    //          << std::endl;
    fprintf(fout, "%lu,%u,%u,%u,%u\n", Simulator::Now().GetNanoSeconds(), dev->GetNode()->GetId(),
            dev->GetNode()->GetNodeType(), if2id[dev->GetNode()][dev->GetIfIndex()] , type);
}

void output_flow_info() {
    FILE* file = logfile::flow_output;
    if (!file) {
        fprintf(stderr, "无效的文件指针\n");
        return;
    }
    
    json jsonArray = json::array();
    
    for (auto& flow : Settings::flowInfos) {
        // 只包含指定的字段
        uint64_t base_rtt = pairRtt[n.Get(flow.src)][n.Get(flow.dst)];
        uint64_t b = 100000000000lu;// pairBw[n.Get(sid)][n.Get(did)];
        uint32_t total_bytes =
            flow.fsize + ((flow.fsize - 1) / packet_payload_size + 1) *
                            (CustomHeader::GetStaticWholeHeaderSize() -
                             IntHeader::GetStaticSize());  // translate to the minimum bytes required
                                                           // (with header but no INT)
        uint64_t standalone_fct = base_rtt + total_bytes * 8000000000lu / b;
        if (flow.finish_time == 0) {
            flow.finish_time = Simulator::Now().GetSeconds();
            printf("FlowId:%u Not Finish!\n", flow.idx);
        }
        json flowJson = {
            {"flow_id", flow.idx},
            {"src", flow.src},
            {"dst", flow.dst},
            {"fsize", flow.fsize},
            {"start_time", flow.start_time},
            {"finish_time", flow.finish_time},
            {"std_fct", 1.0 * standalone_fct / 1e9},
            {"passed_nodes", flow.passed_nodes}
        };
        
        jsonArray.push_back(flowJson);
    }
    
    // 写入开始括号
    fprintf(file, "[\n");

    for (size_t i = 0; i < jsonArray.size(); ++i) {
        std::string jsonStr = jsonArray[i].dump(-1);
        fprintf(file, "  %s%s\n", 
                jsonStr.c_str(), 
                (i < jsonArray.size() - 1) ? "," : "");
    }
    
    // 写入结束括号
    fprintf(file, "]\n");
}

/**
 * @brief Stop simulation in the middle (when almost all flows are done).
 * This function allows to finish simulation quickly when all messages are sent.
 */
void stop_simulation_middle() {
    uint32_t target_flow_num = flow_num - 0;  // can be lower than flownum
    // When TCP flows are enabled, don't stop early purely based on RDMA completion;
    // otherwise TCP apps may not have time to run.
    bool has_tcp_flows = (tcp_flow_num > 0);
    bool rdma_done = (Settings::cnt_finished_flows >= target_flow_num);
    bool time_over = (Simulator::Now() > Seconds(flowgen_stop_time + simulator_extra_time));
    if ((!has_tcp_flows && rdma_done) || time_over) {
        std::cout << "\n*** Simulator is enforced to be finished, finished so far: "
                  << Settings::cnt_finished_flows << "/ total: " << target_flow_num
                  << ", Time:" << Simulator::Now() << std::endl;
        output_flow_info();
        Simulator::Stop(NanoSeconds(1));  // finish soon, stop this schedule (NECESSARY!)
        return;
    }

    Simulator::Schedule(MicroSeconds(100), &stop_simulation_middle);  // check every 100us
}

/**
 * @brief Calculate edge-to-edge delays, TX delays, and bandwidths
 */
void CalculateRoute(Ptr<Node> host) {
    // queue for the BFS.
    vector<Ptr<Node>> q;
    // Distance from the host to each node.
    map<Ptr<Node>, int> dis;
    map<Ptr<Node>, uint64_t> delay;
    map<Ptr<Node>, uint64_t> txDelay;
    map<Ptr<Node>, uint64_t> bw;
    // init BFS.
    q.push_back(host);
    dis[host] = 0;
    delay[host] = 0;
    txDelay[host] = 0;
    bw[host] = 0xfffffffffffffffflu;
    uint32_t current_as = nodeInfos[host->GetId()].as_id;
    // BFS.
    for (int i = 0; i < (int)q.size(); i++) {
        Ptr<Node> now = q[i];
        int d = dis[now];
        for (auto it = nbr2if[now].begin(); it != nbr2if[now].end(); it++) {
            // skip down link
            if (!it->second.up) continue;
            Ptr<Node> next = it->first;
            if (nodeInfos[next->GetId()].as_id != current_as) {
                continue;
            }
            // If 'next' have not been visited.
            if (dis.find(next) == dis.end()) {
                dis[next] = d + 1;
                delay[next] = delay[now] + it->second.delay;  // maybe nanoseconds?
                txDelay[next] = txDelay[now] + packet_payload_size * 1000000000lu * 8 /
                                                   it->second.bw;  // maybe nanoseconds?
                bw[next] = std::min(bw[now], it->second.bw);
                // we only enqueue switch, because we do not want packets to go through host as
                // middle point
                if (next->GetNodeType() == 1) {
                    q.push_back(next);
                }
            }
            // if 'now' is on the shortest path from 'next' to 'host'.
            if (d + 1 == dis[next]) {
                nextHop[next][host].push_back(now);
            }
        }
    }
    for (auto it : delay) {
        pairDelay[it.first][host] = it.second;
    }
    for (auto it : txDelay) {
        pairTxDelay[it.first][host] = it.second;
    }
    for (auto it : bw) {
        pairBw[it.first][host] = it.second;
    }
}
void CalculateRoutes(NodeContainer &n) {
    for (int i = 0; i < (int)n.GetN(); i++) {
        Ptr<Node> node = n.Get(i);
        if (nodeInfos[i].node_type == NodeInfo::NodeType::HOST
            || nodeInfos[i].node_type == NodeInfo::NodeType::DCI_SWITCH) {
            CalculateRoute(node);
        }
    }
}

/**
 * @brief 设置路由表项
 *
 * 此函数为网络中的各节点设置路由表。对于每个类型为 HOST、DC_SWITCH 或 DCI_SWITCH 的节点，
 * 将为所有其他 HOST 节点配置路由表项。
 * 
 * 路由分为两种情况：
 * 1. 同一自治系统内(Intra-AS)：直接使用目标 HOST 节点作为下一跳；
 * 2. 不同自治系统间(Inter-AS)：对于 HOST 与 DC_SWITCH 节点，通过所在 AS 的 DCI 节点转发，
 *    而 DCI_SWITCH 节点仅处理同 AS 内的路由。
 */
void SetRoutingEntries() {
    // [UNCHANGED] 预先收集所有 HOST 节点的 ID，并缓存其 IP 地址
    vector<uint32_t> host_ids;         
    vector<Ipv4Address> host_addresses(nodeInfos.size()); 
    for (uint32_t i = 0; i < nodeInfos.size(); i++) {
        if (nodeInfos[i].node_type == NodeInfo::NodeType::HOST) {
            host_ids.push_back(i);
            Ptr<Node> host_node = n.Get(i);
            host_addresses[i] = host_node->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();
        }
    }

    // [UNCHANGED] Lambda 函数：添加路由表项
    auto addTableEntry = [&](Ptr<Node> src_node, Ipv4Address dstAddr, uint32_t if_idx) {
        if (src_node->GetObject<RdmaDriver>() != nullptr) {
            src_node->GetObject<RdmaDriver>()->m_rdma->AddTableEntry(dstAddr, if_idx);
        } else {
            DynamicCast<SwitchNode>(src_node)->AddTableEntry(dstAddr, if_idx);
        }
    };

    // 遍历所有节点
    for (uint32_t src_id = 0; src_id < nodeInfos.size(); src_id++) {
        // [CHANGED] 修改判断条件，允许 WAN_SWITCH 进入循环
        if (nodeInfos[src_id].node_type == NodeInfo::NodeType::HOST ||
            nodeInfos[src_id].node_type == NodeInfo::NodeType::DC_SWITCH ||
            nodeInfos[src_id].node_type == NodeInfo::NodeType::DCI_SWITCH ||
            nodeInfos[src_id].node_type == NodeInfo::NodeType::WAN_SWITCH) { // <--- Added
            
            Ptr<Node> src_node = n.Get(src_id);
            NodeInfo &srcInfo = nodeInfos[src_id];

            // 对于每个目标 HOST 节点
            for (uint32_t dst_host_id : host_ids) {
                // 跳过自身
                if (src_id == dst_host_id) continue;

                Ipv4Address dstAddr = host_addresses[dst_host_id];

                // ------------------------------------------------------------------
                // 逻辑分支 1: Intra-AS (同一 AS 内)
                // [CHANGED] 排除 WAN Switch，因为 WAN Switch 的直连逻辑在后面单独处理
                // ------------------------------------------------------------------
                if (srcInfo.node_type != NodeInfo::NodeType::WAN_SWITCH && 
                    srcInfo.as_id == nodeInfos[dst_host_id].as_id) {
                    
                    Ptr<Node> dst_node = n.Get(dst_host_id);
                    // [UNCHANGED] 直接路由
                    for (auto next_node : nextHop[src_node][dst_node]) {
                        addTableEntry(src_node, dstAddr, nbr2if[src_node][next_node].idx);
                    }
                }
                // ------------------------------------------------------------------
                // 逻辑分支 2: Inter-AS (不同 AS，或者 WAN Host 到 WAN Switch)
                // [CHANGED] 排除 DCI Switch 和 WAN Switch，这部分是 HOST/DC_SWITCH 的逻辑
                // ------------------------------------------------------------------
                else if (srcInfo.node_type != NodeInfo::NodeType::DCI_SWITCH && 
                         srcInfo.node_type != NodeInfo::NodeType::WAN_SWITCH) {
                    
                    // 子情况 A: 是普通 DC Host (所在的 AS 存在对应的 DCI 节点)
                    if (Settings::asId2DciId.find(srcInfo.as_id) != Settings::asId2DciId.end()) {
                        Ptr<Node> dci_node = n.Get(Settings::asId2DciId[srcInfo.as_id]);
                        for (auto next_node : nextHop[src_node][dci_node]) {
                            addTableEntry(src_node, dstAddr, nbr2if[src_node][next_node].idx);
                        }
                    }
                    // 子情况 B: 是 WAN Host (没有对应的 DCI，直接挂在 WAN Switch 下)
                    else {
                        // [UNCHANGED from previous fix] 直接发给 Uplink
                        for (auto it = nbr2if[src_node].begin(); it != nbr2if[src_node].end(); it++) {
                            if (it->second.up) {
                                addTableEntry(src_node, dstAddr, it->second.idx);
                                break; 
                            }
                        }
                    }
                }
                // ------------------------------------------------------------------
                // [CHANGED/ADDED] 逻辑分支 3: WAN SWITCH 的路由逻辑
                // ------------------------------------------------------------------
                else if (srcInfo.node_type == NodeInfo::NodeType::WAN_SWITCH) {
                    
                    uint32_t dst_as_or_sw_id = nodeInfos[dst_host_id].as_id;

                    // 情况 A: 目标 Host 直连在当前 WAN Switch 上 (Local)
                    // (WAN Host 的 as_id 被设置为了其直连 Switch 的 ID)
                    if (src_id == dst_as_or_sw_id) {
                        // 遍历邻居表，找到连接该 Host 的端口
                        bool found = false;
                        for (auto it = nbr2if[src_node].begin(); it != nbr2if[src_node].end(); it++) {
                            // it->first 是邻居 Node 指针
                            if (it->first->GetId() == dst_host_id && it->second.up) {
                                addTableEntry(src_node, dstAddr, it->second.idx);
                                found = true;
                                break;
                            }
                        }
                        // 如果没找到，说明拓扑配置有误 (as_id 对上了但没物理连接)
                        if (!found) {
                             NS_LOG_WARN("WAN Switch " << src_id << " should have local host " << dst_host_id << " but no link found.");
                        }
                    }
                    // 情况 B: 目标 Host 在其他地方 (Remote: 其他 WAN Switch 或 DC)
                    // 无论是去往其他 WAN Switch (WAN Host) 还是去往 AS (DC Host)，
                    // 都在 SetSPFWanRouting 中填入了 wan_routing 表。
                    else {
                        // 查表转发
                        if (Settings::wan_routing[src_id].count(dst_as_or_sw_id)) {
                            // 可能有多个 ECMP 路径
                            for (auto port : Settings::wan_routing[src_id][dst_as_or_sw_id]) {
                                addTableEntry(src_node, dstAddr, port);
                            }
                        }
                    }
                }
                // [UNCHANGED] 对于 DCI_SWITCH 节点，这里维持原样不做处理
                // (它的路由在 switch-node.cc 或其他地方通过 wan_routing 表动态处理，或者此处无需静态配置)
            }
        }
    }
}

map<uint32_t, map<uint32_t, uint64_t>> as_delay; //(as_id, as_id) -> delay
void SetSPFWanRouting() {
    // [UNCHANGED] 初始化变量
    json& j = topo_json;

    /* ---------- [UNCHANGED] 构建节点集合与边 ----------- */
    std::set<uint32_t> nodes;
    std::set<uint32_t> dci_nodes;                        
    std::map<uint32_t, std::map<uint32_t, uint64_t>> edges; 

    /* DCI 节点 */
    for (const auto& [as_id, dci_id] : Settings::asId2DciId) {
        nodes.insert(dci_id);
        dci_nodes.insert(dci_id);
    }

    /* 普通 WAN 交换机节点 */
    for (const auto& wan_switch : j["wan_switches"])
        nodes.insert(wan_switch.get<uint32_t>());

    /* 链路 */
    for (const auto& wan_link : j["wan_links"]) {
        uint32_t src = wan_link["src"].get<uint32_t>();
        uint32_t dst = wan_link["dst"].get<uint32_t>();
        uint64_t link_delay = Settings::nbr2if[n.Get(src)][n.Get(dst)].delay;
        edges[src][dst] = link_delay;
        edges[dst][src] = link_delay; 
    }

    /* ---------- [UNCHANGED] 构建邻接表 ----------- */
    std::unordered_map<uint32_t, std::vector<uint32_t>> adj;
    for (const auto& [src, dst_map] : edges)
        for (const auto& [dst, _] : dst_map) adj[src].push_back(dst);

    /* ---------- [UNCHANGED] 逐源节点 BFS ---------- */
    Settings::wan_routing.clear();
    as_delay.clear();

    std::queue<uint32_t> q;
    std::unordered_map<uint32_t, uint32_t> parent;  

    for (uint32_t src : nodes) {
        parent.clear();
        parent[src] = src;
        while (!q.empty()) q.pop();                
        q.push(src);

        /* BFS：保证最少跳数 */
        while (!q.empty()) {
            uint32_t u = q.front(); q.pop();
            for (uint32_t v : adj[u]) {
                if (!parent.count(v)) {            
                    parent[v] = u;
                    q.push(v);
                }
            }
        }

        // [CHANGED/ADDED] 定义一个 Lambda Helper 来寻找下一跳，减少重复代码
        auto findNextHop = [&](uint32_t dst_node) -> uint32_t {
            if (src == dst_node || !parent.count(dst_node)) return (uint32_t)-1; 
            uint32_t curr = dst_node;
            while (parent[curr] != src) curr = parent[curr];
            return curr;
        };

        /* [UNCHANGED LOGIC] 为所有 DCI (AS) 目标填 next-hop */
        for (auto [as, dst] : Settings::asId2DciId) {
            uint32_t nextHop = findNextHop(dst); // 使用 helper

            if (nextHop != (uint32_t)-1) {
                Settings::wan_routing[src][as].push_back(nbr2if[n.Get(src)][n.Get(nextHop)].idx);
                // printf("WAN routing: %u -> %u, next hop: %u\n", src, as, nextHop);

                /* 若源本身也是 DCI，则计算两 DCI 之间的最短路径延迟 */
                if (dci_nodes.count(src)) {
                    uint64_t pathDelay = 0;
                    for (uint32_t cur = dst; cur != src; ) {
                        uint32_t prv = parent[cur];
                        pathDelay += edges[prv].at(cur);     
                        cur = prv;
                    }
                    as_delay[src][dst] = pathDelay;
                    as_delay[dst][src] = pathDelay; 
                    // cout << "AS delay: " << src << " -> " << dst << ": " << pathDelay << " ns" << endl;
                }
            }
        }

        /* [CHANGED/ADDED] 为所有 WAN Switch 目标填 next-hop */
        // WAN Host 的路由依赖于能够到达其直连的 WAN Switch
        for (const auto& wan_switch : j["wan_switches"]) {
            uint32_t dst_sw = wan_switch.get<uint32_t>();
            // 注意：这里我们将 wan_switch_id 直接作为 wan_routing 的第二层 key
            // 因为 WAN Host 的 as_id 就等于 wan_switch_id
            uint32_t nextHop = findNextHop(dst_sw);

            if (nextHop != (uint32_t)-1) {
                // 简单的防重复检查（有些拓扑里 WAN Switch 可能同时被标记为 DCI，避免重复添加端口）
                bool already_exists = false;
                if (Settings::wan_routing[src].count(dst_sw)) {
                    for (auto p : Settings::wan_routing[src][dst_sw]) {
                        if (p == nbr2if[n.Get(src)][n.Get(nextHop)].idx) already_exists = true;
                    }
                }
                
                if (!already_exists) {
                    Settings::wan_routing[src][dst_sw].push_back(nbr2if[n.Get(src)][n.Get(nextHop)].idx);
                    // printf("WAN routing (Switch-to-Switch): %u -> %u, next hop: %u\n", src, dst_sw, nextHop);
                }
            }
        }
    }
}



/**
 * @brief take down the link between a and b, and redo the routing
 */
void TakeDownLink(NodeContainer n, Ptr<Node> a, Ptr<Node> b) {
    if (!nbr2if[a][b].up) return;
    // take down link between a and b
    nbr2if[a][b].up = nbr2if[b][a].up = false;
    nextHop.clear();
    CalculateRoutes(n);
    // clear routing tables
    for (uint32_t i = 0; i < n.GetN(); i++) {
        if (n.Get(i)->GetNodeType() == 1)
            DynamicCast<SwitchNode>(n.Get(i))->ClearTable();
        else
            n.Get(i)->GetObject<RdmaDriver>()->m_rdma->ClearTable();
    }
    DynamicCast<QbbNetDevice>(a->GetDevice(nbr2if[a][b].idx))->TakeDown();
    DynamicCast<QbbNetDevice>(b->GetDevice(nbr2if[b][a].idx))->TakeDown();
    // reset routing table
    SetRoutingEntries();

    // redistribute qp on each host
    for (uint32_t i = 0; i < n.GetN(); i++) {
        if (n.Get(i)->GetNodeType() == 0)
            n.Get(i)->GetObject<RdmaDriver>()->m_rdma->RedistributeQp();
    }
}

uint64_t get_nic_rate(NodeContainer &n) {
    uint64_t avg_nic_rate;
    uint64_t n_servers = 0;
    for (uint32_t i = 0; i < n.GetN(); i++) {
        if (n.Get(i)->GetNodeType() == 0) {
            avg_nic_rate +=
                DynamicCast<QbbNetDevice>(n.Get(i)->GetDevice(1))->GetDataRate().GetBitRate();
            n_servers += 1;
        }
    }
    return avg_nic_rate / n_servers;
}

vector<tuple<uint32_t, uint32_t, string, string, double>> links;
void init_nodeinfo_links() {
    /**
     * 初始化Settings::nodeInfos, Settings::asId2DciId, links
     */
    json& j = topo_json;

    // 使用 as_topologies 数组的大小代替冗余字段 num_as
    int num_as = j["as_topologies"].size();
    uint32_t& node_num = Settings::node_num;

    // 遍历每个 AS 的拓扑信息
    for (int as_index = 0; as_index < num_as; ++as_index) {
        const auto &as_topo = j["as_topologies"][as_index];
        int dci_switch = as_topo["dci_switch"].get<int>();
        int as_id = as_topo["as_id"].get<int>();  // 统一使用 as_id 作为 AS 标识

        // 使用数组的 size() 获取交换机和主机数量，去掉冗余字段
        int num_switches = as_topo["switches"].size();
        int num_hosts = as_topo["hosts"].size();
        node_num += 1 + num_switches + num_hosts;

        // 配置 DCI 交换机
        nodeInfos[dci_switch].basic_config(as_id, dci_switch, NodeInfo::NodeType::DCI_SWITCH);
        Settings::asId2DciId[as_id] = dci_switch;

        // 配置交换机
        for (const auto &sw : as_topo["switches"]) {
            uint32_t switch_id = sw.get<uint32_t>();
            nodeInfos[switch_id].basic_config(as_id, switch_id, NodeInfo::NodeType::DC_SWITCH);
        }

        // 配置主机
        for (const auto &host : as_topo["hosts"]) {
            uint32_t host_id = host.get<uint32_t>();
            nodeInfos[host_id].basic_config(as_id, host_id, NodeInfo::NodeType::HOST);
        }

        // 读取链路信息（无需依赖冗余的链路数量字段）
        for (const auto &link : as_topo["links"]) {
            uint32_t src = link["src"].get<uint32_t>();
            uint32_t dst = link["dst"].get<uint32_t>();
            std::string data_rate = link["bw"].get<std::string>();
            std::string link_delay = link["delay"].get<string>();
            double error_rate = link["loss"].get<double>();
            links.push_back(make_tuple(src, dst, data_rate, link_delay, error_rate));
        }
    }

    // 处理广域网部分
    auto wan_switches = j["wan_switches"];
    auto wan_links = j["wan_links"];
    auto wan_hosts = j["wan_hosts"]; // 获取所有 WAN Hosts 的列表

    int wan_host_idx = 0; // 全局索引，用于从 wan_hosts 数组中顺序取值

    for (const auto &wan_switch : wan_switches) {
        uint32_t wan_switch_id = wan_switch.get<uint32_t>();
        // 将 WAN Switch 配置为 WAN_SWITCH 类型
        nodeInfos[wan_switch_id].basic_config(wan_switch_id, wan_switch_id, NodeInfo::NodeType::WAN_SWITCH);
        
        // 配置20个wan hosts
        // 每个 WAN Switch 挂载 20 个 Host
        for (int k = 0; k < 20; ++k) {
            if (wan_host_idx >= wan_hosts.size()) {
                printf("Error: Not enough wan_hosts defined in topology json!\n");
                break;
            }

            uint32_t host_id = wan_hosts[wan_host_idx].get<uint32_t>();
            wan_host_idx++; // 移动索引

            // 配置 WAN Host
            // 将 wan_switch_id 作为 AS ID 传入，以此表示该 Host 属于该区域
            nodeInfos[host_id].basic_config(wan_switch_id, host_id, NodeInfo::NodeType::HOST);
            // 增加总节点计数
            node_num++;
        }
    }

    // 配置 WAN Switch 之间的骨干链路
    for (const auto &wan_link : wan_links) {
        uint32_t src = wan_link["src"].get<uint32_t>();
        uint32_t dst = wan_link["dst"].get<uint32_t>();
        std::string data_rate = wan_link["bw"].get<std::string>();
        std::string link_delay = wan_link["delay"].get<string>();
        double error_rate = wan_link["loss"].get<double>();
        links.push_back(make_tuple(src, dst, data_rate, link_delay, error_rate));
    }
    node_num += wan_switches.size();
    assert(nodeInfos[node_num].node_type == NodeInfo::NodeType::UNCONFIGURED);
    nodeInfos.resize(node_num);
    printf("Successfully init all nodes! Node number:%ld\n", nodeInfos.size());
}

/************************************************************************/
//                                                                      //
//                                M A I N                               //
//                                                                      //
/************************************************************************/

int main(int argc, char *argv[]) {
    uint32_t *workload_cdf = nullptr;
    clock_t begint, endt;
    begint = clock();

//参数配置
#ifndef PGO_TRAINING
    if (argc > 1)
#else
    if (true)
#endif
    {
        // Read the configuration file
        std::ifstream conf;
#ifndef PGO_TRAINING
        conf.open(argv[1]);
#else
        conf.open(PATH_TO_PGO_CONFIG);
#endif
        std::string key;
        while (conf >> key) {
            if (key.compare("OUTPUT_DIR_PATH") == 0) {
                std::string v;
                conf >> v;
                output_dir = v;
            } else if (key.compare("LB_MODE") == 0) {
                uint32_t v;
                conf >> v;
                lb_mode = v;
                std::cerr << "LB_MODE\t\t\t" << lb_mode << "\n";
            } else if (key.compare("SW_MONITORING_INTERVAL") == 0) {
                uint32_t v;
                conf >> v;
                switch_mon_interval = v;
                std::cerr << "SW_MONITORING_INTERVAL\t\t\t" << switch_mon_interval << "\n";
            } else if (key.compare("ENABLE_PFC") == 0) {
                uint32_t v;
                conf >> v;
                enable_pfc = v;
                if (enable_pfc)
                    std::cerr << "ENABLE_PFC\t\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "ENABLE_PFC\t\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("ENABLE_QCN") == 0) {
                uint32_t v;
                conf >> v;
                enable_qcn = v;
                if (enable_qcn)
                    std::cerr << "ENABLE_QCN\t\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "ENABLE_QCN\t\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("USE_DYNAMIC_PFC_THRESHOLD") == 0) {
                uint32_t v;
                conf >> v;
                use_dynamic_pfc_threshold = v;
                if (use_dynamic_pfc_threshold)
                    std::cerr << "USE_DYNAMIC_PFC_THRESHOLD\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "USE_DYNAMIC_PFC_THRESHOLD\t"
                              << "No"
                              << "\n";
            } else if (key.compare("CLAMP_TARGET_RATE") == 0) {
                uint32_t v;
                conf >> v;
                clamp_target_rate = v;
                if (clamp_target_rate)
                    std::cerr << "CLAMP_TARGET_RATE\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "CLAMP_TARGET_RATE\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("PAUSE_TIME") == 0) {
                double v;
                conf >> v;
                pause_time = v;
                std::cerr << "PAUSE_TIME\t\t\t" << pause_time << "\n";
            } else if (key.compare("DATA_RATE") == 0) {
                std::string v;
                conf >> v;
                data_rate = v;
                std::cerr << "DATA_RATE\t\t\t" << data_rate << "\n";
            } else if (key.compare("LINK_DELAY") == 0) {
                std::string v;
                conf >> v;
                link_delay = v;
                std::cerr << "LINK_DELAY\t\t\t" << link_delay << "\n";
            } else if (key.compare("PACKET_PAYLOAD_SIZE") == 0) {
                uint32_t v;
                conf >> v;
                packet_payload_size = v;
                std::cerr << "PACKET_PAYLOAD_SIZE\t\t" << packet_payload_size << "\n";
            } else if (key.compare("L2_CHUNK_SIZE") == 0) {
                uint32_t v;
                conf >> v;
                l2_chunk_size = v;
                std::cerr << "L2_CHUNK_SIZE\t\t\t" << l2_chunk_size << "\n";
            } else if (key.compare("L2_ACK_INTERVAL") == 0) {
                uint32_t v;
                conf >> v;
                l2_ack_interval = v;
                std::cerr << "L2_ACK_INTERVAL\t\t\t" << l2_ack_interval << "\n";
            } else if (key.compare("L2_BACK_TO_ZERO") == 0) {
                uint32_t v;
                conf >> v;
                l2_back_to_zero = v;
                if (l2_back_to_zero)
                    std::cerr << "L2_BACK_TO_ZERO\t\t\t"
                              << "Yes"
                              << "\n";
                else
                    std::cerr << "L2_BACK_TO_ZERO\t\t\t"
                              << "No"
                              << "\n";
            } else if (key.compare("TOPOLOGY_FILE") == 0) {
                std::string v;
                conf >> v;
                topology_file = v;
                std::cerr << "TOPOLOGY_FILE\t\t\t" << topology_file << "\n";
            } else if (key.compare("FLOW_FILE") == 0) {
                std::string v;
                conf >> v;
                flow_file = v;
                std::cerr << "FLOW_FILE\t\t\t" << flow_file << "\n";
            } else if (key.compare("TCP_FLOW_FILE") == 0) {
                std::string v;
                conf >> v;
                tcp_flow_file = v;
                std::cerr << "TCP_FLOW_FILE\t\t\t" << tcp_flow_file << "\n";
            } else if (key.compare("FLOWGEN_START_TIME") == 0) {
                double v;
                conf >> v;
                flowgen_start_time = v;
                cnp_mon_start = v;
                irn_mon_start = v;
                std::cerr << "FLOWGEN_START_TIME\t\t" << flowgen_start_time << "\n";
            } else if (key.compare("FLOWGEN_STOP_TIME") == 0) {
                double v;
                conf >> v;
                flowgen_stop_time = v;
                std::cerr << "FLOWGEN_STOP_TIME\t\t" << flowgen_stop_time << "\n";
            } else if (key.compare("ALPHA_RESUME_INTERVAL") == 0) {
                double v;
                conf >> v;
                alpha_resume_interval = v;
                std::cerr << "ALPHA_RESUME_INTERVAL\t\t" << alpha_resume_interval << "\n";
            } else if (key.compare("RP_TIMER") == 0) {
                double v;
                conf >> v;
                rp_timer = v;
                std::cerr << "RP_TIMER\t\t\t" << rp_timer << "\n";
            } else if (key.compare("EWMA_GAIN") == 0) {
                double v;
                conf >> v;
                ewma_gain = v;
                std::cerr << "EWMA_GAIN\t\t\t" << ewma_gain << "\n";
            } else if (key.compare("FAST_RECOVERY_TIMES") == 0) {
                uint32_t v;
                conf >> v;
                fast_recovery_times = v;
                std::cerr << "FAST_RECOVERY_TIMES\t\t" << fast_recovery_times << "\n";
            } else if (key.compare("RATE_AI") == 0) {
                std::string v;
                conf >> v;
                rate_ai = v;
                std::cerr << "RATE_AI\t\t\t\t" << rate_ai << "\n";
            } else if (key.compare("RATE_HAI") == 0) {
                std::string v;
                conf >> v;
                rate_hai = v;
                std::cerr << "RATE_HAI\t\t\t" << rate_hai << "\n";
            } else if (key.compare("ERROR_RATE_PER_LINK") == 0) {
                double v;
                conf >> v;
                error_rate_per_link = v;
                std::cerr << "ERROR_RATE_PER_LINK\t\t" << error_rate_per_link << "\n";
            } else if (key.compare("CC_MODE") == 0) {
                conf >> cc_mode;
                std::cerr << "CC_MODE\t\t" << cc_mode << '\n';
            } else if (key.compare("RATE_DECREASE_INTERVAL") == 0) {
                double v;
                conf >> v;
                rate_decrease_interval = v;
                std::cerr << "RATE_DECREASE_INTERVAL\t\t" << rate_decrease_interval << "\n";
            } else if (key.compare("MIN_RATE") == 0) {
                conf >> min_rate;
                std::cerr << "MIN_RATE\t\t" << min_rate << "\n";
            } else if (key.compare("HAS_WIN") == 0) {
                conf >> has_win;
                std::cerr << "HAS_WIN\t\t" << has_win << "\n";
            } else if (key.compare("GLOBAL_T") == 0) {
                conf >> global_t;
                std::cerr << "GLOBAL_T\t\t" << global_t << '\n';
            } else if (key.compare("MI_THRESH") == 0) {
                conf >> mi_thresh;
                std::cerr << "MI_THRESH\t\t" << mi_thresh << '\n';
            } else if (key.compare("VAR_WIN") == 0) {
                uint32_t v;
                conf >> v;
                var_win = v;
                std::cerr << "VAR_WIN\t\t" << v << '\n';
            } else if (key.compare("FAST_REACT") == 0) {
                uint32_t v;
                conf >> v;
                fast_react = v;
                std::cerr << "FAST_REACT\t\t" << v << '\n';
            } else if (key.compare("U_TARGET") == 0) {
                conf >> u_target;
                std::cerr << "U_TARGET\t\t" << u_target << '\n';
            } else if (key.compare("INT_MULTI") == 0) {
                conf >> int_multi;
                std::cerr << "INT_MULTI\t\t\t\t" << int_multi << '\n';
            } else if (key.compare("RATE_BOUND") == 0) {
                uint32_t v;
                conf >> v;
                rate_bound = v;
                std::cerr << "RATE_BOUND\t\t" << rate_bound << '\n';
            } else if (key.compare("DCTCP_RATE_AI") == 0) {
                conf >> dctcp_rate_ai;
                std::cerr << "DCTCP_RATE_AI\t\t\t\t" << dctcp_rate_ai << "\n";
            } else if (key.compare("KMAX_MAP") == 0) {
                int n_k;
                conf >> n_k;
                std::cerr << "KMAX_MAP\t\t\t\t";
                for (int i = 0; i < n_k; i++) {
                    uint64_t rate;
                    uint32_t k;
                    conf >> rate >> k;
                    rate2kmax[rate] = k;
                    std::cerr << ' ' << rate << ' ' << k;
                }
                std::cerr << '\n';
            } else if (key.compare("KMIN_MAP") == 0) {
                int n_k;
                conf >> n_k;
                std::cerr << "KMIN_MAP\t\t\t\t";
                for (int i = 0; i < n_k; i++) {
                    uint64_t rate;
                    uint32_t k;
                    conf >> rate >> k;
                    rate2kmin[rate] = k;
                    std::cerr << ' ' << rate << ' ' << k;
                }
                std::cerr << '\n';
            } else if (key.compare("PMAX_MAP") == 0) {
                int n_k;
                conf >> n_k;
                std::cerr << "PMAX_MAP\t\t\t\t";
                for (int i = 0; i < n_k; i++) {
                    uint64_t rate;
                    double p;
                    conf >> rate >> p;
                    rate2pmax[rate] = p;
                    std::cerr << ' ' << rate << ' ' << p;
                }
                std::cerr << '\n';
            } else if (key.compare("BUFFER_SIZE") == 0) {
                conf >> buffer_size;
                std::cerr << "BUFFER_SIZE\t\t\t\t" << buffer_size << '\n';
            } else if (key.compare("DCI_BUFFER_SIZE") == 0) {
                conf >> dci_buffer_size;
                std::cerr << "DCI_BUFFER_SIZE\t\t\t" << dci_buffer_size << '\n';
            } else if (key.compare("WAN_BUFFER_SIZE") == 0) {
                conf >> wan_buffer_size;
                std::cerr << "WAN_BUFFER_SIZE\t\t\t" << wan_buffer_size << '\n';
            } else if (key.compare("MULTI_RATE") == 0) {
                int v;
                conf >> v;
                multi_rate = v;
                std::cerr << "MULTI_RATE\t\t\t\t" << multi_rate << '\n';
            } else if (key.compare("SAMPLE_FEEDBACK") == 0) {
                int v;
                conf >> v;
                sample_feedback = v;
                std::cerr << "SAMPLE_FEEDBACK\t\t\t\t" << sample_feedback << '\n';
            } else if (key.compare("ENABLE_IRN") == 0) {
                bool v;
                conf >> v;
                enable_irn = v;
                std::cerr << "ENABLE_IRN\t\t" << enable_irn << "\n";
            } else if (key.compare("RANDOM_SEED") == 0) {
                int v;
                conf >> v;
                random_seed = v;
                std::cerr << "RANDOM_SEED\t\t\t" << random_seed << "\n";
            } else if (key.compare("WAN_CC_MODE") == 0) {
                int v;
                conf >> v;
                Settings::wan_cc_mode = static_cast<Settings::WanCCMode>(v);
                std::cerr << "WAN_CC_MODE\t\t\t" << v << "\n";
            } else {
                // Unknown key: consume the rest of the line and store as raw string.
                // This enables quick experimentation without plumbing every knob.
                std::string rawValue;
                std::getline(conf, rawValue);
                rawValue = _TrimWs(rawValue);
                Settings::SetRawParam(key, rawValue);
                std::cerr << "RAW_PARAM\t\t\t" << key << "\t" << rawValue << "\n";
            }

            fflush(stdout);
        }
        conf.close();

    } else {
        std::cerr << "Error: require a config file\n";
        fflush(stdout);
        return 1;
    }

    /******************* READING CONFIG FILE IS DONE ***********************/

    /**
     * Activate ns3 logging
     */
    LogComponentEnable("GENERIC_SIMULATION", LOG_LEVEL_DEBUG);

    /**
     * @brief Random seed setup
     */
    NS_LOG_INFO("Initialize random seed: " << random_seed);
    srand((unsigned)random_seed);
    SeedManager::SetSeed(random_seed);

    /**
     * @brief basic setup
     */
    Settings::lb_mode = lb_mode;
    Settings::packet_payload = packet_payload_size;
    initialize_log();

    /**
     * @brief PFC/QCN setup
     */
    bool dynamicth = use_dynamic_pfc_threshold;
    Config::SetDefault("ns3::QbbNetDevice::PauseTime", UintegerValue(pause_time));
    Config::SetDefault("ns3::QbbNetDevice::QcnEnabled", BooleanValue(enable_qcn));
    Config::SetDefault("ns3::QbbNetDevice::DynamicThreshold", BooleanValue(dynamicth));
    Config::SetDefault("ns3::QbbNetDevice::QbbEnabled", BooleanValue(enable_pfc));

    /**
     * @brief INT header setup
     */
    IntHop::multi = int_multi;
    // IntHeader::mode
    if (cc_mode == 7)  // timely, use ts
        IntHeader::mode = 1;
    else if (cc_mode == 3)  // hpcc, use int
        IntHeader::mode = 0;
    else  // others, no extra header
        IntHeader::mode = 5;

    /**
     * @brief open topology config, input-flows config.
     */
    ifstream topof(topology_file);
    topof >> topo_json;
    init_nodeinfo_links();

    //创建节点
    for (auto& node_info : nodeInfos) {
        switch (node_info.node_type) {
            case NodeInfo::NodeType::HOST: {
                Ptr<Node> host = CreateObject<Node>();
                n.Add(host);
                break;
            }
            case NodeInfo::NodeType::DC_SWITCH: {
                Ptr<SwitchNode> sw = CreateObject<SwitchNode>();
                n.Add(sw);
                sw->SetAttribute("EcnEnabled", BooleanValue(enable_qcn));
                sw->SetAttribute("PfcEnabled", BooleanValue(enable_pfc));
                break;
            }
            case NodeInfo::NodeType::DCI_SWITCH: {
                Ptr<SwitchNode> sw = CreateObject<SwitchNode>();
                n.Add(sw);
                sw->SetAttribute("EcnEnabled", BooleanValue(enable_qcn));
                sw->SetAttribute("PfcEnabled", BooleanValue(enable_pfc));
                sw->isDCI = true;
                break;
            }
            case NodeInfo::NodeType::WAN_SWITCH: {
                Ptr<SwitchNode> sw = CreateObject<SwitchNode>();
                sw->SetAttribute("EcnEnabled", BooleanValue(Settings::wan_cc_mode == Settings::WanCCMode::WITH_ECN));
                sw->SetAttribute("PfcEnabled", BooleanValue(false));
                n.Add(sw);
                break;
            }
            default:
                assert(false);
        }
    }


    /*----------------------------------------*/

    InternetStackHelper internet;
    internet.Install(n);  // aggregate ipv4, ipv6, udp, tcp, etc
    //node_id_to_ip just return an ipv4 address based on the node id without change any other thing
    NS_LOG_INFO("Create channels.");
    //for (int i = 0; i < nodeInfos.size(); i++) {
    //    if (nodeInfos[i].node_type == NodeInfo::NodeType::DCI_SWITCH) {
    //        Ptr<Ipv4> ipv4 = n.Get(i)->GetObject<Ipv4>();
    //        ipv4->AddInterface(d.Get(0));
    //        ipv4->AddAddress(1, Ipv4InterfaceAddress(nodeInfos[src].ip, Ipv4Mask(0xff000000)));
    //    }
    //}

    //
    // Explicitly create the channels required by the topology.
    //

    Ptr<RateErrorModel> rem = CreateObject<RateErrorModel>();
    Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
    rem->SetRandomVariable(uv);
    uv->SetStream(50);
    rem->SetAttribute("ErrorRate", DoubleValue(error_rate_per_link));
    rem->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
    QbbHelper qbb;
    Ipv4AddressHelper ipv4;
    uint32_t link_id = 0;
    for (const auto [src, dst, data_rate, link_delay, error_rate] : links) {
        //std::cout << "link_delay: " << link_delay << std::endl;
        /** ASSUME: fixed one-hop delay across network */

        Ptr<Node> snode = n.Get(src), dnode = n.Get(dst);

        qbb.SetDeviceAttribute("DataRate", StringValue(data_rate));
        qbb.SetChannelAttribute("Delay", StringValue(link_delay));

        if (error_rate > 0) {
            Ptr<RateErrorModel> rem = CreateObject<RateErrorModel>();
            Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
            rem->SetRandomVariable(uv);
            uv->SetStream(50);
            rem->SetAttribute("ErrorRate", DoubleValue(error_rate));
            rem->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
            qbb.SetDeviceAttribute("ReceiveErrorModel", PointerValue(rem));
        } else {
            qbb.SetDeviceAttribute("ReceiveErrorModel", PointerValue(rem));
        }

        fflush(stdout);

        // Assigne server IP
        // Note: this should be before the automatic assignment below (ipv4.Assign(d)),
        // because we want our IP to be the primary IP (first in the IP address list),
        // so that the global routing is based on our IP
        // Adding network devices to a link
        NetDeviceContainer d = qbb.Install(snode, dnode);
        if (snode->GetNodeType() == 0) {
            Ptr<Ipv4> ipv4 = snode->GetObject<Ipv4>();
            ipv4->AddInterface(d.Get(0));
            ipv4->AddAddress(1, Ipv4InterfaceAddress(nodeInfos[src].ip, Ipv4Mask(0xff000000)));
        }
        if (dnode->GetNodeType() == 0) {
            Ptr<Ipv4> ipv4 = dnode->GetObject<Ipv4>();
            ipv4->AddInterface(d.Get(1));
            ipv4->AddAddress(1, Ipv4InterfaceAddress(nodeInfos[dst].ip, Ipv4Mask(0xff000000)));
        }
        
        // used to create a graph of the topology
        nbr2if[snode][dnode].idx = DynamicCast<QbbNetDevice>(d.Get(0))->GetIfIndex();
        nbr2if[snode][dnode].up = true;
        nbr2if[snode][dnode].delay =
            DynamicCast<QbbChannel>(DynamicCast<QbbNetDevice>(d.Get(0))->GetChannel())
                ->GetDelay()
                .GetTimeStep();
        nbr2if[snode][dnode].bw = DynamicCast<QbbNetDevice>(d.Get(0))->GetDataRate().GetBitRate();
        nbr2if[dnode][snode].idx = DynamicCast<QbbNetDevice>(d.Get(1))->GetIfIndex();
        nbr2if[dnode][snode].up = true;
        nbr2if[dnode][snode].delay =
            DynamicCast<QbbChannel>(DynamicCast<QbbNetDevice>(d.Get(1))->GetChannel())
                ->GetDelay()
                .GetTimeStep();
        nbr2if[dnode][snode].bw = DynamicCast<QbbNetDevice>(d.Get(1))->GetDataRate().GetBitRate();
        if2id[snode][nbr2if[snode][dnode].idx] = dnode->GetId();
        if2id[dnode][nbr2if[dnode][snode].idx] = snode->GetId();
        //std::cout << "link: " << src << "->" << dst << " interface: " << "id: " << nbr2if[snode][dnode].idx <<  " src: " << nbr2if[snode][dnode].idx << " dst: " << nbr2if[dnode][snode].idx << endl;
        // This is just to set up the connectivity between nodes. The IP addresses are useless
        char ipstring[20];//make complier happy
        //Ipv4Address x;
        snprintf(ipstring, sizeof(ipstring), "10.%d.%d.0", link_id / 254 + 1, link_id % 254 + 1);
        ipv4.SetBase(ipstring, "255.255.255.0");
        ipv4.Assign(d);
    
        // setup PFC trace
        DynamicCast<QbbNetDevice>(d.Get(0))->TraceConnectWithoutContext(
            "QbbPfc", MakeBoundCallback(&get_pfc, pfc_file, DynamicCast<QbbNetDevice>(d.Get(0))));
        DynamicCast<QbbNetDevice>(d.Get(1))->TraceConnectWithoutContext(
            "QbbPfc", MakeBoundCallback(&get_pfc, pfc_file, DynamicCast<QbbNetDevice>(d.Get(1))));
        link_id++;
    }

    std::cout << "(AVG) NIC RATE: " << get_nic_rate(n) << std::endl;

    /* Get IP address <-> NodeID pairs */
    Ipv4Address empty_ip;
    for (uint32_t i = 0; i < nodeInfos.size(); ++i) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            if (nodeInfos[i].ip.IsEqual(empty_ip)) {
                printf("XXX ERROR %d\n", i);
                NS_FATAL_ERROR("An end-host belongs to no link");
            }
        }
        Settings::hostId2IpMap[i] = nodeInfos[i].ip.Get();
        Settings::hostIp2IdMap[nodeInfos[i].ip.Get()] = i;
    }
    // config switch
    for (const auto& node : nodeInfos) {
        if (node.node_type == NodeInfo::NodeType::DC_SWITCH) {
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(node.id));
            for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
                Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(j));
                // set ecn
                uint64_t rate = dev->GetDataRate().GetBitRate();
                sw->m_mmu->ConfigEcn(j, rate2kmin.at(rate), rate2kmax.at(rate), rate2pmax.at(rate));
                // set pfc
                uint64_t delay = DynamicCast<QbbChannel>(dev->GetChannel())->GetDelay().GetTimeStep();
                uint32_t headroom = rate * delay / 8 / 1000000000 * 2 + 2 * sw->m_mmu->MTU;
                sw->m_mmu->ConfigHdrm(j, headroom);
            }
            sw->m_mmu->ConfigNPort(sw->GetNDevices() - 1);
            sw->m_mmu->ConfigBufferSize(buffer_size * 1024 * 1024);  // default 0, specify in run.py!!
            sw->m_mmu->node_id = sw->GetId();
            sw->m_mmu->InitSwitch();

            sw->SetAttribute("CcMode", UintegerValue(cc_mode));
            sw->SetAttribute("AckHighPrio", UintegerValue(1));
            // NS_LOG_INFO("Node %u : Broadcom switch (%u ports / %gMB MMU)\n" %
            //             (node.id, sw->GetNDevices() - 1, sw->m_mmu->GetMmuBufferBytes() / 1000000.));
        } else if (node.node_type == NodeInfo::NodeType::DCI_SWITCH) {
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(node.id));
            for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
                Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(j));
                // set ecn
                uint64_t rate = dev->GetDataRate().GetBitRate();
                //sw->m_mmu->ConfigEcn(j, rate2kmin.at(rate), rate2kmax.at(rate), rate2pmax.at(rate));
                sw->m_mmu->ConfigEcn(j, 1000, 20000, 0.15);
                // set pfc
                uint64_t delay = DynamicCast<QbbChannel>(dev->GetChannel())->GetDelay().GetTimeStep();
                uint32_t headroom = rate * delay / 8 / 1000000000 * 2 + 2 * sw->m_mmu->MTU;
                sw->m_mmu->ConfigHdrm(j, headroom);
            }
            sw->m_mmu->ConfigNPort(sw->GetNDevices() - 1);
            if (dci_buffer_size > 0) {
                sw->m_mmu->ConfigBufferSize(dci_buffer_size * 1024 * 1024);
            } else {
                sw->m_mmu->ConfigBufferSize(160 * 1024 * 1024);  // Magic Number
            }
            sw->m_mmu->node_id = sw->GetId();
            sw->m_mmu->InitSwitch();

            sw->SetAttribute("CcMode", UintegerValue(cc_mode));
            sw->SetAttribute("AckHighPrio", UintegerValue(1));
            // NS_LOG_INFO("Node %u : Broadcom switch (%u ports / %gMB MMU)\n" %
            //             (node.id, sw->GetNDevices() - 1, sw->m_mmu->GetMmuBufferBytes() / 1000000.));
        } else if (node.node_type == NodeInfo::NodeType::WAN_SWITCH) {
            //TODO ECN是否应当被去除？
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(node.id));
            for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
                Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(j));
                dev->SetAttribute("QbbEnabled", BooleanValue(false));
                // set ecn
                uint64_t rate = dev->GetDataRate().GetBitRate();
                //sw->m_mmu->ConfigEcn(j, rate2kmin.at(rate), rate2kmax.at(rate), rate2pmax.at(rate));
                sw->m_mmu->ConfigEcn(j, 1000, 20000, 0.15);
                // set pfc
                //uint64_t delay = DynamicCast<QbbChannel>(dev->GetChannel())->GetDelay().GetTimeStep();
                //uint32_t headroom = rate * delay / 8 / 1000000000 * 2 + 2 * sw->m_mmu->MTU;
                sw->m_mmu->ConfigHdrm(j, 0);
            }
            sw->m_mmu->ConfigNPort(sw->GetNDevices() - 1);
            if (wan_buffer_size > 0) {
                sw->m_mmu->ConfigBufferSize(wan_buffer_size * 1024 * 1024);
            } else {
                sw->m_mmu->ConfigBufferSize(320 * 1024 * 1024);  // Magic Number
            }
            sw->m_mmu->node_id = sw->GetId();
            sw->m_mmu->InitSwitch();

            sw->SetAttribute("CcMode", UintegerValue(cc_mode));
            sw->SetAttribute("AckHighPrio", UintegerValue(1));
        }
    }

    /**
     * @brief install RDMA driver (Mellanox parameters)
     *
     * [ClampTargetRate]clamp_tgt_rate (false) - when receiving a CNP, the target rate is always
     *updated to be the current rate
     *[-]clamp_tgt_rate_after_time_inc (true) - when receiving a CNP, the target rate is updated to
     *be the current rate also if the last rate increase event was due to the timer, and not only
     *due to the byte counter
     * [-]initial_alpha_value(1023) -
     * [RateDecreaseInterval]rate_reduce_monitor_period(4) - Minimal interval for rate reduction for
     *a flow. If a CNP is received during the interval, the flow rate is reduced at the beginning of
     *the next rate_reduce_monitor_period interval to (1-Alpha/Gd)*CurrentRate. rpg_gd is given as
     *log2(Gd), where Gd may only be powers of 2.
     * [-]rpg_gd(11) - If an CNP is received, the flow rate is reduced at the beginning of the next
     *rate_reduce_monitor_period interval to (1-Alpha/Gd)*CurrentRate.
     * -> in this simulator, (alpha / gd) ~ 0.5 setup, initially. We do not need rpg_gd parameter.
     * [RateOnFirstCnp]rate_to_set_on_first_cnp(0) - The rate that is set for the flow, upon first
     *CNP received, in Mbps. [RPTimer]rpg_time_reset(300us) - Time counter for rate increase event
     *[FastRecoveryTimes]rpg_threshold(1) - Number of rate increase events for switching between
     *Fast Recovery, Active Increase, Hyper Active Increase modes.
     * [AlphaResumInterval]dce_tcp_rtt(1) - Window for sampling of moving average calculation of
     *alpha
     * [-]dce_tcp_g(1019) - Weight of the new sampling in moving average calculation of alpha
     * [-]rpg_byte_reset(32767) - Byte counter for rate increase event
     * [-]rpg_min_dec_fac(50) -  Maximal factor by which the rate can be reduced (2 means that the
     *new rate can be divided by 2 at maximum)
     */
 
    // rdmaHw config
    for (uint32_t i = 0; i < nodeInfos.size(); i++) {
        if (n.Get(i)->GetNodeType() == 0) {  // is server
            // create RdmaHw
            Ptr<RdmaHw> rdmaHw = CreateObject<RdmaHw>();
            rdmaHw->SetAttribute("ClampTargetRate", BooleanValue(clamp_target_rate));
            rdmaHw->SetAttribute("AlphaResumInterval", DoubleValue(alpha_resume_interval));
            rdmaHw->SetAttribute("RPTimer", DoubleValue(rp_timer));
            rdmaHw->SetAttribute("FastRecoveryTimes", UintegerValue(fast_recovery_times));
            rdmaHw->SetAttribute("EwmaGain", DoubleValue(ewma_gain));
            rdmaHw->SetAttribute("RateAI", DataRateValue(DataRate(rate_ai)));
            rdmaHw->SetAttribute("RateHAI", DataRateValue(DataRate(rate_hai)));
            rdmaHw->SetAttribute("L2BackToZero", BooleanValue(l2_back_to_zero));
            rdmaHw->SetAttribute("L2ChunkSize", UintegerValue(l2_chunk_size));
            rdmaHw->SetAttribute("L2AckInterval", UintegerValue(l2_ack_interval));
            rdmaHw->SetAttribute("CcMode", UintegerValue(cc_mode));
            rdmaHw->SetAttribute("RateDecreaseInterval", DoubleValue(rate_decrease_interval));
            rdmaHw->SetAttribute("MinRate", DataRateValue(DataRate(min_rate)));
            rdmaHw->SetAttribute("Mtu", UintegerValue(packet_payload_size));
            rdmaHw->SetAttribute("MiThresh", UintegerValue(mi_thresh));
            rdmaHw->SetAttribute("VarWin", BooleanValue(var_win));
            rdmaHw->SetAttribute("FastReact", BooleanValue(fast_react));
            rdmaHw->SetAttribute("MultiRate", BooleanValue(multi_rate));
            rdmaHw->SetAttribute("SampleFeedback", BooleanValue(sample_feedback));
            rdmaHw->SetAttribute("TargetUtil", DoubleValue(u_target));
            rdmaHw->SetAttribute("RateBound", BooleanValue(rate_bound));
            rdmaHw->SetAttribute("DctcpRateAI", DataRateValue(DataRate(dctcp_rate_ai)));
            rdmaHw->SetAttribute("IrnEnable", BooleanValue(enable_irn));
            // topo2bdpMap (e.g., longest BDP 25000: 8us * 25Gbps)
            rdmaHw->SetAttribute("IrnRtoHigh", TimeValue(MicroSeconds(320)));  // 1930
            rdmaHw->SetAttribute("IrnRtoLow", TimeValue(MicroSeconds(100)));   // 454
            //rdmaHw->SetAttribute("IrnBdp", UintegerValue(irn_bdp_lookup)); //计划废弃
            // Monitoring CNP Marking frequency of DCQCN
            if (cc_mode == 1) {
                Simulator::Schedule(NanoSeconds(cnp_mon_start), &cnp_freq_monitoring, cnp_output,
                                    rdmaHw);
            }

            // create and install RdmaDriver
            Ptr<RdmaDriver> rdma = CreateObject<RdmaDriver>();
            Ptr<Node> node = n.Get(i);
            rdma->SetNode(node);
            rdma->SetRdmaHw(rdmaHw);

            node->AggregateObject(rdma);
            rdma->Init();
            rdma->TraceConnectWithoutContext("QpComplete", MakeBoundCallback(qp_finish, flow_output));
        }
    }

    /**
     * @brief setup routing
     */
    CalculateRoutes(n);
    SetRoutingEntries();
    SetSPFWanRouting();
    //init wan_routing
    //for (const auto& routing_entry : topo_json["wan_routing"]) {
    //    int srcSw = routing_entry["srcSw"].get<int>();
    //    int dstAs = routing_entry["dstAs"].get<int>();
    //    for (const auto nextNode : routing_entry["next_nodes"]) {
    //        int next_node = nextNode.get<int>();
    //        Settings::wan_routing[srcSw][dstAs].push_back(nbr2if[n.Get(srcSw)][n.Get(next_node)].idx);
    //    }
    //}
    std::cout << "WAN Routing Table:" << std::endl;
    for (const auto& [srcSw, dstMap] : Settings::wan_routing) {
        std::cout << "Source Switch: " << srcSw << std::endl;
        for (const auto& [dstAs, nextNodes] : dstMap) {
            std::cout << "  Destination AS: " << dstAs << " -> Next Dev: ";
            for (const auto& nextNode : nextNodes) {
                std::cout << nextNode << " ";
            }
            std::cout << std::endl;
        }
    }
    for (int i = 0; i < nodeInfos.size(); i++) {
        if (nodeInfos[i].node_type == NodeInfo::NodeType::DCI_SWITCH) {
            DynamicCast<SwitchNode>(n.Get(i))->m_mmu->m_wanRouting.SetSwitchInfo(i);
            DynamicCast<SwitchNode>(n.Get(i))->m_mmu->m_wanRouting.init();
        }
    }

    /**
     * @brief get BDP and delay
     */
    //unordered_map<uint32_t, unordered_map<uint32_t, uint32_t>> as_delay;
    //for (const auto& delay_entry : topo_json["as_delay"]) {
    //    int src = delay_entry["src"].get<int>();
    //    int dst = delay_entry["dst"].get<int>();
    //    int delay = delay_entry["delay"].get<int>();
    //    as_delay[src][dst] = delay;
    //    as_delay[dst][src] = delay;
    //}
    maxRtt = maxBdp = 0;
    for (uint32_t i = 0; i < nodeInfos.size(); i++) {
        if (nodeInfos[i].node_type != NodeInfo::NodeType::HOST) continue;
        // 只考虑server
        for (uint32_t j = i + 1; j < nodeInfos.size(); j++) {
            if (nodeInfos[j].node_type != NodeInfo::NodeType::HOST) continue;
            if (nodeInfos[i].as_id == nodeInfos[j].as_id) {
                uint64_t delay = pairDelay[n.Get(i)][n.Get(j)];
                uint64_t txDelay = pairTxDelay[n.Get(i)][n.Get(j)];
                uint64_t rtt = delay * 2 + txDelay;
                uint64_t bw = pairBw[n.Get(i)][n.Get(j)];
                uint64_t bdp = rtt * bw / 1000000000 / 8;
                pairBdp[n.Get(i)][n.Get(j)] = bdp;
                pairBdp[n.Get(j)][n.Get(i)] = bdp;
                pairRtt[n.Get(i)][n.Get(j)] = rtt;
                pairRtt[n.Get(j)][n.Get(i)] = rtt;
                if (rtt < server_rtt_mon_interval) server_rtt_mon_interval = rtt;
                if (bdp > maxBdp) maxBdp = bdp;
                if (rtt > maxRtt) maxRtt = rtt;
            } else {
                uint32_t as1 = nodeInfos[i].as_id;
                uint32_t as2 = nodeInfos[j].as_id;
                uint32_t dci1 = Settings::asId2DciId[as1];
                uint32_t dci2 = Settings::asId2DciId[as2];
                uint64_t rtt = (pairDelay[n.Get(i)][n.Get(dci1)] + static_cast<uint64_t>(as_delay[dci1][dci2]) + pairDelay[n.Get(dci2)][n.Get(j)]) * 2;
                uint64_t bdp = rtt / 8 * 100;
                pairBdp[n.Get(i)][n.Get(j)] = bdp;
                pairBdp[n.Get(j)][n.Get(i)] = bdp;
                pairRtt[n.Get(i)][n.Get(j)] = rtt;
                pairRtt[n.Get(j)][n.Get(i)] = rtt;
                //cout << "pair " << i << " " << j << ": rtt " << rtt << " bdp " << bdp << endl;
                if (rtt < server_rtt_mon_interval) server_rtt_mon_interval = rtt;
                if (bdp > maxBdp) maxBdp = bdp;
                if (rtt > maxRtt) maxRtt = rtt;
            }
            //printf("pair %u %u: rtt %lu bdp %lu\n", i, j, pairRtt[n.Get(i)][n.Get(j)],
            //       pairBdp[n.Get(i)][n.Get(j)]);
        }
    }
    std::cout << "server_rtt_mon_interval: " << server_rtt_mon_interval << std::endl;
    fprintf(stderr, "maxRtt: %lu, maxBdp: %lu\n", maxRtt, maxBdp);

    std::cout << "Configuring switches" << std::endl;
    /* config ToR Switch, init TorSwitch_nodelist, hostId2ToRlist*/
    for (const auto [src, dst, data_rate, link_delay, error_rate] : links) {
        Ptr<Node> src_node = n.Get(src);
        Ptr<Node> dst_node = n.Get(dst);

        //dst_node是sw
        if (src_node->GetNodeType() == 0 && dst_node->GetNodeType() == 1) {
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(dst_node);
            sw->m_isToR = true;
            sw->m_isToR_hostIP.insert(nodeInfos[src].ip.Get());
            Settings::TorSwitch_nodelist[dst].push_back(nodeInfos[src].ip.Get());
            Settings::hostId2ToRlist[src].push_back(dst);
        }
        //src_node是sw
        if (src_node->GetNodeType() == 1 && dst_node->GetNodeType() == 0) {
            Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(src_node);
            sw->m_isToR = true;
            sw->m_isToR_hostIP.insert(nodeInfos[dst].ip.Get());
            Settings::TorSwitch_nodelist[src].push_back(nodeInfos[dst].ip.Get());
            Settings::hostId2ToRlist[dst].push_back(src);
        }

    }

    //Settings::ShowInit();
    // populate routing tables (although we use our custom impl in switch_node.cc)
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // maintain port number for each host
    for (uint32_t i = 0; i < nodeInfos.size(); i++) {
        if (n.Get(i)->GetNodeType() == 0) {
            sportNumber[i] = 10000;  // each host use port number from 10000
            dportNumber[i] = 100;
            tcpDportNumber[i] = 50000; // TCP sinks start from a separate high port range
        }
    }

    flowf.open(flow_file.c_str());
    flowf >> flow_num;
    if (ReadFlowInput()) {
        Simulator::Schedule(Seconds(0), &ScheduleFlowInputs);
    }

    if (!tcp_flow_file.empty()) {
        tcp_flowf.open(tcp_flow_file.c_str());
        if (tcp_flowf.is_open()) {
            tcp_flowf >> tcp_flow_num;
            printf("TCP flow num: %lu\n", tcp_flow_num);
            if (ReadTcpFlowInput()) {
                Simulator::Schedule(Seconds(0), &ScheduleTcpFlowInputs);
            }
        } else {
            std::cerr << "WARNING: TCP_FLOW_FILE is set but cannot open: " << tcp_flow_file << "\n";
        }
    }



    // update torId2UplinkIf, torId2DownlinkIf
    for (size_t ToRId = 0; ToRId < Settings::node_num; ToRId++) {
        Ptr<Node> node = n.Get(ToRId);
        if (node->GetNodeType() == 1) {  // switches
            auto swNode = DynamicCast<SwitchNode>(n.Get(ToRId));
            if (swNode->m_isToR) {  // TOR switch
                for (auto &nextNodeIf : nbr2if[node]) {
                    if (nextNodeIf.first->GetNodeType() ==
                        1) {  // nextNode is switch (i.e., uplink)
                        auto &vec = torId2UplinkIf[ToRId];
                        vec.push_back(
                            nextNodeIf.second.idx);  // record this uplink port (outDev index)
                        //printf("Sw %lu - uplink port %u node id %u\n", ToRId, nextNodeIf.second.idx, nextNodeIf.first->GetId());  //
                        // debugging
                    } else {
                        auto &vec = torId2DownlinkIf[ToRId];
                        vec.push_back(
                            nextNodeIf.second.idx);  // record this downlink port (outDev index)
                        //printf("Sw %lu - downlink port %u node id %u\n", ToRId, nextNodeIf.second.idx, nextNodeIf.first->GetId());  //
                        // debugging
                    }
                }
            }
        }
    }

    Simulator::Schedule(Seconds(flowgen_start_time), &my_periodic_monitoring, MicroSeconds(1000));
    Simulator::Schedule(Seconds(flowgen_start_time), &m_QP_rate_monitoring);

    
    Ptr<FlowMonitor> flowMonitor;
    FlowMonitorHelper flowHelper;
    flowMonitor = flowHelper.InstallAll();
    flowMonitor->Start(Seconds(flowgen_start_time));
    flowMonitor->Stop(Seconds(flowgen_stop_time + 10.0));

    Simulator::Schedule(Seconds(flowgen_start_time), &Settings::print_flow_distribution, MicroSeconds(500));

    topof.close();
    std::cout << "============DC Switch===========\n";
    //DynamicCast<SwitchNode>(n.Get(16))->m_mmu->printBufferManagerStatus();
    std::cout << "============DCI Switch===========\n";
    //DynamicCast<SwitchNode>(n.Get(36))->m_mmu->printBufferManagerStatus();

    //
    // Now, do the actual simulation.
    //
    std::cout << "------------------------------------------" << std::endl;
    std::cout << "Running Simulation.\n";
    fflush(stdout);
    NS_LOG_INFO("Run Simulation.");
    Simulator::Schedule(Seconds(flowgen_start_time),
                        &stop_simulation_middle);  // check every 100us
    Simulator::Stop(Seconds(flowgen_stop_time + 10.0));
    Simulator::Run();

    // Dump TCP flow metadata for reproducibility/debugging.
    // Note: tcpFlowInfos keeps all TCP flows that were read from TCP_FLOW_FILE.
    if (tcp_flow_num > 0) {
        const std::string outPath = logfile::output_dir + "/tcp_flows.txt";
        std::ofstream out(outPath, std::ios::out | std::ios::trunc);
        if (out.is_open()) {
            out << "# idx src dst start_time_s size_bytes\n";
            for (const auto& f : tcpFlowInfos) {
                out << f.idx << " " << f.src << " " << f.dst << " "
                    << std::fixed << std::setprecision(9) << f.start_time << " "
                    << f.fsize << "\n";
            }
            out.close();
        } else {
            std::cerr << "WARNING: cannot open tcp flow output file: " << outPath << "\n";
        }
    }

    //TODO:my code to caculate the throughput of each flow
        // 输出每个流的发送速率
    //flowMonitor->SerializeToXmlFile("NameOfFile.xml", true, true);
    /*-----------------------------------------------------------------------------*/
    /*----- we don't need below. Just we can enforce to close this simulation. -----*/
    /*-----------------------------------------------------------------------------*/
    Simulator::Destroy();
    NS_LOG_INFO("Total number of packets: " << RdmaHw::nAllPkts);
    NS_LOG_INFO("Done.");
    endt = clock();
    std::cerr << (double)(endt - begint) / CLOCKS_PER_SEC << "\n";
}