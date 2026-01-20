# TIMELY：机制解析与流体模型（符号表 + 数学公式）

> 本文档根据论文中对 TIMELY 的描述、Algorithm 1 与 Figure 7（Equations 20–24）整理。

## 1. TIMELY 的核心机制（按实现逻辑）

TIMELY 是一种**端到端（end-to-end）、基于速率（rate-based）**的拥塞控制算法，它把 **RTT 的变化**当作拥塞信号，并依赖 NIC 硬件获取细粒度 RTT 测量。RTT 通常**每次 completion event**测一次，completion event 对应一个 chunk（约 16–64KB）的成功传输。

### 1.1 信号处理：RTT 梯度（gradient）与平滑

每当收到新 RTT 样本 `newRTT`：

1. 计算相邻 RTT 差分：`newRTTDiff = newRTT - prevRTT`
2. 采用 EWMA 平滑：`rttDiff = (1-α)*rttDiff + α*newRTTDiff`
3. 归一化得到梯度：`rttGradient = rttDiff / DminRTT`

直觉：
- `rttGradient > 0` 表示 RTT 正在上升（拥塞正在加剧）。
- `rttGradient ≤ 0` 表示 RTT 没在变坏（拥塞不加剧）。

### 1.2 控制律：阈值 + 梯度驱动的 AIMD 变体

TIMELY 用两个 RTT 阈值：\(T_{low}\) 与 \(T_{high}\)。每次更新发送速率 `rate`：

- **低时延区（RTT < \(T_{low}\)**）：加性增（Additive Increase）
  - \(rate \leftarrow rate + \delta\)

- **高时延区（RTT > \(T_{high}\)**）：按“超标程度”乘性减（Multiplicative Decrease）
  - \(rate \leftarrow rate \cdot \left(1 - \beta\cdot\left(1-\frac{T_{high}}{RTT}\right)\right)\)

- **阈值区（\(T_{low}\le RTT \le T_{high}\)**）：看梯度
  - 若 \(rttGradient \le 0\)：仍然加性增 \(+\delta\)
  - 若 \(rttGradient > 0\)：按梯度强度乘性减
    - \(rate \leftarrow rate\cdot(1-\beta\cdot rttGradient)\)

> 直觉总结：**RTT 很低就“探测”带宽；RTT 很高就“强制回退”；中间则用 RTT 趋势（梯度）判断是否需要抑制增长。**


## 2. TIMELY 的流体模型（Figure 7）

论文把离散更新（“每次 RTT 样本更新一次 rate”）抽象成连续时间系统：把“每次更新的增/减”转成速率变化率 \(dR_i/dt\)，并用瓶颈队列 \(q(t)\) 作为系统状态。

### 2.1 建模假设（论文中的简化）

- \(N\) 条流共享**单一瓶颈链路**（容量为 \(C\)）。
- 忽略 PFC 的影响。
- 为简化分析，忽略 TIMELY 的 hyperactive increase phase（论文说明此处简化）。
- 流体模型假设“平滑连续发送”；而真实 TIMELY 通过调节 chunk 之间的 gap 控速，chunk 内接近线速，更“bursty”。

---

## 3. 符号表（Variables & Parameters）

### 3.1 变量（Variables）

| 符号 | 含义 |
|---|---|
| \(R_i(t)\) / \(R\) | 第 \(i\) 条流的发送速率（Rate） |
| \(g_i(t)\) / \(g\) | 第 \(i\) 条流的 RTT 梯度（RTT gradient） |
| \(q(t)\) / \(q\) | 瓶颈队列长度（Queue Size） |
| \(t\) | 时间（Time） |
| \(\tau_i^*\) / \(\tau^*\) | 第 \(i\) 条流速率更新间隔（Rate update interval） |
| \(\tau_0\) | 反馈延迟（Feedback delay） |

### 3.2 参数（Parameters）

| 符号 | 含义 |
|---|---|
| \(N\) | 瓶颈处并发流数 |
| \(C\) | 瓶颈链路带宽（容量） |
| \(\alpha\) | EWMA 平滑系数 |
| \(\delta\) | 加性增步长（Additive increase step） |
| \(\beta\) | 乘性减系数（Multiplicative decrease factor） |
| \(T_{low}\) | RTT 低阈值 |
| \(T_{high}\) | RTT 高阈值 |
| \(D_{minRTT}\) | 用于梯度归一化的最小 RTT（Minimum RTT for normalization） |
| \(D_{prop}\) | 传播时延（Propagation delay） |
| \(Seg\) | burst/chunk 大小（Burst size） |
| \(MTU\) | 最大传输单元大小（用于序列化时间估计） |

---

## 4. 数学公式（Equations 20–24）与逐式解释

### (20) 队列动力学

\[
\frac{dq}{dt}=\sum_i R_i(t)-C
\]

**解释：**
- \(\sum_i R_i(t)\) 是所有流到达瓶颈的总速率；\(C\) 是瓶颈的服务速率。
- 当总到达速率大于容量时队列增长（拥塞加重）；反之队列下降。

---

### (21) 速率动力学（把离散更新“连续化”的控制律）

