#ifndef SWITCH_MMU_H
#define SWITCH_MMU_H

#include <ns3/node.h>
#include <ns3/random-variable-stream.h>
#include <ns3/settings.h>

#include <list>
#include <unordered_map>

#include "ns3/caver-routing.h"
#include "ns3/conga-routing.h"
#include "ns3/conweave-routing.h"
#include "ns3/hula-routing.h"
#include "ns3/letflow-routing.h"
#include "ns3/settings.h"
#include "ns3/wan-routing.h"

namespace ns3 {

class Packet;

class SwitchMmu : public Object {
   public:
    static const unsigned qCnt = 8;    // Number of queues/priorities used
    static const unsigned pCnt = 128;  // port 0 is not used so + 1	// Number of ports used
    static const unsigned MTU = 1048;  // 1000 + headers

    static TypeId GetTypeId(void);

    SwitchMmu(void);
    void InitSwitch(void);

    bool CheckIngressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize);
    bool CheckEgressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize);
    void UpdateIngressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize);
    void UpdateEgressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize);
    void RemoveFromIngressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize);
    void RemoveFromEgressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize);

    void SetPause(uint32_t port, uint32_t qIndex, uint32_t pause_time);
    void SetResume(uint32_t port, uint32_t qIndex);
    void GetPauseClasses(uint32_t port, uint32_t qIndex, bool pClasses[]);
    bool GetResumeClasses(uint32_t port, uint32_t qIndex);

    void SetBroadcomParams(uint32_t buffer_cell_limit_sp,  // ingress sp buffer threshold p.120
                           uint32_t buffer_cell_limit_sp_shared,  // ingress sp buffer shared
                                                                  // threshold, nonshare -> share
                           uint32_t pg_min_cell,                  // ingress pg guarantee
                           uint32_t port_min_cell,                // ingress port guarantee
                           uint32_t pg_shared_limit_cell,         // max buffer for an ingress pg
                           uint32_t port_max_shared_cell,         // max buffer for an ingress port
                           uint32_t pg_hdrm_limit,                // ingress pg headroom
                           uint32_t port_max_pkt_size,            // ingress global headroom
                           uint32_t q_min_cell,                   // egress queue guaranteed buffer
                           uint32_t op_uc_port_config1_cell,      // egress queue threshold
                           uint32_t op_uc_port_config_cell,       // egress port threshold
                           uint32_t op_buffer_shared_limit_cell,  // egress sp threshold
                           uint32_t q_shared_alpha_cell, uint32_t port_share_alpha_cell,
                           uint32_t pg_qcn_threshold);

    void SetMarkingThreshold(uint32_t kmin, uint32_t kmax, double pmax);

    bool ShouldSendCN(uint32_t ifindex, uint32_t qIndex);
    void ConfigUnoPhantom(uint32_t port, bool enabled, uint32_t sizeBytes, uint32_t kminPct,
                          uint32_t kmaxPct, double pmax, double slowdownPct,
                          uint64_t lineRateBps, bool usePhysicalQueue);
    void UpdateUnoPhantomDrain(uint32_t ifindex, uint32_t qIndex);
    void AddUnoPhantomBytes(uint32_t ifindex, uint32_t qIndex, uint32_t bytes);
    uint64_t GetUnoPhantomBytes(uint32_t ifindex, uint32_t qIndex);
    bool ShouldSendCNUno(uint32_t ifindex, uint32_t qIndex);
    bool ShouldSendCNRed(uint32_t ifindex, uint32_t qIndex);

    uint32_t GetUsedBufferTotal();

    void SetDynamicThreshold(bool value);
    bool GetDynamicThreshold(void) const { return m_dynamicth; }

    // void printQueueStat(std::ostream& os, uint32_t port);

    void ConfigEcn(uint32_t port, uint32_t _kmin, uint32_t _kmax, double _pmax);
    void ConfigBufferSize(uint32_t size);

    void ConfigHdrm(uint32_t port, uint32_t size);
    void ConfigNPort(uint32_t n_port);

    uint32_t GetIngressSP(uint32_t port, uint32_t pgIndex);
    uint32_t GetEgressSP(uint32_t port, uint32_t qIndex);

    uint32_t GetusedIngressPortBytes(uint32_t port);
    uint32_t GetusedIngressSPBytes();
    uint32_t Getport_max_shared_cell(void) const { return m_port_max_shared_cell; }
    uint32_t GetusedEgressQSharedBytes(uint32_t port, uint32_t qIndex);
    uint32_t Getop_uc_port_config1_cell(void) const { return m_op_uc_port_config1_cell; }

    // config
    uint32_t node_id;

    uint32_t kmin[pCnt], kmax[pCnt];
    double pmax[pCnt];
    bool m_unoPhantomEnabled[pCnt];
    bool m_unoUsePhysicalQueue[pCnt];
    double m_unoPhantomOccupancyBytes[pCnt][qCnt];
    uint64_t m_unoPhantomLastUpdateNs[pCnt][qCnt];
    uint32_t m_unoPhantomSizeBytes[pCnt];
    uint32_t m_unoPhantomKminPct[pCnt];
    uint32_t m_unoPhantomKmaxPct[pCnt];
    double m_unoPhantomPmax[pCnt];
    double m_unoPhantomSlowdownPct[pCnt];
    uint64_t m_unoPhantomLineRateBps[pCnt];
    uint32_t paused[pCnt][qCnt];
    EventId resumeEvt[pCnt][qCnt];
    bool m_pause_remote[pCnt][qCnt];

    uint32_t pfc_a_shift[pCnt];         // legacy: not used anymore
    uint32_t egress_bytes[pCnt][qCnt];  // legacy: not used anymore

    uint32_t GetActivePortCnt(void) const { return m_activePortCnt; }
    void SetActivePortCnt(uint32_t v) {
        m_activePortCnt = v;
        //InitSwitch();
    }

    uint32_t GetMmuBufferBytes(void) const { return m_maxBufferBytes; }
    uint32_t GetMaxBufferBytesPerPort(void) const { return m_maxBufferBytesPerPort; }
    void SetMaxBufferBytesPerPort(uint32_t v) {
        m_maxBufferBytesPerPort = v;
        //InitSwitch();
    }

    uint32_t GetPgHdrmLimit(void) const { return m_pg_hdrm_limit[0]; }
    void SetPgHdrmLimit(uint32_t v) {
        for (int i = 0; i < pCnt; i++) m_pg_hdrm_limit[i] = v;
        //InitSwitch();
    }

    /*------------ Conga Objects-------------*/
    CongaRouting m_congaRouting;

    /*------------ Letflow Objects-------------*/
    LetflowRouting m_letflowRouting;

    /*------------ ConWeave Objects-------------*/
    ConWeaveRouting m_conweaveRouting;
    
    CaverRouting m_caverRouting;
    HulaRouting m_hulaRouting;
    WanRouting m_wanRouting;

    inline void printBufferInfo() {
        for (uint32_t port = 0; port < Settings::nodeContainer.Get(node_id)->GetNDevices(); ++port) {
            fprintf(logfile::buffer_monitor, "%ld,%u,%u,%u,%u\n", 
                Simulator::Now().GetNanoSeconds(), 
                node_id, 
                Settings::if2id[Settings::nodeContainer.Get(node_id)][port], 
                m_usedIngressPortBytes[port], 
                m_usedEgressBytes[port][0] + m_usedEgressBytes[port][3]);
        }
    }

   //private:
    bool m_PFCenabled;

    uint32_t m_maxBufferBytes{0};  // 总缓冲区的容量
    uint32_t m_usedTotalBytes{0};  // 当前已用缓冲区字节数

    unsigned m_activePortCnt{0};
    uint32_t m_maxBufferBytesPerPort{
        0};  // use this to calculate m_maxBufferBytes 每个端口的最大缓冲区大小
    uint32_t m_staticMaxBufferBytes{
        0};  // use this to calculate m_maxBufferBytes 静态配置的总缓冲区大小

    uint32_t m_usedIngressPGBytes[pCnt][qCnt];  // 每个端口/优先级组（PG）的入端口已用缓冲区字节数。
    uint32_t m_usedIngressPortBytes[pCnt];  // 每个端口的入端口已用缓冲区字节数。
    uint32_t m_usedIngressSPBytes[4];  // 服务池（Service Pool）的入端口已用缓冲区字节数。
    uint32_t m_usedIngressPGHeadroomBytes[pCnt][qCnt];

    //暂时废弃
    uint32_t m_usedEgressQMinBytes[pCnt][qCnt];
    uint32_t m_usedEgressQSharedBytes[pCnt][qCnt];
    uint32_t m_usedEgressPortBytes[pCnt];
    uint32_t m_usedEgressSPBytes[4];

    uint32_t m_usedEgressBytes[pCnt][qCnt];  // 使用的出端口的

    // ingress params
    uint32_t m_buffer_cell_limit_sp;  // ingress sp buffer threshold p.120
    uint32_t
        m_buffer_cell_limit_sp_shared;  // ingress sp buffer shared threshold, nonshare -> share 似乎已经被废弃
    uint32_t m_pg_min_cell;             // ingress pg guarantee
    uint32_t m_port_min_cell;           // ingress port guarantee
    uint32_t m_pg_shared_limit_cell;    // max buffer for an ingress pg
    uint32_t m_port_max_shared_cell;    // max buffer for an ingress port
    uint32_t m_pg_hdrm_limit[pCnt];     // ingress pg headroom
    uint32_t m_port_max_pkt_size;       // ingress global headroom 疑似被废弃
    // still needs reset limits..
    uint32_t m_port_min_cell_off;  // PAUSE off threshold
    uint32_t m_pg_shared_limit_cell_off;
    uint32_t m_global_hdrm_limit;

    // egress params
    uint32_t m_q_min_cell;                   // egress queue guaranteed buffer
    uint32_t m_op_uc_port_config1_cell;      // egress queue threshold
    uint32_t m_op_uc_port_config_cell;       // egress port threshold
    uint32_t m_op_buffer_shared_limit_cell;  // egress sp threshold

    // dynamic threshold
    double m_pg_shared_alpha_cell{0};
    double m_pg_shared_alpha_cell_egress{0};
    double m_pg_shared_alpha_cell_off_diff;
    double m_port_shared_alpha_cell;
    double m_port_shared_alpha_cell_off_diff;
    bool m_dynamicth;

    double m_log_start;
    double m_log_end;
    double m_log_step;

    UniformRandomVariable m_uniform_random_var;

   public:
    inline void printBufferManagerStatus() {
        std::cout << std::boolalpha;  // 输出 bool 值时显示 true/false

        std::cout << "PFC Enabled (m_PFCenabled): " << m_PFCenabled << "\n";
        std::cout << "Max Buffer Bytes (m_maxBufferBytes): " << m_maxBufferBytes << "\n";
        std::cout << "Used Total Bytes (m_usedTotalBytes): " << m_usedTotalBytes << "\n";
        std::cout << "Active Port Count (m_activePortCnt): " << m_activePortCnt << "\n";
        std::cout << "Max Buffer Bytes Per Port (m_maxBufferBytesPerPort): "
                  << m_maxBufferBytesPerPort << "\n";
        std::cout << "Static Max Buffer Bytes (m_staticMaxBufferBytes): " << m_staticMaxBufferBytes
                  << "\n";
        // 继续打印其他成员变量
        std::cout << "Buffer Cell Limit SP (m_buffer_cell_limit_sp): " << m_buffer_cell_limit_sp
                  << "\n";
        std::cout << "PG Min Cell (m_pg_min_cell): " << m_pg_min_cell << "\n";
        std::cout << "Port Min Cell (m_port_min_cell): " << m_port_min_cell << "\n";
        std::cout << "PG Shared Limit Cell (m_pg_shared_limit_cell): " << m_pg_shared_limit_cell
                  << "\n";
        std::cout << "Port Max Shared Cell (m_port_max_shared_cell): " << m_port_max_shared_cell
                  << "\n";

        std::cout << "PG Headroom Limit (m_pg_hdrm_limit): \n";
        for (unsigned i = 0; i < 6; ++i) {
            std::cout << "PGHeadroom[" << i << "] (m_pg_hdrm_limit): " << m_pg_hdrm_limit[i]
                      << "\n";
        }

        std::cout << "Port Max Packet Size (m_port_max_pkt_size): " << m_port_max_pkt_size << "\n";
        std::cout << "Port Min Cell Off (m_port_min_cell_off): " << m_port_min_cell_off << "\n";
        std::cout << "PG Shared Limit Cell Off (m_pg_shared_limit_cell_off): "
                  << m_pg_shared_limit_cell_off << "\n";
        std::cout << "Global Headroom Limit (m_global_hdrm_limit): " << m_global_hdrm_limit << "\n";

        std::cout << "Q Min Cell (m_q_min_cell): " << m_q_min_cell << "\n";
        std::cout << "OP UC Port Config1 Cell (m_op_uc_port_config1_cell): "
                  << m_op_uc_port_config1_cell << "\n";
        std::cout << "OP UC Port Config Cell (m_op_uc_port_config_cell): "
                  << m_op_uc_port_config_cell << "\n";
        std::cout << "OP Buffer Shared Limit Cell (m_op_buffer_shared_limit_cell): "
                  << m_op_buffer_shared_limit_cell << "\n";

        std::cout << "PG Shared Alpha Cell (m_pg_shared_alpha_cell): " << m_pg_shared_alpha_cell
                  << "\n";
        std::cout << "PG Shared Alpha Cell Egress (m_pg_shared_alpha_cell_egress): "
                  << m_pg_shared_alpha_cell_egress << "\n";
        std::cout << "PG Shared Alpha Cell Off Diff (m_pg_shared_alpha_cell_off_diff): "
                  << m_pg_shared_alpha_cell_off_diff << "\n";
        std::cout << "Port Shared Alpha Cell (m_port_shared_alpha_cell): "
                  << m_port_shared_alpha_cell << "\n";
        std::cout << "Port Shared Alpha Cell Off Diff (m_port_shared_alpha_cell_off_diff): "
                  << m_port_shared_alpha_cell_off_diff << "\n";
        std::cout << "Dynamic Threshold (m_dynamicth): " << m_dynamicth << "\n";
    }
};

} /* namespace ns3 */

#endif /* SWITCH_MMU_H */
