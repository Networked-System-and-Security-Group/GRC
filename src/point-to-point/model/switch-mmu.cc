#include "switch-mmu.h"

#include <fstream>
#include <iostream>

#include "ns3/assert.h"
#include "ns3/boolean.h"
#include "ns3/broadcom-node.h"
#include "ns3/double.h"
#include "ns3/global-value.h"
#include "ns3/log.h"
#include "ns3/object-vector.h"
#include "ns3/packet.h"
#include "ns3/random-variable.h"
#include "ns3/simulator.h"
#include "ns3/uinteger.h"
#include <assert.h>

NS_LOG_COMPONENT_DEFINE("SwitchMmu");
namespace ns3 {
TypeId SwitchMmu::GetTypeId(void) {
    static TypeId tid =
        TypeId("ns3::SwitchMmu")
            .SetParent<Object>()
            .AddConstructor<SwitchMmu>()
            .AddAttribute("IngressAlpha", "Broadcom Ingress alpha", DoubleValue(0.0625),
                          MakeDoubleAccessor(&SwitchMmu::m_pg_shared_alpha_cell),
                          MakeDoubleChecker<double>())
            .AddAttribute("EgressAlpha", "Broadcom Egress alpha", DoubleValue(1.),
                          MakeDoubleAccessor(&SwitchMmu::m_pg_shared_alpha_cell_egress),
                          MakeDoubleChecker<double>())
            .AddAttribute("DynamicThreshold", "Broadcom Egress alpha", BooleanValue(true),
                          MakeBooleanAccessor(&SwitchMmu::SetDynamicThreshold,
                                              &SwitchMmu::GetDynamicThreshold),
                          MakeBooleanChecker())
            .AddAttribute(
                "MaxTotalBufferPerPort",
                "Maximum buffer size of MMU per port in bytes (12-port switch: 12 * 375kB = 4.5MB)",
                UintegerValue(375 * 1000),
                MakeUintegerAccessor(&SwitchMmu::SetMaxBufferBytesPerPort,
                                     &SwitchMmu::GetMaxBufferBytesPerPort),
                MakeUintegerChecker<uint32_t>())
            .AddAttribute(
                "ActivePortCnt", "Number of active switch ports", UintegerValue(12),
                MakeUintegerAccessor(&SwitchMmu::SetActivePortCnt, &SwitchMmu::GetActivePortCnt),
                MakeUintegerChecker<uint32_t>())
            .AddAttribute(
                "PGHeadroomLimit", "Headroom Limit per PG",
                UintegerValue(12500 + 2 * MTU),  // 2*(LinkDelay*Bandwidth+MTU) 2*1us*450Gbps+2*MTU
                MakeUintegerAccessor(&SwitchMmu::SetPgHdrmLimit, &SwitchMmu::GetPgHdrmLimit),
                MakeUintegerChecker<uint32_t>());
    return tid;
}
SwitchMmu::SwitchMmu(void) {
    // Default buffer size: 375kB per active ports
    // 12-port switch: 12 * 375kB = 4.5MB
    // 32-port switch: 32 * 375kB = 12MB
    // m_maxBufferBytes = 4500 * 1000; //Originally: 9MB Current:4.5MB
    m_uniform_random_var.SetStream(0);

    // dynamic threshold
    m_dynamicth = false;
    m_unoPhantomConfigured = false;
    for (uint32_t i = 0; i < pCnt; i++) {
        unoPhantomEnabled[i] = false;
        unoPhantomBytes[i] = 0;
        unoPhantomLastUpdateNs[i] = 0;
        unoPhantomSizeBytes[i] = 0;
        unoPhantomKminBytes[i] = 0;
        unoPhantomKmaxBytes[i] = 0;
        unoPhantomPmax[i] = 0;
        unoPhantomDrainBps[i] = 0;
    }

    //InitSwitch();
}

void SwitchMmu::InitSwitch(void) {
    m_maxBufferBytes = m_staticMaxBufferBytes ? m_staticMaxBufferBytes
                                              : (m_maxBufferBytesPerPort * m_activePortCnt);
    m_usedTotalBytes = 0;

    if (m_dynamicth) {
        m_pg_shared_limit_cell = m_maxBufferBytes;  // using dynamic threshold, we don't respect the
                                                    // static thresholds anymore
        m_port_max_shared_cell = m_maxBufferBytes;
    } else {
        m_pg_shared_limit_cell = 20 * MTU;    // max buffer for an ingress pg
        m_port_max_shared_cell = 4800 * MTU;  // max buffer for an ingress port
    }

    for (uint32_t i = 0; i < pCnt; i++)  // port 0 is not used
    {
        m_usedIngressPortBytes[i] = 0;
        m_usedEgressPortBytes[i] = 0;
        if (m_unoPhantomConfigured) {
            unoPhantomBytes[i] = 0;
            unoPhantomLastUpdateNs[i] = Simulator::Now().GetNanoSeconds();
            if (unoPhantomSizeBytes[i] == 0) {
                unoPhantomEnabled[i] = false;
                unoPhantomKminBytes[i] = 0;
                unoPhantomKmaxBytes[i] = 0;
                unoPhantomPmax[i] = 0;
                unoPhantomDrainBps[i] = 0;
            }
        }
        for (uint32_t j = 0; j < qCnt; j++) {
            m_usedIngressPGBytes[i][j] = 0;
            m_usedIngressPGHeadroomBytes[i][j] = 0;
            m_usedEgressQMinBytes[i][j] = 0;
            m_usedEgressQSharedBytes[i][j] = 0;
            m_usedEgressBytes[i][j] = 0;
        }
    }
    for (int i = 0; i < 4; i++) {
        m_usedIngressSPBytes[i] = 0;
        m_usedEgressSPBytes[i] = 0;
    }
    // ingress params
    m_buffer_cell_limit_sp = 4000 * MTU;  // ingress sp buffer threshold
    // m_buffer_cell_limit_sp_shared=4000*MTU; //ingress sp buffer shared threshold, nonshare ->
    // share
    m_pg_min_cell = MTU;    // ingress pg guarantee
    m_port_min_cell = MTU;  // ingress port guarantee
    
    // 【修改】设置PG=1的固定Buffer大小为160MB
    // 注意：160MB = 160 * 1024 * 1024 字节
    m_tcp_pg_min_cell = 160 * 1024 * 1024; 
    
    // PG=1 Port limit usually set to same or slightly larger if dedicated
    m_tcp_port_min_cell = m_tcp_pg_min_cell; 

    // m_pg_hdrm_limit = 103000; //2*10us*40Gbps+2*1.5kB //106 * MTU; //ingress pg headroom // set
    // dynamically
    m_port_max_pkt_size = 100 * MTU;  // ingress global headroom 这个参数疑似被废弃
    uint32_t total_m_pg_hdrm_limit = 0;
    for (int i = 0; i < m_activePortCnt; i++) total_m_pg_hdrm_limit += m_pg_hdrm_limit[i];
    
    // 注意：如果 160MB 非常大，原来的断言可能会失败。
    // 这里我们假设用户已经将 MaxTotalBufferPerPort 设置得足够大以包含这 160MB，
    // 或者我们在此处注释掉针对小Buffer switch的断言，防止报错。
     if (!(m_maxBufferBytes > total_m_pg_hdrm_limit + m_activePortCnt * std::max(qCnt * m_pg_min_cell, m_port_min_cell))) {
        std::cerr << "Assertion failed!" << std::endl;
        // ... logging ...
        assert(m_maxBufferBytes > total_m_pg_hdrm_limit + m_activePortCnt * std::max(qCnt * m_pg_min_cell, m_port_min_cell));
    }
    
    
    m_buffer_cell_limit_sp =
        m_maxBufferBytes - total_m_pg_hdrm_limit -
        (m_activePortCnt)*std::max(qCnt * m_pg_min_cell,
                                     m_port_min_cell);  // 12000 * MTU; //ingress sp buffer threshold
    // still needs reset limits..
    m_port_min_cell_off = 4700 * MTU; //在动态阈值的配置下不需要使用这个
    m_pg_shared_limit_cell_off = m_pg_shared_limit_cell - 2 * MTU; //在动态阈值的配置下不需要使用这个

    // egress params
    m_op_buffer_shared_limit_cell =
        m_maxBufferBytes -
        (m_activePortCnt)*std::max(
            qCnt * m_pg_min_cell,
            m_port_min_cell);  // m_maxBufferBytes; //per egress sp limit

    m_op_uc_port_config_cell = m_maxBufferBytes;  // per egress port limit
    m_q_min_cell = 1 + MTU;
    m_op_uc_port_config1_cell = m_maxBufferBytes;

    m_port_shared_alpha_cell = 128;  // not used for now
    m_pg_shared_alpha_cell_off_diff = 16;
    m_port_shared_alpha_cell_off_diff = 16;
    
    m_log_start = 2.1;
    m_log_end = 2.2;
    m_log_step = 0.00001;
}

bool SwitchMmu::CheckIngressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize) {
    NS_ASSERT(m_pg_shared_alpha_cell > 0);

    if (m_usedTotalBytes + psize > m_maxBufferBytes)  // buffer full
    {
        //std::cerr << "WARNING: Drop because ingress buffer full\n";
        return false;
    }

    // q1 is the isolated TCP queue only in the default mode. In q3 mode,
    // TCP shares the normal RDMA PG3 accounting and threshold logic.
    if (Settings::tcp_queue_index == 1 && qIndex == 1) {
        if (m_usedIngressPGBytes[port][qIndex] + psize > m_tcp_pg_min_cell) {
             // 超过了 160MB 的限制，丢包
             return false;
        }
        // 如果开启了PFC，这里需要检查Headroom吗？
        // 如果是无损队列，通常在达到 headroom 阈值时触发 Pause，但还能继续收包直到 Headroom 满
        // 这里假设 CheckIngressAdmission 是判断物理队列是否溢出（丢包）
        // 如果需要严格不丢包，应该保证 Pause 阈值 < Buffer Size
        return true; 
    }

    // 其他优先级队列 (PG != 1) 走共享池逻辑
    if (m_usedIngressPGBytes[port][qIndex] + psize > m_pg_min_cell &&
        m_usedIngressPortBytes[port] + psize > m_port_min_cell) { // exceed guaranteed, use share buffer
        
        if (m_usedIngressSPBytes[GetIngressSP(port, qIndex)] > m_buffer_cell_limit_sp) {  // check if headroom is already being used
            if (m_usedIngressPGHeadroomBytes[port][qIndex] + psize > m_pg_hdrm_limit[port]) { // exceed headroom space
                if (m_PFCenabled) {
                    std::cerr << "WARNING: Drop because ingress headroom full:"
                              << m_usedIngressPGBytes[port][qIndex] << "\t" // Fixed log to show total PG usage
                              << m_pg_hdrm_limit[port] << "\n";
                }
                return false;
            }
        }
    }
    
    return true;
}

