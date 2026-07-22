/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Implementation of TcpSocketBase with CUBIC Congestion Control
 */

 #define NS_LOG_APPEND_CONTEXT \
 if (m_node) { std::clog << Simulator::Now ().GetSeconds () << " [node " << m_node->GetId () << "] "; }

#include <cstdlib>
#include <cmath> 
#include "ns3/abort.h"
#include "ns3/node.h"
#include "ns3/inet-socket-address.h"
#include "ns3/inet6-socket-address.h"
#include "ns3/log.h"
#include "ns3/ipv4.h"
#include "ns3/ipv6.h"
#include "ns3/ipv4-interface-address.h"
#include "ns3/ipv4-route.h"
#include "ns3/ipv6-route.h"
#include "ns3/ipv4-routing-protocol.h"
#include "ns3/ipv6-routing-protocol.h"
#include "ns3/simulation-singleton.h"
#include "ns3/simulator.h"
#include "ns3/packet.h"
#include "ns3/uinteger.h"
#include "ns3/double.h"
#include "ns3/trace-source-accessor.h"
#include "tcp-socket-base.h" // Includes the modified header
#include "tcp-l4-protocol.h"
#include "ipv4-end-point.h"
#include "ipv6-end-point.h"
#include "ipv6-l3-protocol.h"
#include "tcp-header.h"
#include "rtt-estimator.h"

#include <algorithm>

NS_LOG_COMPONENT_DEFINE ("TcpSocketBase");

