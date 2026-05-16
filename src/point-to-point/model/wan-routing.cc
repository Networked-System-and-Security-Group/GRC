#include "wan-routing.h"
#include "settings.h"
#include "ns3/flow-id-num-tag.h"
#include <assert.h>
#include <inttypes.h>
#include <ns3/cn-header.h>
#include <ns3/ipv4-header.h>
#include <ns3/random-variable.h>
#include <ns3/ppp-header.h>
#include <ns3/qbb-net-device.h>

#include <algorithm>
#include <cstdlib>
#include <cmath>
#include <limits>
namespace ns3 {

namespace {
// Centralized defaults for Settings::GetRawParam() used in this file.
// Keep them here so tuning doesn't require hunting through the logic below.
constexpr const char* kEnableWDefault = "FALSE";
constexpr const char* kWMaxDefault = "4.0";
constexpr const char* kWKDefault = "0.0000001";
constexpr const char* kInvDeltaDefault = "20971520";  // 1/20MB
constexpr const char* kBetaDefault = "0.3";
constexpr const char* kEnableVDefault = "TRUE";
constexpr const char* kWanEpochUsDefault = "1000";  // 1ms
constexpr const char* kEnable2LayerHashDefault = "TRUE";
constexpr const char* kGsccFairDefault = "FALSE";

bool IsEnabledRawParam(const std::string& value) {
    return value == "TRUE" || value == "true" || value == "1" || value == "YES" ||
           value == "yes" || value == "ON" || value == "on";
}

void ClearIpv4EcnMark(Ptr<Packet> p, CustomHeader& ch) {
    if (ch.GetIpv4EcnBits() == 0) {
        return;
    }

    PppHeader ppp;
    Ipv4Header ipv4;
    p->RemoveHeader(ppp);
    p->RemoveHeader(ipv4);
    ipv4.SetEcn(Ipv4Header::NotECT);
    ch.m_tos &= 0xFC;
    p->AddHeader(ipv4);
    p->AddHeader(ppp);
}
}  // namespace

Time WanRouting::epoch_duration = MicroSeconds(1000); // 1ms
bool WanRouting::s_w_k_update_scheduled = false;
double WanRouting::s_w_k = 0;
std::vector<double> WanRouting::s_w_k_samples;

WanRouting::WanRouting() {
    // 初始化回调函数为空
    m_hash_seed1 = rand();
    m_hash_seed2 = rand();
}

void WanRouting::DstDCHandler::Init(WanRouting* wan_routing, int64_t max_rate) {
    m_wanRouting = wan_routing;
    this->max_rate = max_rate;
    guaranteed_rate = static_cast<int64_t>(max_rate * 0.3);

    sensitive_rtt = MicroSeconds(0);
    last_update_time = Seconds(0);
    entry_timeout_count = 0;

    rtt_sum = Seconds(0);
    rtt_num = 0;
    rtt_miss_counter = 0;
    send_bytes_history.clear();
    rtt_history.clear();

    cc_last_update = Simulator::Now();
    cur_rate = 0;

    last_cnp_send_time = Seconds(0);
    ref_rate = guaranteed_rate;
    total_send_bytes = 0;

    epoch_pkt_cnt = 0;
    epoch_cnp_cnt = 0;

    rate_change_state = STABLE;
    consecutive_state_epochs = 0;

    start_bytes = 0;
    end_bytes = static_cast<int64_t>(ref_rate * WanRouting::epoch_duration.GetSeconds());
    cur_bytes = 0;
}

void WanRouting::DstDCHandler::record_rtt(Time rtt) {
    rtt_sum += rtt;
    rtt_num++;

    // 记录EWMA RTT
    Time delta_t = Simulator::Now() - last_update_time;
    //printf("Record RTT: %.2lfms\n", rtt.GetSeconds() * 1000);
    last_update_time = Simulator::Now();
    double weight1 = std::min(delta_t.GetSeconds() / rtt_tau.GetSeconds(), 1.0);
    sensitive_rtt = Seconds((1 - weight1) * sensitive_rtt.GetSeconds() + weight1 * rtt.GetSeconds());
}

int64_t WanRouting::DstDCHandler::get_std_bytes() const {
    Time epoch_elapsed = Simulator::Now() - m_wanRouting->m_epoch_start_time;
    double ratio = 0.0;
    if (epoch_elapsed > Seconds(0)) {
        ratio = epoch_elapsed.GetSeconds() / WanRouting::epoch_duration.GetSeconds();
        ratio = std::min(ratio, 1.0);
    }
    return start_bytes + static_cast<int64_t>((end_bytes - start_bytes) * ratio);
}

bool WanRouting::DstDCHandler::update_and_check_cnp(uint32_t pkt_size) {
    cur_bytes += pkt_size;
    int64_t std_bytes = get_std_bytes();
    int64_t bytes_diff = cur_bytes - std_bytes;
    uint32_t kmin = 100 * 1024; // 100KB
    uint32_t kmax = 8 * 1024 * 1024; // 8MB
    double pmax = 0.5;
    if (bytes_diff <= kmin) return false;
    if (bytes_diff >= kmax) return true;   // 关键：上阈值必丢

    double p = pmax * (double)(bytes_diff - kmin) / (double)(kmax - kmin);
    // 此时 p ∈ (0, pmax)
    double rand_val = std::rand() / (RAND_MAX + 1.0);
    return rand_val < p;
    //if (bytes_diff > kmin) {
    //    double p = std::min(pmax, pmax * (bytes_diff - kmin) / (kmax - kmin));
    //    p = p > pmax ? 1 : p;
    //    double rand_val = std::rand() / (RAND_MAX + 1.0);
    //    if (rand_val < p) {
    //        return true;
    //    }
    //}
    //return false;
}

void WanRouting::init() {
    assert(m_switch_id != -1);

    // Allow tuning epoch duration via raw params.
    // Unit: microseconds. Key: WAN_EPOCH_US (default 1000us = 1ms).
    {
        int64_t epoch_us = std::stoll(Settings::GetRawParam("WAN_EPOCH_US", kWanEpochUsDefault));
        WanRouting::epoch_duration = MicroSeconds(epoch_us);
    }
    m_gsccFair = IsEnabledRawParam(Settings::GetRawParam("GSCC_FAIR", kGsccFairDefault));
    if (m_gsccFair) {
        printf("[Info] WanRouting on switch %u enables GSCC_FAIR mode\n", m_switch_id);
    }

    for (const auto& [dst_as, next_hops] : Settings::wan_routing[m_switch_id]) {
        if (next_hops.empty()) {
            continue;
        }
        uint32_t next_dev = static_cast<uint32_t>(next_hops.front());
        if (next_hops.size() > 1) {
            printf("[Warn] wan_routing has %zu next hops for switch %u -> dst_as %u; using the first dev %u (single-path mode)\n",
                   next_hops.size(), m_switch_id, dst_as, next_dev);
        }
        m_rtTable[dst_as] = next_dev;
        int64_t max_rate = DynamicCast<QbbNetDevice>(Settings::nodeContainer.Get(m_switch_id)->GetDevice(next_dev))
                               ->GetDataRate()
                               .GetBitRate() /
                           8;
        m_dcHandler[dst_as].Init(this, max_rate);
    }
    m_epoch_start_time = Seconds(2);
    Simulator::Schedule(Seconds(2), &WanRouting::controlplane_logic, this);
    Simulator::Schedule(Seconds(2), &WanRouting::periodic_decrease_bytes, this);
    if (Settings::GetRawParam("ENABLE_W", kEnableWDefault) == "TRUE" && !s_w_k_update_scheduled) {
        s_w_k = std::stod(Settings::GetRawParam("W_K", kWKDefault));
        s_w_k_update_scheduled = true;
        Simulator::Schedule(Seconds(2) + MilliSeconds(20), &WanRouting::update_w_k);
    }
}

void WanRouting::RouteInput(Ptr<Packet> p, CustomHeader& ch) {
    if (Settings::nodeInfos[m_switch_id].node_type != NodeInfo::NodeType::DCI_SWITCH) {
        m_switchSendToDevCallback(p, ch);
        return;
    } 
    switch (ch.l3Prot) {
        case 0x11:  // UDP
            HandleUdpReceived(p, ch);
            return;
        case 0xFC:
            HandleAckReceived(p, ch);
            return;
        default:
            m_switchSendToDevCallback(p, ch);
            return;
    }
}

void WanRouting::HandleUdpReceived(Ptr<Packet> p, CustomHeader& ch) {
    // 处理UDP数据包
    // 报文过滤
    uint32_t dst_as = Settings::nodeInfos[Settings::hostIp2IdMap[ch.dip]].as_id;
    uint32_t cur_as = Settings::nodeInfos[m_switch_id].as_id;
    if (dst_as == cur_as) { //向DC内发送
        m_switchSendToDevCallback(p, ch);
        return;
    }

    // 获取出端口（单路径）
    auto it = m_rtTable.find(dst_as);
    if (it == m_rtTable.end()) {
        m_switchSendToDevCallback(p, ch);
        return;
    }
    uint32_t out_port = it->second;

    auto& dc_handler = m_dcHandler.at(dst_as);
    // per-epoch statistics
    dc_handler.epoch_pkt_cnt++;
    // RTT过滤
    FlowIDNUMTag fit;
    assert(p->PeekPacketTag(fit));
    bool ack_req = (bool)fit.GetAckReq();
    if (ack_req) {
        uint32_t hashed_seq = Hash5tupleSeq(ch.sip, ch.dip, ch.udp.sport, ch.udp.dport, ch.udp.pg, ch.udp.seq + p->GetSize() - ch.GetSerializedSize());
        uint32_t index;
        if (Settings::GetRawParam("ENABLE_2LAYER_HASH", kEnable2LayerHashDefault) == "TRUE") {
            uint32_t flow_hash_value = (Hash5Tuple(ch.sip, ch.dip, ch.udp.sport, ch.udp.dport, ch.udp.pg));
            index = (flow_hash_value ^ (hashed_seq % 16)) % rtt_table_size;
        } else {
            index = hashed_seq % rtt_table_size;
        }
        //printf("[%ld]Udp passed, %u->%u, index:%u, hashed_seq:%u\n", 
        //    Simulator::Now().GetNanoSeconds(), cur_as, dst_as, index, hashed_seq);
        if (rtt_table[index].hashed_seq == hashed_seq) {
            printf("[%ld]Repeated UDP Packet! %u->%u, index:%u, pkt[%u, %u], entry[%x, %ld]\n", 
                Simulator::Now().GetNanoSeconds(), cur_as, dst_as, index, 
                Settings::get_flowid(p), ch.udp.seq, hashed_seq, rtt_table[index].timestamp.GetNanoSeconds());
            rtt_table[index].timestamp = Simulator::Now();
        } else if (Simulator::Now() - rtt_table[index].timestamp > MilliSeconds(30)) {
            if (rtt_table[index].hashed_seq != 0) {
                printf("[%ld]UDP Packet Timeout! %u->%u, hash:%x\n", 
                    Simulator::Now().GetNanoSeconds(), cur_as, dst_as, rtt_table[index].hashed_seq);
            }
            //printf("111\n")
            rtt_table[index].hashed_seq = hashed_seq;
            rtt_table[index].timestamp = Simulator::Now();
        }
    }
    // 更新速率
    double cc_delta_t = (Simulator::Now() - dc_handler.cc_last_update).GetSeconds();
    double w = 1 - cc_delta_t / dc_handler.cc_tau.GetSeconds();
    w = std::max(0.0, w);
    dc_handler.cur_rate *= w;
    dc_handler.cur_rate += p->GetSize();
    dc_handler.cc_last_update = Simulator::Now();

    const bool ecn_marked = ch.GetIpv4EcnBits() != 0;
    if (Settings::wan_cc_mode == Settings::WanCCMode::WAN_OPT && m_gsccFair && ecn_marked) {
        dc_handler.epoch_cnp_cnt++;
        send_cnp(p, ch);
        ClearIpv4EcnMark(p, ch);
    } else if (Settings::wan_cc_mode == Settings::WanCCMode::WAN_OPT &&
               dc_handler.update_and_check_cnp(p->GetSize())) {
        dc_handler.epoch_cnp_cnt++;
        send_cnp(p, ch);
    }
    dc_handler.total_send_bytes += p->GetSize();
    m_switchSendCallback(p, ch, out_port, ch.udp.pg);
    return;
}

void WanRouting::HandleAckReceived(Ptr<Packet> p, CustomHeader& ch) {
    uint32_t src_as = Settings::nodeInfos[Settings::hostIp2IdMap[ch.sip]].as_id;
    uint32_t cur_as = Settings::nodeInfos[m_switch_id].as_id;
    if (src_as == cur_as) {
        m_switchSendToDevCallback(p, ch);
        return;
    }
    auto rtIt = m_rtTable.find(src_as);
    if (rtIt == m_rtTable.end()) {
        m_switchSendToDevCallback(p, ch);
        return;
    }
    uint32_t out_port = rtIt->second;
    auto dcIt = m_dcHandler.find(src_as);
    if (dcIt == m_dcHandler.end()) {
        m_switchSendToDevCallback(p, ch);
        return;
    }
    auto& dcHandler = dcIt->second;
    uint32_t hashed_seq = Hash5tupleSeq(ch.dip, ch.sip, ch.ack.dport, ch.ack.sport, ch.ack.pg, ch.ack.seq);
    uint32_t index;
    if (Settings::GetRawParam("ENABLE_2LAYER_HASH", kEnable2LayerHashDefault) == "TRUE") {
        uint32_t flow_hash_value = (Hash5Tuple(ch.dip, ch.sip, ch.ack.dport, ch.ack.sport, ch.ack.pg)); // 这里ack的源和目的地要反过来
        index = (flow_hash_value ^ (hashed_seq % 16)) % rtt_table_size;
    } else {
        index = hashed_seq % rtt_table_size;
    }
    //printf("[%ld]Ack Passed! %u->%u, index:%u, hashed_seq:%u\n", 
    //    Simulator::Now().GetNanoSeconds(), cur_as, src_as, index, hashed_seq);
    if (rtt_table[index].hashed_seq == hashed_seq) {
        Time rtt = Simulator::Now() - rtt_table[index].timestamp;
        if (rtt < MicroSeconds(100)) {
            printf("[Warn][%ld] RTT too small: %lf us, switch %u, %u->%u, pkt[%u, %u], index %u, hashed_seq %x, entry[%x, %ld]\n",
                Simulator::Now().GetNanoSeconds(),
                rtt.GetSeconds() * 1e6,
                m_switch_id,
                src_as,
                cur_as,
                Settings::get_flowid(p),
                ch.ack.seq,
                index,
                hashed_seq,
                rtt_table[index].hashed_seq,
                rtt_table[index].timestamp.GetNanoSeconds());
        }
        dcHandler.record_rtt(rtt);
        rtt_table[index].timestamp = Seconds(0);
        rtt_table[index].hashed_seq = 0;
    }
    //dcHandler.record_rtt(flow_hash_value, hashed_seq, src_as == 2 && cur_as == 0);
    //printf("Switch %u, Seq %u ack passed, bucket:%u, index:%u\n", m_switch_id, ch.ack.seq, flow_hash_value, hashed_seq);
    m_switchSendToDevCallback(p, ch);
}

void WanRouting::periodic_decrease_bytes() {
    Simulator::Schedule(bytes_decreace_interval, &WanRouting::periodic_decrease_bytes, this);
    for (auto& [dst_as, dc_handler] : m_dcHandler) {
        int64_t bytes_diff = dc_handler.cur_bytes - dc_handler.get_std_bytes();
        fprintf(logfile::accumulated_bytes_log, "%ld,%u,%u,%ld\n", 
            Simulator::Now().GetNanoSeconds(), m_switch_id, dst_as, bytes_diff);
    }
}

void WanRouting::controlplane_logic() {
    Simulator::Schedule(epoch_duration, &WanRouting::controlplane_logic, this);
    m_epoch_start_time = Simulator::Now();
    for (auto& [dst_as, dc_handler] : m_dcHandler) {
        auto rtIt = m_rtTable.find(dst_as);
        if (rtIt == m_rtTable.end()) {
            continue;
        }
        uint32_t out_port = rtIt->second;

        //logging
        const double measured_rtt_ms = (dc_handler.rtt_num > 0)
                                           ? (dc_handler.rtt_sum.GetSeconds() / dc_handler.rtt_num) * 1000.0
                                           : std::numeric_limits<double>::quiet_NaN();
        fprintf(logfile::rtt_log,
            "%" PRIu64 ",%" PRIu32 ",%" PRIu32 ",%" PRIu32 ",%.3f,%.3f,%" PRIu32 "\n",
            static_cast<uint64_t>(Simulator::Now().GetNanoSeconds()), m_switch_id, dst_as,
            Settings::if2id.at(Settings::nodeContainer.Get(m_switch_id)).at(out_port),
            dc_handler.sensitive_rtt.GetSeconds() * 1000.0,
            measured_rtt_ms,
            dc_handler.entry_timeout_count
        );
        dc_handler.entry_timeout_count = 0;
        fprintf(logfile::rate_monitor, "%lu,%u,%u,%lu,%lu\n", 
            Simulator::Now().GetNanoSeconds(), Settings::nodeInfos[m_switch_id].as_id, dst_as, 
            dc_handler.get_normalize_cur_rate(), dc_handler.ref_rate);

        // Per-epoch CNP trigger probability log
        {
            const uint64_t pkt_cnt = dc_handler.epoch_pkt_cnt;
            const uint64_t cnp_cnt = dc_handler.epoch_cnp_cnt;
            const double prob = (pkt_cnt == 0) ? 0.0 : (static_cast<double>(cnp_cnt) / static_cast<double>(pkt_cnt));
            double w = 1.0;
            if (Settings::GetRawParam("ENABLE_W", kEnableWDefault) == "TRUE") {
                double w_max = std::stod(Settings::GetRawParam("W_MAX", kWMaxDefault));
                double k = s_w_k;
                w = std::pow(prob, 0.75) * dc_handler.ref_rate * k;
                w = std::max(1.0, std::min(w, w_max));
                double x = std::pow(prob, 0.75) * dc_handler.ref_rate;
                if (x > 1e-9) {
                    s_w_k_samples.push_back(x);
                }
            }
            fprintf(logfile::cnp_trigger_prob_log, "%lu,%u,%u,%u,%lu,%lu,%.6f,%.6f\n",
                    Simulator::Now().GetNanoSeconds(),
                    m_switch_id,
                    Settings::nodeInfos[m_switch_id].as_id,
                    dst_as,
                    cnp_cnt,
                    pkt_cnt,
                    prob,
                    w);
        }

        if (Settings::wan_cc_mode == Settings::WanCCMode::WAN_OPT) {
            if (dc_handler.sensitive_rtt >= MicroSeconds(600)) {//rtt已经接收到第一个数据
                printf("[%ld]AS%u->%u, SenRtt%.2lf ", 
                    Simulator::Now().GetNanoSeconds(), Settings::nodeInfos[m_switch_id].as_id, dst_as, 
                    dc_handler.sensitive_rtt.GetSeconds() * 1000);
                dc_handler.send_bytes_history.push_back(dc_handler.total_send_bytes);
                dc_handler.update_ref_rate();
            }
            //将参考速率下发给速率控制模块
            dc_handler.start_bytes = dc_handler.end_bytes - dc_handler.cur_bytes;
            dc_handler.start_bytes = std::min(dc_handler.start_bytes, (int64_t)0LL);
            dc_handler.end_bytes = dc_handler.start_bytes + dc_handler.ref_rate * epoch_duration.GetSeconds();
            dc_handler.cur_bytes = 0;
            
            dc_handler.rtt_sum = Seconds(0);
            dc_handler.rtt_num = 0;
        }
        dc_handler.total_send_bytes = 0;

        // Reset per-epoch statistics
        dc_handler.epoch_pkt_cnt = 0;
        dc_handler.epoch_cnp_cnt = 0;
    }
    fflush(logfile::rate_monitor);
}

void WanRouting::update_w_k() {
    Simulator::Schedule(MilliSeconds(20), &WanRouting::update_w_k);
    if (s_w_k_samples.empty()) {
        return;
    }
    double w_max = std::stod(Settings::GetRawParam("W_MAX", kWMaxDefault));
    std::vector<std::pair<double, int> > events;
    events.reserve(s_w_k_samples.size() * 2);
    for (double x : s_w_k_samples) {
        events.push_back(std::make_pair(1.0 / x, 1));
        events.push_back(std::make_pair(w_max / x, -1));
    }
    s_w_k_samples.clear();

    std::sort(events.begin(), events.end(), [](const std::pair<double, int>& a, const std::pair<double, int>& b) {
        if (a.first != b.first) {
            return a.first < b.first;
        }
        return a.second > b.second;
    });

    int max_overlap = 0;
    int current_overlap = 0;
    double best_k = s_w_k;
    for (const auto& event : events) {
        current_overlap += event.second;
        if (current_overlap > max_overlap) {
            max_overlap = current_overlap;
            best_k = event.first;
        }
    }
    s_w_k = best_k;
}

void WanRouting::DstDCHandler::update_ref_rate() {
    // update ref_rate
    int hsize = send_bytes_history.size();
    if (hsize < 3) {
        printf("Insufficient send_bytes_history (%d), skip update_ref_rate\n", hsize);
        return;
    }
    int64_t rate_before = (send_bytes_history[hsize - 1] + send_bytes_history[hsize - 2] +
                           send_bytes_history[hsize - 3]) /
                          3.0 / WanRouting::epoch_duration.GetSeconds();
    int64_t upper_rate = std::max(guaranteed_rate, static_cast<int64_t>(rate_before * 1.2));
    bool flag = (ref_rate > upper_rate);
    int64_t pre_ref_rate = ref_rate;

    // Saturation definition: the recent real sending rate should not be smaller than ref_rate by more than 3GB/s.
    // If not saturated but still judged to increase, we allow the increase but prevent consecutive_state_epochs
    // from growing (and instead decay it) so that v stays small and the step won't blow up.
    const int64_t kSaturationSlack = 3LL * 1000 * 1000 * 1000;  // 3GB/s in our rate unit
    const bool saturated = (rate_before + kSaturationSlack >= pre_ref_rate);

    if (rtt_num == 0) {
        rtt_miss_counter++;    
        if (ref_rate > upper_rate) {
            ref_rate = upper_rate + (ref_rate - upper_rate) * 0.8;
        }
        printf("No RTT information %d, ref_rate %.3lf->%.3lf\n", 
            rtt_miss_counter, pre_ref_rate / 1e9, ref_rate / 1e9);
        return;
    }
    Time cur_rtt = Seconds(rtt_sum.GetSeconds() / rtt_num);
    rtt_history.push_back(cur_rtt);
    Time min_rtt = *std::min_element(rtt_history.begin(), rtt_history.end());
    rtt_miss_counter = 0;
    double epochs_per_rtt = min_rtt.GetSeconds() / WanRouting::epoch_duration.GetSeconds();
    if (epochs_per_rtt <= 0 || min_rtt.GetSeconds() <= 0) {
        printf("Invalid min_rtt/epochs_per_rtt, skip update_ref_rate\n");
        return;
    }

    //Get w
    double w = 1;
        if (Settings::GetRawParam("ENABLE_W", kEnableWDefault) == "TRUE") {
            double w_max = std::stod(Settings::GetRawParam("W_MAX", kWMaxDefault));
        double k = WanRouting::s_w_k;
        double p = epoch_pkt_cnt ? static_cast<double>(epoch_cnp_cnt) / static_cast<double>(epoch_pkt_cnt) : 0.0;
        // w = clip(p^0.75 * pre_ref_rate * k, 1, w_max)
        w = std::pow(p, 0.75) * pre_ref_rate * k;
        w = std::max(1.0, std::min(w, w_max));
    }

    // Get target_rate and target_state
    const double delta = 1.0 / std::stod(Settings::GetRawParam("INV_DELTA", kInvDeltaDefault)); // 1/20MBps
    const double beta = std::stod(Settings::GetRawParam("BETA", kBetaDefault));
    Time queue_delay = std::max(cur_rtt - min_rtt, MicroSeconds(10));
    int64_t target_rate = static_cast<int64_t>(w / delta / queue_delay.GetSeconds());
    RateChangeState target_state = (target_rate > pre_ref_rate) ? INCREASE : DECREASE;
    if (rate_change_state == target_state) {
        if (target_state == INCREASE && !saturated) {
            if (consecutive_state_epochs > 1) {
                consecutive_state_epochs--;
            } else {
                consecutive_state_epochs = 1;
            }
        } else {
            consecutive_state_epochs++;
        }
    } else {
        rate_change_state = target_state;
        consecutive_state_epochs = 1;
    }

    //Get v
    int v = 1;    
    if (Settings::GetRawParam("ENABLE_V", kEnableVDefault) == "TRUE") {
        if (consecutive_state_epochs >= 6 * epochs_per_rtt) {
            v = 4;
        } else if (consecutive_state_epochs >= 3 * epochs_per_rtt) {
            v = 2;
        }
    }

    int64_t step = static_cast<int64_t>(w * v / (delta * epochs_per_rtt * min_rtt.GetSeconds()));
    if (target_state == INCREASE) {
        ref_rate += step;
        printf("[Copa Increase] ");
    } else {
        // Fast decrease requirement (your intent): after one RTT, ref_rate should be <= (1-beta) * pre_ref_rate.
        // Convert it to a per-epoch multiplicative bound: gamma^(epochs_per_rtt) = 1-beta.
        // So each epoch we ensure ref_rate <= pre_ref_rate * gamma, i.e., step >= pre_ref_rate * (1-gamma).
        const double gamma = std::pow(1.0 - beta, 1.0 / epochs_per_rtt);
        const int64_t min_step = static_cast<int64_t>(std::ceil(pre_ref_rate * (1.0 - gamma)));

        const int64_t origin_step = step;
        step = std::max(step, min_step);
        step = std::min(step, pre_ref_rate);  // avoid negative ref_rate

        ref_rate -= step;
        printf("[Copa %sDecrease] ", (step > origin_step) ? "Fast " : "linear ");
    }
    printf(
        "cur_rtt: %.2lfms, min_rtt: %.2lfms, queue_delay: %.2lfms, target_rate: %.2lfGB/s, step: %.2lfGB/s "
        "state: %d, consecutive: %u ",
        cur_rtt.GetSeconds() * 1000, min_rtt.GetSeconds() * 1000, queue_delay.GetSeconds() * 1000,
        target_rate / 1e9, step / 1e9, (int)rate_change_state, consecutive_state_epochs);

    if (flag && ref_rate > upper_rate) {
        ref_rate = upper_rate + (ref_rate - upper_rate) * 0.8;
    }
    printf("ref_rate %.3lf->%.3lf\n", pre_ref_rate / 1e9, ref_rate / 1e9);
}

void WanRouting::send_cnp(Ptr<Packet> p, CustomHeader &ch) {
    fprintf(logfile::cnp_log, "%lu,%u,%u\n", 
        Simulator::Now().GetNanoSeconds(), m_switch_id, Settings::get_flowid(p));
    CnHeader seqh;
    seqh.SetPG(ch.udp.pg);
    seqh.SetSport(ch.udp.dport);
    seqh.SetDport(ch.udp.sport);

    Ptr<Packet> newp = Create<Packet>(std::max(60-14-20-(int)seqh.GetSerializedSize(), 0));
    newp->AddHeader(seqh);

    Ipv4Header ipv4h;	// Prepare IPv4 header
    ipv4h.SetDestination(Ipv4Address(ch.sip));
    //Source为当前设备
    //ipv4h.SetSource(m_node->GetObject<Ipv4>()->GetAddress(m_ifIndex, 0).GetLocal());
    ipv4h.SetSource(Ipv4Address(ch.dip));
    ipv4h.SetProtocol(0xFF); //ack=0xFC nack=0xFD cnp=0xFF
    ipv4h.SetTtl(64);
    ipv4h.SetPayloadSize(newp->GetSize());
    ipv4h.SetIdentification(UniformVariable(0, 65536).GetValue());
    //控制台输出ipv4h的信息
    newp->AddHeader(ipv4h);

    PppHeader ppp;
    ppp.SetProtocol(0x0021);
    newp->AddHeader (ppp);
    // send
    CustomHeader ch2(CustomHeader::L2_Header | CustomHeader::L3_Header | CustomHeader::L4_Header);
    newp->PeekHeader(ch2);

    FlowIDNUMTag fit;
    if (p->PeekPacketTag(fit)) {
        newp->AddPacketTag(fit);
    }
    m_switchSendToDevCallback(newp, ch2);
}

uint32_t WanRouting::Hash5Tuple(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg) {
    union {
        uint8_t u8[4 + 4 + 2 + 2];
        uint32_t u32[3];
    } buf;
    buf.u32[0] = sip;
    buf.u32[1] = dip;
    buf.u32[2] = sport | ((uint32_t)dport << 16);
    return ECMPHash(buf.u8, 12, m_hash_seed1);
}

uint32_t WanRouting::Hash5tupleSeq(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, uint32_t seq) {
    union {
        uint8_t u8[4 + 4 + 2 + 2 + 4];
        uint32_t u32[4];
    } buf;
    buf.u32[0] = sip;
    buf.u32[1] = dip;
    buf.u32[2] = sport | ((uint32_t)dport << 16);
    buf.u32[3] = seq;
    return ECMPHash(buf.u8, 16, m_hash_seed2);
}

uint32_t WanRouting::ECMPHash(const uint8_t *key, size_t len, uint32_t seed) {
    uint32_t h = seed;
    if (len > 3) {
        const uint32_t *key_x4 = (const uint32_t *)key;
        size_t i = len >> 2;
        do {
            uint32_t k = *key_x4++;
            k *= 0xcc9e2d51;
            k = (k << 15) | (k >> 17);
            k *= 0x1b873593;
            h ^= k;
            h = (h << 13) | (h >> 19);
            h += (h << 2) + 0xe6546b64;
        } while (--i);
        key = (const uint8_t *)key_x4;
    }
    if (len & 3) {
        size_t i = len & 3;
        uint32_t k = 0;
        key = &key[i - 1];
        do {
            k <<= 8;
            k |= *key--;
        } while (--i);
        k *= 0xcc9e2d51;
        k = (k << 15) | (k >> 17);
        k *= 0x1b873593;
        h ^= k;
    }
    h ^= len;
    h ^= h >> 16;
    h *= 0x85ebca6b;
    h ^= h >> 13;
    h *= 0xc2b2ae35;
    h ^= h >> 16;
    return h;
}

void WanRouting::SetSwitchInfo(uint32_t switch_id) {
    m_switch_id = switch_id;
    m_as_id = Settings::nodeInfos[m_switch_id].as_id;
}

void WanRouting::SetSwitchSendCallback(SwitchSendCallback switchSendCallback) {
    m_switchSendCallback = switchSendCallback;
}

void WanRouting::SetSwitchSendToDevCallback(SwitchSendToDevCallback switchSendToDevCallback) {
    m_switchSendToDevCallback = switchSendToDevCallback;
}

}  // namespace ns3