// Egress logic unchanged for this request
bool SwitchMmu::CheckEgressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize) {
    NS_ASSERT(m_pg_shared_alpha_cell_egress > 0);
    return true;
}

void SwitchMmu::UpdateIngressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize) {
    m_usedTotalBytes += psize;  // count total buffer usage
    m_usedIngressPortBytes[port] += psize;
    m_usedIngressPGBytes[port][qIndex] += psize;

    // Isolated q1 does not consume the shared pool. q3 mode follows the
    // ordinary PG/shared-pool logic.
    if (Settings::tcp_queue_index == 1 && qIndex == 1) {
        // 对于 PG=1，我们可能仍然需要统计 Headroom 使用情况用于调试，或者完全基于固定阈值
        // 此处不再更新 m_usedIngressSPBytes，实现了与共享池的隔离
        
        // 可选：如果 PG=1 也需要 Headroom 统计（虽然它不使用 SP），可以单独处理
        // 但根据题目要求 "自己使用一个固定大小的buffer"，通常意味着线性使用。
        return; 
    }

    // PG != 1 的逻辑，更新共享池
    m_usedIngressSPBytes[GetIngressSP(port, qIndex)] += psize;
    
    if (m_usedIngressSPBytes[GetIngressSP(port, qIndex)] >
        m_buffer_cell_limit_sp)  // begin to use headroom buffer
    {
        m_usedIngressPGHeadroomBytes[port][qIndex] += psize;
    }
}

