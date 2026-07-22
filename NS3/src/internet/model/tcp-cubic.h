#ifndef TCP_CUBIC_H
#define TCP_CUBIC_H

#include "tcp-congestion-ops.h"
#include "tcp-socket-base.h"
#include "ns3/nstime.h"
#include "ns3/object.h"

namespace ns3 {

/**
 * \ingroup internet
 * \brief Implementation of the CUBIC congestion control algorithm
 *
 * This class implements the CUBIC congestion control algorithm as described
 * in RFC 8312.
 */
class TcpCubic : public TcpCongestionOps
{
public:
  static TypeId GetTypeId (void);

  TcpCubic ();
  TcpCubic (const TcpCubic &other);
  virtual ~TcpCubic ();

  virtual std::string GetName () const override;

  virtual void IncreaseWindow (Ptr<TcpSocketState> tcb, uint32_t segmentsAcked) override;
  virtual uint32_t GetSsThresh (Ptr<const TcpSocketState> tcb, uint32_t bytesInFlight) override;
  virtual void PktsAcked (Ptr<TcpSocketState> tcb, uint32_t segmentsAcked, const Time &rtt) override;
  virtual void CongestionStateSet (Ptr<TcpSocketState> tcb, const TcpSocketState::TcpCongState_t newState) override;

  virtual Ptr<TcpCongestionOps> Fork () override;

private:
  void ResetCubic ();
  void UpdateCubicParams (Ptr<TcpSocketState> tcb);

  double m_c;               //!< Scaling factor for CUBIC
  double m_beta;            //!< Multiplicative decrease factor
  double m_lastMaxCwnd;     //!< Last maximum congestion window
  double m_cubicK;          //!< Time to reach Wmax
  double m_bicOriginPoint;  //!< Origin point of the cubic function
  Time m_epochStart;        //!< Start time of the current epoch
  Time m_minRtt;            //!< Minimum RTT observed
  bool m_fastConvergence;   //!< Enable fast convergence
};

} // namespace ns3

#endif // TCP_CUBIC_H