#include "wan-routing.h"
#include "settings.h"
#include "ns3/flow-id-num-tag.h"
#include <assert.h>
#include <inttypes.h>
#include <ns3/cn-header.h>
#include <ns3/ipv4-header.h>
#include <ns3/random-variable.h>
#include <ns3/ppp-header.h>
namespace ns3 {

uint64_t WanRouting::GetQpKey(uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg) {
    return ((uint64_t)dip << 32) | ((uint64_t)sport << 16) | (uint64_t)pg | (uint64_t)dport;
}

WanRouting::WanRouting() {
    // 初始化回调函数为空
    m_hash_seed1 = rand();
    m_hash_seed2 = rand();
}

void WanRouting::init() {
    assert(m_switch_id != -1);
    for (const auto& [dst_as, next_hops] : Settings::wan_routing[m_switch_id]) {
        dst2path_selector[dst_as].routing_table = &m_rtTable[dst_as];
        for (auto next_dev : next_hops) {
            dst2path_selector[dst_as].path2weight[next_dev] = 1.0;
        }
        dst2path_selector[dst_as].set_routing_table();
        printf("Switch %u, AS %u, RtTable: ", m_switch_id, dst_as);
        for (const auto& entry : m_rtTable[dst_as].entries) {
            printf("%u ", entry.out_port);
        }
        printf("\n");
    }
    Simulator::Schedule(controller_active_interval, &WanRouting::controlplane_logic, this);
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
        case 0xFD:
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
    uint32_t dst_as = Settings::nodeInfos[Settings::hostIp2IdMap[ch.dip]].as_id;
    uint32_t cur_as = Settings::nodeInfos[m_switch_id].as_id;
    if (dst_as == cur_as) {
        m_switchSendToDevCallback(p, ch);
        return;
    }

    uint32_t flow_hash_value = (Hash5Tuple(ch.sip, ch.dip, ch.udp.sport, ch.udp.dport, ch.udp.pg));
    uint64_t flow_key = static_cast<uint64_t>(ch.dip) << 32 | flow_hash_value;
    auto& flowlet_item = m_flowletTable[flow_key];
    if (flowlet_item.update_time + flowlet_elapsed_time < Simulator::Now()) {
        flowlet_item.out_port = m_rtTable[dst_as].entries[flow_hash_value % 64].out_port;
        //printf("Switch %u, dst_as %u, flow_hash_value %u, out_port %u\n", m_switch_id, dst_as, flow_hash_value % 64, flowlet_item.out_port);
        flowlet_item.create_time = Simulator::Now();
    }
    flowlet_item.update_time = Simulator::Now();
    uint32_t out_port = flowlet_item.out_port;

    FlowIDNUMTag fit;
    assert(p->PeekPacketTag(fit));
    bool ack_req = (bool)fit.GetAckReq();
    if (ack_req) {
        auto& rtt_monitor = m_rttTable[dst_as][out_port];
        auto& entries = rtt_monitor.table[(flow_hash_value >> 3) % 8];
        uint16_t hashed_seq = Hash5tupleSeq(ch.sip, ch.dip, ch.udp.sport, ch.udp.dport, ch.udp.pg, ch.udp.seq + p->GetSize() - ch.GetSerializedSize());
        uint32_t e_index1 = hashed_seq % 16;
        uint32_t e_index2 = (e_index1 + 1) % 16;
        uint32_t e_index3 = (e_index1 + 2) % 16;
        Time now = Simulator::Now();
        //printf("UDP bucket:%u, index:%u\n", (flow_hash_value >> 3) % 8, e_index1);        
        if (entries[e_index1].hashed_seq == 0) {
            entries[e_index1].hashed_seq = hashed_seq;
            entries[e_index1].timestamp = now;
        } else if (entries[e_index2].hashed_seq == 0) {
            entries[e_index2].hashed_seq = hashed_seq;
            entries[e_index2].timestamp = now;
        } else if (entries[e_index3].hashed_seq == 0) {
            entries[e_index3].hashed_seq = hashed_seq;
            entries[e_index3].timestamp = now;
        } else {
            if (entries[e_index1].timestamp > entries[e_index2].timestamp) std::swap(e_index1, e_index2);
            if (entries[e_index1].timestamp > entries[e_index3].timestamp) std::swap(e_index1, e_index3);
            if (entries[e_index2].timestamp > entries[e_index3].timestamp) std::swap(e_index2, e_index3);
            if (now - entries[e_index3].timestamp > entries[e_index3].timestamp - entries[e_index1].timestamp) {
                entries[e_index2].hashed_seq = hashed_seq;
                entries[e_index2].timestamp = now;
            }
        }
        //printf("Switch %u, Seq %u udp passed, bucket:%u, index:%u\n", 
        //    m_switch_id, ch.udp.seq + p->GetSize() - ch.GetSerializedSize(), flow_hash_value, hashed_seq);
    }
    m_switchSendCallback(p, ch, out_port, ch.udp.pg);  // 示例调用
    return;
}

void WanRouting::HandleAckReceived(Ptr<Packet> p, CustomHeader& ch) {
    uint32_t src_as = Settings::nodeInfos[Settings::hostIp2IdMap[ch.sip]].as_id;
    uint32_t cur_as = Settings::nodeInfos[m_switch_id].as_id;
    if (src_as == cur_as) {
        m_switchSendToDevCallback(p, ch);
        return;
    }
    uint32_t flow_hash_value = (Hash5Tuple(ch.dip, ch.sip, ch.ack.dport, ch.ack.sport, ch.ack.pg)); // 这里ack的源和目的地要反过来
    uint64_t flow_key = static_cast<uint64_t>(ch.sip) << 32 | flow_hash_value;
    auto& flowlet_item = m_flowletTable[flow_key];
    uint32_t out_port = flowlet_item.out_port;
    auto& rtt_monitor = m_rttTable[src_as][out_port];
    uint16_t hashed_seq = Hash5tupleSeq(ch.dip, ch.sip, ch.ack.dport, ch.ack.sport, ch.ack.pg, ch.ack.seq);
    rtt_monitor.try_record_rtt(flow_hash_value, hashed_seq);
    //printf("Switch %u, Seq %u ack passed, bucket:%u, index:%u\n", m_switch_id, ch.ack.seq, flow_hash_value, hashed_seq);
    m_switchSendToDevCallback(p, ch);
}

void WanRouting::controlplane_logic() {
    Simulator::Schedule(controller_active_interval, &WanRouting::controlplane_logic, this);
    if (Simulator::Now() < Seconds(2)) {
        return;
    }
    for (auto& [dst_as, port_map] : m_rttTable) {
        for (auto& [port, rtt_monitor] : port_map) {
            fprintf(logfile::rtt_log, 
                "%" PRIu64 ",%" PRIu32 ",%" PRIu32 ",%" PRIu32 ",%.3f,%.3f,%" PRIu32 "\n",  // 格式说明符
                Simulator::Now().GetNanoSeconds(),          // 时间戳（纳秒）
                m_switch_id,          // 交换机ID
                dst_as,              // AS编号
                Settings::if2id[Settings::nodeContainer.Get(m_switch_id)][port],               // 下一跳
                rtt_monitor.estimated_rtt1.GetSeconds() * 1000.0,  // RTT1（毫秒，保留3位小数）
                rtt_monitor.estimated_rtt2.GetSeconds() * 1000.0,  // RTT2（毫秒，保留3位小数）
                rtt_monitor.entry_timeout_count                    // 超时计数
            );
            rtt_monitor.entry_timeout_count = 0;
        }
    }
}

void WanRouting::send_cnp(CustomHeader &ch) {/*
    CnHeader seqh;
    seqh.SetPG(0);
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
    m_switchSendToDevCallback(newp, ch2);*/
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

uint16_t WanRouting::Hash5tupleSeq(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, uint32_t seq) {
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