void SwitchMmu::UpdateEgressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize) {
    m_usedEgressBytes[port][qIndex] += psize;  // count total buffer usage
    if (unoPhantomEnabled[port] && qIndex != 0) {
        const uint64_t nowNs = Simulator::Now().GetNanoSeconds();
        const uint64_t elapsed = nowNs - unoPhantomLastUpdateNs[port];
        const double drained = unoPhantomDrainBps[port] * elapsed / 8e9;
        unoPhantomBytes[port] = std::max(0.0, unoPhantomBytes[port] - drained);
        unoPhantomBytes[port] = std::min<double>(unoPhantomSizeBytes[port], unoPhantomBytes[port] + psize);
        unoPhantomLastUpdateNs[port] = nowNs;
    }
    //if (m_usedEgressQMinBytes[port][qIndex] + psize < m_q_min_cell)  // guaranteed
    //{
    //    m_usedEgressQMinBytes[port][qIndex] += psize;
    //    m_usedEgressPortBytes[port] = m_usedEgressPortBytes[port] + psize;
    //    return;
    //} else {
    //    /*
    //    2 case
    //    First, when there is left space in q_min_cell, and we should use remaining space in
    //    q_min_cell and add rest to the shared_pool Second, just adding to shared pool
    //    */
    //    if (m_usedEgressQMinBytes[port][qIndex] != m_q_min_cell) {
    //        m_usedEgressQSharedBytes[port][qIndex] = m_usedEgressQSharedBytes[port][qIndex] +
    //                                                 psize + m_usedEgressQMinBytes[port][qIndex] -
    //                                                 m_q_min_cell;
    //        m_usedEgressPortBytes[port] =
    //            m_usedEgressPortBytes[port] +
    //            psize;  //+ m_usedEgressQMinBytes[port][qIndex] - m_q_min_cell ;
    //        m_usedEgressSPBytes[GetEgressSP(port, qIndex)] =
    //            m_usedEgressSPBytes[GetEgressSP(port, qIndex)] + psize +
    //            m_usedEgressQMinBytes[port][qIndex] - m_q_min_cell;
    //        m_usedEgressQMinBytes[port][qIndex] = m_q_min_cell;
//
    //    } else {
    //        m_usedEgressQSharedBytes[port][qIndex] += psize;
    //        m_usedEgressPortBytes[port] += psize;
    //        m_usedEgressSPBytes[GetEgressSP(port, qIndex)] += psize;
    //    }
    //}
}

