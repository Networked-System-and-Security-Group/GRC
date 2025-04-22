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
    struct RttMonitor {
        Time tau1 = MicroSeconds(1000);
        Time tau2 = MicroSeconds(5000);
        Time estimated_rtt1 = MicroSeconds(0);
        Time estimated_rtt2 = MicroSeconds(0);
        Time last_update_time = MicroSeconds(0);
        uint32_t entry_timeout_count = 0;

        
        struct Entry {
            uint16_t hashed_seq = 0;
            Time timestamp;
        } table[8][16];
        inline void try_record_rtt(uint32_t hashed_flow, uint16_t hashed_seq) {
            uint32_t bucket = (hashed_flow >> 3) % 8;
            uint32_t e_index1 = hashed_seq % 16;
            uint32_t e_index2 = (e_index1 + 1) % 16;
            uint32_t e_index3 = (e_index1 + 2) % 16;
            //printf("Ack bucket:%u, index:%u\n", bucket, e_index1);
            try_update_rtt(bucket, e_index1, hashed_seq);
            try_update_rtt(bucket, e_index2, hashed_seq);
            try_update_rtt(bucket, e_index3, hashed_seq);
        }
        private:
        inline void try_update_rtt(uint32_t bucket, uint32_t index, uint16_t hashed_seq) {
            //printf("%u %u\n", table[bucket][index].hashed_seq, hashed_seq);
            if (table[bucket][index].hashed_seq == hashed_seq) {
                Time rtt = Simulator::Now() - table[bucket][index].timestamp;
                Time delta_t = Simulator::Now() - last_update_time;
                last_update_time = Simulator::Now();
                double weight1 = std::min(delta_t.GetSeconds() / tau1.GetSeconds(), 1.0);
                double weight2 = std::min(delta_t.GetSeconds() / tau2.GetSeconds(), 1.0);
                estimated_rtt1 = Seconds((1 - weight1) * estimated_rtt1.GetSeconds() + weight1 * rtt.GetSeconds());
                estimated_rtt2 = Seconds((1 - weight2) * estimated_rtt2.GetSeconds() + weight2 * rtt.GetSeconds());
                table[bucket][index].hashed_seq = 0;
                //printf("RTT1: %lf, RTT2: %lf\n", estimated_rtt1.GetSeconds() * 1000, estimated_rtt2.GetSeconds() * 1000);
            } else if (table[bucket][index].timestamp.GetInteger() + estimated_rtt1.GetInteger() * 8 < Simulator::Now().GetInteger() && estimated_rtt1 != MicroSeconds(0)) {
                table[bucket][index].hashed_seq = 0;
                entry_timeout_count++;
            }
        }
    };
    std::map<uint32_t, std::map<uint32_t, RttMonitor>> m_rttTable;  // (dst_as, outport) -> rtt monitor
    uint32_t Hash5Tuple(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg);
    uint16_t Hash5tupleSeq(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, uint32_t seq);
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
    Time controller_active_interval = MicroSeconds(500);
    std::map<uint32_t, ControllerPathSelector> dst2path_selector;
    void controlplane_logic();

    //Congestion control module
    void send_cnp(CustomHeader& ch);
};


}  // namespace ns3
 