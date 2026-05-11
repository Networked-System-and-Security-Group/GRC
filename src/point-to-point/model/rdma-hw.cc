#include "rdma-hw.h"

#include <ns3/ipv4-header.h>
#include <ns3/seq-ts-header.h>
#include <ns3/simulator.h>
#include <ns3/udp-header.h>

#include <climits>
#include <cmath>

#include "cn-header.h"
#include "flow-stat-tag.h"
#include "ns3/boolean.h"
#include "ns3/data-rate.h"
#include "ns3/double.h"
#include "ns3/flow-id-num-tag.h"
#include "ns3/pointer.h"
#include "ns3/ppp-header.h"
#include "ns3/settings.h"
#include "ns3/switch-node.h"
#include "ns3/uinteger.h"
#include "ppp-header.h"
#include "qbb-header.h"
#include <assert.h>

namespace ns3 {

NS_LOG_COMPONENT_DEFINE("RdmaHw");

std::unordered_map<unsigned, unsigned> acc_timeout_count;
uint64_t RdmaHw::nAllPkts = 0;

TypeId RdmaHw::GetTypeId(void) {
    static TypeId tid =
        TypeId("ns3::RdmaHw")
            .SetParent<Object>()
            .AddAttribute("MinRate", "Minimum rate of a throttled flow",
                          DataRateValue(DataRate("100Mb/s")),
                          MakeDataRateAccessor(&RdmaHw::m_minRate), MakeDataRateChecker())
            .AddAttribute("Mtu", "Mtu.", UintegerValue(1000), MakeUintegerAccessor(&RdmaHw::m_mtu),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("CcMode", "which mode of DCQCN is running", UintegerValue(0),
                          MakeUintegerAccessor(&RdmaHw::m_cc_mode), MakeUintegerChecker<uint32_t>())
            .AddAttribute("NACKGenerationInterval", "The NACK/CNP Generation interval",
                          DoubleValue(20000.0), MakeDoubleAccessor(&RdmaHw::m_nack_interval),
                          MakeDoubleChecker<double>())
            .AddAttribute("L2ChunkSize", "Layer 2 chunk size. Disable chunk mode if equals to 0.",
                          UintegerValue(4000), MakeUintegerAccessor(&RdmaHw::m_chunk),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("L2AckInterval", "Layer 2 Ack intervals. Disable ack if equals to 0.",
                          UintegerValue(1), MakeUintegerAccessor(&RdmaHw::m_ack_interval),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("L2BackToZero", "Layer 2 go back to zero transmission.",
                          BooleanValue(false), MakeBooleanAccessor(&RdmaHw::m_backto0),
                          MakeBooleanChecker())
            .AddAttribute("EwmaGain",
                          "Control gain parameter which determines the level of rate decrease",
                          DoubleValue(1.0 / 16), MakeDoubleAccessor(&RdmaHw::m_g),
                          MakeDoubleChecker<double>())
            .AddAttribute("RateOnFirstCnp", "the fraction of rate on first CNP", DoubleValue(1.0),
                          MakeDoubleAccessor(&RdmaHw::m_rateOnFirstCNP),
                          MakeDoubleChecker<double>())
            .AddAttribute("ClampTargetRate", "Clamp target rate.", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_EcnClampTgtRate), MakeBooleanChecker())
            .AddAttribute("RPTimer", "The rate increase timer at RP in microseconds",
                          DoubleValue(300.0), MakeDoubleAccessor(&RdmaHw::m_rpgTimeReset),
                          MakeDoubleChecker<double>())
            .AddAttribute("RateDecreaseInterval", "The interval of rate decrease check",
                          DoubleValue(4.0), MakeDoubleAccessor(&RdmaHw::m_rateDecreaseInterval),
                          MakeDoubleChecker<double>())
            .AddAttribute("FastRecoveryTimes", "The rate increase timer at RP", UintegerValue(1),
                          MakeUintegerAccessor(&RdmaHw::m_rpgThreshold),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("AlphaResumInterval", "The interval of resuming alpha", DoubleValue(1.0),
                          MakeDoubleAccessor(&RdmaHw::m_alpha_resume_interval),
                          MakeDoubleChecker<double>())
            .AddAttribute("RateAI", "Rate increment unit in AI period",
                          DataRateValue(DataRate("5Mb/s")), MakeDataRateAccessor(&RdmaHw::m_rai),
                          MakeDataRateChecker())
            .AddAttribute("RateHAI", "Rate increment unit in hyperactive AI period",
                          DataRateValue(DataRate("50Mb/s")), MakeDataRateAccessor(&RdmaHw::m_rhai),
                          MakeDataRateChecker())
            .AddAttribute("VarWin", "Use variable window size or not", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_var_win), MakeBooleanChecker())
            .AddAttribute("FastReact", "Fast React to congestion feedback", BooleanValue(true),
                          MakeBooleanAccessor(&RdmaHw::m_fast_react), MakeBooleanChecker())
            .AddAttribute("MiThresh", "Threshold of number of consecutive AI before MI",
                          UintegerValue(5), MakeUintegerAccessor(&RdmaHw::m_miThresh),
                          MakeUintegerChecker<uint32_t>())
            .AddAttribute("TargetUtil",
                          "The Target Utilization of the bottleneck bandwidth, by default 95%",
                          DoubleValue(0.95), MakeDoubleAccessor(&RdmaHw::m_targetUtil),
                          MakeDoubleChecker<double>())
            .AddAttribute(
                "UtilHigh",
                "The upper bound of Target Utilization of the bottleneck bandwidth, by default 98%",
                DoubleValue(0.98), MakeDoubleAccessor(&RdmaHw::m_utilHigh),
                MakeDoubleChecker<double>())
            .AddAttribute("RateBound", "Bound packet sending by rate, for test only",
                          BooleanValue(true), MakeBooleanAccessor(&RdmaHw::m_rateBound),
                          MakeBooleanChecker())
            .AddAttribute("MultiRate", "Maintain multiple rates in HPCC", BooleanValue(true),
                          MakeBooleanAccessor(&RdmaHw::m_multipleRate), MakeBooleanChecker())
            .AddAttribute("SampleFeedback", "Whether sample feedback or not", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_sampleFeedback), MakeBooleanChecker())
            .AddAttribute("TimelyAlpha", "Alpha of TIMELY", DoubleValue(0.875),
                          MakeDoubleAccessor(&RdmaHw::m_tmly_alpha), MakeDoubleChecker<double>())
            .AddAttribute("TimelyBeta", "Beta of TIMELY", DoubleValue(0.8),
                          MakeDoubleAccessor(&RdmaHw::m_tmly_beta), MakeDoubleChecker<double>())
            .AddAttribute("TimelyTLow", "TLow of TIMELY (ns)", UintegerValue(50000),
                          MakeUintegerAccessor(&RdmaHw::m_tmly_TLow),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("TimelyTHigh", "THigh of TIMELY (ns)", UintegerValue(500000),
                          MakeUintegerAccessor(&RdmaHw::m_tmly_THigh),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("TimelyMinRtt", "MinRtt of TIMELY (ns)", UintegerValue(20000),
                          MakeUintegerAccessor(&RdmaHw::m_tmly_minRtt),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("DctcpRateAI", "DCTCP's Rate increment unit in AI period",
                          DataRateValue(DataRate("1000Mb/s")),
                          MakeDataRateAccessor(&RdmaHw::m_dctcp_rai), MakeDataRateChecker())
            .AddAttribute("UnoAiFactor", "UnoCC additive increase as a BDP fraction",
                          DoubleValue(0.001), MakeDoubleAccessor(&RdmaHw::m_unoAiFactor),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoBeta", "UnoCC quick-adapt cwnd ratio threshold",
                          DoubleValue(0.5), MakeDoubleAccessor(&RdmaHw::m_unoBeta),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoEwmaGain", "UnoCC ECN fraction EWMA gain",
                          DoubleValue(0.65), MakeDoubleAccessor(&RdmaHw::m_unoEwmaGain),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoK", "UnoCC K in bytes; <=0 means BDP/7",
                          DoubleValue(-1.0), MakeDoubleAccessor(&RdmaHw::m_unoK),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoGentleScale", "UnoCC MD scale for phantom-only congestion",
                          DoubleValue(0.3), MakeDoubleAccessor(&RdmaHw::m_unoGentleScale),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoDelayThreshold", "Relative RTT threshold for physical queues",
                          DoubleValue(0.05), MakeDoubleAccessor(&RdmaHw::m_unoDelayThreshold),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoEpochRttFactor", "UnoCC epoch length in intra-DC RTTs",
                          DoubleValue(2.0), MakeDoubleAccessor(&RdmaHw::m_unoEpochRttFactor),
                          MakeDoubleChecker<double>())
            .AddAttribute("UnoIntraRttNs", "Topology-derived intra-DC RTT for UnoCC epoch",
                          UintegerValue(0), MakeUintegerAccessor(&RdmaHw::m_unoIntraRttNs),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("IrnEnable", "Enable IRN", BooleanValue(false),
                          MakeBooleanAccessor(&RdmaHw::m_irn), MakeBooleanChecker())
            .AddAttribute("IrnRtoLow", "Low RTO for IRN", TimeValue(MicroSeconds(454)),
                          MakeTimeAccessor(&RdmaHw::m_irn_rtoLow), MakeTimeChecker())
            .AddAttribute("IrnRtoHigh", "High RTO for IRN", TimeValue(MicroSeconds(1350)),
                          MakeTimeAccessor(&RdmaHw::m_irn_rtoHigh), MakeTimeChecker())
            .AddAttribute("IrnBdp", "BDP Limit for IRN in Bytes", UintegerValue(100000),
                          MakeUintegerAccessor(&RdmaHw::m_irn_bdp), MakeUintegerChecker<uint32_t>())//这一项计划废弃
            .AddAttribute("L2Timeout", "Sender's timer of waiting for the ack",
                          TimeValue(MilliSeconds(4)), MakeTimeAccessor(&RdmaHw::m_waitAckTimeout),
                          MakeTimeChecker());
    return tid;
}

RdmaHw::RdmaHw() {
    cnp_total = 0;
    cnp_by_ecn = 0;
    cnp_by_ooo = 0;
}

void RdmaHw::SetNode(Ptr<Node> node) { m_node = node; }
void RdmaHw::Setup(QpCompleteCallback cb) {
    for (uint32_t i = 0; i < m_nic.size(); i++) {
        Ptr<QbbNetDevice> dev = m_nic[i].dev;
        if (dev == NULL) continue;
        // share data with NIC
        dev->m_rdmaEQ->m_qpGrp = m_nic[i].qpGrp;
        // setup callback
        dev->m_rdmaReceiveCb = MakeCallback(&RdmaHw::Receive, this);
        dev->m_rdmaLinkDownCb = MakeCallback(&RdmaHw::SetLinkDown, this);
        dev->m_rdmaPktSent = MakeCallback(&RdmaHw::PktSent, this);
        // config NIC
        dev->m_rdmaEQ->m_mtu = m_mtu;
        dev->m_rdmaEQ->m_rdmaGetNxtPkt = MakeCallback(&RdmaHw::GetNxtPacket, this);
    }
    // setup qp complete callback
    m_qpCompleteCallback = cb;
}

uint32_t RdmaHw::GetNicIdxOfQp(Ptr<RdmaQueuePair> qp) {
    auto &v = m_rtTable[qp->dip.Get()];
    if (v.size() > 0) {
        uint32_t hash = qp->GetHash();
        auto it = std::find(Hashlist.begin(), Hashlist.end(), hash);
        if (it == Hashlist.end()) {
            Hashlist.push_back(hash);
            return v[(Hashlist.size() - 1) % v.size()];
        }else{
            return v[std::distance(Hashlist.begin(), it) % v.size()];
        }
        // return v[qp->GetHash() % v.size()];
    }
    NS_ASSERT_MSG(false, "We assume at least one NIC is alive");
    std::cout << "We assume at least one NIC is alive" << std::endl;
    exit(1);
}
 
uint64_t RdmaHw::GetQpKey(uint32_t dip, uint16_t sport, uint16_t dport,
                          uint16_t pg) {  // Sender perspective
    return ((uint64_t)dip << 32) | ((uint64_t)sport << 16) | (uint64_t)dport | (uint64_t)pg;
}
Ptr<RdmaQueuePair> RdmaHw::GetQp(uint64_t key) {
    auto it = m_qpMap.find(key);

    // lookup main memory
    if (it != m_qpMap.end()) {
        return it->second;
    }

    return NULL;
}
void RdmaHw::AddQueuePair(uint64_t size, uint16_t pg, Ipv4Address sip, Ipv4Address dip,
                          uint16_t sport, uint16_t dport, uint32_t win, uint64_t baseRtt,
                          int32_t flow_id) {
    // create qp
    Ptr<RdmaQueuePair> qp = CreateObject<RdmaQueuePair>(pg, sip, dip, sport, dport);
    qp->SetSize(size);
    qp->SetWin(win);
    qp->SetBaseRtt(baseRtt);
    qp->SetVarWin(m_var_win);
    qp->SetFlowId(flow_id);
    auto& flow_info = Settings::flowInfos[flow_id];
    if (Settings::nodeInfos[flow_info.src].as_id == Settings::nodeInfos[flow_info.dst].as_id) {
        qp->SetTimeout(m_waitAckTimeout);
    } else {
        qp->SetTimeout(MilliSeconds(35)); //Magic Number
    }

    if (m_irn) {
        qp->irn.m_enabled = m_irn;
        //qp->irn.m_bdp = m_irn_bdp;
        qp->irn.m_bdp = Settings::pairBdp[Settings::nodeContainer.Get(Settings::hostIp2IdMap[sip.Get()])]
                                         [Settings::nodeContainer.Get(Settings::hostIp2IdMap[dip.Get()])];
        qp->irn.m_rtoLow = m_irn_rtoLow;
        qp->irn.m_rtoHigh = m_irn_rtoHigh;
    }

    // add qp
    uint32_t nic_idx = GetNicIdxOfQp(qp);
    //std::cout << "node: " << m_node->GetId() << " flow id : " << qp->m_flow_id <<" nic_idx: " << nic_idx << std::endl;
    m_nic[nic_idx].qpGrp->AddQp(qp);
    uint64_t key = GetQpKey(dip.Get(), sport, dport, pg);
    m_qpMap[key] = qp;
    //printf("%u insert qp with key %lx\n", m_node->GetId(), key);

    // set init variables
    DataRate m_bps = m_nic[nic_idx].dev->GetDataRate();
    //std::cout << "bps: " << m_bps << std::endl;
    qp->m_rate = m_bps;
    qp->m_max_rate = m_bps;
    if (m_cc_mode == 1) {
        qp->mlx.m_targetRate = m_bps;
    } else if (m_cc_mode == 3) {
        qp->hp.m_curRate = m_bps;
        if (m_multipleRate) {
            for (uint32_t i = 0; i < IntHeader::maxHop; i++) qp->hp.hopState[i].Rc = m_bps;
        }
    } else if (m_cc_mode == 7) {
        qp->tmly.m_curRate = m_bps;
    } else if (m_cc_mode == CC_MODE_UNOCC) {
        InitUno(qp);
    }

    // Notify Nic
    m_nic[nic_idx].dev->NewQp(qp);
}

void RdmaHw::DeleteQueuePair(Ptr<RdmaQueuePair> qp) {
    // remove qp from the m_qpMap
    uint64_t key = GetQpKey(qp->dip.Get(), qp->sport, qp->dport, qp->m_pg);

    // record to Akashic record
    //NS_ASSERT(akashic_Qp.find(key) == akashic_Qp.end());  // should not be already existing
    //akashic_Qp.insert(key);

    // delete
    m_qpMap.erase(key);
}

// DATA UDP's src = this key's dst (receiver's dst)
uint64_t RdmaHw::GetRxQpKey(uint32_t dip, uint16_t dport, uint16_t sport,
                            uint16_t pg) {  // Receiver perspective
    return ((uint64_t)dip << 32) | ((uint64_t)pg << 16) | ((uint64_t)sport << 16) |
           (uint64_t)dport;  // srcIP, srcPort
}

// src/dst are already flipped (this is calleld by UDP Data packet)
Ptr<RdmaRxQueuePair> RdmaHw::GetRxQp(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport,
                                     uint16_t pg, bool create) {
    uint64_t rxKey = GetRxQpKey(dip, dport, sport, pg);
    auto it = m_rxQpMap.find(rxKey);

    // main memory lookup
    if (it != m_rxQpMap.end()) return it->second;

    if (create) {
        // create new rx qp
        Ptr<RdmaRxQueuePair> q = CreateObject<RdmaRxQueuePair>();
        // init the qp
        q->sip = sip;
        q->dip = dip;
        q->sport = sport;
        q->dport = dport;
        q->m_ecn_source.qIndex = pg;
        q->m_flow_id = -1;     // unknown
        m_rxQpMap[rxKey] = q;  // store in map
        return q;
    }
    return NULL;
}
uint32_t RdmaHw::GetNicIdxOfRxQp(Ptr<RdmaRxQueuePair> q) {
    auto &v = m_rtTable[q->dip];
    if (v.size() > 0) {
        return v[q->GetHash() % v.size()];
    }
    NS_ASSERT_MSG(false, "We assume at least one NIC is alive");
    std::cout << "We assume at least one NIC is alive" << std::endl;
    exit(1);
}

// Receiver's perspective?
void RdmaHw::DeleteRxQp(uint32_t dip, uint16_t dport, uint16_t sport, uint16_t pg) {
    uint64_t key = GetRxQpKey(dip, dport, sport, pg);

    // record to Akashic record
    //NS_ASSERT(akashic_RxQp.find(key) == akashic_RxQp.end());  // should not be already existing
    //akashic_RxQp.insert(key);

    const auto& rxQpIt = m_rxQpMap.find(key);
    assert(rxQpIt != m_rxQpMap.end());
    // delete
    m_rxQpMap.erase(key);
}

int RdmaHw::ReceiveUdp(Ptr<Packet> p, CustomHeader &ch) {
    uint8_t ecnbits = ch.GetIpv4EcnBits();

    uint32_t payload_size = p->GetSize() - ch.GetSerializedSize();
    FlowIDNUMTag fit;
    assert(p->PeekPacketTag(fit));
    uint32_t flow_id = fit.GetId();
    bool ack_req = (bool)fit.GetAckReq();

    // find corresponding rx queue pair
    Ptr<RdmaRxQueuePair> rxQp =
        GetRxQp(ch.dip, ch.sip, ch.udp.dport, ch.udp.sport, ch.udp.pg, true);

    if (ecnbits != 0) {
        rxQp->m_ecn_source.ecnbits |= ecnbits;
        rxQp->m_ecn_source.qfb++;
    }

    rxQp->m_ecn_source.total++;
    const uint32_t unoEcnMarked = rxQp->m_ecn_source.qfb;
    const uint32_t unoEcnTotal = rxQp->m_ecn_source.total;
    if (rxQp->m_milestone_rx == 0) {
        rxQp->m_milestone_rx = m_ack_interval;
    }

    if (rxQp->m_flow_id < 0) {
        rxQp->m_flow_id = flow_id;
    }

    bool cnp_check = false;
    int x = ReceiverCheckSeq(ch.udp.seq, rxQp, payload_size, cnp_check);
    if (x == 2 || x == 4) {
        //printf("[%ld]Out of order，Flow:%u, 期待Seq：%u，当前Seq:%u\n", Simulator::Now().GetNanoSeconds(), flow_id, rxQp->ReceiverNextExpectedSeq, ch.udp.seq);
        //fflush(stdout);
    }
    rxQp->send_cnp =
        (m_cc_mode == CC_MODE_UNOCC) ? (ecnbits || cnp_check)
                                     : ((ecnbits || cnp_check) &&
                                        Simulator::Now() - rxQp->last_cnp_send_time > MicroSeconds(10));
    //printf("Receive a udp\n");
    if ((ack_req && x == 1) || x == 2 || x == 6) {  // generate ACK or NACK
        qbbHeader seqh;
        seqh.SetSeq(rxQp->ReceiverNextExpectedSeq);
        seqh.SetPG(ch.udp.pg);
        seqh.SetSport(ch.udp.dport);
        seqh.SetDport(ch.udp.sport);
        seqh.SetIntHeader(ch.udp.ih);

        if (m_cc_mode == CC_MODE_UNOCC) {
            seqh.SetIrnNack(unoEcnMarked);
            seqh.SetIrnNackSize(unoEcnTotal);
            rxQp->m_ecn_source.qfb = 0;
            rxQp->m_ecn_source.total = 0;
        } else if (m_irn) {
            if (x == 2) {
                seqh.SetIrnNack(ch.udp.seq);
                seqh.SetIrnNackSize(payload_size);
            } else {
                seqh.SetIrnNack(0);  // NACK without ackSyndrome (ACK) in loss recovery mode
                seqh.SetIrnNackSize(0);
            }
        }

        if (rxQp->send_cnp) {  // NACK accompanies with CNP packet
            // XXX monitor CNP generation at sender
            cnp_total++;
            if (ecnbits) cnp_by_ecn++;
            if (cnp_check) cnp_by_ooo++;
            seqh.SetCnp();
            rxQp->send_cnp = false;
            rxQp->last_cnp_send_time = Simulator::Now();
        }

        Ptr<Packet> newp =
            Create<Packet>(std::max(60 - 14 - 20 - (int)seqh.GetSerializedSize(), 0));
        newp->AddHeader(seqh);

        Ipv4Header head;  // Prepare IPv4 header
        head.SetDestination(Ipv4Address(ch.sip));
        head.SetSource(Ipv4Address(ch.dip));
        head.SetProtocol(x == 1 ? 0xFC : 0xFD);  // ack=0xFC nack=0xFD
        if (x != 1) {
            printf("[%ld]Send NACK, FlowId:%u, Expect:%u, PacketSeq:%u\n",
                   Simulator::Now().GetNanoSeconds(), flow_id, rxQp->ReceiverNextExpectedSeq, ch.udp.seq);
        }
        head.SetTtl(64);
        head.SetPayloadSize(newp->GetSize());
        head.SetIdentification(rxQp->m_ipid++);

        {
            FlowIDNUMTag fit;
            if (p->PeekPacketTag(fit)) {
                newp->AddPacketTag(fit);
            }
        }

        newp->AddHeader(head);
        AddHeader(newp, 0x800);  // Attach PPP header
        // send
        uint32_t nic_idx = GetNicIdxOfRxQp(rxQp);
        //printf("send a ack\n");
        m_nic[nic_idx].dev->RdmaEnqueueHighPrioQ(newp);
        m_nic[nic_idx].dev->TriggerTransmit();
    }
    return 0;
}


int RdmaHw::ReceiveCnp(Ptr<Packet> p, CustomHeader &ch) {
    uint64_t key = GetQpKey(ch.sip, ch.cnp.dport, ch.cnp.sport, ch.cnp.pg);
    fflush(stdout);
	Ptr<RdmaQueuePair> qp = GetQp(key);
	assert(qp != NULL);
    //printf("Receive CNP, FlowId: %u\n", qp->m_flow_id);
	if (m_cc_mode == 1){ // mlx version
		if (qp == NULL){
			std::cout << "ERROR: QCN NIC cannot find the flow\n";
			return 0;
		} else {
			cnp_received_mlx(qp);
		}
	}
	return 0;
}

int RdmaHw::ReceiveAck(Ptr<Packet> p, CustomHeader &ch) {
    uint16_t qIndex = ch.ack.pg;
    uint16_t port = ch.ack.dport;   // sport for this host
    uint16_t sport = ch.ack.sport;  // dport for this host (sport of ACK packet)
    uint32_t seq = ch.ack.seq;
    uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
    int i;
    uint64_t key = GetQpKey(ch.sip, port, sport, qIndex);
    Ptr<RdmaQueuePair> qp = GetQp(key);
    uint64_t oldSndUna = qp ? qp->snd_una : 0;

    uint32_t nic_idx = GetNicIdxOfQp(qp);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    if (ch.l3Prot == 0xFD) {
        //printf("[%lu]Receive Nack, FlowId:%u, %lu->%lu, PacketSeq:%u\n",
        //    Simulator::Now().GetNanoSeconds(), Settings::get_flowid(p), qp->snd_nxt,
        //    qp->snd_una, seq);
    }
    if (m_ack_interval == 0)
        std::cout << "ERROR: shouldn't receive ack\n";
    else {
        if (!m_backto0) {
            qp->Acknowledge(seq);
        } else {
            uint32_t goback_seq = seq / m_chunk * m_chunk;
            qp->Acknowledge(goback_seq);
        }
        if (qp->irn.m_enabled) {
            // handle NACK
            NS_ASSERT(ch.l3Prot == 0xFD);

            // for bdp-fc calculation update m_irn_maxAck
            if (seq > qp->irn.m_highest_ack) qp->irn.m_highest_ack = seq;

            if (ch.ack.irnNackSize != 0) {
                // ch.ack.irnNack contains the seq triggered this NACK
                qp->irn.m_sack.sack(ch.ack.irnNack, ch.ack.irnNackSize);
            }

            uint32_t sack_seq, sack_len;
            if (qp->irn.m_sack.peekFrontBlock(&sack_seq, &sack_len)) {
                if (qp->snd_una == sack_seq) {
                    qp->snd_una += sack_len;
                }
            }

            qp->irn.m_sack.discardUpTo(qp->snd_una);

            if (qp->snd_nxt < qp->snd_una) {
                qp->snd_nxt = qp->snd_una;
            }
            // if (qp->irn.m_sack.IsEmpty())  { //
            if (qp->irn.m_recovery && qp->snd_una >= qp->irn.m_recovery_seq) {
                qp->irn.m_recovery = false;
            }
        } else {
            if (qp->snd_nxt < qp->snd_una) {
                qp->snd_nxt = qp->snd_una;
            }
        }
        if (qp->IsFinished()) {
            QpComplete(qp);
        }
    }

    /**
     * IB Spec Vol. 1 o9-85
     * The requester need not separately time each request launched into the
     * fabric, but instead simply begins the timer whenever it is expecting a response.
     * Once started, the timer is restarted each time an acknowledge
     * packet is received as long as there are outstanding expected responses.
     * The timer does not detect the loss of a particular expected acknowledge
     * packet, but rather simply detects the persistent absence of response
     * packets.
     * */
    if (!qp->IsFinished() && qp->GetOnTheFly() > 0) {
        if (qp->m_retransmit.IsRunning()) qp->m_retransmit.Cancel();
        qp->m_retransmit = Simulator::Schedule(qp->GetRto(m_mtu), &RdmaHw::HandleTimeout, this, qp,
                                               qp->GetRto(m_mtu));
    }


    if (m_irn) {
        if (ch.ack.irnNackSize != 0) {
            if (!qp->irn.m_recovery) {
                qp->irn.m_recovery_seq = qp->snd_nxt;
                RecoverQueue(qp);
                qp->irn.m_recovery = true;
            }
        } else {
            if (qp->irn.m_recovery) {
                qp->irn.m_recovery = false;
            }
        }

    } else if (ch.l3Prot == 0xFD) {
        //printf("Received a NACK! flow_id:%u, qp_seq_nxt:%lu, qp_seq_unk:%lu\n",Settings::get_flowid(p), qp->snd_nxt, qp->snd_una);
        RecoverQueue(qp); //注意！！这里好像有问题，recover之后确认了ack之后才进行恢复，似乎是无效恢复
    }   // NACK

    // handle cnp
    if (!qp->IsFinished() && cnp) {
        if (m_cc_mode == 1) {  // mlx version
            cnp_received_mlx(qp);
        }
    }

    if (m_cc_mode == 3) {
        HandleAckHp(qp, p, ch);
    } else if (m_cc_mode == 7) {
        HandleAckTimely(qp, p, ch);
    } else if (m_cc_mode == 8) {
        HandleAckDctcp(qp, p, ch);
    } else if (m_cc_mode == CC_MODE_UNOCC) {
        HandleAckUno(qp, p, ch, oldSndUna);
    }
    // ACK may advance the on-the-fly window, allowing more packets to send
    dev->TriggerTransmit();
    return 0;
}

size_t RdmaHw::getIrnBufferOverhead() {
    size_t overhead = 0;
    for (auto it = m_rxQpMap.begin(); it != m_rxQpMap.end(); it++) {
        overhead += it->second->m_irn_sack_.getSackBufferOverhead();
    }
    return overhead;
}

int RdmaHw::Receive(Ptr<Packet> p, CustomHeader &ch) {
    #if (SLB_DEBUG == true)
        std::cout << "[RdmaHw::Receive] Node(" << m_node->GetId() << ")," << PARSE_FIVE_TUPLE(ch)
        << "l3Prot:" << ch.l3Prot << ",at" << Simulator::Now() << std::endl;
    #endif
    // std::cout << "[RdmaHw::Receive] Node(" << m_node->GetId() << ")," << PARSE_FIVE_TUPLE(ch)
    //     << "l3Prot:" << std::hex  << ch.l3Prot << ",at" << std::dec << Simulator::Now() << std::endl;
    uint32_t flow_id = Settings::get_flowid(p);
    if (Settings::flowInfos[flow_id].finish_time != 0) {//如果这条流已经完成传输，这可能是残存在拓扑中的包，直接丢弃
        //printf("Received a packet of finished flow, FlowId:%u, Seq:%u\n", flow_id, ch.udp.seq);
        return 1;
    }
    if (ch.l3Prot == 0x11) {  // UDP
        return ReceiveUdp(p, ch);
    } else if (ch.l3Prot == 0xFF) {  // CNP
        return ReceiveCnp(p, ch);
    } else if (ch.l3Prot == 0xFD) {  // NACK
        return ReceiveAck(p, ch);
    } else if (ch.l3Prot == 0xFC) {  // ACK
        return ReceiveAck(p, ch);
    }
    return 0;
}

/**
 * @brief Check sequence number when UDP DATA is received
 *
 * @return int
 * 0: should not reach here
 * 1: generate ACK
 * 2: still in loss recovery of IRN
 * 4: OoO, but skip to send NACK as it is already NACKed.
 * 6: NACK but functionality is ACK (indicating all packets are received)
 */
int RdmaHw::ReceiverCheckSeq(uint32_t seq, Ptr<RdmaRxQueuePair> q, uint32_t size, bool &cnp) {
    uint32_t expected = q->ReceiverNextExpectedSeq;
    if (seq == expected || (seq < expected && seq + size >= expected)) {
        q->ReceiverNextExpectedSeq += size - (expected - seq);
        if (m_irn) {
            if (q->m_milestone_rx < seq + size) q->m_milestone_rx = seq + size;
            {
                uint32_t sack_seq, sack_len;
                if (q->m_irn_sack_.peekFrontBlock(&sack_seq, &sack_len)) {
                    if (sack_seq <= q->ReceiverNextExpectedSeq)
                        q->ReceiverNextExpectedSeq +=
                            (sack_len - (q->ReceiverNextExpectedSeq - sack_seq));
                }
            }
            size_t progress = q->m_irn_sack_.discardUpTo(q->ReceiverNextExpectedSeq);
            if (q->m_irn_sack_.IsEmpty()) {
                return 6;  // This generates NACK, but actually functions as an ACK (indicates all
                           // packet has been received)
            } else {
                // should we put nack timer here
                return 2;  // Still in loss recovery mode of IRN
            }
            return 0;  // should not reach here
        }
        return 1;
        //if (q->ReceiverNextExpectedSeq >= q->m_milestone_rx) {
        //    q->m_milestone_rx +=
        //        m_ack_interval;  // if ack_interval is small (e.g., 1), condition is meaningless
        //    return 1;            // Generate ACK
        //} else if (q->ReceiverNextExpectedSeq % m_chunk == 0) {
        //    return 1;
        //} else {
        //    return 5;
        //}
    } else if (seq > expected) {
        // Generate NACK
        if (m_irn) {
            if (q->m_milestone_rx < seq + size) q->m_milestone_rx = seq + size;

            // if seq is already nacked, check for nacktimer
            if (q->m_irn_sack_.blockExists(seq, size) && Simulator::Now() < q->m_nackTimer) {
                return 4;  // don't need to send nack yet
            }
            q->m_nackTimer = Simulator::Now() + MicroSeconds(m_nack_interval);
            q->m_irn_sack_.sack(seq, size);  // set SACK
            NS_ASSERT(q->m_irn_sack_.discardUpTo(expected) ==
                      0);  // SACK blocks must be larger than expected
            cnp = true;    // XXX: out-of-order should accompany with CNP (?) TODO: Check on CX6
            return 2;      // generate SACK
        }
        if (Simulator::Now() >= q->m_nackTimer || q->m_lastNACK != expected) {  
            // 如果NACK已经超过了当前的冷却时间，或者当前要发的NACK和上次发的NACK不一样
            q->m_nackTimer = Simulator::Now() + MicroSeconds(m_nack_interval);
            q->m_lastNACK = expected;
            if (m_backto0) {
                q->ReceiverNextExpectedSeq = q->ReceiverNextExpectedSeq / m_chunk * m_chunk;
            }
            cnp = true;  // XXX: out-of-order should accompany with CNP (?) TODO: Check on CX6
            return 2;
        } else {
            // skip to send NACK
            return 4;
        }
    } else {
        // Duplicate.
        if (m_irn) {
            // if (q->ReceiverNextExpectedSeq - 1 == q->m_milestone_rx) {
            // 	return 6; // This generates NACK, but actually functions as an ACK (indicates all
            // packet has been received)
            // }
            if (q->m_irn_sack_.IsEmpty()) {
                return 6;  // This generates NACK, but actually functions as an ACK (indicates all
                           // packet has been received)
            } else {
                // should we put nack timer here
                return 2;  // Still in loss recovery mode of IRN
            }
        }
        // Duplicate.
        //printf("收到重复报文\n");
        return 1;  // According to IB Spec C9-110
                   /**
                    * IB Spec C9-110
                    * A responder shall respond to all duplicate requests in PSN order;
                    * i.e. the request with the (logically) earliest PSN shall be executed first. If,
                    * while responding to a new or duplicate request, a duplicate request is received
                    * with a logically earlier PSN, the responder shall cease responding
                    * to the original request and shall begin responding to the duplicate request
                    * with the logically earlier PSN.
                    */
    }
}

void RdmaHw::AddHeader(Ptr<Packet> p, uint16_t protocolNumber) {
    PppHeader ppp;
    ppp.SetProtocol(EtherToPpp(protocolNumber));
    p->AddHeader(ppp);
}

uint16_t RdmaHw::EtherToPpp(uint16_t proto) {
    switch (proto) {
        case 0x0800:
            return 0x0021;  // IPv4
        case 0x86DD:
            return 0x0057;  // IPv6
        default:
            NS_ASSERT_MSG(false, "PPP Protocol number not defined!");
    }
    return 0;
}

void RdmaHw::RecoverQueue(Ptr<RdmaQueuePair> qp) { 
    qp->snd_nxt = qp->snd_una; 
}

void RdmaHw::QpComplete(Ptr<RdmaQueuePair> qp) {
    NS_ASSERT(!m_qpCompleteCallback.IsNull());
    if (m_cc_mode == 1) {
        Simulator::Cancel(qp->mlx.m_eventUpdateAlpha);
        Simulator::Cancel(qp->mlx.m_eventDecreaseRate);
        Simulator::Cancel(qp->mlx.m_rpTimer);
    }
    if (qp->m_retransmit.IsRunning()) qp->m_retransmit.Cancel();

    // This callback will log info. It also calls deletetion the rxQp on the receiver
    m_qpCompleteCallback(qp);
    // delete TxQueuePair
    DeleteQueuePair(qp);
}

void RdmaHw::SetLinkDown(Ptr<QbbNetDevice> dev) {
    printf("RdmaHw: node:%u a link down\n", m_node->GetId());
}

void RdmaHw::AddTableEntry(Ipv4Address &dstAddr, uint32_t intf_idx) {
    uint32_t dip = dstAddr.Get();
    m_rtTable[dip].push_back(intf_idx);
}

void RdmaHw::ClearTable() { m_rtTable.clear(); }

void RdmaHw::RedistributeQp() {
    // clear old qpGrp
    for (uint32_t i = 0; i < m_nic.size(); i++) {
        if (m_nic[i].dev == NULL) continue;
        m_nic[i].qpGrp->Clear();
    }

    // redistribute qp
    for (auto &it : m_qpMap) {
        Ptr<RdmaQueuePair> qp = it.second;
        uint32_t nic_idx = GetNicIdxOfQp(qp);
        m_nic[nic_idx].qpGrp->AddQp(qp);
        // Notify Nic
        m_nic[nic_idx].dev->ReassignedQp(qp);
    }
}

Ptr<Packet> RdmaHw::GetNxtPacket(Ptr<RdmaQueuePair> qp) {
    uint32_t payload_size = qp->GetBytesLeft();
    if (m_mtu < payload_size) {  // possibly last packet
        payload_size = m_mtu;
    }
    uint32_t seq = (uint32_t)qp->snd_nxt;
    bool proceed_snd_nxt = true;
    qp->stat.txTotalPkts += 1;
    qp->stat.txTotalBytes += payload_size;
    Ptr<Packet> p = Create<Packet>(payload_size);
    // add SeqTsHeader
    SeqTsHeader seqTs;
    seqTs.SetSeq(seq);
    seqTs.SetPG(qp->m_pg);
    p->AddHeader(seqTs);
    // add udp header
    UdpHeader udpHeader;
    udpHeader.SetDestinationPort(qp->dport);
    udpHeader.SetSourcePort(qp->sport);
    p->AddHeader(udpHeader);
    // add ipv4 header
    Ipv4Header ipHeader;
    ipHeader.SetSource(qp->sip);
    ipHeader.SetDestination(qp->dip);
    ipHeader.SetProtocol(0x11);
    ipHeader.SetPayloadSize(p->GetSize());
    ipHeader.SetTtl(64);
    ipHeader.SetTos(0);
    ipHeader.SetIdentification(qp->m_ipid);
    p->AddHeader(ipHeader);
    // add ppp header
    PppHeader ppp;
    ppp.SetProtocol(0x0021);  // EtherToPpp(0x800), see point-to-point-net-device.cc
    p->AddHeader(ppp);
    //if (qp->m_flow_id == 90) {
    //    printf("Generate a packet, FlowId:%u, Seq:%u\n", qp->m_flow_id, seq);
    //}

    bool ack_req = (m_cc_mode == CC_MODE_UNOCC) || (seq + payload_size >= qp->m_size) ||
                   (m_ack_interval > 0 && seq % m_ack_interval == 0 && seq != 0);
    // attach Stat Tag
    uint8_t packet_pos = UINT8_MAX;
    {
        FlowIDNUMTag fint;
        if (!p->PeekPacketTag(fint)) {
            fint.SetId(qp->m_flow_id);
            fint.SetFlowSize(qp->m_size);
            fint.SetAckReq((uint8_t)ack_req);
            p->AddPacketTag(fint);
        }
        FlowStatTag fst;
        uint64_t size = qp->m_size;
        if (!p->PeekPacketTag(fst)) {
            if (size < m_mtu && qp->snd_nxt + payload_size >= qp->m_size) {
                fst.SetType(FlowStatTag::FLOW_START_AND_END);
            } else if (qp->snd_nxt + payload_size >= qp->m_size) {
                fst.SetType(FlowStatTag::FLOW_END);
            } else if (qp->snd_nxt == 0) {
                fst.SetType(FlowStatTag::FLOW_START);
            } else {
                fst.SetType(FlowStatTag::FLOW_NOTEND);
            }
            packet_pos = fst.GetType();
            fst.setInitiatedTime(Simulator::Now().GetSeconds());
            p->AddPacketTag(fst);
        }
    }

    if (qp->irn.m_enabled) {
        if (qp->irn.m_max_seq < seq) qp->irn.m_max_seq = seq;
    }

    // // update state
    if (proceed_snd_nxt) qp->snd_nxt += payload_size;

    qp->m_ipid++;

    // return
    return p;
}

void RdmaHw::PktSent(Ptr<RdmaQueuePair> qp, Ptr<Packet> pkt, Time interframeGap) {
    qp->lastPktSize = pkt->GetSize();
    UpdateNextAvail(qp, interframeGap, pkt->GetSize());

    if (pkt) {
        CustomHeader ch(CustomHeader::L2_Header | CustomHeader::L3_Header |
                        CustomHeader::L4_Header);
        pkt->PeekHeader(ch);
#if (SLB_DEBUG == true)
        std::cout << "[RdmaHw::PktSent] Node(" << m_node->GetId() << ")," << PARSE_FIVE_TUPLE(ch)
                  << "l3Prot:" << ch.l3Prot << ",at" << Simulator::Now() << std::endl;
#endif
        RdmaHw::nAllPkts += 1;
        if (ch.l3Prot == 0x11) {  // UDP
            // Update Timer
            if (qp->m_retransmit.IsRunning()) qp->m_retransmit.Cancel();
            qp->m_retransmit = Simulator::Schedule(qp->GetRto(m_mtu), &RdmaHw::HandleTimeout, this,
                                                   qp, qp->GetRto(m_mtu));
        } else if (ch.l3Prot == 0xFC || ch.l3Prot == 0xFD || ch.l3Prot == 0xFF) {  // ACK, NACK, CNP
        } else if (ch.l3Prot == 0xFE) {                                            // PFC
        }
    }
}

void RdmaHw::HandleTimeout(Ptr<RdmaQueuePair> qp, Time rto) {
    // Assume Outstanding Packets are lost
    // std::cerr << "Timeout on qp=" << qp << std::endl;
    if (qp->IsFinished()) {
        return;
    }

    uint32_t nic_idx = GetNicIdxOfQp(qp);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

    // IRN: disable timeouts when PFC is enabled to prevent spurious retransmissions
    if (qp->irn.m_enabled && dev->IsQbbEnabled()) return;

    if (acc_timeout_count.find(qp->m_flow_id) == acc_timeout_count.end())
        acc_timeout_count[qp->m_flow_id] = 0;
    acc_timeout_count[qp->m_flow_id]++;

    if (qp->irn.m_enabled) qp->irn.m_recovery = true;
    if (m_cc_mode == 1){ // mlx version
        cnp_received_mlx(qp); //当超时发生的时候，等效于接收到CNP？
	}
    if (m_cc_mode == CC_MODE_UNOCC && qp->uno.m_initialized) {
        qp->uno.m_cwnd = std::max<double>(m_mtu, qp->uno.m_cwnd - m_mtu);
        UnoApplyRateFromCwnd(qp);
    }
    printf("[%ld]Retransmission Timeout! FlowId:%u, %lu->%lu, fsize:%lu, Rate:%lu, Alpha:%lf\n", 
        Simulator::Now().GetNanoSeconds(), qp->m_flow_id, qp->snd_nxt, qp->snd_una,
        qp->m_size, qp->m_rate.GetBitRate(), qp->mlx.m_alpha);
    RecoverQueue(qp);
    //Settings::flowInfos[qp->m_flow_id].print();
    //printf("\n");
    dev->TriggerTransmit();
}

void RdmaHw::UpdateNextAvail(Ptr<RdmaQueuePair> qp, Time interframeGap, uint32_t pkt_size) {
    Time sendingTime;
    if (m_rateBound)
        sendingTime = interframeGap + Seconds(qp->m_rate.CalculateTxTime(pkt_size));
    else
        sendingTime = interframeGap + Seconds(qp->m_max_rate.CalculateTxTime(pkt_size));
    qp->m_nextAvail = Simulator::Now() + sendingTime;
}

void RdmaHw::ChangeRate(Ptr<RdmaQueuePair> qp, DataRate new_rate) {
#if 1
    Time sendingTime = Seconds(qp->m_rate.CalculateTxTime(qp->lastPktSize));
    Time new_sendintTime = Seconds(new_rate.CalculateTxTime(qp->lastPktSize));
    qp->m_nextAvail = qp->m_nextAvail + new_sendintTime - sendingTime;
    // update nic's next avail event
    uint32_t nic_idx = GetNicIdxOfQp(qp);
    m_nic[nic_idx].dev->UpdateNextAvail(qp->m_nextAvail);
#endif

    // change to new rate
    qp->m_rate = new_rate;
}

#define PRINT_LOG 0
/******************************
 * Mellanox's version of DCQCN
 *****************************/
void RdmaHw::UpdateAlphaMlx(Ptr<RdmaQueuePair> q) {
// std::cout << Simulator::Now() << " alpha update:" << m_node->GetId() << ' ' << q->mlx.m_alpha <<
// ' ' << (int)q->mlx.m_alpha_cnp_arrived << '\n'; printf("%lu alpha update: %08x %08x %u %u %.6lf->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport,q->mlx.m_alpha);
    if (q->mlx.m_alpha_cnp_arrived) {                       // cnp -> increase
        q->mlx.m_alpha = (1 - m_g) * q->mlx.m_alpha + m_g;  // binary feedback
    } else {                                                // no cnp -> decrease
        q->mlx.m_alpha = (1 - m_g) * q->mlx.m_alpha;        // binary feedback
    }
    q->mlx.m_alpha_cnp_arrived = false;  // clear the CNP_arrived bit
    ScheduleUpdateAlphaMlx(q);
}
void RdmaHw::ScheduleUpdateAlphaMlx(Ptr<RdmaQueuePair> q) {
    q->mlx.m_eventUpdateAlpha = Simulator::Schedule(MicroSeconds(m_alpha_resume_interval),
                                                    &RdmaHw::UpdateAlphaMlx, this, q);
}

void RdmaHw::cnp_received_mlx(Ptr<RdmaQueuePair> q) {
    q->mlx.m_alpha_cnp_arrived = true;     // set CNP_arrived bit for alpha update
    q->mlx.m_decrease_cnp_arrived = true;  // set CNP_arrived bit for rate decrease
    //printf("[%lu]Receive cnp, flow:%u\n", Simulator::Now().GetNanoSeconds(), q->m_flow_id);
    //std::cout << "ID: " << m_node->GetId() << ",Receive cnp " << q->m_flow_id <<  ",m_first_cnp:" <<q->mlx.m_first_cnp << ",at" << Simulator::Now() << std::endl;
    Time interval = Simulator::Now() - q->mlx.last_cnp_time;
    q->mlx.last_cnp_time = Simulator::Now();
    if (q->mlx.m_first_cnp || interval > MilliSeconds(10)) {
        // init alpha
        q->mlx.m_alpha = 1;
        q->mlx.m_alpha_cnp_arrived = false;
        // schedule alpha update
        ScheduleUpdateAlphaMlx(q);
        // schedule rate decrease
        ScheduleDecreaseRateMlx(q, 1);  // add 1 ns to make sure rate decrease is after alpha update
        // set rate on first CNP
        q->mlx.m_targetRate = q->m_rate = m_rateOnFirstCNP * q->m_rate;
        //std::cout << "ID: " << m_node->GetId() <<  ",First cnp target rate:" << q->mlx.m_targetRate << ",at" << Simulator::Now() << std::endl;
        q->mlx.m_first_cnp = false;
    }
}

void RdmaHw::CheckRateDecreaseMlx(Ptr<RdmaQueuePair> q) {
    ScheduleDecreaseRateMlx(q, 0);
    if (q->mlx.m_decrease_cnp_arrived) {
        //printf("%lu rate dec: %08x %08x %u %u (%0.3lf %.3lf)\n", Simulator::Now().GetTimeStep(),
        //       q->sip.Get(), q->dip.Get(), q->sport, q->dport,
        //       q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
        //std::cout  << "m_EcnClampTgtRate:" << m_EcnClampTgtRate << std::endl; 
        bool clamp = true;
        if (!m_EcnClampTgtRate) {
            if (q->mlx.m_rpTimeStage == 0) clamp = false;
        }
        if (clamp) {
            q->mlx.m_targetRate = q->m_rate;
        }
        q->m_rate = std::max(m_minRate, q->m_rate * (1 - q->mlx.m_alpha / 2));
        // reset rate increase related things
        q->mlx.m_rpTimeStage = 0;
        q->mlx.m_decrease_cnp_arrived = false;
        Simulator::Cancel(q->mlx.m_rpTimer);
        // std::cout << "m_rpgTimeReset: " << m_rpgTimeReset << std::endl;
        q->mlx.m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset),
                                               &RdmaHw::RateIncEventTimerMlx, this, q);
#if PRINT_LOG
        printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
               q->m_rate.GetBitRate() * 1e-9);
#endif
    }
}
void RdmaHw::ScheduleDecreaseRateMlx(Ptr<RdmaQueuePair> q, uint32_t delta) {
    q->mlx.m_eventDecreaseRate =
        Simulator::Schedule(MicroSeconds(m_rateDecreaseInterval) + NanoSeconds(delta),
                            &RdmaHw::CheckRateDecreaseMlx, this, q);
}

void RdmaHw::RateIncEventTimerMlx(Ptr<RdmaQueuePair> q) {
    // std::cout << "ID: " << m_node->GetId() << ",RateIncEventTimerMlx " << q->m_flow_id << ",at" << Simulator::Now() << std::endl;
    q->mlx.m_rpTimer =
        Simulator::Schedule(MicroSeconds(m_rpgTimeReset), &RdmaHw::RateIncEventTimerMlx, this, q);
    RateIncEventMlx(q);
    q->mlx.m_rpTimeStage++;
}
void RdmaHw::RateIncEventMlx(Ptr<RdmaQueuePair> q) {
    // check which increase phase: fast recovery, active increase, hyper increase
    if (q->mlx.m_rpTimeStage < m_rpgThreshold) {  // fast recovery
        FastRecoveryMlx(q);
    } else if (q->mlx.m_rpTimeStage == m_rpgThreshold) {  // active increase
        ActiveIncreaseMlx(q);
    } else {  // hyper increase
        HyperIncreaseMlx(q);
    }
}

void RdmaHw::FastRecoveryMlx(Ptr<RdmaQueuePair> q) {

    //printf("%lu fast recovery: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
    //       q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9,
    //       q->m_rate.GetBitRate() * 1e-9);

    q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);

    //printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
    //       q->m_rate.GetBitRate() * 1e-9);

}
void RdmaHw::ActiveIncreaseMlx(Ptr<RdmaQueuePair> q) {
#if PRINT_LOG
    printf("%lu active inc: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
           q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
    // get NIC
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
    // increate rate
    q->mlx.m_targetRate += m_rai;
    if (q->mlx.m_targetRate > dev->GetDataRate()) q->mlx.m_targetRate = dev->GetDataRate();
    // std::cout << "ID: " << m_node->GetId() << ",Dev_getdatarate " << dev->GetDataRate() << ",at" << Simulator::Now() << std::endl;
    q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
#if PRINT_LOG
    printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
}
void RdmaHw::HyperIncreaseMlx(Ptr<RdmaQueuePair> q) {
#if PRINT_LOG
    printf("%lu hyper inc: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(),
           q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
    // get NIC
    uint32_t nic_idx = GetNicIdxOfQp(q);
    Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
    // increate rate
    q->mlx.m_targetRate += m_rhai;
    if (q->mlx.m_targetRate > dev->GetDataRate()) q->mlx.m_targetRate = dev->GetDataRate();
    q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
#if PRINT_LOG
    printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9,
           q->m_rate.GetBitRate() * 1e-9);
#endif
}

/***********************
 * High Precision CC
 ***********************/
void RdmaHw::HandleAckHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    uint32_t ack_seq = ch.ack.seq;
    // update rate
    if (ack_seq > qp->hp.m_lastUpdateSeq) {  // if full RTT feedback is ready, do full update
        UpdateRateHp(qp, p, ch, false);
    } else {  // do fast react
        FastReactHp(qp, p, ch);
    }
}

void RdmaHw::UpdateRateHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool fast_react) {
    uint32_t next_seq = qp->snd_nxt;
    bool print = !fast_react || true;
    if (qp->hp.m_lastUpdateSeq == 0) {  // first RTT
        qp->hp.m_lastUpdateSeq = next_seq;
        // store INT
        IntHeader &ih = ch.ack.ih;
        NS_ASSERT(ih.nhop <= IntHeader::maxHop);
        for (uint32_t i = 0; i < ih.nhop; i++) qp->hp.hop[i] = ih.hop[i];
#if PRINT_LOG
        if (print) {
            printf("%lu %s %08x %08x %u %u [%u,%u,%u]", Simulator::Now().GetTimeStep(),
                   fast_react ? "fast" : "update", qp->sip.Get(), qp->dip.Get(), qp->sport,
                   qp->dport, qp->hp.m_lastUpdateSeq, ch.ack.seq, next_seq);
            for (uint32_t i = 0; i < ih.nhop; i++)
                printf(" %u %lu %lu", ih.hop[i].GetQlen(), ih.hop[i].GetBytes(),
                       ih.hop[i].GetTime());
            printf("\n");
        }
#endif
    } else {
        // check packet INT
        IntHeader &ih = ch.ack.ih;
        if (ih.nhop <= IntHeader::maxHop) {
            double max_c = 0;
            bool inStable = false;
#if PRINT_LOG
            if (print)
                printf("%lu %s %08x %08x %u %u [%u,%u,%u]", Simulator::Now().GetTimeStep(),
                       fast_react ? "fast" : "update", qp->sip.Get(), qp->dip.Get(), qp->sport,
                       qp->dport, qp->hp.m_lastUpdateSeq, ch.ack.seq, next_seq);
#endif
            // check each hop
            double U = 0;
            uint64_t dt = 0;
            bool updated[IntHeader::maxHop] = {false}, updated_any = false;
            NS_ASSERT(ih.nhop <= IntHeader::maxHop);
            for (uint32_t i = 0; i < ih.nhop; i++) {
                if (m_sampleFeedback) {
                    if (ih.hop[i].GetQlen() == 0 and fast_react) continue;
                }
                updated[i] = updated_any = true;
#if PRINT_LOG
                if (print)
                    printf(" %u(%u) %lu(%lu) %lu(%lu)", ih.hop[i].GetQlen(),
                           qp->hp.hop[i].GetQlen(), ih.hop[i].GetBytes(), qp->hp.hop[i].GetBytes(),
                           ih.hop[i].GetTime(), qp->hp.hop[i].GetTime());
#endif
                uint64_t tau = ih.hop[i].GetTimeDelta(qp->hp.hop[i]);
                ;
                double duration = tau * 1e-9;
                double txRate = (ih.hop[i].GetBytesDelta(qp->hp.hop[i])) * 8 / duration;
                double u = txRate / ih.hop[i].GetLineRate() +
                           (double)std::min(ih.hop[i].GetQlen(), qp->hp.hop[i].GetQlen()) *
                               qp->m_max_rate.GetBitRate() / ih.hop[i].GetLineRate() / qp->m_win;
#if PRINT_LOG
                if (print) printf(" %.3lf %.3lf", txRate, u);
#endif
                if (!m_multipleRate) {
                    // for aggregate (single R)
                    if (u > U) {
                        U = u;
                        dt = tau;
                    }
                } else {
                    // for per hop (per hop R)
                    if (tau > qp->m_baseRtt) tau = qp->m_baseRtt;
                    qp->hp.hopState[i].u =
                        (qp->hp.hopState[i].u * (qp->m_baseRtt - tau) + u * tau) /
                        double(qp->m_baseRtt);
                }
                qp->hp.hop[i] = ih.hop[i];
            }

            DataRate new_rate;
            int32_t new_incStage;
            DataRate new_rate_per_hop[IntHeader::maxHop];
            int32_t new_incStage_per_hop[IntHeader::maxHop];
            if (!m_multipleRate) {
                // for aggregate (single R)
                if (updated_any) {
                    if (dt > qp->m_baseRtt) dt = qp->m_baseRtt;
                    qp->hp.u = (qp->hp.u * (qp->m_baseRtt - dt) + U * dt) / double(qp->m_baseRtt);
                    max_c = qp->hp.u / m_targetUtil;

                    if (max_c >= 1 || qp->hp.m_incStage >= m_miThresh) {
                        new_rate = qp->hp.m_curRate / max_c + m_rai;
                        new_incStage = 0;
                    } else {
                        new_rate = qp->hp.m_curRate + m_rai;
                        new_incStage = qp->hp.m_incStage + 1;
                    }
                    if (new_rate < m_minRate) new_rate = m_minRate;
                    if (new_rate > qp->m_max_rate) new_rate = qp->m_max_rate;
#if PRINT_LOG
                    if (print) printf(" u=%.6lf U=%.3lf dt=%u max_c=%.3lf", qp->hp.u, U, dt, max_c);
#endif
#if PRINT_LOG
                    if (print)
                        printf(" rate:%.3lf->%.3lf\n", qp->hp.m_curRate.GetBitRate() * 1e-9,
                               new_rate.GetBitRate() * 1e-9);
#endif
                }
            } else {
                // for per hop (per hop R)
                new_rate = qp->m_max_rate;
                for (uint32_t i = 0; i < ih.nhop; i++) {
                    if (updated[i]) {
                        double c = qp->hp.hopState[i].u / m_targetUtil;
                        if (c >= 1 || qp->hp.hopState[i].incStage >= m_miThresh) {
                            new_rate_per_hop[i] = qp->hp.hopState[i].Rc / c + m_rai;
                            new_incStage_per_hop[i] = 0;
                        } else {
                            new_rate_per_hop[i] = qp->hp.hopState[i].Rc + m_rai;
                            new_incStage_per_hop[i] = qp->hp.hopState[i].incStage + 1;
                        }
                        // bound rate
                        if (new_rate_per_hop[i] < m_minRate) new_rate_per_hop[i] = m_minRate;
                        if (new_rate_per_hop[i] > qp->m_max_rate)
                            new_rate_per_hop[i] = qp->m_max_rate;
                        // find min new_rate
                        if (new_rate_per_hop[i] < new_rate) new_rate = new_rate_per_hop[i];
#if PRINT_LOG
                        if (print) printf(" [%u]u=%.6lf c=%.3lf", i, qp->hp.hopState[i].u, c);
#endif
#if PRINT_LOG
                        if (print)
                            printf(" %.3lf->%.3lf", qp->hp.hopState[i].Rc.GetBitRate() * 1e-9,
                                   new_rate.GetBitRate() * 1e-9);
#endif
                    } else {
                        if (qp->hp.hopState[i].Rc < new_rate) new_rate = qp->hp.hopState[i].Rc;
                    }
                }
#if PRINT_LOG
                printf("\n");
#endif
            }
            if (updated_any) ChangeRate(qp, new_rate);
            if (!fast_react) {
                if (updated_any) {
                    qp->hp.m_curRate = new_rate;
                    qp->hp.m_incStage = new_incStage;
                }
                if (m_multipleRate) {
                    // for per hop (per hop R)
                    for (uint32_t i = 0; i < ih.nhop; i++) {
                        if (updated[i]) {
                            qp->hp.hopState[i].Rc = new_rate_per_hop[i];
                            qp->hp.hopState[i].incStage = new_incStage_per_hop[i];
                        }
                    }
                }
            }
        }
        if (!fast_react) {
            if (next_seq > qp->hp.m_lastUpdateSeq)
                qp->hp.m_lastUpdateSeq = next_seq;  //+ rand() % 2 * m_mtu;
        }
    }
}

void RdmaHw::FastReactHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    if (m_fast_react) UpdateRateHp(qp, p, ch, true);
}

