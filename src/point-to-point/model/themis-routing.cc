#include "themis-routing.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <iostream>

#include "ns3/cn-header.h"
#include "ns3/flow-id-num-tag.h"
#include "ns3/ipv4-header.h"
#include "ns3/packet.h"
#include "ns3/ppp-header.h"
#include "ns3/random-variable.h"
#include "ns3/simulator.h"

namespace ns3 {

namespace {
constexpr const char* kPnpDelayUsDefault = "2";
constexpr const char* kPnpIntervalUsDefault = "5";
constexpr const char* kTrpTimeoutUsDefault = "500";
constexpr const char* kTrpDelayNsDefault = "100";
constexpr const char* kTrpMaxLoopsDefault = "64";
constexpr const char* kTrpRecirculationGbpsDefault = "1600";

Time ParseMicroseconds(const char* key, const char* fallback) {
    const int64_t value = std::max<int64_t>(0, std::stoll(Settings::GetRawParam(key, fallback)));
    return MicroSeconds(value);
}

Time ParseNanoseconds(const char* key, const char* fallback) {
    const int64_t value = std::max<int64_t>(0, std::stoll(Settings::GetRawParam(key, fallback)));
    return NanoSeconds(value);
}
}  // namespace

ThemisRouting::ThemisRouting() = default;

void ThemisRouting::SetSwitchInfo(uint32_t switch_id) {
    m_switch_id = switch_id;
}

void ThemisRouting::SetRouteInputCallback(RouteInputCallback callback) {
    m_routeInputCallback = callback;
}

void ThemisRouting::Init() {
    m_enabled = Settings::themis_enabled && m_switch_id < Settings::nodeInfos.size() &&
                Settings::nodeInfos[m_switch_id].node_type == NodeInfo::NodeType::DCI_SWITCH;
    if (!m_enabled) {
        return;
    }

    m_pnpDelay = ParseMicroseconds("THEMIS_PNP_DELAY_US", kPnpDelayUsDefault);
    m_pnpInterval = ParseMicroseconds("THEMIS_PNP_INTERVAL_US", kPnpIntervalUsDefault);
    m_trpTimeout = ParseMicroseconds("THEMIS_TRP_TIMEOUT_US", kTrpTimeoutUsDefault);
    m_trpDelay = ParseNanoseconds("THEMIS_TRP_DELAY_NS", kTrpDelayNsDefault);
    m_trpMaxLoops = std::max<uint32_t>(1, static_cast<uint32_t>(
                                               std::stoul(Settings::GetRawParam(
                                                   "THEMIS_TRP_MAX_LOOPS", kTrpMaxLoopsDefault))));
    const double recirculationGbps = std::max(
        1.0, std::stod(Settings::GetRawParam("THEMIS_TRP_RECIRC_GBPS",
                                             kTrpRecirculationGbpsDefault)));
    m_trpRecirculationBps = static_cast<uint64_t>(recirculationGbps * 1e9);
    m_trpNextAvailable = Seconds(0);

    std::cout << "[Themis] enabled on DCI switch " << m_switch_id
              << " (PNP + TRP)\n";
}

bool ThemisRouting::IsDataPacket(const CustomHeader& ch) {
    return ch.l3Prot == 0x11;
}

bool ThemisRouting::IsInterDc(const CustomHeader& ch) const {
    if (!IsDataPacket(ch)) {
        return false;
    }
    auto src_it = Settings::hostIp2IdMap.find(ch.sip);
    auto dst_it = Settings::hostIp2IdMap.find(ch.dip);
    if (src_it == Settings::hostIp2IdMap.end() || dst_it == Settings::hostIp2IdMap.end()) {
        return false;
    }
    return Settings::nodeInfos[src_it->second].as_id != Settings::nodeInfos[dst_it->second].as_id;
}

bool ThemisRouting::IsDataTowardLocalDc(const CustomHeader& ch) const {
    if (!IsInterDc(ch)) {
        return false;
    }
    auto dst_it = Settings::hostIp2IdMap.find(ch.dip);
    return dst_it != Settings::hostIp2IdMap.end() &&
           Settings::nodeInfos[dst_it->second].as_id == Settings::nodeInfos[m_switch_id].as_id;
}

bool ThemisRouting::IsCnpFromLocalDc(const CustomHeader& ch) const {
    if (ch.l3Prot != 0xFF) {
        return false;
    }
    auto src_it = Settings::hostIp2IdMap.find(ch.sip);
    auto dst_it = Settings::hostIp2IdMap.find(ch.dip);
    if (src_it == Settings::hostIp2IdMap.end() || dst_it == Settings::hostIp2IdMap.end()) {
        return false;
    }
    return Settings::nodeInfos[src_it->second].as_id == Settings::nodeInfos[m_switch_id].as_id &&
           Settings::nodeInfos[src_it->second].as_id != Settings::nodeInfos[dst_it->second].as_id;
}

ThemisRouting::FlowKey ThemisRouting::GetDataKey(const CustomHeader& ch) const {
    return FlowKey{ch.sip, ch.dip, ch.udp.sport, ch.udp.dport, ch.udp.pg};
}

ThemisRouting::FlowKey ThemisRouting::GetCnpKey(const CustomHeader& ch) const {
    // A CNP reverses both IPs and UDP ports relative to the data flow.
    return FlowKey{ch.dip, ch.sip, ch.cnp.dport, ch.cnp.sport, ch.cnp.pg};
}

void ThemisRouting::RecordCnp(const CustomHeader& ch) {
    const FlowKey key = GetCnpKey(ch);
    auto& state = m_cnpHandlers[key];
    const Time now = Simulator::Now();
    if (state.last_cnp != Seconds(0) && now - state.last_cnp < NanoSeconds(5)) {
        return;
    }

    state.last_cnp = now;
    state.cnp_count++;
    if (state.cnp_count >= state.alpha) {
        state.cnp_count = 0;
        state.alpha = std::min<uint32_t>(state.alpha + 1, m_trpMaxLoops);
        state.loop_num = std::min<uint32_t>(state.loop_num + 1, m_trpMaxLoops);
    }
}

bool ThemisRouting::GetTrpDelay(Ptr<Packet> p, const CustomHeader& ch, Time& delay) {
    if (!IsDataTowardLocalDc(ch)) {
        return false;
    }
    const FlowKey key = GetDataKey(ch);
    auto it = m_cnpHandlers.find(key);
    if (it == m_cnpHandlers.end()) {
        return false;
    }

    const Time now = Simulator::Now();
    if (now - it->second.last_cnp > m_trpTimeout) {
        // Expire stale state.  A new CNP starts with one recirculation-equivalent
        // delay, matching the upstream TRP's initial loop count.
        m_cnpHandlers.erase(it);
        return false;
    }

    const uint32_t loops = std::max<uint32_t>(1, std::min(it->second.loop_num, m_trpMaxLoops));
    const Time service_start = std::max(now, m_trpNextAvailable);
    const long double service_ns =
        std::ceil(static_cast<long double>(p->GetSize()) * 8.0L * loops * 1e9L /
                  static_cast<long double>(m_trpRecirculationBps));
    const Time service = NanoSeconds(std::max<int64_t>(1, static_cast<int64_t>(service_ns)));
    m_trpNextAvailable = service_start + service;

    // The self-loop's propagation delay is incurred once per loop.  The
    // shared service term models the finite recirculation-port rate, so TRP
    // throttles aggregate traffic instead of merely shifting every packet by
    // a fixed latency.
    delay = (service_start - now) + service +
            Time(m_trpDelay.GetTimeStep() * static_cast<int64_t>(loops));
    return delay > Seconds(0);
}

bool ThemisRouting::ShouldSendPnp(const FlowKey& key) {
    const Time now = Simulator::Now();
    auto it = m_pnpNextAllowed.find(key);
    if (it != m_pnpNextAllowed.end() && now < it->second) {
        return false;
    }
    m_pnpNextAllowed[key] = now + m_pnpInterval;
    return true;
}

void ThemisRouting::ClearEcnMark(Ptr<Packet> p) {
    PppHeader ppp;
    Ipv4Header ipv4;
    p->RemoveHeader(ppp);
    p->RemoveHeader(ipv4);
    ipv4.SetEcn(Ipv4Header::NotECT);
    p->AddHeader(ipv4);
    p->AddHeader(ppp);
}

void ThemisRouting::SendPnp(Ptr<Packet> p, CustomHeader ch) {
    if (m_routeInputCallback.IsNull()) {
        return;
    }

    CnHeader cnpHeader;
    cnpHeader.SetPG(ch.udp.pg);
    cnpHeader.SetSport(ch.udp.dport);
    cnpHeader.SetDport(ch.udp.sport);

    Ptr<Packet> cnp = Create<Packet>(std::max(60 - 14 - 20 -
                                               static_cast<int>(cnpHeader.GetSerializedSize()),
                                               0));
    cnp->AddHeader(cnpHeader);

    Ipv4Header ipv4;
    ipv4.SetDestination(Ipv4Address(ch.sip));
    ipv4.SetSource(Ipv4Address(ch.dip));
    ipv4.SetProtocol(0xFF);
    ipv4.SetTtl(64);
    ipv4.SetPayloadSize(cnp->GetSize());
    ipv4.SetIdentification(UniformVariable(0, 65536).GetValue());
    cnp->AddHeader(ipv4);

    PppHeader ppp;
    ppp.SetProtocol(0x0021);
    cnp->AddHeader(ppp);

    FlowIDNUMTag flowTag;
    if (p->PeekPacketTag(flowTag)) {
        cnp->AddPacketTag(flowTag);
    }

    CustomHeader cnpCh(CustomHeader::L2_Header | CustomHeader::L3_Header |
                       CustomHeader::L4_Header);
    cnp->PeekHeader(cnpCh);
    m_routeInputCallback(cnp, cnpCh);
}

void ThemisRouting::OnDequeue(uint32_t if_index, uint32_t q_index, Ptr<Packet> p) {
    (void)if_index;
    if (!m_enabled || q_index == 0) {
        return;
    }

    CustomHeader ch(CustomHeader::L2_Header | CustomHeader::L3_Header | CustomHeader::L4_Header);
    p->PeekHeader(ch);
    if (!IsInterDc(ch) || ch.GetIpv4EcnBits() == 0) {
        return;
    }

    const FlowKey key = GetDataKey(ch);
    // Clear every marked data packet, including packets suppressed by the
    // per-flow PNP interval. Otherwise the receiver would generate a second
    // CNP for the same mark and defeat PNP's purpose.
    ClearEcnMark(p);
    if (!ShouldSendPnp(key)) {
        return;
    }
    if (logfile::cnp_log != nullptr) {
        fprintf(logfile::cnp_log, "%lu,%u,%u\n", Simulator::Now().GetNanoSeconds(),
                m_switch_id, Settings::get_flowid(p));
    }
    Simulator::Schedule(m_pnpDelay, &ThemisRouting::SendPnp, this, p, ch);
}

void ThemisRouting::ForwardDelayed(Ptr<Packet> p, CustomHeader ch) {
    if (!m_routeInputCallback.IsNull()) {
        m_routeInputCallback(p, ch);
    }
}

void ThemisRouting::RouteInput(Ptr<Packet> p, CustomHeader& ch) {
    if (!m_enabled || m_routeInputCallback.IsNull()) {
        if (!m_routeInputCallback.IsNull()) {
            m_routeInputCallback(p, ch);
        }
        return;
    }

    if (ch.l3Prot == 0xFF) {
        if (IsCnpFromLocalDc(ch)) {
            RecordCnp(ch);
        }
        m_routeInputCallback(p, ch);
        return;
    }

    Time delay;
    if (GetTrpDelay(p, ch, delay)) {
        Simulator::Schedule(delay, &ThemisRouting::ForwardDelayed, this, p, ch);
        return;
    }
    m_routeInputCallback(p, ch);
}

}  // namespace ns3
