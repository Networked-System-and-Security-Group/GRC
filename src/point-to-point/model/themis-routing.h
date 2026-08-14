#ifndef THEMIS_ROUTING_H
#define THEMIS_ROUTING_H

#include <cstdint>
#include <map>

#include "ns3/callback.h"
#include "ns3/custom-header.h"
#include "ns3/object.h"
#include "ns3/packet.h"
#include "ns3/settings.h"
#include "ns3/nstime.h"

namespace ns3 {

/**
 * Switch-side Themis control for long-haul RDMA.
 *
 * The module deliberately lives outside SwitchNode.  SwitchNode only dispatches
 * DCI traffic here; this class owns PNP notification state and TRP reaction
 * state.  The simulator equivalent of TRP is a delayed re-injection into the
 * normal DCI/WAN routing callback.  This preserves the packet order and avoids
 * hard-coding the self-loop port used by the upstream HPCC simulator.
 */
class ThemisRouting : public Object {
  public:
    using RouteInputCallback = Callback<void, Ptr<Packet>, CustomHeader&>;

    ThemisRouting();

    void SetSwitchInfo(uint32_t switch_id);
    void SetRouteInputCallback(RouteInputCallback callback);
    void Init();

    bool IsEnabled() const { return m_enabled; }

    /* DCI ingress path: observe CNPs, apply TRP, then call normal WAN routing. */
    void RouteInput(Ptr<Packet> p, CustomHeader& ch);

    /* DCI egress path: consume ECN marks for PNP and emit a direct CNP. */
    void OnDequeue(uint32_t if_index, uint32_t q_index, Ptr<Packet> p);

  private:
    struct FlowKey {
        uint32_t sip = 0;
        uint32_t dip = 0;
        uint16_t sport = 0;
        uint16_t dport = 0;
        uint16_t pg = 0;

        bool operator<(const FlowKey& other) const {
            if (sip != other.sip) return sip < other.sip;
            if (dip != other.dip) return dip < other.dip;
            if (sport != other.sport) return sport < other.sport;
            if (dport != other.dport) return dport < other.dport;
            return pg < other.pg;
        }
    };

    struct CnpState {
        Time last_cnp = Seconds(0);
        uint32_t cnp_count = 0;
        uint32_t alpha = 5;
        uint32_t loop_num = 1;
    };

    uint32_t m_switch_id = 0;
    bool m_enabled = false;
    RouteInputCallback m_routeInputCallback;

    std::map<FlowKey, CnpState> m_cnpHandlers;
    std::map<FlowKey, Time> m_pnpNextAllowed;

    Time m_pnpDelay = MicroSeconds(2);
    Time m_pnpInterval = MicroSeconds(5);
    Time m_trpTimeout = MicroSeconds(500);
    Time m_trpDelay = NanoSeconds(100);
    uint32_t m_trpMaxLoops = 64;

    static bool IsDataPacket(const CustomHeader& ch);
    bool IsInterDc(const CustomHeader& ch) const;
    bool IsDataTowardLocalDc(const CustomHeader& ch) const;
    bool IsCnpFromLocalDc(const CustomHeader& ch) const;
    FlowKey GetDataKey(const CustomHeader& ch) const;
    FlowKey GetCnpKey(const CustomHeader& ch) const;

    void RecordCnp(const CustomHeader& ch);
    bool GetTrpDelay(Ptr<Packet> p, const CustomHeader& ch, Time& delay);
    bool ShouldSendPnp(const FlowKey& key);
    void SendPnp(Ptr<Packet> p, CustomHeader ch);
    void ClearEcnMark(Ptr<Packet> p);
    void ForwardDelayed(Ptr<Packet> p, CustomHeader ch);

    uint64_t m_trpRecirculationBps = 1600000000000ULL;
    Time m_trpNextAvailable = Seconds(0);
};

}  // namespace ns3

#endif  // THEMIS_ROUTING_H
