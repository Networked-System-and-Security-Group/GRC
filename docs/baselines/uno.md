# Uno: A One-Stop Solution for Inter- and Intra-Data Center Congestion Control and Reliable Connectivity

> Cleaned plain-text Markdown version.  
> Figures, most tables, author metadata, references, and artifact-evaluation appendix are omitted.  
> The mechanism sections are preserved close to the original wording where possible, with formatting cleaned for readability.

## Abstract

Cloud computing and AI workloads are driving unprecedented demand for efficient communication within and across datacenters. However, the coexistence of intra- and inter-datacenter traffic within datacenters, plus the disparity between the RTTs of intra- and inter-datacenter networks, complicates congestion management and traffic routing.

In particular, the faster congestion responses of intra-datacenter traffic can cause rate unfairness when competing with slower inter-datacenter flows. Additionally, inter-datacenter messages suffer from slow loss recovery and thus require reliability. Existing solutions overlook these challenges and handle inter- and intra-datacenter congestion with separate control loops or at different granularities.

Uno is proposed as a unified system for both inter- and intra-datacenter environments. It integrates a transport protocol for rapid congestion reaction and fair rate control with a load-balancing scheme that combines erasure coding and adaptive routing. The evaluation shows that Uno significantly improves the completion times of both inter- and intra-datacenter flows compared to state-of-the-art methods such as Gemini.

## 1. Introduction

With the growth of cloud computing, HPC, and AI workloads, efficient traffic routing and congestion-free communication inside and across datacenters are becoming increasingly important. Large-scale AI training is no longer always feasible inside a single datacenter; training jobs may span multiple clusters or datacenters. As a result, inter-datacenter WAN traffic and intra-datacenter traffic coexist and compete for resources.

Many congestion control protocols have been developed separately for intra-datacenter and inter-datacenter environments. However, treating these traffic classes as separate entities is insufficient because they coexist within datacenters. Efficient communication for one class must therefore be designed while considering the other.

The main difficulty comes from the inherent differences between datacenter networks and WANs. Inside a datacenter, cable lengths and propagation delays are small and mostly homogeneous. Across datacenters, WAN links are long, propagation delays are large, and paths may traverse different geographic routes. This introduces heterogeneous delays and additional failure risks.

Unlike datacenter networks, inter-datacenter WANs often make the completion time of even large messages latency-bound rather than throughput-bound. For intra-datacenter RTTs on the order of tens of microseconds, larger messages quickly become throughput-bound. For inter-datacenter RTTs on the order of milliseconds, completion time remains dominated by propagation delay across a much larger range of message sizes. This effect becomes stronger as link bandwidth increases.

This massive delay gap introduces several challenges:

1. **Diverse congestion feedback granularity.** The congestion feedback loop for inter-datacenter flows is significantly delayed compared with intra-datacenter traffic. When congestion signals arrive for inter-datacenter flows, the path may no longer be congested. The mismatch also makes it hard to maintain fairness between intra- and inter-datacenter flows sharing a bottleneck link.

2. **BDP heterogeneity.** Inter-datacenter bandwidth-delay product is much larger than intra-datacenter BDP because of long RTTs. Commodity switch buffers are much smaller than inter-datacenter BDP, especially in shallow-buffered commodity switches. Many congestion control algorithms assume switch buffers can hold at least a fraction of BDP; this assumption is realistic inside datacenters but unrealistic across datacenters.

3. **Inefficient loss handling.** Packet loss and retransmission significantly increase message completion time in latency-bound WANs. Even advanced loss detection mechanisms still take a long time because of large propagation delay. Efficient loss recovery is therefore necessary.

Existing solutions address only part of this space. BBR targets WAN traffic and requires a separate transport such as DCTCP for intra-datacenter traffic. Gemini provides window-based congestion control for both intra- and inter-datacenter communication, but its reaction granularity differs between the two environments, causing slow convergence to fairness and possible under-utilization. These techniques also suffer from inefficient loss handling for WAN traffic.

