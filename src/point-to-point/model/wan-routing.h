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
    friend struct DstDCHandler;

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
    bool m_gsccFair = false;
    bool m_ackTsMode = false;

    /************数据平面延迟检测*********/
    static const inline int rtt_table_size = 64 * 16;
    struct RttEntry {
        uint32_t hashed_seq = 0;
        Time timestamp = Seconds(0);
    } rtt_table[rtt_table_size];

    void periodic_decrease_bytes();
    double bytes_decrease_coefficient = 0.25;
    Time bytes_decreace_interval = MicroSeconds(100);
    struct DstDCHandler {
        DstDCHandler() = default;

        void Init(WanRouting* wan_routing, int64_t max_rate);

        //Sensitive RTT监测 使用EWMA的方式 实际上与GSCC方案无关，仅作为监控使用
        Time rtt_tau = MicroSeconds(1000);
        Time sensitive_rtt = MicroSeconds(0);
        Time last_update_time = MicroSeconds(0);  

        //实时速率测量EWMA 仅作为统计使用，与GSCC无关
        Time cc_tau = MicroSeconds(200);        //更新速率计算的tau值
        Time cc_last_update = Seconds(0); //上一次更新速率的时间
        int64_t cur_rate = 0;                  //当前速率
        inline int64_t get_normalize_cur_rate() const {
            return cur_rate / cc_tau.GetSeconds();
        }

        uint32_t entry_timeout_count = 0;

        //GSCC rtt监测
        // In ACK_TS mode rtt_sum/rtt_num accumulate one-way delays; in legacy mode they accumulate RTTs.
        Time rtt_sum = Seconds(0);
        int rtt_num = 0;
        void record_rtt(Time rtt);
        Time min_one_way_delay = Seconds(0);  // ACK_TS: min of per-epoch avg one-way delays; set in update_ref_rate
        Time record_one_way_delay(Time one_way_delay);
        bool m_ackTsMode = false;

        //速率计算        
        //controlplane para
        int64_t max_rate = 0;
        int64_t guaranteed_rate = 0;
        //int64_t ai;//addition increase
        int rtt_miss_counter = 0;
        void update_ref_rate();
        std::vector<uint64_t> send_bytes_history;
        std::vector<Time> rtt_history;

        //速率控制模块
        int64_t cnp_gen_threshold = 400 * 1000;
        Time last_cnp_send_time = MicroSeconds(0);
        Time cnp_gen_interval = MicroSeconds(40); //生成cnp的时间间隔
        int64_t ref_rate = 0;//每秒发送的基准字节数，从10GB/s开始
        uint64_t total_send_bytes = 0;

        // CNP trigger statistics per epoch
        uint64_t epoch_pkt_cnt = 0;
        uint64_t epoch_cnp_cnt = 0;
        std::vector<double> w_x_history;
        double latest_w_x = 0.0;
        double record_w_x(double raw_x, bool enable_smoothing);

        enum RateChangeState { STABLE, INCREASE, DECREASE };
        RateChangeState rate_change_state = STABLE;
        uint32_t consecutive_state_epochs = 0;

        int64_t start_bytes = 0;
        int64_t end_bytes = 0;
        int64_t cur_bytes = 0;
        int64_t get_std_bytes() const;

        bool update_and_check_cnp(uint32_t pkt_size);

    private:
        WanRouting* m_wanRouting = nullptr;

    };
    std::map<uint32_t, DstDCHandler> m_dcHandler;
    uint32_t Hash5Tuple(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg);
    uint32_t Hash5tupleSeq(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, uint32_t seq);
    static uint32_t ECMPHash(const uint8_t *key, size_t len, uint32_t seed);
    /************数据平面路由查找*********/
    // 单路径：dst_as -> out_port
    std::map<uint32_t, uint32_t> m_rtTable;

    // Epoch starts at 2s; updated at the beginning of each epoch.
    Time m_epoch_start_time = Seconds(2);

    static Time epoch_duration;
    void controlplane_logic();
    static bool s_w_k_update_scheduled;
    static bool s_w_k_initialized;
    static double s_w_k;
    static std::vector<double> s_w_k_samples;
    static void update_w_k();

    //Congestion control module
    void send_cnp(Ptr<Packet> p, CustomHeader& ch);
};


}  // namespace ns3