/**********************
 * TIMELY
 *********************/
void RdmaHw::HandleAckTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    uint32_t ack_seq = ch.ack.seq;
    // update rate
    if (ack_seq > qp->tmly.m_lastUpdateSeq) {  // if full RTT feedback is ready, do full update
        UpdateRateTimely(qp, p, ch, false);
    } else {  // do fast react
        FastReactTimely(qp, p, ch);
    }
}
void RdmaHw::UpdateRateTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool us) {
    uint32_t next_seq = qp->snd_nxt;
    uint64_t rtt = Simulator::Now().GetTimeStep() - ch.ack.ih.ts;
    bool print = !us;
    if (qp->tmly.m_lastUpdateSeq != 0) {  // not first RTT
        int64_t new_rtt_diff = (int64_t)rtt - (int64_t)qp->tmly.lastRtt;
        double rtt_diff = (1 - m_tmly_alpha) * qp->tmly.rttDiff + m_tmly_alpha * new_rtt_diff;
        double gradient = rtt_diff / m_tmly_minRtt;
        bool inc = false;
        double c = 0;
#if PRINT_LOG
        if (print)
            printf("%lu node:%u rtt:%lu rttDiff:%.0lf gradient:%.3lf rate:%.3lf",
                   Simulator::Now().GetTimeStep(), m_node->GetId(), rtt, rtt_diff, gradient,
                   qp->tmly.m_curRate.GetBitRate() * 1e-9);
#endif
        if (rtt < m_tmly_TLow) {
            inc = true;
        } else if (rtt > m_tmly_THigh) {
            c = 1 - m_tmly_beta * (1 - (double)m_tmly_THigh / rtt);
            inc = false;
        } else if (gradient <= 0) {
            inc = true;
        } else {
            c = 1 - m_tmly_beta * gradient;
            if (c < 0) c = 0;
            inc = false;
        }
        if (inc) {
            if (qp->tmly.m_incStage < 5) {
                qp->m_rate = qp->tmly.m_curRate + m_rai;
            } else {
                qp->m_rate = qp->tmly.m_curRate + m_rhai;
            }
            if (qp->m_rate > qp->m_max_rate) qp->m_rate = qp->m_max_rate;
            if (!us) {
                qp->tmly.m_curRate = qp->m_rate;
                qp->tmly.m_incStage++;
                qp->tmly.rttDiff = rtt_diff;
            }
        } else {
            qp->m_rate = std::max(m_minRate, qp->tmly.m_curRate * c);
            if (!us) {
                qp->tmly.m_curRate = qp->m_rate;
                qp->tmly.m_incStage = 0;
                qp->tmly.rttDiff = rtt_diff;
            }
        }
#if PRINT_LOG
        if (print) {
            printf(" %c %.3lf\n", inc ? '^' : 'v', qp->m_rate.GetBitRate() * 1e-9);
        }
#endif
    }
    if (!us && next_seq > qp->tmly.m_lastUpdateSeq) {
        qp->tmly.m_lastUpdateSeq = next_seq;
        // update
        qp->tmly.lastRtt = rtt;
    }
}
void RdmaHw::FastReactTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {}