Uno addresses these limitations by tightly integrating congestion control, load balancing, and loss resiliency into a unified system.

## 2. Coexistence Among Inter- and Intra-Datacenter Traffic: Challenges and Opportunities

### 2.1 Diverse Congestion Feedback Granularity

A datacenter workload is typically composed of both intra-datacenter and inter-datacenter traffic. There is a large gap between the congestion feedback granularity of these flows because of the difference in propagation delay. For example, if intra-datacenter RTT is 10 microseconds and inter-datacenter RTT is 10 milliseconds, each inter-datacenter RTT corresponds to about 1000 intra-datacenter RTTs.

This means intra-datacenter flows can receive congestion signals far more frequently than inter-datacenter flows. Under mixed congestion, intra-datacenter flows adjust their rates more frequently, which can hurt flow-level fairness.

The delay gap can also cause under-utilization and queue oscillation. Inter-datacenter congestion feedback can arrive at senders long after actual congestion has been resolved by intra-datacenter flows reducing their rates. If inter-datacenter flows reduce their sending rate at that point, they can create long periods of under-utilization before ramping up again.

### 2.2 Heterogeneous Hot Spots

Commodity switches, especially those deployed in inter-datacenter WANs, limit the signals available for congestion detection. Packet loss, delay, and ECN are commonly used signals.

Relying only on packet loss and retransmission imposes extra latency because loss is triggered only when switch buffers are already highly congested.

With ECN, setting the marking threshold is difficult when inter- and intra-datacenter traffic are mixed. WAN switches may have different buffer capacities from datacenter switches, and inter-datacenter BDP is much larger than intra-datacenter BDP. Inter-datacenter traffic therefore requires larger ECN thresholds than local datacenter traffic.

With delay, it is difficult to distinguish inter-datacenter hot spots from intra-datacenter hot spots. Increased delay could mean severe congestion in a shallow-buffered intra-datacenter switch or minor congestion in a deep-buffered inter-datacenter switch.

### 2.3 BDP Heterogeneity

Most reactive congestion control protocols assume a minimum amount of available buffer capacity. For example, DCTCP requires buffer space to be at least a fraction of BDP. With 10 ms inter-datacenter RTT and 400 Gbps bandwidth, the required buffering can be far larger than the buffering available per port in modern switching fabrics.

This gap is likely to increase as network bandwidth grows faster than switch buffer size. Having buffers far smaller than BDP also makes it harder to assess congestion extent, because small changes in sending rate can lead to over-utilization or under-utilization.

Uno repurposes phantom queues, originally designed for low latency inside datacenters, for inter-datacenter communication so that the virtual queue can match the inter-datacenter BDP regardless of physical queue capacity.

### 2.4 Inefficient Loss Handling

Most messages crossing WAN links are bounded by propagation delay. A single packet loss can significantly increase delivery time because detecting a loss and retransmitting across datacenters is proportional to the large inter-datacenter RTT.

The paper reports measurements between pairs of cloud VMs in different North American regions. Losses were rare but still imposed significant extra latency. The measurements also showed that losses can be correlated within a small block of consecutive packets. This motivates a multi-link failure-resilient scheme rather than relying only on retransmission over one path.

## 3. Uno Design Goals

### 3.1 Unified Congestion Control Logic

In a congested network, there is a massive gap in the granularity at which transports such as Gemini react to congestion signals for inter- and intra-datacenter flows. This can potentially victimize intra-datacenter flows. At the same time, the scale of AI training tasks is exceeding the resources available in one datacenter, meaning that messages of the same importance can flow both within and across datacenters. Therefore, ensuring bandwidth fairness among inter- and intra-datacenter flows, as well as fast convergence to the bandwidth fair share, is critical.

Existing solutions either do not achieve bandwidth fairness because they separate congestion control for inter- and intra-datacenter flows, or they experience slow convergence because they react to inter- and intra-datacenter congestion at different granularities.

