# Congestion Control for Cross-Datacenter Networks - Cleaned Plain Text

Source paper: Gaoxiong Zeng, Wei Bai, Ge Chen, Kai Chen, Dongsu Han, Yibo Zhu, and Lei Cui, "Congestion Control for Cross-Datacenter Networks," IEEE/ACM Transactions on Networking.

This cleaned Markdown version removes non-essential figures, tables, author metadata, references, and biographies. It keeps the logical mechanism of the paper intact. The GEMINI design and algorithm sections preserve the original section wording as much as practical while improving plain-text readability.

---

## Abstract

Geographically distributed applications hosted on cloud are becoming prevalent. They run on cross-datacenter network that consists of multiple data center networks (DCNs) connected by a wide area network (WAN). Such a cross-DC network poses significant challenges in transport design because the DCN and WAN segments have vastly distinct characteristics, such as buffer depths and RTTs.

The paper finds that existing DCN or WAN transport reacting to ECN or delay alone do not, and cannot be easily extended to, work well for such an environment. The key reason is that neither ECN nor delay, by itself, can simultaneously capture both the location and the degree of congestion, mainly due to the discrepancies between DCN and WAN.

Motivated by this, the paper presents the design and implementation of **GEMINI**, which strategically integrates both ECN and delay signals for cross-DC congestion control. To achieve low latency, GEMINI bounds the inter-DC latency with the delay signal and prevents intra-DC packet loss with ECN. To maintain high throughput, GEMINI modulates the window dynamics and maintains low buffer occupancy using both congestion signals.

GEMINI is implemented in the Linux kernel and evaluated by extensive testbed experiments. Results show that GEMINI reduces small-flow and large-flow average completion times compared to TCP Cubic, DCTCP, BBR, and TCP Vegas.

---

## 1. Introduction

Applications running in geographically distributed settings are becoming prevalent. Large-scale online services often share or replicate their data into multiple data centers in different geographic regions. For example, a retailer website may run a database of in-stock items replicated in each regional data center for fast local service, while the regional databases synchronize periodically for the latest data. Other examples include image sharing on online social networks, video storage and streaming, and geo-distributed data analytics.

These applications run on a **cross-datacenter network** consisting of multiple data center networks connected by a wide area network. The wide-area and intra-DC networks have vastly distinct characteristics:

- For WAN, achieving high network utilization is a focus, and switches or routers have deep buffers.
- For DCN, latency is critical, and switches have shallow buffers.

There are many transport protocols designed for either DCN or WAN individually. However, very little prior work has considered a cross-DC environment consisting of both parts at the same time.

Existing congestion-control solutions commonly use either ECN or delay as the congestion signal. ECN-based examples include DCTCP and DCQCN. Delay-based examples include Vegas and TIMELY. These schemes have delivered strong performance in more homogeneous settings, but due to the discrepancies between DCN and WAN, existing DCN or WAN transport protocols do not work well for a cross-DC network.

The fundamental reason is that these solutions only exploit one signal, either ECN or delay, which suffices for a relatively homogeneous environment but cannot handle heterogeneity. ECN is difficult to configure for mixed flows with RTTs varying by orders of magnitude. Delay, by itself, is end-to-end and cannot distinguish whether congestion occurs in WAN or DCN. This creates a dilemma between under-utilizing WAN links and increasing packet losses in shallow-buffered DCN switches.

This motivates a new design that considers both ECN and delay signals in congestion control for cross-DC communication. The new solution must address two key challenges:

1. **Persistent low latency in a heterogeneous environment**, even when DC switches and WAN routers have vastly different buffer depths.
2. **High throughput for inter-DC traffic with shallow-buffered DC switches**, even when propagation delay is in the tens-of-milliseconds range, rather than the sub-millisecond range assumed by many DCN transport protocols.

GEMINI addresses these challenges through three core ideas:

1. **Integrating ECN and delay signals for congestion detection.** Delay bounds the total in-flight traffic over the entire network path, including the WAN segment; ECN controls per-hop queue inside DCN.
2. **Modulating ECN-triggered window reduction by the RTT of a flow.** Large-RTT flows decrease rates more gently, resulting in smoother sawtooth window dynamics.
3. **Adapting window increase to RTT variation.** The additive window-increase step is scaled in proportion to RTT to balance convergence speed and stability under mixed inter-DC and intra-DC traffic.

---

## 2. Background and Motivation