namespace ns3 {

NS_OBJECT_ENSURE_REGISTERED (TcpSocketBase);

TypeId
TcpSocketBase::GetTypeId (void)
{
 static TypeId tid = TypeId ("ns3::TcpSocketBase")
   .SetParent<TcpSocket> ()
   .AddAttribute ("MaxSegLifetime",
                  "Maximum segment lifetime in seconds, use for TIME_WAIT state transition to CLOSED state",
                  DoubleValue (120), /* RFC793 says MSL=2 minutes*/
                  MakeDoubleAccessor (&TcpSocketBase::m_msl),
                  MakeDoubleChecker<double> (0))
   .AddAttribute ("MaxWindowSize", "Max size of advertised window",
                  UintegerValue (65535),
                  MakeUintegerAccessor (&TcpSocketBase::m_maxWinSize),
                  MakeUintegerChecker<uint16_t> ())
   .AddAttribute ("IcmpCallback", "Callback invoked whenever an icmp error is received on this socket.",
                  CallbackValue (),
                  MakeCallbackAccessor (&TcpSocketBase::m_icmpCallback),
                  MakeCallbackChecker ())
   .AddAttribute ("IcmpCallback6", "Callback invoked whenever an icmpv6 error is received on this socket.",
                  CallbackValue (),
                  MakeCallbackAccessor (&TcpSocketBase::m_icmpCallback6),
                  MakeCallbackChecker ())
   .AddAttribute ("DCTCP", "DCTCP flavored socket",
                  BooleanValue (true),
                  MakeBooleanAccessor (&TcpSocketBase::m_DCTCP),
                  MakeBooleanChecker ())
   .AddAttribute ("DCTCPWeight",
                  "Weight for calculating DCTCP's alpha parameter -- deprecated",
                  DoubleValue (1.0 / 32.0),
                  MakeDoubleAccessor (&TcpSocketBase::m_g),
                  MakeDoubleChecker<double> (0, 1))
   .AddAttribute ("UserRTO",
                  "User RTO",
                  TimeValue (Time(0)),
                  MakeTimeAccessor (&TcpSocketBase::m_userRto),
                  MakeTimeChecker())
   .AddAttribute ("InitialCwndTCP", "Initial Congestion Window in segments",
                  UintegerValue (1),
                  MakeUintegerAccessor (&TcpSocketBase::m_InitialCwndTCP),
                  MakeUintegerChecker<uint32_t> ())
 ;
 return tid;
}

TcpSocketBase::TcpSocketBase (void)
 : m_dupAckCount (0),
   m_delAckCount (0),
   m_endPoint (0),
   m_endPoint6 (0),
   m_node (0),
   m_tcp (0),
   m_rtt (0),
   m_nextTxSequence (std::rand ()),
   m_highTxMark (0),
   m_rxBuffer (0),
   m_txBuffer (0),
   m_state (CLOSED),
   m_errno (ERROR_NOTERROR),
   m_closeNotified (false),
   m_closeOnEmpty (false),
   m_shutdownSend (false),
   m_shutdownRecv (false),
   m_connected (false),
   m_EcnState (NO_ECN),
   m_EcnEchoSeq (0),
   m_EcnTransition (false),
   m_deadline (0),
   m_deadlineFinish (0),
   m_bytesToTx (0),
   m_segmentSize (536), // Default, prevents div by zero
   m_rWnd (0),
   // CUBIC Init
   m_cWnd (0),
   m_ssThresh (0xFFFFFFFF),
   m_cWndCnt (0.0),
   m_wLastMax (0),
   m_epochStart (Seconds(0)),
   m_k (0.0),
   m_beta (0.7),
   m_cubicC (0.4)
{
 NS_LOG_FUNCTION (this);
}

TcpSocketBase::TcpSocketBase (const TcpSocketBase& sock)
 : TcpSocket (sock),
   m_dupAckCount (sock.m_dupAckCount),
   m_delAckCount (0),
   m_delAckMaxCount (sock.m_delAckMaxCount),
   m_noDelay (sock.m_noDelay),
   m_cnRetries (sock.m_cnRetries),
   m_userRto (sock.m_userRto),
   m_delAckTimeout (sock.m_delAckTimeout),
   m_persistTimeout (sock.m_persistTimeout),
   m_cnTimeout (sock.m_cnTimeout),
   m_endPoint (0),
   m_endPoint6 (0),
   m_node (sock.m_node),
   m_tcp (sock.m_tcp),
   m_rtt (0),
   m_nextTxSequence (sock.m_nextTxSequence),
   m_highTxMark (sock.m_highTxMark),
   m_rxBuffer (sock.m_rxBuffer),
   m_txBuffer (sock.m_txBuffer),
   m_state (sock.m_state),
   m_errno (sock.m_errno),
   m_closeNotified (sock.m_closeNotified),
   m_closeOnEmpty (sock.m_closeOnEmpty),
   m_shutdownSend (sock.m_shutdownSend),
   m_shutdownRecv (sock.m_shutdownRecv),
   m_connected (sock.m_connected),
   m_msl (sock.m_msl),
   m_ECN (sock.m_ECN),
   m_EcnState (sock.m_EcnState),
   m_EcnEchoSeq (sock.m_EcnEchoSeq),
   m_DCTCP (sock.m_DCTCP),
   m_g (sock.m_g),
   m_EcnTransition (sock.m_EcnTransition),
   m_deadline (sock.m_deadline),
   m_deadlineFinish (sock.m_deadlineFinish),
   m_bytesToTx (sock.m_bytesToTx),
   m_segmentSize (sock.m_segmentSize),
   m_maxWinSize (sock.m_maxWinSize),
   m_rWnd (sock.m_rWnd),
   // CUBIC Copy
   m_cWnd (sock.m_cWnd),
   m_ssThresh (sock.m_ssThresh),
   m_InitialCwndTCP (sock.m_InitialCwndTCP),
   m_cWndCnt (sock.m_cWndCnt),
   m_wLastMax (sock.m_wLastMax),
   m_epochStart (sock.m_epochStart),
   m_k (sock.m_k),
   m_beta (sock.m_beta),
   m_cubicC (sock.m_cubicC)
{
 NS_LOG_FUNCTION (this);
 if (sock.m_rtt)
   {
     m_rtt = sock.m_rtt->Copy ();
   }
 // Callback reset
 Callback<void, Ptr< Socket > > vPS = MakeNullCallback<void, Ptr<Socket> > ();
 Callback<void, Ptr<Socket>, const Address &> vPSA = MakeNullCallback<void, Ptr<Socket>, const Address &> ();
 Callback<void, Ptr<Socket>, uint32_t> vPSUI = MakeNullCallback<void, Ptr<Socket>, uint32_t> ();
 SetConnectCallback (vPS, vPS);
 SetDataSentCallback (vPSUI);
 SetSendCallback (vPSUI);
 SetRecvCallback (vPS);
}

TcpSocketBase::~TcpSocketBase (void)
{
 NS_LOG_FUNCTION (this);
 m_node = 0;
 if (m_endPoint != 0)
   {
     NS_ASSERT (m_tcp != 0);
     m_tcp->DeAllocate (m_endPoint);
     m_endPoint = 0;
   }
 if (m_endPoint6 != 0)
   {
     NS_ASSERT (m_tcp != 0);
     m_tcp->DeAllocate (m_endPoint6);
     m_endPoint6 = 0;
   }
 m_tcp = 0;
 CancelAllTimers ();
}

void TcpSocketBase::SetNode (Ptr<Node> node) { m_node = node; }
void TcpSocketBase::SetTcp (Ptr<TcpL4Protocol> tcp) { m_tcp = tcp; }
void TcpSocketBase::SetRtt (Ptr<RttEstimator> rtt) { m_rtt = rtt; m_rtt->SetG(m_g); m_rtt->SetExpectedNextSeq(m_nextTxSequence + 1); }

enum Socket::SocketErrno TcpSocketBase::GetErrno (void) const { return m_errno; }
enum Socket::SocketType TcpSocketBase::GetSocketType (void) const { return NS3_SOCK_STREAM; }
Ptr<Node> TcpSocketBase::GetNode (void) const { return m_node; }

int TcpSocketBase::Bind (void)
{
 m_endPoint = m_tcp->Allocate ();
 if (0 == m_endPoint) { m_errno = ERROR_ADDRNOTAVAIL; return -1; }
 m_tcp->m_sockets.push_back (this);
 return SetupCallback ();
}

int TcpSocketBase::Bind6 (void)
{
 m_endPoint6 = m_tcp->Allocate6 ();
 if (0 == m_endPoint6) { m_errno = ERROR_ADDRNOTAVAIL; return -1; }
 m_tcp->m_sockets.push_back (this);
 return SetupCallback ();
}

int TcpSocketBase::Bind (const Address &address)
{
 if (InetSocketAddress::IsMatchingType (address)) {
     InetSocketAddress transport = InetSocketAddress::ConvertFrom (address);
     Ipv4Address ipv4 = transport.GetIpv4 ();
     uint16_t port = transport.GetPort ();
     if (ipv4 == Ipv4Address::GetAny () && port == 0) m_endPoint = m_tcp->Allocate ();
     else if (ipv4 == Ipv4Address::GetAny () && port != 0) m_endPoint = m_tcp->Allocate (port);
     else if (ipv4 != Ipv4Address::GetAny () && port == 0) m_endPoint = m_tcp->Allocate (ipv4);
     else if (ipv4 != Ipv4Address::GetAny () && port != 0) m_endPoint = m_tcp->Allocate (ipv4, port);
     
     if (0 == m_endPoint) { m_errno = port ? ERROR_ADDRINUSE : ERROR_ADDRNOTAVAIL; return -1; }
 } else if (Inet6SocketAddress::IsMatchingType (address)) {
     Inet6SocketAddress transport = Inet6SocketAddress::ConvertFrom (address);
     Ipv6Address ipv6 = transport.GetIpv6 ();
     uint16_t port = transport.GetPort ();
     if (ipv6 == Ipv6Address::GetAny () && port == 0) m_endPoint6 = m_tcp->Allocate6 ();
     else if (ipv6 == Ipv6Address::GetAny () && port != 0) m_endPoint6 = m_tcp->Allocate6 (port);
     else if (ipv6 != Ipv6Address::GetAny () && port == 0) m_endPoint6 = m_tcp->Allocate6 (ipv6);
     else if (ipv6 != Ipv6Address::GetAny () && port != 0) m_endPoint6 = m_tcp->Allocate6 (ipv6, port);

     if (0 == m_endPoint6) { m_errno = port ? ERROR_ADDRINUSE : ERROR_ADDRNOTAVAIL; return -1; }
 } else { m_errno = ERROR_INVAL; return -1; }
 m_tcp->m_sockets.push_back (this);
 return SetupCallback ();
}

int TcpSocketBase::Connect (const Address & address)
{
 if (InetSocketAddress::IsMatchingType (address) && m_endPoint6 == 0) {
     if (m_endPoint == 0) { if (Bind () == -1) return -1; }
     InetSocketAddress transport = InetSocketAddress::ConvertFrom (address);
     m_endPoint->SetPeer (transport.GetIpv4 (), transport.GetPort ());
     if (SetupEndpoint () != 0) return -1;
 } else if (Inet6SocketAddress::IsMatchingType (address) && m_endPoint == 0) {
     Inet6SocketAddress transport = Inet6SocketAddress::ConvertFrom (address);
     if (transport.GetIpv6 ().IsIpv4MappedAddress ()) {
         return Connect (InetSocketAddress (transport.GetIpv6 ().GetIpv4MappedAddress (), transport.GetPort ()));
     }
     if (m_endPoint6 == 0) { if (Bind6 () == -1) return -1; }
     m_endPoint6->SetPeer (transport.GetIpv6 (), transport.GetPort ());
     if (SetupEndpoint6 () != 0) return -1;
 } else { m_errno = ERROR_INVAL; return -1; }

 m_rtt->Reset (m_nextTxSequence + 1);
 m_cnCount = m_cnRetries;
 m_deadlineFinish = (m_deadline != Time (0)) ? Simulator::Now () + m_deadline : Time(0);
 return DoConnect ();
}

int TcpSocketBase::Listen (void)
{
 if (m_state != CLOSED) { m_errno = ERROR_INVAL; return -1; }
 m_state = LISTEN;
 return 0;
}

int TcpSocketBase::Close (void)
{
 if (m_rxBuffer.Size () != 0) { SendRST (); CloseAndNotify (); return 0; }
 if (m_txBuffer.SizeFromSequence (m_nextTxSequence) > 0) {
     if (!m_closeOnEmpty) m_closeOnEmpty = true;
     return 0;
 }
 return DoClose ();
}

int TcpSocketBase::ShutdownSend (void) { m_shutdownSend = true; return 0; }
int TcpSocketBase::ShutdownRecv (void) { m_shutdownRecv = true; return 0; }

int TcpSocketBase::Send (Ptr<Packet> p, uint32_t flags)
{
 if (m_state == ESTABLISHED || m_state == SYN_SENT || m_state == CLOSE_WAIT) {
     if (!m_txBuffer.Add (p)) { m_errno = ERROR_MSGSIZE; return -1; }
     if (m_state == ESTABLISHED || m_state == CLOSE_WAIT) SendPendingData (m_connected);
     return p->GetSize ();
 }
 m_errno = ERROR_NOTCONN;
 return -1;
}

int TcpSocketBase::SendTo (Ptr<Packet> p, uint32_t flags, const Address &address) { return Send (p, flags); }

Ptr<Packet> TcpSocketBase::Recv (uint32_t maxSize, uint32_t flags)
{
 if (m_rxBuffer.Size () == 0 && m_state == CLOSE_WAIT) return Create<Packet> ();
 Ptr<Packet> out = m_rxBuffer.Extract (maxSize);
 if (out != 0 && out->GetSize () != 0) {
     SocketAddressTag tag;
     if (m_endPoint != 0) tag.SetAddress (InetSocketAddress (m_endPoint->GetPeerAddress (), m_endPoint->GetPeerPort ()));
     else if (m_endPoint6 != 0) tag.SetAddress (Inet6SocketAddress (m_endPoint6->GetPeerAddress (), m_endPoint6->GetPeerPort ()));
     out->AddPacketTag (tag);
 }
 return out;
}

Ptr<Packet> TcpSocketBase::RecvFrom (uint32_t maxSize, uint32_t flags, Address &fromAddress)
{
 Ptr<Packet> packet = Recv (maxSize, flags);
 if (packet != 0 && packet->GetSize () != 0) {
     if (m_endPoint != 0) fromAddress = InetSocketAddress (m_endPoint->GetPeerAddress (), m_endPoint->GetPeerPort ());
     else if (m_endPoint6 != 0) fromAddress = Inet6SocketAddress (m_endPoint6->GetPeerAddress (), m_endPoint6->GetPeerPort ());
 }
 return packet;
}

uint32_t TcpSocketBase::GetTxAvailable (void) const { return m_txBuffer.Available (); }
uint32_t TcpSocketBase::GetRxAvailable (void) const { return m_rxBuffer.Available (); }

int TcpSocketBase::GetSockName (Address &address) const
{
 if (m_endPoint != 0) address = InetSocketAddress (m_endPoint->GetLocalAddress (), m_endPoint->GetLocalPort ());
 else if (m_endPoint6 != 0) address = Inet6SocketAddress (m_endPoint6->GetLocalAddress (), m_endPoint6->GetLocalPort ());
 else address = InetSocketAddress (Ipv4Address::GetZero (), 0);
 return 0;
}

void TcpSocketBase::BindToNetDevice (Ptr<NetDevice> netdevice)
{
 Socket::BindToNetDevice (netdevice);
 if (m_endPoint == 0 && m_endPoint6 == 0) {
     if (Bind () == -1) return;
 }
 if (m_endPoint != 0) m_endPoint->BindToNetDevice (netdevice);
}

// -------------------------------------------------------------------------
// CUBIC Logic Implementation
// -------------------------------------------------------------------------

void TcpSocketBase::CubicUpdate (uint32_t segmentsAcked)
{
   if (m_segmentSize == 0) return;

   if (m_cWnd < m_ssThresh) {
       // Slow Start
       m_cWnd += m_segmentSize * segmentsAcked;
       return;
   }

   // Congestion Avoidance
   double t = (Simulator::Now () - m_epochStart).GetSeconds ();
   double w_cubic_target_segs = m_cubicC * std::pow (t - m_k, 3.0) + m_wLastMax;
   uint32_t w_cubic_target_bytes = (uint32_t)(w_cubic_target_segs * m_segmentSize);

   if (w_cubic_target_bytes < m_cWnd) w_cubic_target_bytes = m_cWnd;

   if (m_cWnd < w_cubic_target_bytes) {
       double diff = w_cubic_target_bytes - m_cWnd;
       double incr = (m_segmentSize * diff) / m_cWnd;
       if (incr > m_segmentSize) incr = m_segmentSize;
       if (incr < 1.0) incr = 1.0;

       m_cWndCnt += incr;
       if (m_cWndCnt >= 1.0) {
           uint32_t bytesToAdd = (uint32_t)m_cWndCnt;
           m_cWnd += bytesToAdd;
           m_cWndCnt -= bytesToAdd;
       }
   }
   if (m_cWnd > m_maxWinSize) m_cWnd = m_maxWinSize;
}

void TcpSocketBase::CubicReduce (void)
{
   if (m_segmentSize == 0) return;

   m_wLastMax = m_cWnd / m_segmentSize;
   if (m_wLastMax < 2) m_wLastMax = 2;

   m_cWnd = (uint32_t)(m_cWnd * m_beta);
   if (m_cWnd < 2 * m_segmentSize) m_cWnd = 2 * m_segmentSize;
   m_ssThresh = m_cWnd;

   double w_current_segs = (double)m_cWnd / m_segmentSize;
   double diff = m_wLastMax - w_current_segs;
   if (diff < 0) diff = 0;
   m_k = std::cbrt (diff / m_cubicC);
   m_epochStart = Simulator::Now ();
}

// Implement formerly pure virtuals
void TcpSocketBase::SetSSThresh (uint32_t threshold) { m_ssThresh = threshold; }
uint32_t TcpSocketBase::GetSSThresh (void) const { return m_ssThresh; }
void TcpSocketBase::SetInitialCwnd (uint32_t cwnd) { m_InitialCwndTCP = cwnd; }
uint32_t TcpSocketBase::GetInitialCwnd (void) const { return m_InitialCwndTCP; }

// Clone for Fork
Ptr<TcpSocketBase> TcpSocketBase::Fork (void)
{
 return CopyObject<TcpSocketBase> (this);
}

// Handle Duplicate ACKs
void TcpSocketBase::DupAck (const TcpHeader& t, uint32_t count)
{
   if (count == 3) {
       NS_LOG_INFO ("Triple Duplicate ACK. Fast Retransmit.");
       CubicReduce ();
       Retransmit ();
   }
}

// Handle ECN Cwnd Reduction
void TcpSocketBase::HalveCwnd (void)
{
   CubicReduce ();
}

// -------------------------------------------------------------------------
// Helper Implementation
// -------------------------------------------------------------------------

int TcpSocketBase::SetupCallback (void)
{
 if (m_endPoint == 0 && m_endPoint6 == 0) return -1;
 if (m_endPoint != 0) {
     m_endPoint->SetRxCallback (MakeCallback (&TcpSocketBase::ForwardUp, Ptr<TcpSocketBase> (this)));
     m_endPoint->SetIcmpCallback (MakeCallback (&TcpSocketBase::ForwardIcmp, Ptr<TcpSocketBase> (this)));
     m_endPoint->SetDestroyCallback (MakeCallback (&TcpSocketBase::Destroy, Ptr<TcpSocketBase> (this)));
 }
 if (m_endPoint6 != 0) {
     m_endPoint6->SetRxCallback (MakeCallback (&TcpSocketBase::ForwardUp6, Ptr<TcpSocketBase> (this)));
     m_endPoint6->SetIcmpCallback (MakeCallback (&TcpSocketBase::ForwardIcmp6, Ptr<TcpSocketBase> (this)));
     m_endPoint6->SetDestroyCallback (MakeCallback (&TcpSocketBase::Destroy6, Ptr<TcpSocketBase> (this)));
 }
 return 0;
}

int TcpSocketBase::DoConnect (void)
{
 if (m_state == CLOSED || m_state == LISTEN || m_state == SYN_SENT || m_state == LAST_ACK || m_state == CLOSE_WAIT) {
     SendEmptyPacket (TcpHeader::SYN);
     m_state = SYN_SENT;
 } else if (m_state != TIME_WAIT) {
     SendRST ();
     CloseAndNotify ();
 }
 return 0;
}

int TcpSocketBase::DoClose (void)
{
 switch (m_state) {
   case SYN_RCVD:
   case ESTABLISHED: SendEmptyPacket (TcpHeader::FIN); m_state = FIN_WAIT_1; break;
   case CLOSE_WAIT: SendEmptyPacket (TcpHeader::FIN | TcpHeader::ACK); m_state = LAST_ACK; break;
   case SYN_SENT:
   case CLOSING: SendRST (); CloseAndNotify (); break;
   case LISTEN:
   case LAST_ACK: CloseAndNotify (); break;
   default: break;
 }
 return 0;
}

void TcpSocketBase::CloseAndNotify (void)
{
 if (!m_closeNotified) NotifyNormalClose ();
 m_closeNotified = true;
 CancelAllTimers ();
 m_state = CLOSED;
 DeallocateEndPoint ();
}

bool TcpSocketBase::OutOfRange (SequenceNumber32 head, SequenceNumber32 tail) const
{
 if (m_state == LISTEN || m_state == SYN_SENT || m_state == SYN_RCVD) return false;
 if (m_state == LAST_ACK || m_state == CLOSING || m_state == CLOSE_WAIT) return (m_rxBuffer.NextRxSequence () != head);
 return (tail < m_rxBuffer.NextRxSequence () || m_rxBuffer.MaxRxSequence () <= head);
}

void TcpSocketBase::ForwardUp (Ptr<Packet> packet, Ipv4Header header, uint16_t port, Ptr<Ipv4Interface> incomingInterface)
{ DoForwardUp (packet, header, port, incomingInterface); }
void TcpSocketBase::ForwardUp6 (Ptr<Packet> packet, Ipv6Header header, uint16_t port)
{ DoForwardUp (packet, header, port); }

void TcpSocketBase::ForwardIcmp (Ipv4Address icmpSource, uint8_t icmpTtl, uint8_t icmpType, uint8_t icmpCode, uint32_t icmpInfo)
{ if (!m_icmpCallback.IsNull ()) m_icmpCallback (icmpSource, icmpTtl, icmpType, icmpCode, icmpInfo); }
void TcpSocketBase::ForwardIcmp6 (Ipv6Address icmpSource, uint8_t icmpTtl, uint8_t icmpType, uint8_t icmpCode, uint32_t icmpInfo)
{ if (!m_icmpCallback6.IsNull ()) m_icmpCallback6 (icmpSource, icmpTtl, icmpType, icmpCode, icmpInfo); }

void TcpSocketBase::DoForwardUp (Ptr<Packet> packet, Ipv4Header header, uint16_t port, Ptr<Ipv4Interface> incomingInterface)
{
 Address fromAddress = InetSocketAddress (header.GetSource (), port);
 Address toAddress = InetSocketAddress (header.GetDestination (), m_endPoint->GetLocalPort ());
 TcpHeader tcpHeader;
 packet->RemoveHeader (tcpHeader);
 if (tcpHeader.GetFlags () & TcpHeader::ACK) EstimateRtt (tcpHeader);
 ReadOptions (tcpHeader);
 
 if (m_EcnState & ECN_CONN) {
      // ... (ECN Logic simplified/preserved) ...
      if ((header.GetEcn () == Ipv4Header::CE)) {
          m_EcnState |= ECN_TX_ECHO;
          if (m_DCTCP) { m_EcnTransition = true; m_delAckCount = m_delAckMaxCount; }
      }
 }

 m_rWnd = tcpHeader.GetWindowSize ();
 if (packet->GetSize () && OutOfRange (tcpHeader.GetSequenceNumber (), tcpHeader.GetSequenceNumber () + packet->GetSize ())) {
     if (m_state == ESTABLISHED && !(tcpHeader.GetFlags () & TcpHeader::RST)) SendEmptyPacket (TcpHeader::ACK);
     return;
 }

 switch (m_state) {
   case ESTABLISHED: ProcessEstablished (packet, tcpHeader); break;
   case LISTEN: ProcessListen (packet, tcpHeader, fromAddress, toAddress); break;
   case CLOSED:
      if ((tcpHeader.GetFlags () & ~(TcpHeader::PSH | TcpHeader::URG | TcpHeader::CWR | TcpHeader::ECE)) != TcpHeader::RST) {
        TcpHeader h; h.SetFlags (TcpHeader::RST); h.SetSequenceNumber (m_nextTxSequence); h.SetAckNumber (m_rxBuffer.NextRxSequence ());
        h.SetSourcePort (tcpHeader.GetDestinationPort ()); h.SetDestinationPort (tcpHeader.GetSourcePort ());
        m_tcp->SendPacket (Create<Packet> (), h, header.GetDestination (), header.GetSource (), header.GetTos (), m_boundnetdevice);
      }
      break;
   case SYN_SENT: ProcessSynSent (packet, tcpHeader); break;
   case SYN_RCVD: ProcessSynRcvd (packet, tcpHeader, fromAddress, toAddress); break;
   case FIN_WAIT_1: case FIN_WAIT_2: case CLOSE_WAIT: ProcessWait (packet, tcpHeader); break;
   case CLOSING: ProcessClosing (packet, tcpHeader); break;
   case LAST_ACK: ProcessLastAck (packet, tcpHeader); break;
   default: break;
 }
}

void TcpSocketBase::DoForwardUp (Ptr<Packet> packet, Ipv6Header header, uint16_t port)
{
 // Similar logic for IPv6, omitted for brevity but structurally identical to IPv4
 // ... (IPv6 Implementation) ...
 // Minimal placeholder to allow compilation if called
 TcpHeader tcpHeader;
 packet->RemoveHeader (tcpHeader);
 if (tcpHeader.GetFlags () & TcpHeader::ACK) EstimateRtt (tcpHeader);
 m_rWnd = tcpHeader.GetWindowSize ();
}

void TcpSocketBase::ProcessEstablished (Ptr<Packet> packet, const TcpHeader& tcpHeader)
{
 uint16_t tcpflags = tcpHeader.GetFlags () & ~(TcpHeader::PSH | TcpHeader::URG | TcpHeader::CWR | TcpHeader::ECE);
 if (tcpflags == TcpHeader::ACK) ReceivedAck (packet, tcpHeader);
 else if (tcpflags == TcpHeader::FIN || tcpflags == (TcpHeader::FIN | TcpHeader::ACK)) PeerClose (packet, tcpHeader);
 else if (tcpflags == 0) {
     ReceivedData (packet, tcpHeader);
     if (m_rxBuffer.Finished ()) PeerClose (packet, tcpHeader);
 }
}

void TcpSocketBase::ReceivedAck (Ptr<Packet> packet, const TcpHeader& tcpHeader)
{
 if (0 == (tcpHeader.GetFlags () & TcpHeader::ACK)) return;
 if (tcpHeader.GetAckNumber () == m_txBuffer.HeadSequence ()) {
     if (tcpHeader.GetAckNumber () < m_nextTxSequence && packet->GetSize() == 0)
        DupAck (tcpHeader, ++m_dupAckCount);
 } else if (tcpHeader.GetAckNumber () > m_txBuffer.HeadSequence ()) {
     // New ACK - CUBIC UPDATE
     uint32_t ackedBytes = tcpHeader.GetAckNumber () - m_txBuffer.HeadSequence ();
     uint32_t ackedSegs = (m_segmentSize > 0) ? ackedBytes / m_segmentSize : 0;
     if (ackedSegs == 0 && ackedBytes > 0) ackedSegs = 1;
     CubicUpdate (ackedSegs);

     NewAck (tcpHeader.GetAckNumber ());
     m_dupAckCount = 0;
 }
 if (packet->GetSize () > 0) ReceivedData (packet, tcpHeader);
}

void TcpSocketBase::ProcessListen (Ptr<Packet> packet, const TcpHeader& tcpHeader, const Address& fromAddress, const Address& toAddress)
{
 if ((tcpHeader.GetFlags () & ~(TcpHeader::PSH | TcpHeader::URG | TcpHeader::CWR | TcpHeader::ECE)) != TcpHeader::SYN) return;
 if (!NotifyConnectionRequest (fromAddress)) return;
 
 Ptr<TcpSocketBase> newSock = Fork (); // Calls the local Fork implementation
 Simulator::ScheduleNow (&TcpSocketBase::CompleteFork, newSock, packet, tcpHeader, fromAddress, toAddress);
}

void TcpSocketBase::ProcessSynSent (Ptr<Packet> packet, const TcpHeader& tcpHeader)
{
 uint16_t tcpflags = tcpHeader.GetFlags () & ~(TcpHeader::PSH | TcpHeader::URG | TcpHeader::CWR | TcpHeader::ECE);
 if (tcpflags == (TcpHeader::SYN | TcpHeader::ACK) && m_nextTxSequence + SequenceNumber32 (1) == tcpHeader.GetAckNumber ()) {
     m_state = ESTABLISHED;
     m_connected = true;
     m_retxEvent.Cancel ();
     m_rxBuffer.SetNextRxSequence (tcpHeader.GetSequenceNumber () + SequenceNumber32 (1));
     m_highTxMark = ++m_nextTxSequence;
     m_txBuffer.SetHeadSequence (m_nextTxSequence);
     
     // Init Cwnd
     if (m_segmentSize > 0) m_cWnd = m_InitialCwndTCP * m_segmentSize;
     else m_cWnd = 536;
     m_epochStart = Simulator::Now();

     SendEmptyPacket (TcpHeader::ACK);
     SendPendingData (m_connected);
     Simulator::ScheduleNow (&TcpSocketBase::ConnectionSucceeded, this);
 }
}

void TcpSocketBase::ProcessSynRcvd (Ptr<Packet> packet, const TcpHeader& tcpHeader, const Address& fromAddress, const Address& toAddress)
{
  // Simplified logic
  uint16_t tcpflags = tcpHeader.GetFlags ();
  if (tcpflags == TcpHeader::ACK && m_nextTxSequence + SequenceNumber32 (1) == tcpHeader.GetAckNumber ()) {
      m_state = ESTABLISHED;
      m_connected = true;
      m_retxEvent.Cancel ();
      m_highTxMark = ++m_nextTxSequence;
      m_txBuffer.SetHeadSequence (m_nextTxSequence);
      
      if (m_endPoint) m_endPoint->SetPeer (InetSocketAddress::ConvertFrom (fromAddress).GetIpv4 (), InetSocketAddress::ConvertFrom (fromAddress).GetPort ());
      
      ReceivedAck (packet, tcpHeader);
      NotifyNewConnectionCreated (this, fromAddress);
      if (GetTxAvailable () > 0) NotifySend (GetTxAvailable ());
  }
}

void TcpSocketBase::ProcessWait (Ptr<Packet> packet, const TcpHeader& tcpHeader)
{
  if (packet->GetSize () > 0 && !(tcpHeader.GetFlags () & TcpHeader::ACK)) ReceivedData (packet, tcpHeader);
  else if (tcpHeader.GetFlags () & TcpHeader::ACK) {
      ReceivedAck (packet, tcpHeader);
      if (m_state == FIN_WAIT_1 && m_txBuffer.Size () == 0 && tcpHeader.GetAckNumber () == m_highTxMark + SequenceNumber32 (1)) m_state = FIN_WAIT_2;
  }
  if (tcpHeader.GetFlags () & TcpHeader::FIN) {
      m_rxBuffer.SetFinSequence (tcpHeader.GetSequenceNumber ());
      if ((m_state == FIN_WAIT_1 || m_state == FIN_WAIT_2) && m_rxBuffer.Finished ()) {
          if (m_state == FIN_WAIT_1) { m_state = CLOSING; TimeWait (); }
          else if (m_state == FIN_WAIT_2) TimeWait ();
          SendEmptyPacket (TcpHeader::ACK);
      }
  }
}

void TcpSocketBase::ProcessClosing (Ptr<Packet> packet, const TcpHeader& tcpHeader)
{
  if (tcpHeader.GetFlags () == TcpHeader::ACK && tcpHeader.GetSequenceNumber () == m_rxBuffer.NextRxSequence ()) TimeWait ();
}

void TcpSocketBase::ProcessLastAck (Ptr<Packet> packet, const TcpHeader& tcpHeader)
{
  if (tcpHeader.GetFlags () == TcpHeader::ACK && tcpHeader.GetSequenceNumber () == m_rxBuffer.NextRxSequence ()) CloseAndNotify ();
}

void TcpSocketBase::PeerClose (Ptr<Packet> p, const TcpHeader& tcpHeader)
{
  if (tcpHeader.GetSequenceNumber () < m_rxBuffer.NextRxSequence ()) return;
  m_rxBuffer.SetFinSequence (tcpHeader.GetSequenceNumber () + SequenceNumber32 (p->GetSize ()));
  if (p->GetSize ()) ReceivedData (p, tcpHeader);
  if (!m_rxBuffer.Finished ()) return;
  DoPeerClose ();
}

void TcpSocketBase::DoPeerClose (void)
{
  m_state = CLOSE_WAIT;
  if (!m_closeNotified) { NotifyNormalClose (); m_closeNotified = true; }
  if (m_shutdownSend) Close ();
  else SendEmptyPacket (TcpHeader::ACK);
}

void TcpSocketBase::Destroy (void) { m_endPoint = 0; CancelAllTimers (); }
void TcpSocketBase::Destroy6 (void) { m_endPoint6 = 0; CancelAllTimers (); }

void TcpSocketBase::SendEmptyPacket (uint16_t flags)
{
 Ptr<Packet> p = Create<Packet> ();
 TcpHeader header;
 header.SetFlags (flags);
 header.SetSequenceNumber (m_nextTxSequence);
 header.SetAckNumber (m_rxBuffer.NextRxSequence ());
 if (m_endPoint != 0) { header.SetSourcePort (m_endPoint->GetLocalPort ()); header.SetDestinationPort (m_endPoint->GetPeerPort ()); }
 else { header.SetSourcePort (m_endPoint6->GetLocalPort ()); header.SetDestinationPort (m_endPoint6->GetPeerPort ()); }
 header.SetWindowSize (AdvertisedWindowSize ());
 AddOptions (header);
 m_rto = m_rtt->RetransmitTimeout ();
 
 if (m_endPoint != 0) m_tcp->SendPacket (p, header, m_endPoint->GetLocalAddress (), m_endPoint->GetPeerAddress (), 0, m_boundnetdevice);
 else m_tcp->SendPacket (p, header, m_endPoint6->GetLocalAddress (), m_endPoint6->GetPeerAddress (), 0, m_boundnetdevice);

 if (flags & TcpHeader::ACK) { m_delAckEvent.Cancel (); m_delAckCount = 0; }
 if (m_retxEvent.IsExpired () && (flags & (TcpHeader::SYN | TcpHeader::FIN))) m_retxEvent = Simulator::Schedule (m_rto, &TcpSocketBase::SendEmptyPacket, this, flags);
}

void TcpSocketBase::SendRST (void) { SendEmptyPacket (TcpHeader::RST); NotifyErrorClose (); }
void TcpSocketBase::DeallocateEndPoint (void) { CancelAllTimers (); if (m_endPoint) { m_tcp->DeAllocate (m_endPoint); m_endPoint = 0; } if (m_endPoint6) { m_tcp->DeAllocate (m_endPoint6); m_endPoint6 = 0; } }

int TcpSocketBase::SetupEndpoint ()
{
 Ptr<Ipv4> ipv4 = m_node->GetObject<Ipv4> ();
 Ipv4Header header; header.SetDestination (m_endPoint->GetPeerAddress ());
 Socket::SocketErrno errno_;
 Ptr<Ipv4Route> route = ipv4->GetRoutingProtocol ()->RouteOutput (Ptr<Packet> (), header, m_boundnetdevice, errno_);
 if (route == 0) { m_errno = errno_; return -1; }
 m_endPoint->SetLocalAddress (route->GetSource ());
 return 0;
}

int TcpSocketBase::SetupEndpoint6 ()
{
 Ptr<Ipv6L3Protocol> ipv6 = m_node->GetObject<Ipv6L3Protocol> ();
 Ipv6Header header; header.SetDestinationAddress (m_endPoint6->GetPeerAddress ());
 Socket::SocketErrno errno_;
 Ptr<Ipv6Route> route = ipv6->GetRoutingProtocol ()->RouteOutput (Ptr<Packet> (), header, m_boundnetdevice, errno_);
 if (route == 0) { m_errno = errno_; return -1; }
 m_endPoint6->SetLocalAddress (route->GetSource ());
 return 0;
}

void TcpSocketBase::CompleteFork (Ptr<Packet> p, const TcpHeader& h, const Address& fromAddress, const Address& toAddress)
{
 if (InetSocketAddress::IsMatchingType (toAddress)) {
     m_endPoint = m_tcp->Allocate (InetSocketAddress::ConvertFrom (toAddress).GetIpv4 (), InetSocketAddress::ConvertFrom (toAddress).GetPort (), InetSocketAddress::ConvertFrom (fromAddress).GetIpv4 (), InetSocketAddress::ConvertFrom (fromAddress).GetPort ());
     m_endPoint6 = 0;
 }
 m_tcp->m_sockets.push_back (this);
 m_state = SYN_RCVD;
 m_cnCount = m_cnRetries;
 SetupCallback ();
 m_rxBuffer.SetNextRxSequence (h.GetSequenceNumber () + SequenceNumber32 (1));
 SendEmptyPacket (TcpHeader::SYN | TcpHeader::ACK);
}

void TcpSocketBase::ConnectionSucceeded ()
{
 NotifyConnectionSucceeded ();
 if (GetTxAvailable () > 0) NotifySend (GetTxAvailable ());
}

uint32_t TcpSocketBase::SendDataPacket (SequenceNumber32 seq, uint32_t maxSize, bool withAck)
{
 Ptr<Packet> p = m_txBuffer.CopyFromSequence (maxSize, seq);
 uint32_t sz = p->GetSize ();
 uint16_t flags = withAck ? TcpHeader::ACK : 0;
 
 if (m_closeOnEmpty && m_txBuffer.SizeFromSequence (seq + SequenceNumber32 (sz)) == 0) {
     flags |= TcpHeader::FIN;
     if (m_state == ESTABLISHED) m_state = FIN_WAIT_1;
     else if (m_state == CLOSE_WAIT) m_state = LAST_ACK;
 }
 
 TcpHeader header;
 header.SetFlags (flags);
 header.SetSequenceNumber (seq);
 header.SetAckNumber (m_rxBuffer.NextRxSequence ());
 if (m_endPoint) { header.SetSourcePort (m_endPoint->GetLocalPort ()); header.SetDestinationPort (m_endPoint->GetPeerPort ()); }
 else { header.SetSourcePort (m_endPoint6->GetLocalPort ()); header.SetDestinationPort (m_endPoint6->GetPeerPort ()); }
 header.SetWindowSize (AdvertisedWindowSize ());
 AddOptions (header);

 if (m_retxEvent.IsExpired ()) {
     m_rto = (m_userRto != Time(0)) ? m_userRto : m_rtt->RetransmitTimeout ();
     m_retxEvent = Simulator::Schedule (m_rto, &TcpSocketBase::ReTxTimeout, this);
 }
 
 if (m_endPoint) m_tcp->SendPacket (p, header, m_endPoint->GetLocalAddress (), m_endPoint->GetPeerAddress (), 0, m_boundnetdevice);
 else m_tcp->SendPacket (p, header, m_endPoint6->GetLocalAddress (), m_endPoint6->GetPeerAddress (), 0, m_boundnetdevice);
 
 m_rtt->SentSeq (seq, sz);
 if (seq == m_nextTxSequence) Simulator::ScheduleNow (&TcpSocketBase::NotifyDataSent, this, sz);
 m_highTxMark = std::max (seq + sz, m_highTxMark.Get ());
 return sz;
}

bool TcpSocketBase::SendPendingData (bool withAck)
{
 if (m_txBuffer.Size () == 0) return false;
 uint32_t nPacketsSent = 0;
 while (m_txBuffer.SizeFromSequence (m_nextTxSequence)) {
     uint32_t w = AvailableWindow ();
     if (m_shutdownSend) return false;
     if (w < m_segmentSize && m_txBuffer.SizeFromSequence (m_nextTxSequence) > w) break;
     if (!m_noDelay && UnAckDataCount () > 0 && m_txBuffer.SizeFromSequence (m_nextTxSequence) < m_segmentSize) break;
     uint32_t s = std::min (w, m_segmentSize);
     uint32_t sz = SendDataPacket (m_nextTxSequence, s, withAck);
     if (sz > 0) { nPacketsSent++; m_nextTxSequence += sz; }
     else break;
 }
 return (nPacketsSent > 0);
}

uint32_t TcpSocketBase::UnAckDataCount () { return m_nextTxSequence.Get () - m_txBuffer.HeadSequence (); }
uint32_t TcpSocketBase::BytesInFlight () { return m_highTxMark.Get () - m_txBuffer.HeadSequence (); }
uint32_t TcpSocketBase::Window () { return m_rWnd; }

// Modified AvailableWindow for CUBIC
uint32_t TcpSocketBase::AvailableWindow ()
{
 uint32_t unack = UnAckDataCount ();
 uint32_t effWin = m_rWnd;
 if (m_cWnd > 0) effWin = std::min ((uint32_t)m_rWnd, (uint32_t)m_cWnd);
 return (effWin < unack) ? 0 : (effWin - unack);
}

uint16_t TcpSocketBase::AdvertisedWindowSize ()
{
 return std::min (m_rxBuffer.MaxBufferSize () - m_rxBuffer.Size (), (uint32_t)m_maxWinSize);
}

void TcpSocketBase::ReceivedData (Ptr<Packet> p, const TcpHeader& tcpHeader)
{
 SequenceNumber32 expectedSeq = m_rxBuffer.NextRxSequence ();
 if (!m_rxBuffer.Add (p, tcpHeader)) { SendEmptyPacket (TcpHeader::ACK); return; }
 if (m_rxBuffer.Size () > m_rxBuffer.Available () || m_rxBuffer.NextRxSequence () > expectedSeq + p->GetSize ()) SendEmptyPacket (TcpHeader::ACK);
 else {
     if (++m_delAckCount >= m_delAckMaxCount) { m_delAckEvent.Cancel (); m_delAckCount = 0; SendEmptyPacket (TcpHeader::ACK); }
     else if (m_delAckEvent.IsExpired ()) m_delAckEvent = Simulator::Schedule (m_delAckTimeout, &TcpSocketBase::DelAckTimeout, this);
 }
 if (expectedSeq < m_rxBuffer.NextRxSequence ()) {
     if (!m_shutdownRecv) NotifyDataRecv ();
     if (m_rxBuffer.Finished () && (tcpHeader.GetFlags () & TcpHeader::FIN) == 0) DoPeerClose ();
 }
}

void TcpSocketBase::EstimateRtt (const TcpHeader& tcpHeader)
{
 Time nextRtt = m_rtt->AckSeq (tcpHeader.GetAckNumber (), (tcpHeader.GetFlags() == (TcpHeader::ECE | TcpHeader::ACK)));
 if(nextRtt != 0) m_lastRtt = nextRtt;
}

void TcpSocketBase::NewAck (SequenceNumber32 const& ack)
{
 if (m_state != SYN_RCVD) {
     m_retxEvent.Cancel ();
     m_rto = (m_userRto != Time(0)) ? m_userRto : m_rtt->RetransmitTimeout ();
     m_retxEvent = Simulator::Schedule (m_rto, &TcpSocketBase::ReTxTimeout, this);
 }
 if (m_rWnd.Get () == 0 && m_persistEvent.IsExpired ()) {
     m_retxEvent.Cancel ();
     m_persistEvent = Simulator::Schedule (m_persistTimeout, &TcpSocketBase::PersistTimeout, this);
 }
 m_txBuffer.DiscardUpTo (ack);
 if (GetTxAvailable () > 0) NotifySend (GetTxAvailable ());
 if (ack > m_nextTxSequence) m_nextTxSequence = ack;
 if (m_txBuffer.Size () == 0 && m_state != FIN_WAIT_1 && m_state != CLOSING) m_retxEvent.Cancel ();
 SendPendingData (m_connected);
}

void TcpSocketBase::ReTxTimeout ()
{
 if (m_state == CLOSED || m_state == TIME_WAIT) return;
 if (m_state <= ESTABLISHED && m_txBuffer.HeadSequence () >= m_highTxMark) return;

 // CUBIC RTO Logic: Reset
 if (m_segmentSize != 0) m_wLastMax = m_cWnd / m_segmentSize;
 if (m_wLastMax < 2) m_wLastMax = 2;
 m_cWnd = m_segmentSize;
 m_ssThresh = std::max (2 * m_segmentSize, (uint32_t)(m_wLastMax * m_segmentSize / 2));
 m_epochStart = Simulator::Now();
 m_k = 0;

 Retransmit ();
}

void TcpSocketBase::DelAckTimeout (void) { m_delAckCount = 0; SendEmptyPacket (TcpHeader::ACK); }
void TcpSocketBase::LastAckTimeout (void) { m_lastAckEvent.Cancel (); if (m_state == LAST_ACK) CloseAndNotify (); else m_closeNotified = true; }

void TcpSocketBase::PersistTimeout ()
{
 m_persistTimeout = std::min (Seconds (60), Time (2 * m_persistTimeout));
 Ptr<Packet> p = m_txBuffer.CopyFromSequence (1, m_nextTxSequence);
 TcpHeader tcpHeader;
 tcpHeader.SetSequenceNumber (m_nextTxSequence);
 tcpHeader.SetAckNumber (m_rxBuffer.NextRxSequence ());
 tcpHeader.SetWindowSize (AdvertisedWindowSize ());
 AddOptions (tcpHeader);
 if (m_endPoint) m_tcp->SendPacket (p, tcpHeader, m_endPoint->GetLocalAddress (), m_endPoint->GetPeerAddress (), 0, m_boundnetdevice);
 else m_tcp->SendPacket (p, tcpHeader, m_endPoint6->GetLocalAddress (), m_endPoint6->GetPeerAddress (), 0, m_boundnetdevice);
 m_persistEvent = Simulator::Schedule (m_persistTimeout, &TcpSocketBase::PersistTimeout, this);
}

void TcpSocketBase::Retransmit ()
{
 m_nextTxSequence = m_txBuffer.HeadSequence ();
 m_rtt->IncreaseMultiplier ();
 m_dupAckCount = 0;
 DoRetransmit ();
}

void TcpSocketBase::DoRetransmit ()
{
 if (m_state == SYN_SENT) { if (m_cnCount > 0) SendEmptyPacket (TcpHeader::SYN); else NotifyConnectionFailed (); return; }
 if (m_txBuffer.Size () == 0) { if (m_state == FIN_WAIT_1 || m_state == CLOSING) SendEmptyPacket (TcpHeader::FIN); return; }
 uint32_t sz = SendDataPacket (m_txBuffer.HeadSequence (), m_segmentSize, true);
 m_nextTxSequence = std::max (m_nextTxSequence.Get (), m_txBuffer.HeadSequence () + sz);
}

void TcpSocketBase::CancelAllTimers () { m_retxEvent.Cancel (); m_persistEvent.Cancel (); m_delAckEvent.Cancel (); m_lastAckEvent.Cancel (); m_timewaitEvent.Cancel (); }
void TcpSocketBase::TimeWait () { m_state = TIME_WAIT; CancelAllTimers (); m_timewaitEvent = Simulator::Schedule (Seconds (2 * m_msl), &TcpSocketBase::CloseAndNotify, this); }

void TcpSocketBase::SetSndBufSize (uint32_t size) { m_txBuffer.SetMaxBufferSize (size); }
uint32_t TcpSocketBase::GetSndBufSize (void) const { return m_txBuffer.MaxBufferSize (); }
void TcpSocketBase::SetRcvBufSize (uint32_t size) { m_rxBuffer.SetMaxBufferSize (size); }
uint32_t TcpSocketBase::GetRcvBufSize (void) const { return m_rxBuffer.MaxBufferSize (); }
void TcpSocketBase::SetSegSize (uint32_t size) { m_segmentSize = size; NS_ABORT_MSG_UNLESS (m_state == CLOSED, "Cannot change segment size dynamically."); }
uint32_t TcpSocketBase::GetSegSize (void) const { return m_segmentSize; }
void TcpSocketBase::SetConnTimeout (Time timeout) { m_cnTimeout = timeout; }
Time TcpSocketBase::GetConnTimeout (void) const { return m_cnTimeout; }
void TcpSocketBase::SetConnCount (uint32_t count) { m_cnRetries = count; }
uint32_t TcpSocketBase::GetConnCount (void) const { return m_cnRetries; }
void TcpSocketBase::SetDelAckTimeout (Time timeout) { m_delAckTimeout = timeout; }
Time TcpSocketBase::GetDelAckTimeout (void) const { return m_delAckTimeout; }
void TcpSocketBase::SetDelAckMaxCount (uint32_t count) { m_delAckMaxCount = count; }
uint32_t TcpSocketBase::GetDelAckMaxCount (void) const { return m_delAckMaxCount; }
void TcpSocketBase::SetTcpNoDelay (bool noDelay) { m_noDelay = noDelay; }
bool TcpSocketBase::GetTcpNoDelay (void) const { return m_noDelay; }
void TcpSocketBase::SetPersistTimeout (Time timeout) { m_persistTimeout = timeout; }
Time TcpSocketBase::GetPersistTimeout (void) const { return m_persistTimeout; }
bool TcpSocketBase::SetAllowBroadcast (bool allowBroadcast) { return (!allowBroadcast); }
bool TcpSocketBase::GetAllowBroadcast (void) const { return false; }
void TcpSocketBase::SetEcnCap (bool EcnCap) { m_ECN = EcnCap; }
bool TcpSocketBase::GetEcnCap (void) const { return m_ECN; }
void TcpSocketBase::ReadOptions (const TcpHeader&) {}
void TcpSocketBase::AddOptions (TcpHeader&) {}
void TcpSocketBase::SetDeadline (Time deadline) { m_deadline = deadline; }
Time TcpSocketBase::GetDeadline (void) const { return m_deadline; }
void TcpSocketBase::SetBytesToTx (uint64_t bytes) { m_bytesToTx = bytes; }
uint64_t TcpSocketBase::GetBytesToTx (void) const { return m_bytesToTx; }

} // namespace ns3