Uno deploys a unified control loop for both inter- and intra-datacenter traffic. This control loop guarantees fairness while reacting to congestion signals at the same granularity for both traffic classes. Uno also uses Quick Adapt: under extreme network congestion, indicated by a sharp drop in ACKed bytes, Uno dramatically reduces send rates to quickly resolve over-utilization.

### 3.2 Near-Zero Queuing

To ensure low latency, especially for small messages, without significantly under-utilizing the network, keeping switch buffers lightly occupied is essential. However, with empty queues, there is a serious chance of network under-utilization. To avoid this, ECN-based protocols typically keep some packets in the queue with small queue occupancy fluctuations around the ECN marking threshold.

However, doing so is challenging with inter-datacenter traffic in the picture, because inter-datacenter flows can easily overwhelm small commodity switches due to their large BDPs. To address this, Uno uses phantom queues: virtual queues with arbitrary sizes and drain rates that mimic physical queues. They increase occupancy on ingress and drain at a constant rate, typically slightly below the line rate.

Intuitively, phantom queues offer two advantages:

- early congestion signaling, due to lower drain rates;
- burst smoothing.

Phantom queues facilitate near-zero queuing because the physical queues can remain mostly empty while the virtual queue provides congestion feedback. This reduces flow completion times for short intra-datacenter messages while avoiding large under-utilization.

### 3.3 Reliability and Load Balancing

To mitigate the delay penalties induced by packet loss and retransmissions, Uno adopts Maximum Distance Separable erasure coding as a proactive countermeasure.

In this scheme, data is organized into distinct blocks, each composed of both original data packets and additional parity packets computed through MDS coding. This block represents the minimal unit of encoded data, ensuring that the original information can be fully recovered as long as a sufficient number of packets are received, even if some fail during transit.

Because packet losses are not purely random and may occur in correlated clusters, the redundancy introduced by MDS coding is crucial. It allows the system to tolerate minor burst losses without waiting for slow retransmission timeouts, thereby maintaining low latency across WAN links. This reduces recovery delays and improves resource utilization by minimizing unnecessary retransmissions.

Erasure coding alone does not solve every failure mode. If ECMP routing sends all packets in a block over a link that fails temporarily or permanently, all packets in that block may be lost until the routing table is updated. This makes reconstruction difficult. Uno therefore develops a custom load-balancing scheme to mitigate ECMP shortcomings, such as hash collisions, while also improving erasure-coding resilience.

## 4. Uno: A Unified System for Intra- and Inter-Datacenter Communication

Uno is a unified system that facilitates low-latency and fair communication in both intra- and inter-datacenter environments. It has two components:

1. **UnoCC**, the congestion control component.
2. **UnoRC**, the reliable connectivity component.

UnoCC is a window-based congestion control scheme for both intra- and inter-datacenter traffic. It uses Additive Increase Multiplicative Decrease window adjustment to ensure fair bandwidth sharing. To quickly converge to bandwidth fairness, UnoCC reacts to congestion signals at the same granularity for intra- and inter-datacenter flows.

UnoCC further employs Quick Adapt, which promptly reduces the congestion window under extreme congestion, indicated by a sharp drop in ACKed bytes. This quickly alleviates congestion and avoids persistent over-utilization.

To efficiently handle ECN marking in both inter- and intra-datacenter switch buffers, UnoCC is augmented with phantom queues: virtual queues with arbitrary sizes and drain rates that mimic physical ones. Delay is used to distinguish physical from phantom queue congestion.

UnoRC combines subflow-level load balancing with erasure coding for inter-datacenter flows to improve routing performance between datacenters and ensure loss resiliency. The key idea is to use erasure coding to maximize the chances of latency-bound messages being delivered correctly to the receiver. Uno sends a certain number of parity packets for every block. To further improve loss resiliency, Uno spreads packets of a single block across different paths, maximizing successful delivery probabilities even in the case of link failures.