### 2.1 Heterogeneity in Cross-DC Networks

Real-world cross-datacenter networks present heterogeneous characteristics in several aspects.

#### Heterogeneous networking devices

A cross-DC network consists of heterogeneous networking devices with distinct buffer depths from intra-DC networks and inter-DC WAN. DCN switches have shallow buffers, up to tens of kilobytes per port per Gbps. In contrast, WAN routers use deep buffers, up to tens of megabytes per port per Gbps.

#### Mixed intra-DC and inter-DC traffic

Intra-DC and inter-DC traffic coexist in cross-DC networks, but they exhibit very different RTTs. Intra-DC RTTs are often as small as hundreds of microseconds, whereas inter-DC RTTs vary from several milliseconds to hundreds of milliseconds.

#### Different administrative control

Cloud operators have full control over DCN, but they do not always control WAN devices. Many cloud operators lease network resources, such as guaranteed bandwidth, from ISPs, and WAN equipment may be maintained by those ISPs. As a result, switch features such as ECN may not be well supported in WAN, or may be configured with undesirable marking thresholds.

The heterogeneity imposes major challenges in transport design. Ideally, transport protocols should consider congestion location, traffic type, RTT, buffer depth, and supported mechanisms such as ECN.

---

### 2.2 Single Signal's Limitations with Heterogeneity

Most existing transport protocols use either ECN or delay as the congestion signal. While they may work well in either DCN or WAN, ECN or delay alone cannot handle cross-DC heterogeneity.

The paper evaluates representative protocols: Cubic, Vegas, BBR, and DCTCP. Cubic is tested with and without ECN. Vegas is tested with default parameters and scaled parameters. The testbed emulates two DCs connected by an inter-DC WAN link, with all links at 1 Gbps. Intra-DC and inter-DC base RTTs are approximately 200 microseconds and 10 ms, respectively.

The experiments lead to three main observations:

- Transport protocols based only on loss or ECN, such as Cubic, Cubic with ECN, and DCTCP, perform poorly for small-flow completion times because they experience high packet losses in shallow-buffered DCN and large queueing delay without ECN in WAN.
- Delay-based protocols with small thresholds, such as default Vegas, achieve good small-flow performance but slow down large flows. With large thresholds, they improve throughput but degrade small-flow performance and increase packet losses in DCN.
- BBR suffers from high packet loss rates under dynamic workload because it depends on precise estimates of available bandwidth and RTT. Its probing cycle may not catch up with bursty traffic quickly enough to avoid buffer overflow.

---

### 2.3 Problems of ECN-Signal-Only Solutions

ECN-based transport uses ECN signal that often reflects exceeding queue length at a congested link. To deliver high throughput, switches should not mark ECN until the queue length reaches the bandwidth-delay product, or a constant fraction of it.

In a cross-DC setting, configuring ECN marking parameters is difficult because paths have very different RTTs and because intra-DC and inter-DC flows impose divergent requirements:

- Intra-DC flows have small buffer pressure but stringent latency requirements.
- Inter-DC flows have looser latency requirements due to large WAN base latency, but require large buffer space for high WAN utilization.

The result is a conflict: a small ECN threshold is desirable for low latency in intra-DC flows, while a high ECN threshold is desirable for high throughput in inter-DC flows. One cannot achieve both high throughput and low latency for inter-DC and intra-DC flows by using one ECN threshold alone.

In addition, ECN-based transport requires ECN support from all relevant switches. But ECN may not be supported, enabled, or properly configured in WAN. Therefore, DCTCP-like transport may fall back to packet loss, causing high loss and queueing delay.

---

### 2.4 Problems of Delay-Signal-Only Solutions

Delay-based transports use delay signal to reflect cumulative end-to-end network delay. They often use a threshold to control total in-flight traffic. However, given the different buffer depths in WAN and DCN, setting the delay threshold creates a dilemma:

- If the threshold is large enough for WAN utilization, it may exceed shallow DCN switch buffers and cause frequent packet loss when the bottleneck is in DCN.
- If the threshold is small enough to avoid DCN packet loss, it may under-utilize WAN links when the bottleneck is in WAN.

Cross-DC flows may face congestion either in WAN or DCN, but end-to-end delay does not distinguish these cases. Therefore, delay alone cannot simultaneously optimize for high throughput in deep-buffered WAN and low loss in shallow-buffered DCN.