/**********************
 * DCTCP
 *********************/
void RdmaHw::HandleAckDctcp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch) {
    uint32_t ack_seq = ch.ack.seq;
    uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
    bool new_batch = false;

    // update alpha
    qp->dctcp.m_ecnCnt += (cnp > 0);
    if (ack_seq > qp->dctcp.m_lastUpdateSeq) {  // if full RTT feedback is ready, do alpha update
#if PRINT_LOG
        printf("%lu %s %08x %08x %u %u [%u,%u,%u] %.3lf->", Simulator::Now().GetTimeStep(), "alpha",
               qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->dctcp.m_lastUpdateSeq,
               ch.ack.seq, qp->snd_nxt, qp->dctcp.m_alpha);
#endif
        new_batch = true;
        if (qp->dctcp.m_lastUpdateSeq == 0) {  // first RTT
            qp->dctcp.m_lastUpdateSeq = qp->snd_nxt;
            qp->dctcp.m_batchSizeOfAlpha = qp->snd_nxt / m_mtu + 1;
        } else {
            double frac = std::min(1.0, double(qp->dctcp.m_ecnCnt) / qp->dctcp.m_batchSizeOfAlpha);
            qp->dctcp.m_alpha = (1 - m_g) * qp->dctcp.m_alpha + m_g * frac;
            qp->dctcp.m_lastUpdateSeq = qp->snd_nxt;
            qp->dctcp.m_ecnCnt = 0;
            qp->dctcp.m_batchSizeOfAlpha = (qp->snd_nxt - ack_seq) / m_mtu + 1;
#if PRINT_LOG
            printf("%.3lf F:%.3lf", qp->dctcp.m_alpha, frac);
#endif
        }
#if PRINT_LOG
        printf("\n");
#endif
    }

    // check cwr exit
    if (qp->dctcp.m_caState == 1) {
        if (ack_seq > qp->dctcp.m_highSeq) qp->dctcp.m_caState = 0;
    }

    // check if need to reduce rate: ECN and not in CWR
    if (cnp && qp->dctcp.m_caState == 0) {
#if PRINT_LOG
        printf("%lu %s %08x %08x %u %u %.3lf->", Simulator::Now().GetTimeStep(), "rate",
               qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->m_rate.GetBitRate() * 1e-9);
#endif
        qp->m_rate = std::max(m_minRate, qp->m_rate * (1 - qp->dctcp.m_alpha / 2));
#if PRINT_LOG
        printf("%.3lf\n", qp->m_rate.GetBitRate() * 1e-9);
#endif
        qp->dctcp.m_caState = 1;
        qp->dctcp.m_highSeq = qp->snd_nxt;
    }

    // additive inc
    if (qp->dctcp.m_caState == 0 && new_batch)
        qp->m_rate = std::min(qp->m_max_rate, qp->m_rate + m_dctcp_rai);
}