void SwitchMmu::RemoveFromIngressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize) {
    // Safety checks
    if (m_usedTotalBytes < psize) {
        m_usedTotalBytes = psize;
        std::cerr << "Warning : Illegal Remove Total" << std::endl;
    }
    if (m_usedIngressPortBytes[port] < psize) {
        m_usedIngressPortBytes[port] = psize;
        std::cerr << "Warning : Illegal Remove Port" << std::endl;
    }
    if (m_usedIngressPGBytes[port][qIndex] < psize) {
        m_usedIngressPGBytes[port][qIndex] = psize;
        std::cerr << "Warning : Illegal Remove PG" << std::endl;
    }

    m_usedTotalBytes -= psize;
    m_usedIngressPortBytes[port] -= psize;
    m_usedIngressPGBytes[port][qIndex] -= psize;

    // Keep isolated q1 out of the shared pool. In q3 mode, TCP/RDMA PG3
    // accounting must be removed through the ordinary shared-pool path.
    if (Settings::tcp_queue_index == 1 && qIndex == 1) {
        return;
    }

    // PG != 1 的逻辑
    if (m_usedIngressSPBytes[GetIngressSP(port, qIndex)] < psize) {
        m_usedIngressSPBytes[GetIngressSP(port, qIndex)] = psize;
        std::cerr << "Warning : Illegal Remove SP" << std::endl;
    }
    m_usedIngressSPBytes[GetIngressSP(port, qIndex)] -= psize;

    if ((double)m_usedIngressPGHeadroomBytes[port][qIndex] - psize > 0)
        m_usedIngressPGHeadroomBytes[port][qIndex] -= psize;
    else
        m_usedIngressPGHeadroomBytes[port][qIndex] = 0;
}