Low delay thresholds also impose strict requirements on accurate delay measurement, which may require additional device support.

---

## 3. GEMINI

### 3.1 Design Rationale

#### How to achieve persistent low latency in the heterogeneous network environment?

Persistent low latency implies low end-to-end queueing delay and near-zero packet loss. ECN, as a per-hop signal, is not a good choice for bounding end-to-end latency; furthermore, ECN has limited availability in WAN. If delay signal alone is used, a small delay threshold is necessary for low loss given the shallow DC switch buffer. However, with a small amount of in-flight traffic, the transport may not fill the network pipe of the WAN segment.

Instead of using a single type of signal, GEMINI integrates ECN and delay signals:

- Delay signal, given its end-to-end nature, is used to bound total in-flight traffic.
- ECN signal, as a per-hop signal, is used to control per-hop queues.

Aggressive ECN marking is performed at the DC switch to prevent shallow-buffer overflow. Thus, the constraint of using small delay thresholds is removed, leaving more space to improve WAN utilization. In this way, the delay-based transport dilemma is naturally resolved.

#### How to maintain high throughput for inter-DC traffic with shallow-buffered DC switches?

A majority of transport protocols, including DCTCP, follow additive-increase multiplicative-decrease congestion control. The queue length they drain in each window reduction is proportionate to BDP, namely `C * RTT`. To avoid buffer underflow and maintain full throughput, the queue length drained each time should be smaller than the switch buffer size.

Because RTT varies widely in cross-DC networks, high buffers would be required. This is acceptable in deep-buffered WAN, but in shallow-buffered DCN, aggressive ECN marking is required for low queueing and low loss. With limited buffer space, sustaining high throughput becomes difficult.

To address this buffer-mismatch challenge, GEMINI modulates the aggressiveness of ECN-triggered window reduction by RTT. Maintaining high throughput requires large-RTT flows to drain queues about as little as small-RTT flows do during window reduction. Intuitively, GEMINI makes larger-RTT flows reduce rates more gently, resulting in smoother sawtooth window and queue-length dynamics.

GEMINI also adjusts the window-increase step in proportion to BDP. Conventional AIMD uses a fixed constant window-increase step for all flows. This either hurts convergence speed for large-BDP inter-DC flows or makes the system unstable for small-BDP intra-DC flows. Scaling the increase step by BDP improves robustness under heterogeneity.

---

### 3.2 GEMINI Algorithm

GEMINI is a window-based congestion control algorithm that uses additive increase and multiplicative decrease. It leverages both ECN and delay signals for congestion detection. It further adjusts the extent of window reduction as well as the growth function based on the RTTs of flows.

#### Integrating ECN and delay for congestion detection

The congestion detection mechanism leverages both ECN and delay signals:

- Delay signal is used to bound total in-flight traffic in the network pipe.
- ECN signal is used to control per-hop queues inside DCN.

By integrating ECN and delay signals, low latency can be achieved. Specifically:

- DCN congestion is detected by ECN to meet the stringent per-hop queueing control requirement imposed by shallow buffers.
- WAN congestion is detected by delay because end-to-end delay is dominated mostly by WAN rather than DCN.

DCN congestion is indicated by the ECN signal: the ECN-Echo flag set in ACKs received by senders. The ECN signal is generated similarly to DCTCP. Data packets are marked with Congestion Experienced codepoint when instantaneous queueing exceeds the marking threshold at DC switches. Receivers echo ECN marks to senders through ACKs with ECN-Echo flags. Given shallow-buffered DCN, the ECN signal is used with a small marking threshold for low packet loss.

WAN congestion is indicated by the delay signal: ACKs returned after data sending with persistently larger delays:

```text
RTT_min > RTT_base + T
```

where:

- `RTT_min` is the minimum RTT observed in the previous RTT window.
- `RTT_base`, simplified as `RTT`, is the base RTT, i.e., the minimum RTT observed during a long time.
- `T` is the delay threshold.

GEMINI uses `RTT_min` instead of average or maximum RTT to better detect persistent queueing and tolerate transient queueing caused by bursty traffic. Given deep-buffered WAN, the delay signal is used with a moderately high threshold for high throughput and bounded end-to-end latency.

When either signal indicates congestion, GEMINI reduces the congestion window accordingly. When both ECN and delay signals indicate congestion, GEMINI reacts to the signal of heavier congestion:

```text
CWND = CWND * (1 - max(f_dcn, f_wan))
```