void RdmaHw::InitUno(Ptr<RdmaQueuePair> qp) {
    const double bdp = std::max<double>(m_mtu, qp->m_baseRtt * qp->m_max_rate.GetBitRate() / 8e9);
    qp->uno.m_cwnd = bdp;
    qp->uno.m_aiBytes = std::max<double>(1.0, m_unoAiFactor * bdp);
    qp->uno.m_kBytes = m_unoK > 0 ? m_unoK : std::max<double>(1.0, bdp / 7.0);
    qp->uno.m_mdGainEcn = 4.0 * qp->uno.m_kBytes / (bdp + qp->uno.m_kBytes);
    qp->uno.m_ecnFractionEwma = 0;
    qp->uno.m_baseRtt = qp->m_baseRtt ? qp->m_baseRtt : 1;
    qp->uno.m_lastRtt = qp->uno.m_baseRtt;
    qp->uno.m_epochPeriodNs =
        std::max<uint64_t>(1, static_cast<uint64_t>((m_unoIntraRttNs ? m_unoIntraRttNs : qp->uno.m_baseRtt) *
                                                    m_unoEpochRttFactor));
    qp->uno.m_epochStartTs = 0;
    qp->uno.m_epochEndTs = 0;
    qp->uno.m_epochAckedBytes = 0;
    qp->uno.m_epochMarkedBytes = 0;
    qp->uno.m_qaPeriodNs = qp->uno.m_baseRtt;
    qp->uno.m_qaEndTimeNs = qp->uno.m_qaPeriodNs;
    qp->uno.m_qaAckedBytes = 0;
    qp->uno.m_skipUntilNs = 0;
    qp->uno.m_lastAckSeq = 0;
    qp->uno.m_qaEnabled = false;
    qp->uno.m_epochInitialized = false;
    qp->uno.m_initialized = true;
    qp->m_win = static_cast<uint32_t>(std::min<double>(UINT32_MAX, qp->uno.m_cwnd));
    UnoApplyRateFromCwnd(qp);
}