void SwitchMmu::RemoveFromEgressAdmission(uint32_t port, uint32_t qIndex, uint32_t psize) {
    m_usedEgressBytes[port][qIndex] -= psize;
}

void SwitchMmu::GetPauseClasses(uint32_t port, uint32_t qIndex, bool pClasses[]) {
    if (port > m_activePortCnt) {
        std::cerr << "ERROR: port is " << port << std::endl;
    }

    if (m_dynamicth) {
        for (uint32_t i = 0; i < qCnt; i++) {
            pClasses[i] = false;
            
            // Isolated TCP q1 flow control. q3 mode uses ordinary PG logic.
            if (Settings::tcp_queue_index == 1 && i == 1) {
                // 如果使用固定 Buffer，Pause 阈值通常设为：总容量 - Headroom
                // m_tcp_pg_min_cell 是总容量 (160MB)
                // m_pg_hdrm_limit[port] 是 headroom
                uint32_t pause_threshold = m_tcp_pg_min_cell > m_pg_hdrm_limit[port] 
                                         ? m_tcp_pg_min_cell - m_pg_hdrm_limit[port] 
                                         : 0;

                if (m_usedIngressPGBytes[port][i] > pause_threshold) {
                    pClasses[i] = true;
                }
                continue; // 处理完 PG=1 后跳过后续共享逻辑
            }

            // PG != 1 的共享逻辑
            if (m_usedIngressPGBytes[port][i] <= m_pg_min_cell + m_port_min_cell) continue;

            if ((double)m_usedIngressPGBytes[port][i] - m_pg_min_cell - m_port_min_cell >
                    m_pg_shared_alpha_cell * ((double)m_buffer_cell_limit_sp -
                                                m_usedIngressSPBytes[GetIngressSP(port, qIndex)]) ||
                m_usedIngressPGHeadroomBytes[port][qIndex] != 0) {
                pClasses[i] = true;
            }
        }
    } else {
        // Static threshold logic (non-dynamic)
        if (m_usedIngressPortBytes[port] > m_port_max_shared_cell) { // pause the whole port
            for (uint32_t i = 0; i < qCnt; i++) {
                pClasses[i] = true;
            }
            return;
        } else {
            for (uint32_t i = 0; i < qCnt; i++) {
                pClasses[i] = false;
            }
        }
        
        // Isolated TCP q1 static check
        if (Settings::tcp_queue_index == 1 && qIndex == 1) {
             uint32_t pause_threshold = m_tcp_pg_min_cell > m_pg_hdrm_limit[port] 
                                         ? m_tcp_pg_min_cell - m_pg_hdrm_limit[port] 
                                         : 0;
             if (m_usedIngressPGBytes[port][qIndex] > pause_threshold) {
                 pClasses[qIndex] = true;
             }
        } else {
            if (m_usedIngressPGBytes[port][qIndex] > m_pg_shared_limit_cell) {
                pClasses[qIndex] = true;
            }
        }
    }
    return;
}