where `f_dcn` determines the extent of window reduction for congestion in DCN, and `f_wan` determines the extent of window reduction for congestion in WAN.

---

#### Modulating ECN-triggered window reduction aggressiveness by RTT

The window-reduction algorithm aims to maintain full bandwidth utilization while reducing network queueing as much as possible. This requires that the switch buffer never underflows at the bottleneck link.

In DCN, given shallow buffers, a strictly low ECN threshold is used for low packet loss. GEMINI adopts the DCTCP algorithm, which works well under a low ECN threshold for intra-DC flows. However, for large-RTT inter-DC flows, throughput drops greatly if the same reduction behavior is used. The reason is that the buffer drained by a flow during window reduction increases with RTT. Larger-RTT flows drain queues more and easily empty switch buffers, leading to low utilization.

GEMINI extends DCTCP by modulating window-reduction aggressiveness based on RTT. This defines `f_dcn`, the extent of window reduction when congestion is detected in DCN. When ECN indicates congestion:

```text
f_dcn = alpha * F
```

where:

- `alpha` is the exponentially weighted moving average fraction of ECN-marked packets.
- `F` is the factor that modulates congestion-reduction aggressiveness.

The scale factor is:

```text
F = 4K / (C * RTT + K)
```

where:

- `C` is bandwidth capacity.
- `RTT` is the minimum RTT observed during a long time.
- `K` is the ECN marking threshold.

For intra-DC flows, following the DCTCP guideline by setting `K = (C * RTT) / 7`, GEMINI has `F = 1/2`, exactly matching DCTCP. For inter-DC flows with larger RTTs, `F` becomes smaller, leading to smaller window reduction and smoother queue-length oscillation.

In WAN, given much deeper buffers, high throughput can be maintained more easily than in DCN. Window reduction based on a fixed constant is enough for high throughput. This defines `f_wan`, the extent of window reduction when congestion is detected in WAN. When RTT signal indicates congestion:

```text
f_wan = beta
```

where `beta` is a window-decrease parameter for WAN.

The window reduction is performed no more than once per RTT, which is the minimum time required to get feedback from the network under the new sending rate. Despite congestion detection by ECN and delay, packet losses and timeouts may still occur. GEMINI keeps the same fast recovery and fast retransmission mechanisms from TCP.

---

#### Window increase that adapts to RTT variation

The congestion-avoidance algorithm adapts to RTT or BDP to balance convergence speed and stability. For conventional AIMD, large-BDP flows need more RTTs to climb to peak rate, leading to slow convergence. Small-BDP flows may frequently overshoot bottleneck bandwidth, leading to unstable performance.

GEMINI adjusts the window-increase step in proportion to BDP. When there is no congestion indication, for each ACK:

```text
CWND = CWND + h / CWND
```

where `h` is a congestion-avoidance factor in proportion to BDP:

```text
h = H * C * RTT
```

Here, `H` is a constant parameter, `C` is bandwidth capacity, and `RTT` is the minimum RTT observed during a long time.

---

#### Algorithm summary

Input: new incoming ACK  
Output: new congestion window size

```text
1. update_transport_state(alpha, rtt_base, rtt_min)

2. congested_dcn = ecn_indicated_congestion()
3. congested_wan = rtt_indicated_congestion()

4. if congested_dcn or congested_wan:
5.     if time since last cwnd reduction > 1 RTT:
6.         F = 4 * K / (C * rtt_base + K)
7.         f_dcn = alpha * F * congested_dcn
8.         f_wan = beta * congested_wan
9.         cwnd = cwnd * (1 - max(f_dcn, f_wan))
10. else:
11.     h = H * C * rtt_base
12.     cwnd = cwnd + h / cwnd
```

---

### 3.3 Summary of GEMINI's Mechanism

GEMINI resolves conflicting requirements imposed by network heterogeneity by integrating ECN and delay signal.

First, in the face of distinct buffer depths, GEMINI handles congestion in WAN and DCN using delay and ECN signals respectively. This simultaneously meets the need for strictly low latency in DCN and high bandwidth utilization in WAN.

Second, in the face of mixed traffic with a large range of RTTs in shallow-buffered DCN, GEMINI maintains high throughput by modulating window-reduction aggressiveness based on RTT. Large-RTT flows reduce their windows more gently, effectively avoiding buffer emptying and bandwidth under-utilization.