void RdmaHw::HandleAckUno(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, uint64_t oldSndUna) {
    if (!qp->uno.m_initialized) {
        InitUno(qp);
    }

    const uint64_t ackSeq = ch.ack.seq;
    const uint64_t bytesAcked = ackSeq > oldSndUna ? ackSeq - oldSndUna : 0;
    const bool marked = ((ch.ack.flags >> qbbHeader::FLAG_CNP) & 1) != 0;
    const double ackMarkedFraction =
        ch.ack.irnNackSize > 0
            ? std::min(1.0, static_cast<double>(ch.ack.irnNack) / ch.ack.irnNackSize)
            : (marked ? 1.0 : 0.0);
    const uint64_t nowNs = Simulator::Now().GetNanoSeconds();
    const uint64_t ackedPktTs = ch.ack.ih.GetTs();

    if (ackedPktTs > 0 && nowNs > ackedPktTs) {
        const uint64_t rtt = nowNs - ackedPktTs;
        qp->uno.m_lastRtt = rtt;
        if (qp->uno.m_baseRtt == 0 || rtt < qp->uno.m_baseRtt) {
            qp->uno.m_baseRtt = rtt;
            qp->uno.m_qaPeriodNs = std::max<uint64_t>(1, rtt);
        }
    }

    if (bytesAcked > 0) {
        if (ackMarkedFraction == 0.0) {
            qp->uno.m_cwnd += qp->uno.m_aiBytes * bytesAcked / std::max<double>(1.0, qp->uno.m_cwnd);
        }
        qp->uno.m_epochAckedBytes += bytesAcked;
        qp->uno.m_epochMarkedBytes += bytesAcked * ackMarkedFraction;
        if (qp->uno.m_qaEnabled) {
            qp->uno.m_qaAckedBytes += bytesAcked;
        }
    }

    const uint64_t epochProbe = ackedPktTs > 0 ? ackedPktTs : nowNs;
    if (!qp->uno.m_epochInitialized) {
        qp->uno.m_epochStartTs = epochProbe;
        qp->uno.m_epochEndTs = epochProbe + qp->uno.m_epochPeriodNs;
        qp->uno.m_epochInitialized = true;
    } else {
        while (epochProbe >= qp->uno.m_epochEndTs) {
            UnoProcessEpochEnd(qp);
            qp->uno.m_epochStartTs = qp->uno.m_epochEndTs;
            qp->uno.m_epochEndTs += qp->uno.m_epochPeriodNs;
        }
    }

    if (ackedPktTs > 0 && nowNs >= qp->uno.m_skipUntilNs) {
        if (!qp->uno.m_qaEnabled && ackedPktTs >= qp->uno.m_qaEndTimeNs) {
            qp->uno.m_qaEnabled = true;
            qp->uno.m_qaAckedBytes = 0;
            qp->uno.m_qaEndTimeNs = nowNs + qp->uno.m_qaPeriodNs;
        } else if (qp->uno.m_qaEnabled && nowNs >= qp->uno.m_qaEndTimeNs) {
            UnoProcessQa(qp);
        }
    }

    UnoApplyRateFromCwnd(qp);
}

