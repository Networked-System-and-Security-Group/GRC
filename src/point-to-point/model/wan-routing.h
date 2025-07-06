#pragma once

#include <arpa/inet.h>

#include <map>
#include <queue>
#include <unordered_map>
#include <vector>

#include "ns3/address.h"
#include "ns3/callback.h"
#include "ns3/event-id.h"
#include "ns3/net-device.h"
#include "ns3/object.h"
#include "ns3/packet.h"
#include "ns3/ptr.h"
#include "ns3/settings.h"
#include "ns3/simulator.h"
#include "ns3/tag.h"
#include <assert.h>

namespace ns3 {
/**
 * @brief Conga object is created for each ToR Switch
 */
class WanRouting : public Object {
    friend class SwitchMmu;
    friend class SwitchNode;

    static uint64_t GetQpKey(uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg);
public:
    WanRouting();
    void init();
    /* main function */
    void RouteInput(Ptr<Packet> p, CustomHeader& ch);

    /* SET functions */
    void SetSwitchInfo(uint32_t switch_id);

    // topological info (should be initialized in the beginning)
    /*-----CALLBACK------*/
    typedef Callback<void, Ptr<Packet>, CustomHeader&, uint32_t, uint32_t> SwitchSendCallback;
    typedef Callback<void, Ptr<Packet>, CustomHeader&> SwitchSendToDevCallback;
    void SetSwitchSendCallback(SwitchSendCallback switchSendCallback);  // set callback
    void SetSwitchSendToDevCallback(
        SwitchSendToDevCallback switchSendToDevCallback);  // set callback
    inline void print_status() {
        fprintf(logfile::wan_log, "Time: %.2fs, Switch ID: %u\n", Simulator::Now().GetSeconds(), m_switch_id);

        // Clear expired flowlet entries
        auto it = m_flowletTable.begin();
        while (it != m_flowletTable.end()) {
            if (Simulator::Now() - it->second.update_time > flowlet_elapsed_time) {
            it = m_flowletTable.erase(it);
            } else {
            ++it;
            }
        }

        fprintf(logfile::wan_log, "Flowlet Table Size: %zu\n", m_flowletTable.size());
    }
    /*-----------*/
private:
    SwitchSendCallback m_switchSendCallback;  // bound to SwitchNode::SwitchSend (for Request/UDP)
    SwitchSendToDevCallback m_switchSendToDevCallback;  // bound to SwitchNode::SendToDevContinue (for Probe, Reply)
    uint32_t m_switch_id = -1;  // switch's nodeID
    uint32_t m_as_id;
    uint32_t m_hash_seed1, m_hash_seed2;
    void HandleUdpReceived(Ptr<Packet> p, CustomHeader& ch);
    void HandleAckReceived(Ptr<Packet> p, CustomHeader& ch);

    /************数据平面延迟检测*********/
    void periodic_decrease_bytes();
    double bytes_decrease_coefficient = 0.25;
    Time bytes_decreace_interval = MicroSeconds(50);
    struct RttMonitor {
        RttMonitor() {
            //assert(false);
        };
        inline RttMonitor(int64_t max_rate) : 
            max_rate(max_rate),
            guaranteed_rate(max_rate * 0.3){
            std::cout << max_rate << "maxrate!" << std::endl;
        }
        //Sensitive RTT监测 使用EWMA的方式 实际上与GSCC方案无关，仅作为监控使用
        Time tau1 = MicroSeconds(1000);
        Time sensitive_rtt = MicroSeconds(0);
        Time last_update_time = MicroSeconds(0);    
        uint32_t entry_timeout_count = 0;