Finally, Uno adaptively removes paths from routing options when they are identified as failed or congested. This can be detected either via a sender-based timeout or a NACK from the receiver.

## 4.1 UnoCC

UnoCC assumes three congestion states for the network:

1. **Uncongested**
2. **Congested**
3. **Extremely congested**

To cope with the first two states, UnoCC employs an AIMD rate control mechanism that uses ECN as the congestion signal. UnoCC also uses relative delay, defined as measured RTT minus base RTT, but only to differentiate between phantom and physical queue congestion events. The measured RTT is a packet's observed RTT, while the base RTT is the minimum RTT in an uncongested network.

Additionally, UnoCC deploys Quick Adapt to facilitate fast reaction to extreme network congestion.

### Algorithm 1: UnoCC Control Loop

```text
procedure OnAck
    if ECN not marked then
        # Uncongested network: Additive Increase
        cwnd = cwnd + alpha * bytes_acked / cwnd
    end if
end procedure

procedure OnEpoch
    if ecn_fraction > 0 then
        # Congested network: Multiplicative Decrease
        if delay == 0 then
            # Congestion in phantom queues
            MD_scale = MD_scale * 0.3
        else
            # Congestion in physical queues
            MD_scale = 1
        end if
        cwnd = cwnd * (1 - MD_ECN * MD_scale)
    end if
end procedure

procedure OnQA
    if bytes_acked_in_qa < cwnd * beta then
        # Very congested network: Quick Adapt
        cwnd = bytes_acked_in_qa
    end if
end procedure
```

### 4.1.1 Additive Increase and Multiplicative Decrease

When an ACK packet arrives and it is not ECN marked, UnoCC increases the congestion window by:

```text
alpha * bytes_acked / cwnd
```

Here, `alpha` is the additive-increase factor and is set as a fraction of BDP. Thus, after one RTT in an uncongested network, the congestion window increases by `alpha`. The value of `alpha` should be scaled depending on the queue size and the degree of incast that a network can support without losses in the steady state.

Unlike additive increase, which is applied per ACK, multiplicative decrease is applied at most once per epoch. Upon receiving the first ACK of the flow, UnoCC stores an epoch activation time for that flow. When a packet is sent or re-sent, UnoCC stores its send or re-send time. An epoch terminates when an ACK is received for a data packet whose send time is greater than or equal to the epoch activation time.

Upon epoch termination, UnoCC increases the epoch activation time by an epoch period, a time span proportional to the packet's RTT, and reactivates the epoch. This ensures that enough packets are received before deciding to apply multiplicative decrease, giving the sender a better grasp of the network condition.

UnoCC considers an epoch period congested if any packet has been ECN-marked during the epoch. When applying multiplicative decrease, UnoCC computes the multiplicative-decrease factor using an EWMA of the fraction of ECN-marked packets across epochs and a user-set constant that determines the strength of the reaction to congested epochs.

UnoCC selects its additive-increase and multiplicative-decrease factors similarly to Gemini to achieve guaranteed convergence to fairness. However, Gemini experiences slow convergence because it reacts to congestion signals at different granularities for inter- and intra-datacenter traffic.

UnoCC instead reacts to congestion signals at the same granularity for both traffic types. This better captures congestion events inside and across datacenters and significantly improves convergence speed toward fair bandwidth sharing. The same epoch period, set based on intra-datacenter RTT, is used for both inter- and intra-datacenter flows.

Finally, since phantom queues have slower drain rates than physical queues, they can signal the sender to slow down more than needed and for too long. To avoid this, if UnoCC detects that the physical queues are empty and phantom queues are congested, meaning packets are ECN marked but packet delays indicate no physical congestion, it employs a gentler reduction by scaling down the multiplicative-decrease factor.

### 4.1.2 Quick Adapt

Events such as the arrival of new flows or incast can create extreme network congestion. Solely relying on multiplicative decrease to resolve such congestion is slow and can significantly hurt latency. UnoCC therefore deploys Quick Adapt.