void RdmaHw::UnoProcessEpochEnd(Ptr<RdmaQueuePair> qp) {
    const uint64_t nowNs = Simulator::Now().GetNanoSeconds();
    const double frac = qp->uno.m_epochAckedBytes > 0
                            ? std::min(1.0, static_cast<double>(qp->uno.m_epochMarkedBytes) /
                                                 qp->uno.m_epochAckedBytes)
                            : 0.0;
    qp->uno.m_ecnFractionEwma =
        (1.0 - m_unoEwmaGain) * qp->uno.m_ecnFractionEwma + m_unoEwmaGain * frac;

    if (qp->uno.m_epochMarkedBytes > 0 && nowNs >= qp->uno.m_skipUntilNs) {
        const double targetRtt = qp->uno.m_baseRtt * (1.0 + m_unoDelayThreshold);
        const double mdScale = qp->uno.m_lastRtt <= targetRtt ? m_unoGentleScale : 1.0;
        double reduction = qp->uno.m_ecnFractionEwma * qp->uno.m_mdGainEcn * mdScale;
        reduction = std::min(0.95, std::max(0.0, reduction));
        qp->uno.m_cwnd = std::max<double>(m_mtu, qp->uno.m_cwnd * (1.0 - reduction));
    }

    qp->uno.m_epochAckedBytes = 0;
    qp->uno.m_epochMarkedBytes = 0;
}