bool SwitchMmu::GetResumeClasses(uint32_t port, uint32_t qIndex) {
    if (!paused[port][qIndex]) return false;

    // Isolated TCP q1 recovery logic
    if (Settings::tcp_queue_index == 1 && qIndex == 1) {
        // 恢复阈值通常比暂停阈值低一点 (Hysteresis)
        // 这里简单设置为 Pause阈值 - 2个MTU
        uint32_t pause_threshold = m_tcp_pg_min_cell > m_pg_hdrm_limit[port] 
                                    ? m_tcp_pg_min_cell - m_pg_hdrm_limit[port] 
                                    : 0;
        uint32_t resume_threshold = pause_threshold > 2 * MTU ? pause_threshold - 2 * MTU : 0;

        if (m_usedIngressPGBytes[port][qIndex] < resume_threshold) {
            return true;
        }
        return false;
    }

    // PG != 1 的逻辑
    if (m_dynamicth) {
        if ((double)m_usedIngressPGBytes[port][qIndex] - m_pg_min_cell - m_port_min_cell <
                m_pg_shared_alpha_cell * ((double)m_buffer_cell_limit_sp -
                                            m_usedIngressSPBytes[GetIngressSP(port, qIndex)] -
                                            m_pg_shared_alpha_cell_off_diff) &&
            m_usedIngressPGHeadroomBytes[port][qIndex] == 0) {
            return true;
        }
    } else {
        if (m_usedIngressPGBytes[port][qIndex] < m_pg_shared_limit_cell_off &&
            m_usedIngressPortBytes[port] < m_port_min_cell_off) {
            return true;
        }
    }
    return false;
}

uint32_t SwitchMmu::GetIngressSP(uint32_t port, uint32_t pgIndex) {
    if (pgIndex == 1)
        return 1;
    else
        return 0;
}

uint32_t SwitchMmu::GetEgressSP(uint32_t port, uint32_t qIndex) {
    if (qIndex == 0)
        return 0;
    else
        return 1;
}
uint32_t SwitchMmu::GetusedIngressPortBytes(uint32_t port){
    return m_usedIngressPortBytes[port];
}
uint32_t SwitchMmu::GetusedIngressSPBytes(){
    return m_usedIngressSPBytes[1];

}
uint32_t SwitchMmu::GetusedEgressQSharedBytes(uint32_t port, uint32_t qIndex){
    return m_usedEgressQSharedBytes[port][qIndex];

}

bool SwitchMmu::ShouldSendCN(uint32_t ifindex, uint32_t qIndex) {
    if (qIndex == 0)  // qidx=0 as highest priority
        return false;
    if (unoPhantomEnabled[ifindex]) {
        const uint64_t nowNs = Simulator::Now().GetNanoSeconds();
        const uint64_t elapsed = nowNs - unoPhantomLastUpdateNs[ifindex];
        const double drained = unoPhantomDrainBps[ifindex] * elapsed / 8e9;
        unoPhantomBytes[ifindex] = std::max(0.0, unoPhantomBytes[ifindex] - drained);
        unoPhantomLastUpdateNs[ifindex] = nowNs;
        if (unoPhantomBytes[ifindex] > unoPhantomKmaxBytes[ifindex])
            return true;
        if (unoPhantomBytes[ifindex] > unoPhantomKminBytes[ifindex] &&
            unoPhantomKmaxBytes[ifindex] > unoPhantomKminBytes[ifindex]) {
            double p = unoPhantomPmax[ifindex] *
                       (unoPhantomBytes[ifindex] - unoPhantomKminBytes[ifindex]) /
                       (unoPhantomKmaxBytes[ifindex] - unoPhantomKminBytes[ifindex]);
            if (m_uniform_random_var.GetValue(0, 1) < p)
                return true;
        }
        return false;
    }
    if (m_usedEgressBytes[ifindex][qIndex] > kmax[ifindex])
        return true;
    if (m_usedEgressBytes[ifindex][qIndex] > kmin[ifindex]){
        double p = pmax[ifindex] * double(m_usedEgressBytes[ifindex][qIndex] - kmin[ifindex]) / (kmax[ifindex] - kmin[ifindex]);
        if (m_uniform_random_var.GetValue(0, 1) < p)
            return true;
    }
    return false;
}