        //GSCC rtt监测
        Time rtt_sum = Seconds(0);
        int rtt_num = 0;
        struct RttEntry {
            uint32_t hashed_seq = 0;
            Time timestamp;
        } rtt_table[8][16];
        inline int get_entries_number() const {
            int count = 0;
            for (int i = 0; i < 8; ++i) {
                for (int j = 0; j < 16; ++j) {
                    if (rtt_table[i][j].hashed_seq != 0) {
                        ++count;
                    }
                }
            }
            return count;
        }
        inline void print_rtt_table() const {
            for (int i = 0; i < 8; ++i) {
                for (int j = 0; j < 16; ++j) {
                    printf("%x|%.1lf ", rtt_table[i][j].hashed_seq, rtt_table[i][j].timestamp.GetSeconds() * 1000);
                }
                printf("\n");
            }
        }

        //速率检测        
        //controlplane para
        int64_t max_rate;
        int64_t guaranteed_rate; 
        double alpha = 0.5;
        double beta = 0.6;
        double h = 1.0 / 16.0;
        //int64_t ai;//addition increase
        Time min_rtt = Seconds(0);
        Time rtt_diff = Seconds(0);
        Time prev_rtt = Seconds(0);
        void update_ref_rate();
        std::vector<uint64_t> send_bytes_history;
        std::vector<Time> rtt_history;

        //实时速率测量EWMA 仅作为统计使用，与GSCC无关
        Time cc_tau = MicroSeconds(200);        //更新速率计算的tau值
        Time cc_last_update = Simulator::Now(); //上一次更新速率的时间
        int64_t cur_rate = 0;                  //当前速率
        inline int64_t get_normalize_cur_rate() const {
            return cur_rate / cc_tau.GetSeconds();
        }
        //速率控制模块
        int64_t cnp_gen_threshold = 400 * 1000;
        Time last_cnp_send_time = MicroSeconds(0);
        Time cnp_gen_interval = MicroSeconds(40); //生成cnp的时间间隔
        int64_t ref_rate = guaranteed_rate;//每秒发送的基准字节数，从10GB/s开始
        uint64_t total_send_bytes = 0;

        int64_t start_bytes = 0;
        int64_t end_bytes = ref_rate * MilliSeconds(1).GetSeconds();
        int64_t cur_bytes = 0;
        inline int64_t get_std_bytes() const {
            double ratio = 1.0 * (Simulator::Now().GetNanoSeconds() % MilliSeconds(1).GetNanoSeconds()) / MilliSeconds(1).GetNanoSeconds();
            return start_bytes + static_cast<int64_t>((end_bytes - start_bytes) * ratio);
        }

        inline bool update_and_check_cnp(uint32_t pkt_size) {
            cur_bytes += pkt_size;
            int64_t std_bytes = get_std_bytes();
            int64_t bytes_diff = cur_bytes - std_bytes;
            if (bytes_diff > cnp_gen_threshold
                && (Simulator::Now() - last_cnp_send_time).GetSeconds() > cnp_gen_interval.GetSeconds() * (1.0 * cnp_gen_threshold / bytes_diff)) {
                //printf("[%ld]Send CNP, bytes_diff:%ld, cur_bytes:%ld, std_bytes:%ld\n",
                //    Simulator::Now().GetNanoSeconds(), bytes_diff, cur_bytes, std_bytes);
                last_cnp_send_time = Simulator::Now();
                return true;
            }
            return false;
        }