void RdmaHw::UnoProcessQa(Ptr<RdmaQueuePair> qp) {
    const uint64_t nowNs = Simulator::Now().GetNanoSeconds();
    if (nowNs >= qp->uno.m_skipUntilNs &&
        qp->uno.m_qaAckedBytes < static_cast<uint64_t>(qp->uno.m_cwnd * m_unoBeta)) {
        qp->uno.m_cwnd = std::max<double>(m_mtu, qp->uno.m_qaAckedBytes);
        qp->uno.m_skipUntilNs = nowNs + qp->uno.m_qaPeriodNs;
        qp->uno.m_qaEnabled = false;
        qp->uno.m_qaEndTimeNs = nowNs;
    } else {
        qp->uno.m_qaEndTimeNs = nowNs + qp->uno.m_qaPeriodNs;
    }
    qp->uno.m_qaAckedBytes = 0;
}

void RdmaHw::UnoApplyRateFromCwnd(Ptr<RdmaQueuePair> qp) {
    const uint64_t rtt = std::max<uint64_t>(1, qp->uno.m_baseRtt);
    const uint64_t bps = static_cast<uint64_t>(std::max<double>(
        m_minRate.GetBitRate(), std::min<double>(qp->m_max_rate.GetBitRate(), qp->uno.m_cwnd * 8e9 / rtt)));
    ChangeRate(qp, DataRate(bps));
    qp->m_win = static_cast<uint32_t>(std::min<double>(UINT32_MAX, std::max<double>(1, qp->uno.m_cwnd)));
}

}  // namespace ns3