Once every RTT, UnoCC evaluates whether the network is extremely congested by checking whether the number of ACKed bytes is considerably low, specifically less than:

```text
cwnd * beta
```

Here, `beta` is the user-set Quick Adapt ratio. If the network is deemed extremely congested, the congestion window is sharply decreased to the number of bytes ACKed during the Quick Adapt period. This quickly matches the sender's window to the network's instantaneous capacity.

To avoid over-reacting to congestion, after triggering Quick Adapt, UnoCC skips one RTT without triggering any further Quick Adapt or multiplicative-decrease actions.

### 4.1.3 Phantom Queues

Efficiently setting ECN marking thresholds for a mixture of inter- and intra-datacenter traffic is challenging because intra- and inter-datacenter switch buffer capacities differ. Using only shallow buffers everywhere can also lead to oscillations for modern congestion controls because of large inter-datacenter BDPs.

Uno uses phantom queues in conjunction with UnoCC. The phantom queue occupancy increases every time a new packet is enqueued in the physical queue and decreases at a constant drain rate, which is a fraction of the link bandwidth. A phantom queue can be implemented using a counter that tracks its occupancy.

Using phantom queues enables packets to be correctly marked with ECN signals regardless of the physical queue's capacity. By properly setting the drain rate of phantom queues, the system can achieve near-zero queuing in physical queues at steady state. Because phantom queues drain more slowly than physical queues, physical queues become empty before phantom queue occupancy reaches zero.

This is important because it gives extra bandwidth headroom, especially for small and latency-sensitive intra-datacenter flows. Phantom queues can potentially penalize large throughput-intensive flows. However, by setting the phantom queue drain rate only slightly lower than the physical queue drain rate, for example 10% lower, Uno avoids victimizing large flows while benefiting small flows.

## 4.2 UnoRC

UnoRC has two components:

1. **Erasure coding**, which enhances reliability, especially under failure.
2. **Subflow-level load balancing**, called UnoLB.

### Erasure Coding

For reliability, each inter-datacenter message is divided into blocks of `n` packets, with `x` data packets and `y` parity packets. A block can be reconstructed if at most `y` out of `n` packets are lost.

Upon receiving the first packet of a block, the receiver starts a timer set to the estimated maximum queuing and transmission delay. If the timer expires before enough packets arrive, a NACK is sent to the sender requesting retransmission of the missing block.

UnoRC applies erasure coding only to inter-datacenter traffic because recovery delays are long in this environment. While erasure coding adds fixed overhead, it reduces packet loss and improves completion times under failure and congestion events, which is crucial in latency-bound scenarios.

### Load Balancing: UnoLB

UnoLB uses `n` subflows, and each subflow is assigned its own path. This can be done through source-based assignment or by changing the source port value for ECMP hashing. By itself, this action is similar in spirit to multipath transport and improves performance by reducing hash collisions.

To integrate UnoLB with erasure coding, Uno spreads the packets of a block across `n` subflows. This increases resilience to link failures. UnoRC also switches away from bad paths when it detects extreme congestion on them.

Upon receiving a NACK, indicating an unrecoverable block, or when a sender timeout occurs, possibly due to lost NACKs caused by failures or corruption, UnoRC reroutes affected flows by randomly selecting a subflow that has recently received ACKs. This reduces the likelihood of switching to another congested or failed path.

### Algorithm 2: UnoLB Pseudocode

```text
procedure onSend(packet)
    packet[header.source_port] = subflow[index]
    index = (index + 1) mod total_subflows
end procedure

procedure onNackOrTimeout(packet)
    if now() - last_reroute > base_rtt then
        update_subflow(packet)
        last_reroute = now()
    end if
end procedure
```

## 5. Performance Evaluation

The paper evaluates Uno using htsim, a packet-level network simulator, across distinct workloads and traffic patterns.

The main findings are:

- Uno improves average and tail latency compared with state-of-the-art solutions. Under mixed inter- and intra-datacenter workloads, Uno reduces 99th percentile flow completion time compared with MPRDMA+BBR and Gemini.
- UnoCC provides fast convergence to fairness. Under incast events created from various combinations of intra- and inter-datacenter flows, all flows quickly converge to their fair bandwidth share.
- UnoRC, combining UnoLB and erasure coding, further improves performance under several failure scenarios compared with Uno without erasure coding and compared with other load-balancing schemes.

### 5.1 Simulation Setup

The simulation uses two 8-ary fat-tree datacenters. Each datacenter contains core, aggregation, and edge switches, and each edge switch connects to servers. The datacenters are connected through border switches and multiple inter-datacenter links. Unless otherwise stated, 100 Gbps links are used and switch buffer capacities are set to 1 MiB per port.

The evaluation includes microbenchmarks and realistic workloads.

For microbenchmarks, the paper evaluates:

- incast traffic originating from different sources;
- permutation traffic with randomly selected source and destination nodes.

For realistic workloads, intra-datacenter traffic is generated using Google's web search flow size distribution, while inter-datacenter traffic uses Alibaba regional WAN flow size distribution. The flow arrival process is exponential, and rates are scaled to achieve the desired network load. Source and destination servers are selected uniformly at random.

The paper also evaluates an AI training workload, assuming data-parallel training across two datacenters. After gradient computation in each iteration, an AllReduce-like collective operation synchronizes gradients across datacenters.

The main evaluation metrics are mean flow completion time and 99th percentile flow completion time. Additional metrics include queue occupancy and sending rate.

The main baselines are:

- **MPRDMA+BBR**: BBR for inter-datacenter communication and MPRDMA for intra-datacenter communication.
- **Gemini**: a congestion control protocol designed for both intra- and inter-datacenter communication.
- **Random Packet Spraying and PLB**: load-balancing baselines used to evaluate UnoRC.

### 5.2 Microbenchmark Results

In incast scenarios, Uno outperforms or matches the other algorithms and achieves near-ideal latency. In all scenarios, the sending rates of inter- and intra-datacenter flows quickly converge to their fair bandwidth share, showing Uno's fast convergence to fairness.

In permutation workloads, Uno with ECMP is already significantly better than the baselines. Uno with UnoLB further improves performance by reducing collisions and improving path utilization. Average flow completion times are higher when fewer links connect the datacenters, as expected.

### 5.3 Realistic Workload Results

Under realistic mixed workloads, UnoCC reduces the average and tail latency of inter-datacenter flows compared with Gemini and MPRDMA+BBR. It can slightly increase the latency of intra-datacenter web-search flows because phantom queues drain slower than physical queues. However, overall latency improves because UnoCC provides better congestion management and faster convergence to fair bandwidth sharing.

Full Uno, combining UnoCC and UnoRC, reduces the latency of both intra- and inter-datacenter flows compared with the baselines.

The paper also evaluates different inter-datacenter propagation delays. When the RTT gap between intra- and inter-datacenter traffic is small, MPRDMA+BBR can slightly outperform Uno because Uno's phantom queue introduces controlled slowdown. However, as the RTT ratio increases toward values observed in real networks, Uno significantly outperforms both MPRDMA+BBR and Gemini. This shows that existing solutions struggle with the large gap between intra- and inter-datacenter delays, while Uno is designed for it.

Uno also performs well when queue capacities inside and across datacenters differ. Experiments with shallow-buffered intra-datacenter switches and deeper inter-datacenter switches show that Uno continues to lower overall flow completion time and reduce both intra- and inter-datacenter tail latency.

### 5.4 Failure Scenarios

The paper evaluates UnoRC under different failure scenarios.

First, one of the border links is failed while latency-sensitive flows are sent between two datacenters. Uno outperforms packet spraying and PLB both with and without erasure coding. This is due to Uno's ability to adaptively avoid problematic links and intelligently distribute packets within the same block.