void SwitchMmu::SetBroadcomParams(
    uint32_t buffer_cell_limit_sp,  // ingress sp buffer threshold p.120
    uint32_t
        buffer_cell_limit_sp_shared,  // ingress sp buffer shared threshold p.120, nonshare -> share
    uint32_t pg_min_cell,             // ingress pg guarantee p.121                 ---1
    uint32_t port_min_cell,           // ingress port guarantee                     ---2
    uint32_t pg_shared_limit_cell,    // max buffer for an ingress pg           ---3    PAUSE
    uint32_t port_max_shared_cell,    // max buffer for an ingress port     ---4    PAUSE
    uint32_t pg_hdrm_limit,           // ingress pg headroom
    uint32_t port_max_pkt_size,       // ingress global headroom
    uint32_t q_min_cell,              // egress queue guaranteed buffer
    uint32_t op_uc_port_config1_cell,      // egress queue threshold
    uint32_t op_uc_port_config_cell,       // egress port threshold
    uint32_t op_buffer_shared_limit_cell,  // egress sp threshold
    uint32_t q_shared_alpha_cell, uint32_t port_share_alpha_cell, uint32_t pg_qcn_threshold) {
    m_buffer_cell_limit_sp = buffer_cell_limit_sp;
    m_buffer_cell_limit_sp_shared = buffer_cell_limit_sp_shared;
    m_pg_min_cell = pg_min_cell;
    m_port_min_cell = port_min_cell;
    m_pg_shared_limit_cell = pg_shared_limit_cell;
    m_port_max_shared_cell = port_max_shared_cell;
    for (int i = 0; i < pCnt; i++) m_pg_hdrm_limit[i] = pg_hdrm_limit;
    m_port_max_pkt_size = port_max_pkt_size;
    m_q_min_cell = q_min_cell;
    m_op_uc_port_config1_cell = op_uc_port_config1_cell;
    m_op_uc_port_config_cell = op_uc_port_config_cell;
    m_op_buffer_shared_limit_cell = op_buffer_shared_limit_cell;
    m_pg_shared_alpha_cell = q_shared_alpha_cell;
    m_port_shared_alpha_cell = port_share_alpha_cell;
}

uint32_t SwitchMmu::GetUsedBufferTotal() { return m_usedTotalBytes; }

void SwitchMmu::SetDynamicThreshold(bool v) {
    m_dynamicth = v;
    //InitSwitch();
    return;
}

void SwitchMmu::ConfigEcn(uint32_t port, uint32_t _kmin, uint32_t _kmax, double _pmax) {
    kmin[port] = _kmin * 1000;
    kmax[port] = _kmax * 1000;
    pmax[port] = _pmax;
}

void SwitchMmu::ConfigUnoPhantom(uint32_t port, uint32_t sizeBytes, uint32_t kminPct,
                                 uint32_t kmaxPct, double _pmax, double slowdownPct,
                                 uint64_t lineRate) {
    m_unoPhantomConfigured = m_unoPhantomConfigured || sizeBytes > 0;
    unoPhantomEnabled[port] = sizeBytes > 0;
    unoPhantomBytes[port] = 0;
    unoPhantomLastUpdateNs[port] = Simulator::Now().GetNanoSeconds();
    unoPhantomSizeBytes[port] = sizeBytes;
    unoPhantomKminBytes[port] = sizeBytes * kminPct / 100;
    unoPhantomKmaxBytes[port] = sizeBytes * kmaxPct / 100;
    unoPhantomPmax[port] = _pmax;
    unoPhantomDrainBps[port] = lineRate * std::max(0.0, 1.0 - slowdownPct / 100.0);
}

void SwitchMmu::SetPause(uint32_t port, uint32_t qIndex, uint32_t pause_time) {
    paused[port][qIndex] = true;
    Simulator::Cancel(resumeEvt[port][qIndex]);
    resumeEvt[port][qIndex] =
        Simulator::Schedule(MicroSeconds(pause_time), &SwitchMmu::SetResume, this, port, qIndex);
}
void SwitchMmu::SetResume(uint32_t port, uint32_t qIndex) {
    paused[port][qIndex] = false;
    Simulator::Cancel(resumeEvt[port][qIndex]);
}

void SwitchMmu::ConfigHdrm(uint32_t port, uint32_t size) {
    m_pg_hdrm_limit[port] = size;
    //InitSwitch();
}
void SwitchMmu::ConfigNPort(uint32_t n_port) {
    m_activePortCnt = n_port;
    //InitSwitch();
}
void SwitchMmu::ConfigBufferSize(uint32_t size) {
    // if size == 0, buffer size will be automatically decided
    m_staticMaxBufferBytes = size;
    //InitSwitch();
}

}  // namespace ns3