\[
\frac{dR_i}{dt}=
\begin{cases}
\frac{\delta}{\tau_i^*}, & q(t-\tau_0)<C\cdot T_{low}\\[6pt]
\frac{\delta}{\tau_i^*}, & g_i\le 0\\[6pt]
-\frac{g_i\beta}{\tau_i^*}R_i(t), & g_i>0\\[6pt]
-\frac{\beta}{\tau_i^*}\left(1-\frac{C\cdot T_{high}}{q(t-\tau_0)}\right)R_i(t), & q(t-\tau_0)>C\cdot T_{high}
\end{cases}
\]

**解释（逐分支）：**
1. **低延迟区**：\(q(t-\tau_0)<C\cdot T_{low}\)  
   这相当于“排队时延 \(\approx q/C\) 小于阈值 \(T_{low}\)”时加性增。连续化后，“每 \(\tau_i^*\) 秒加 \(\delta\)”对应“每秒增加 \(\delta/\tau_i^*\)”。

2. **阈值区且梯度非正**：\(g_i\le 0\)  
   RTT 没在上升（趋势不变坏），继续加性增，形式同上。

3. **阈值区且梯度为正**：\(g_i>0\)  
   乘性减写成 \(-k\cdot R_i(t)\) 的形式：当前速率越大，绝对降幅越大；梯度越大降得越狠。

4. **高延迟区**：\(q(t-\tau_0)>C\cdot T_{high}\)  
   超阈值越多（\(q\) 相比 \(C T_{high}\) 越大），括号项 \(\left(1-\frac{C T_{high}}{q}\right)\) 越接近 1，降速越猛烈。

> 备注：这里用到 \(q(t-\tau_0)\) 而不是 \(q(t)\)，因为发送端决策依赖“带反馈延迟”的拥塞观测。

---

### (22) RTT 梯度的动态（EWMA + 归一化的连续形式）

\[
\frac{dg_i}{dt}=\frac{\alpha}{\tau_i^*}\left(
-g_i(t)+
\frac{q(t-\tau_0)-q(t-\tau_0-\tau_i^*)}{C\cdot D_{minRTT}}
\right)
\]

**解释：**
- “目标梯度”项：
  \[
  \frac{q(t-\tau_0)-q(t-\tau_0-\tau_i^*)}{C\cdot D_{minRTT}}
  \]
  它对应“相邻两次 RTT 样本之间排队时延变化量”，并用 \(D_{minRTT}\) 做归一化（与离散算法一致）。
- 外层结构 \(-g_i(t)+(\cdot)\) 是标准的一阶滤波器形式：\(g_i(t)\) 以时间尺度 \(\tau_i^*/\alpha\) 追踪“目标梯度”。

---

### (23) 更新间隔近似：一次 burst 更新一次

\[
\tau_i^*=\max\left\{\frac{Seg}{R_i},\; D_{minRTT}\right\}
\]

**解释：**
- \(\frac{Seg}{R_i}\)：以速率 \(R_i\) 发完一个 burst/chunk（大小为 \(Seg\)）所需时间。
- \(D_{minRTT}\) 作为下限：限制速率更新频率不会过高（与实现按 completion event 更新的事实一致）。

---

### (24) 反馈延迟：排队 + 序列化 + 传播

\[
\tau_0=\frac{q}{C}+\frac{MTU}{C}+D_{prop}
\]

**解释：**
- \(\frac{q}{C}\)：排队（队列清空/等待）时间。
- \(\frac{MTU}{C}\)：序列化时间（把一个 MTU 发上链路的时间量级）。
- \(D_{prop}\)：传播时延（拓扑与物理决定的相对常量）。

**关键意义：**
- 对 ECN 来说，论文指出控制环路延迟可以近似看作常量（主要由传播时延主导）。
- 对 TIMELY 来说，RTT 信号的控制环路延迟会随队列变化，因此必须显式建模 \(\tau_0\)。

---

## 5. 一个常见疑问：为什么用 \(q<C\cdot T_{low}\) 而不是直接用 RTT？

在模型里，RTT 可理解为：
\[
RTT \approx D_{prop} + \frac{q}{C} + \text{(少量序列化/处理项)}
\]

- \(D_{prop}\) 在短时间尺度通常近似常量，不反映拥塞“变化”。
- TIMELY 的拥塞信号关注的是 RTT 的**可变部分**，也就是排队时延 \(\approx q/C\)。  
  因此把阈值判断写成 \(q<C\cdot T_{low}\) 与 \(q>C\cdot T_{high}\) 更便于分析。
- 传播时延并未忽略：它被体现在反馈延迟 \(\tau_0\) 的建模里（式(24)），用于刻画控制环的“滞后”。

---

## 6. 小结

- TIMELY 机制：RTT 阈值 + RTT 梯度（EWMA 平滑）驱动的速率调节。
- 流体模型：用 \(\{q(t), R_i(t), g_i(t)\}\) 的连续动力学 + 显式反馈延迟 \(\tau_0\) 来刻画系统行为。
- 关键差异：与 ECN 类算法相比，TIMELY 的控制环延迟随队列增长而变大，这会显著影响稳定性与收敛特性。