Second, the paper simulates random loss events based on real measurements. Uno largely matches packet spraying and outperforms PLB with and without erasure coding. PLB tends to stick to one path for a given flow; when a link becomes temporarily flaky, this negatively affects the entire block.

Third, the paper simulates AI training communication with both link failures and random drops. Uno consistently outperforms other baselines both with and without erasure coding. With erasure coding, Uno performs significantly better than the second-best algorithm and remains close to the ideal completion time that assumes no ECMP collisions or random drops.

## 6. Discussion

### Leveraging Modern Datacenter Congestion Control for Inter-Datacenter Traffic

The paper shows that separating intra- and inter-datacenter control loops, as in MPRDMA+BBR, creates drawbacks. Other alternatives, such as HPCC and PowerTCP, also suffer from fairness issues due to this separation.

Most state-of-the-art intra-datacenter congestion control protocols rely on fast RTT feedback and specialized switch support, such as INT and packet trimming. This makes them impractical across inter-datacenter environments. Some also use single-path routing, limiting their ability to balance load.

Uno applies congestion control uniformly across intra- and inter-datacenter traffic, relies on widely supported ECN, and employs multipathing to achieve low latency, high reliability, and fairness.

### Hardware Implementation

Uno is designed with hardware feasibility in mind.

UnoCC's key operations, AIMD and Quick Adapt, can be deployed in the Linux kernel similarly to protocols such as TCP and DCTCP. UnoCC uses ECN as the congestion signal, which is commonly supported by modern switches. Phantom queues can be implemented with simple packet-increment and decrement counters and are already supported in some vendor architectures.

Uno uses hardware pacing for congestion control, which is commonly available at the sender NIC.

UnoRC can be deployed as a software shim layer. The sender inserts parity packets, and the receiver decodes once enough packets arrive. A coarse software timer is sufficient for long-latency links. Uno's rerouting can be implemented by changing the IPv6 flow label or updating the UDP source port.

## 7. Related Work

Most existing congestion-control proposals focus either on intra-datacenter networks or inter-datacenter WANs. Intra-datacenter systems often rely on ECN, delay, receiver-driven transmission, or switch-assisted feedback. WAN congestion-management proposals typically use delay because WAN switches provide limited congestion detection support.

Gemini is among the first proposals that tries to bring inter- and intra-datacenter congestion control together as a system, using ECN and delay to detect intra- and inter-datacenter congestion. However, Gemini suffers from slow convergence to bandwidth fairness. Annulus addresses congestion near the source but does not effectively handle congestion that occurs far from the source and closer to the destination. It also works on top of other protocols rather than being a standalone solution.

Uno acts as an effective system for both intra- and inter-datacenter environments by ensuring fast reaction to congestion, bandwidth fairness, and loss resiliency.

For load balancing, existing protocols operate at different granularities: per-flow, per-subflow, or per-packet. Per-flow schemes can suffer from hash collisions or require complex global controllers. Per-subflow schemes improve routing performance but may still be prone to collisions. Packet-level schemes can achieve high performance but require out-of-order support and complicate loss detection.

UnoLB aims to combine the benefits of these approaches by using multiple subflows at any given time and adaptively rerouting away from congested or failed paths. Erasure coding further enhances reliability by adding redundancy so that data can be recovered despite some packet losses.

## 8. Conclusion

Simultaneously handling congestion inside and across datacenters is challenging because of the large gap between intra- and inter-datacenter propagation delays.

Uno is a unified system for efficient datacenter communication with two components:

1. **UnoCC**, a congestion control scheme that ensures fairness and fast reaction.
2. **UnoRC**, a reliable routing mechanism that combines subflow-level load balancing and erasure coding.

Through extensive simulations, the paper shows that Uno improves latency and fairness compared with state-of-the-art solutions. It also demonstrates the effectiveness of Uno in ensuring loss resiliency under failures and across different load balancers.

The key idea is to treat congestion control, reliability, and load balancing as a single integrated design problem for mixed intra- and inter-datacenter communication.