This is achieved by the scale factor `F`, which guarantees full throughput under limited buffer space or a small ECN threshold at steady state. GEMINI also adapts its window-increase step in proportion to RTT, achieving faster convergence speed and better fairness.

---

### 3.4 Theorem 1: Scale Factor for Full Throughput

Given a positive ECN marking threshold `K`, full throughput can be maintained under DCN congestion if the congestion window is reduced as follows:

```text
CWND = CWND * (1 - alpha * F)
```

where `alpha` is the EWMA of ECN fraction and:

```text
F <= 4K / (C * RTT + K)
```

The theoretical result explains why larger-RTT flows should reduce more gently. Given a fixed ECN marking threshold `K`, the larger RTT a flow has, the smaller `F` it gets. Therefore, flows with larger RTTs adjust their windows more smoothly to achieve high throughput.

This generalized result is consistent with the DCTCP guideline. When using the DCTCP-style constant `F = 1/2`, the condition becomes:

```text
K >= (C * RTT) / 7
```

which matches the original DCTCP threshold rule.

---

### 3.5 Parameter Guidelines

#### ECN marking threshold K

The scaling factor `F` ensures full link utilization given an ECN threshold `K`. A lower `K` indicates a smaller queue, which seems desirable. However, when `K` is too small, `F` also becomes small, making flows reduce congestion windows slowly and leading to slower convergence. The paper recommends a moderately small threshold of **50 packets per Gbps**.

To mitigate packet bursts, especially for large-BDP inter-DC traffic, GEMINI uses a per-flow rate limiter at the sender to pace packets evenly.

#### Queueing delay threshold T

`T` should be sufficiently large to achieve high throughput in the cross-DC pipe. It should also leave enough room to filter out interference from DCN queueing delay. In production DCNs, RTTs including queueing are usually at most 1 ms. The paper recommends:

```text
T = 5 ms
```

This is high enough to remove potential DCN queueing interference.

#### Window decrease parameter beta

GEMINI reduces the window size by `beta` multiplicatively when WAN congestion is detected. To avoid bandwidth under-utilization, the queueing headroom should satisfy:

```text
T > beta / (1 - beta) * RTT
```

or equivalently:

```text
beta < T / (T + RTT)
```

Assuming `RTT = 10 ms` and `T = 5 ms`, this yields `beta < 0.33`. The paper recommends:

```text
beta = 0.2
```

which gives smoother sawtooth dynamics.

#### Window increase parameter H

In congestion avoidance, GEMINI grows its congestion window by `h` MSS every RTT. The implementation scales `h` with BDP:

```text
h = H * C * RTT
```

This balances convergence speed and stability. The paper recommends:

```text
H = 1.2 * 10^-7
```

with bounded minimum and maximum increase speeds of 0.1 and 5 as protection.

---

## 4. Evaluation

GEMINI is implemented in Linux kernel 4.9.25. The Linux TCP stack has a universal congestion-control interface defined in `struct tcp_congestion_ops`, supporting pluggable congestion-control modules. GEMINI implements:

- window reduction in `in_ack_event()` and `ssthresh()`;
- congestion avoidance in `cong_avoid()`.

The paper evaluates GEMINI on 1 Gbps and 10 Gbps testbeds. Both testbeds emulate two data centers connected by an inter-DC WAN link. Each data center has border routers, DC switches, and servers. Border routers are emulated by servers with multiple NICs so that NETEM can emulate WAN propagation delay. Intra-DC RTT is around 200 microseconds, and inter-DC RTT is around 10 ms.

The compared protocols are Cubic, Cubic with ECN, Vegas, Vegas with scaled thresholds, BBR, DCTCP, and GEMINI.

---

### 4.1 Throughput and Latency

#### Handling congestion in DCN

An ECN-based DCN congestion-control module must handle the mismatch between shallow DC switch buffers and high-BDP inter-DC traffic. GEMINI mitigates this mismatch by adding the BDP-aware scale factor `F`.

In experiments with inter-DC flows bottlenecked at a DCN link, GEMINI maintains higher throughput than DCTCP at small ECN thresholds. It is less buffer-hungry, requiring a smaller ECN threshold than DCTCP for similar throughput. This leaves more buffer space for absorbing bursts and improving latency.

#### Handling congestion in WAN

GEMINI uses delay signal for WAN congestion control. The paper measures RTT noise and verifies that the default `T = 5 ms` threshold filters out DCN queueing interference. GEMINI maintains near-full throughput with much lower average RTT than loss-based protocols such as Cubic under WAN congestion.