        inline void try_record_rtt(uint32_t hashed_flow, uint32_t hashed_seq, bool t) {
            uint32_t bucket = (hashed_flow >> 3) % 8;
            uint32_t e_index1 = hashed_seq % 16;
            uint32_t e_index2 = (e_index1 + 1) % 16;
            uint32_t e_index3 = (e_index1 + 2) % 16;
            //printf("Ack bucket:%u, index:%u\n", bucket, e_index1);
            try_update_rtt(bucket, e_index1, hashed_seq, t);
            try_update_rtt(bucket, e_index2, hashed_seq, t);
            try_update_rtt(bucket, e_index3, hashed_seq, t);
        }
        private:
        inline void try_update_rtt(uint32_t bucket, uint32_t index, uint32_t hashed_seq, bool t) {
            //printf("%u %u\n", rtt_table[bucket][index].hashed_seq, hashed_seq);
            if (rtt_table[bucket][index].hashed_seq == hashed_seq) {
                //找到匹配的AckReq报文
                Time rtt = Simulator::Now() - rtt_table[bucket][index].timestamp;
                rtt_table[bucket][index].hashed_seq = 0;
                rtt_table[bucket][index].timestamp = Seconds(0);
                Time delta_t = Simulator::Now() - last_update_time;
                last_update_time = Simulator::Now();
                double weight1 = std::min(delta_t.GetSeconds() / tau1.GetSeconds(), 1.0);
                sensitive_rtt = Seconds((1 - weight1) * sensitive_rtt.GetSeconds() + weight1 * rtt.GetSeconds());
                rtt_sum += rtt;
                rtt_num += 1;
                if (t) fprintf(logfile::wan_log, "Now: %lf, RTT: %lf, Sensitive RTT: %lf, Count: %d\n",
                    Simulator::Now().GetSeconds(), rtt.GetSeconds(), sensitive_rtt.GetSeconds(), rtt_num);
                if (Simulator::Now() > Seconds(2.4)) {
                    printf("[%ld]Update RTT %.3lf\n", 
                        Simulator::Now().GetNanoSeconds(), rtt.GetSeconds() * 1000);
                }
            } else if (rtt_table[bucket][index].hashed_seq != 0
                        && Simulator::Now() - rtt_table[bucket][index].timestamp > MilliSeconds(20)) {
                //没找到匹配的报文，尝试去除该项
                if (Simulator::Now() > Seconds(2.4)) {
                    printf("[%ld]Erase RTT %x|%.1lf\n", 
                        Simulator::Now().GetNanoSeconds(), rtt_table[bucket][index].hashed_seq, rtt_table[bucket][index].timestamp.GetSeconds() * 1000);
                }
                rtt_table[bucket][index].hashed_seq = 0;
                entry_timeout_count++;
            }
        }
    };
    std::map<uint32_t, std::map<uint32_t, RttMonitor>> m_rttTable;  // (dst_as, outport) -> rtt monitor
    uint32_t Hash5Tuple(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg);
    uint32_t Hash5tupleSeq(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, uint32_t seq);
    static uint32_t ECMPHash(const uint8_t *key, size_t len, uint32_t seed);
    /************数据平面路由查找*********/
    struct RoutingTable {
        struct {
            uint32_t out_port;
        } entries[64];
    };
    std::map<uint32_t, RoutingTable> m_rtTable;  // dst_as -> routing table

    struct FlowletItem {
        uint32_t out_port;
        Time create_time;
        Time update_time;
    };
    Time flowlet_elapsed_time = MilliSeconds(10);
    std::map<uint64_t, FlowletItem> m_flowletTable;

    /************控制平面路由选择*********/
    struct ControllerPathSelector {
        std::map<uint32_t, double> path2weight; //outport -> weight
        RoutingTable* routing_table = nullptr;
        inline void set_routing_table() {
            normalize();
            int rt_index = 0;
            for (auto [out_port, weight] : path2weight) {
                int port_num = weight * 64;
                while (port_num-- && rt_index < 64) {
                    routing_table->entries[rt_index].out_port = out_port;
                    rt_index++;
                }
            }
        }
        private:
        inline void normalize() {
            double total_weight = 0.0;
            for (const auto& entry : path2weight) {
                total_weight += entry.second;
            }
            if (total_weight > 0) {
                for (auto& entry : path2weight) {
                    entry.second /= total_weight;
                }
            }
        }
    };
    Time controller_active_interval = MicroSeconds(1000);
    std::map<uint32_t, ControllerPathSelector> dst2path_selector;
    void controlplane_logic();

    //Congestion control module
    void send_cnp(Ptr<Packet> p, CustomHeader& ch);
};


}  // namespace ns3
 