In general, lower `T` leads to lower RTT latency at the cost of slightly decreased throughput. Reducing `beta` improves throughput but may hurt convergence speed. The recommended settings are:

```text
T = 5 ms
beta = 0.2
```

The default settings work across a wide RTT range, including experiments with 100 ms base RTT.

---

### 4.2 Convergence, Stability, and Fairness

GEMINI converges to fair sharing quickly and stably under both DCN congestion and WAN congestion. The paper evaluates throughput dynamics by starting groups of flows at different times and shows that GEMINI converges quickly with high fairness.

RTT unfairness is a major challenge in cross-DC networks because intra-DC and inter-DC traffic have different RTTs. GEMINI achieves RTT fairness by using both:

- the adaptive window-increase factor `h`;
- the scale factor `F`.

In experiments where intra-DC and inter-DC flows share the same DC bottleneck link, Cubic and DCTCP exhibit proportional RTT fairness, BBR skews toward large-RTT flows, while GEMINI maintains near-equal bandwidth sharing regardless of RTT.

---

### 4.3 Realistic Workloads

The paper evaluates GEMINI under realistic workloads generated based on web-search data-center traffic patterns. Flows arrive according to a Poisson process, and the workload is heavy-tailed: about half of the flows are small, while most bytes belong to large flows. Flow completion time is the main metric.

#### Traffic pattern 1: inter-DC traffic, highly congested in WAN

All flows cross the WAN segment. The inter-DC WAN link has around 90% utilization, while intra-DC links have lower utilization. Under this setting:

- GEMINI performs better than Cubic, DCTCP, and BBR for small-flow FCT because it handles WAN queueing delay with RTT signal.
- GEMINI performs much better than default Vegas for large-flow FCT because default Vegas is too conservative.
- Vegas with larger thresholds improves large-flow throughput but hurts small-flow latency.
- GEMINI has the best overall FCT among tested transport protocols.

#### Traffic pattern 2: mixed traffic, highly congested in both WAN and DCN

Sources and destinations are chosen uniformly from all servers, so intra-DC and inter-DC traffic coexist. WAN and DCN are both highly congested. Under this setting:

- GEMINI achieves one of the best small-flow FCTs.
- GEMINI maintains consistently low packet loss rates because it handles DCN congestion adaptively across different RTTs, allows a low ECN threshold, and uses pacing to reduce burst loss.
- GEMINI performs better than Cubic and Vegas for large-flow FCT.
- GEMINI achieves one of the best overall FCTs.

---

## 5. Discussion

### 5.1 Practical Considerations

#### TCP friendliness

GEMINI is not TCP-friendly. Like other ECN-based protocols, GEMINI has fairness issues if it coexists with non-ECN protocols. Recent work shows that it is fundamentally difficult to achieve high performance while also maintaining perfect friendliness to buffer-filling protocols. GEMINI can adopt similar approaches, such as switching to a TCP-competitive mode when buffer-fillers are detected. The paper does not focus on this problem.

#### Real-world deployment

For private clouds, deploying GEMINI requires adding the new congestion-control kernel module at end hosts and configuring ECN at DC switches. For partial deployment, GEMINI can work with common TCP remote ends because it relies on the same ACK mechanism as TCP Cubic.

For public clouds, cloud users and cloud operators are separate entities. Cloud users control VMs and can deploy GEMINI with minimal ECN support from cloud operators. Cloud operators control hypervisors and underlying network devices and can enforce GEMINI in the virtualization layer.

---

### 5.2 Alternative Solutions

#### Multiple queues and different protocols

A straightforward solution might be to use different transport protocols for intra-DC and inter-DC traffic. However, this is less attractive for several reasons:

1. Classifying inter-DC and intra-DC flows based on IPs is nontrivial, especially when virtual subnets extend across data centers.
2. Different transport protocols are unlikely to fair-share network bandwidth, requiring switches to allocate different queues.
3. Inter-DC traffic may encounter congestion in either WAN or DCN, and existing protocols do not address both at the same time.
4. Coarse-grained traffic isolation cannot guarantee flow-level fair sharing and may lead to bandwidth under-utilization.

#### TCP proxy / Split TCP

Another possible solution is to terminate and relay TCP flows with proxies at the border of each network. Traffic could then use the best-suited protocol for each segment. However, this approach has practical flaws:

- Proxies add extra latency, which can hurt short flows that finish in one RTT.
- Relaying every inter-DC flow is impractical due to required relay bandwidth.
- Configuring and managing proxy chains is complex and error-prone; a single relay fault may tear down the whole communication.

---

## 6. Related Work

Cross-DC communication can be improved at several granularities:

- WAN traffic engineering works at the data-center level.
- Bandwidth allocation works at the tenant or flow-group level.
- Transport protocols regulate per-flow sending rate in real time.

This paper focuses on transport design.

Prior WAN transport protocols include Cubic, Vegas, BBR, and other delay-based designs. They consider WAN only and may suffer from intra-DC congestion in cross-DC networks.

Prior data-center network transport protocols include DCTCP, DCQCN, TIMELY, RoGUE, and other ECN- or delay-based designs. ECN or delay signal alone is insufficient for cross-DC congestion control because the environment mixes shallow-buffer DCN and deep-buffer WAN, as well as small-RTT intra-DC and large-RTT inter-DC traffic.

Other transport approaches include explicit rate control, centralized rate control, multipath transport, proactive congestion control, and learning-based congestion control. These may require advanced network support or have less predictable performance in cross-DC facilities.

---

## 7. Conclusion

As geo-distributed applications become prevalent, cross-DC communication becomes increasingly important. Existing transport protocols use either ECN or delay signal alone, which cannot accommodate the heterogeneity of cross-DC networks.

GEMINI is a congestion-control solution for cross-DC networks that integrates ECN and delay signals:

- Delay bounds the total in-flight traffic end-to-end.
- ECN controls per-hop queues inside DCN.
- RTT-aware window reduction maintains high throughput under limited buffers.
- RTT-scaled window increase improves convergence and fairness.

GEMINI is implemented in the Linux kernel and evaluated on commodity switches. Experiments show that it achieves low latency, high throughput, fair and stable convergence, and lower flow completion times compared with Cubic, Vegas, DCTCP, and BBR in cross-DC networks.

---

## Appendix: Key Derivations Retained

### A. Derivation of the Scale Factor F

The paper analyzes steady-state behavior and proves that GEMINI achieves full throughput with:

```text
F = 4K / (C * RTT + K)
```

Consider `N` long-lived flows with identical RTT sharing a bottleneck of capacity `C`. Assuming synchronized window sizes, the queue size is:

```text
Q(t) = N * W(t) - C * RTT
```

where `W(t)` is the dynamic window size. To achieve full utilization, the minimum queue length must be non-negative:

```text
Q_min >= 0
```

The queue size exceeds the ECN marking threshold `K` for exactly one RTT in each cycle before sources receive ECN feedback and reduce their windows. Let `S(W1, W2)` denote the number of packets sent by a sender while its window increases from `W1` to `W2`. Since this takes `(W2 - W1) / h` round trips, and the average window size is `(W1 + W2) / 2`:

```text
S(W1, W2) = (W2^2 - W1^2) / 2h
```

Let:

```text
W* = (C * RTT + K) / N
```

This is the critical window size at which the queue reaches `K` and the switch starts marking packets. During the RTT before the sender reacts, the window peaks at `W* + h`.

From the sawtooth analysis, the relationship between the scale factor and ECN marking threshold becomes:

```text
F <= 4K / (C * RTT + K)
```

Therefore, given a fixed ECN marking threshold `K`, larger-RTT flows receive smaller `F`, and adjust their congestion windows more smoothly to maintain throughput.

---

### B. Proof Idea of RTT Fairness

GEMINI aims to achieve fair sharing of bottleneck bandwidth in DCN where inter-DC and intra-DC flows coexist. It uses the following AIMD rule.

Decrease when congestion is indicated by ECN per RTT:

```text
CWND = CWND * (1 - alpha * F)
```

where:

```text
F = 4K / (C * RTT + K)
```

Increase when there is no congestion indication per ACK:

```text
CWND = CWND + h / CWND
```

where:

```text
h is proportional to RTT
```

The key insight is that for two flows with different RTTs sharing one bottleneck link, GEMINI's RTT-dependent decrease factor and RTT-proportional increase factor compensate for RTT differences. Under the paper's assumptions, the sending-rate ratio approaches:

```text
R1 / R2 ≈ 1
```

Thus, GEMINI achieves ideal RTT fairness at steady state.