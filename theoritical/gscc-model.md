# 参考速率（refRate）流体模型（与 TIMELY 记号对齐）

> 目标：把“按 epoch 更新的参考速率控制算法”写成 **TIMELY Figure 7 那种形式**：队列 $q(t)$ + 速率 $R(t)$ + RTT 梯度 $g(t)$ 的连续时间（流体）闭环模型，并显式包含反馈延迟 $\tau_0$ 与更新间隔 $\tau^*$。

---

## 1. 对齐 TIMELY 的符号与假设

### 1.1 状态变量（与 TIMELY 一致）

- $R(t)$：参考速率（refRate）
- $q(t)$：瓶颈队列长度
- $g(t)$：RTT 梯度（RTT gradient，**归一化后的 EWMA 差分**）
- $\tau^*$：速率更新间隔（这里对应 epochDur）
- $\tau_0$：反馈延迟（feedback delay）；本模型还用它作为 **基准 RTT / 链路固有传播时延**（你的假设：minRTT = propagation delay）

> TIMELY 在 Table 2 中使用的同名变量集为 $\{R, g, q, \tau^*, \tau_0\}$。

### 1.2 核心简化（按你的要求）

1. **只建模参考速率 $R(t)$**，不建模 “实际速率/上界约束(realRate clamp)”。
2. **基准 RTT = 链路本身延迟**：$\text{baseRTT} = \tau_0$，为常数。
3. 单瓶颈链路容量 $C$；忽略 PFC 等复杂效应（和 TIMELY 流体模型假设一致）。

---

## 2. 网络侧（Plant）：队列与 RTT 观测

### (E1) 队列动力学（反射边界的流体队列）

$$
\frac{dq}{dt}=
\begin{cases}
R(t)-C, & q(t)>0\\
\max\{R(t)-C,\,0\}, & q(t)=0
\end{cases}
$$

它与 TIMELY 的队列方程 $\dot q=\sum_i R_i - C$ 同构，只是这里将“聚合到瓶颈的总速率”直接记为 $R(t)$。

### (E2) RTT（含反馈延迟）

令发送端在时刻 $t$ 看到的 RTT 为：
$$
r(t)=\tau_0+\frac{q(t-\tau_0)}{C}
$$

- $\tau_0$ 是固定传播时延（也是基准 RTT）。
- $\frac{q}{C}$ 是排队时延。
- 使用 $q(t-\tau_0)$ 是为了体现“拥塞信息需要一个往返才能反馈回来”，与 TIMELY 在模型中显式引入 $\tau_0$ 的做法一致。

> 可选扩展（更贴 TIMELY 的细节）：如果你希望把“反馈延迟随队列变化”也纳入，可以把上式的 $\tau_0$ 改写为 $\tau_0(t)=\tau_0+\frac{q(t)}{C}$；但这会变成“状态依赖时延”，分析更复杂。

---

## 3. 信号处理：用 $g(t)$ 表示“RTT 差分 EWMA + 归一化”

### 3.1 定义（对齐 TIMELY 的“normalized RTT gradient”）

令 $g(t)$ 为 **归一化的 RTT 差分 EWMA**（TIMELY 将梯度定义为“两个连续 RTT 样本的变化量，再除以最小 RTT 做归一化”）。

在“按 epoch（$\tau^*$）采样”的语境下，梯度依赖两个过去时刻的队列值（当前样本与上次样本）。TIMELY 明确指出这一点，并在其 Equation 22 中建模。

### (E3) 梯度动力学（TIMELY Eq. 22 的同构形式）

因为你假设 $\text{DminRTT}=\tau_0$，可把 TIMELY 的归一化项 $C\cdot \text{DminRTT}$ 替换成 $C\tau_0$，并把更新间隔记为 $\tau^*$：

$$
\frac{dg}{dt}
=
\frac{\alpha}{\tau^*}
\left(
-g(t)
+
\frac{q(t-\tau_0)-q(t-\tau_0-\tau^*)}{C\,\tau_0}
\right)
$$

- $\alpha$：EWMA 平滑系数
- $\frac{q(\cdot)-q(\cdot-\tau^*)}{C}$：近似两次采样间“排队时延变化量”
- 再除以 $\tau_0$：得到无量纲梯度（normalized gradient）

---

## 4. 预测 RTT（one-RTT-ahead prediction）

算法中常见的做法是：利用 EWMA 的 RTT 差分去预测“未来一个 base RTT 后的 RTT”。在我们只保留 $g(t)$ 的记号下，可写成：

### (E4) 预测 RTT

$$
\hat r(t)=r(t)+\underbrace{g(t)\tau_0}_{\text{EWMA RTT diff}}\cdot\frac{\tau_0}{\tau^*}
=
r(t)+g(t)\frac{\tau_0^2}{\tau^*}
$$

解释：

- $g(t)\tau_0$ 对应“平滑后的 RTT 差分量”（单位：时间）
- $\tau_0/\tau^*$ 近似表示“一个 RTT 内包含多少个 epoch 更新”

---

## 5. 阈值：把 RTT 阈值等价为队列阈值（像 TIMELY 一样写成 $q<C\cdot(\cdot)$）

令阈值（相对基准 RTT 的偏移）为 $T$（单位：时间），则：

### (E5) RTT 阈值

$$
\theta=\tau_0+T
$$

由于 $r(t)=\tau_0+\frac{q(t-\tau_0)}{C}$，判断 $r(t)<\theta$ 等价于：
$$
q(t-\tau_0)<C\,T
$$

---

## 6. 参考速率控制律：分段 ODE（AIMD 结构，与 TIMELY Eq. 21 对齐）

### 6.1 连续化参数（把“每 RTT 的 AI/MD 目标”变成 ODE 系数）

- **AI 强度 $H$**：常用设计目标是“一个 RTT 内 AI 总增量 $\approx H\cdot \text{BDP}$”。
  - 在单链路近似下 $\text{BDP}=C\tau_0$，因此自然得到 **每秒 AI 斜率**：

$$
A = H\cdot C
$$

- **MD 强度 $\beta\in(0,1)$**：常用设计目标是“一个 RTT 内累计乘性变为 $\beta$ 倍”，对应连续指数衰减率：

$$
\kappa = \frac{\ln\beta}{\tau_0}\quad(\kappa<0)
$$

### 6.2 “跨阈值谨慎切换”系数（力度 /3）

为模拟算法中“当前 RTT 与预测 RTT 分处阈值两侧时，更新幅度缩小 3 倍”的逻辑，引入：

$$
\sigma(t)=
\begin{cases}
1, & (r(t)-\theta)(\hat r(t)-\theta)\ge 0\\[4pt]
\frac{1}{3}, & (r(t)-\theta)(\hat r(t)-\theta)< 0
\end{cases}
$$

### (E6) 参考速率的分段动力学

用队列阈值写成最像 TIMELY 的形式：

$$
\frac{dR}{dt}=
\begin{cases}
\sigma(t)\,A, & q(t-\tau_0)<C\,T\\[6pt]
\sigma(t)\,\kappa\,R(t), & q(t-\tau_0)\ge C\,T
\end{cases}
$$

其中 $A=HC$，$\kappa=\ln(\beta)/\tau_0$。

> 结构对齐：TIMELY 的 Eq. 21 在不同区间同样给出 “常数加性增（$+\delta/\tau^*$）” 与 “比例乘性减（$-kR$）” 的分段形式。

---

## 7. 最终闭环系统（TIMELY 风格的“Figure 7”集合）

把 (E1)–(E6) 合在一起，得到一个与 TIMELY 形式高度对齐的闭环流体模型：

1. **队列：**

$$
\dot q(t)=
\begin{cases}
R(t)-C, & q(t)>0\\
\max\{R(t)-C,0\}, & q(t)=0
\end{cases}
$$

2. **RTT 观测：**

$$
r(t)=\tau_0+\frac{q(t-\tau_0)}{C}
$$

3. **梯度：**

$$
\dot g(t)
=
\frac{\alpha}{\tau^*}
\left(
-g(t)
+
\frac{q(t-\tau_0)-q(t-\tau_0-\tau^*)}{C\,\tau_0}
\right)
$$

4. **预测 RTT：**

$$
\hat r(t)=r(t)+g(t)\frac{\tau_0^2}{\tau^*}
$$

5. **谨慎系数：**

$$
\sigma(t)=
\begin{cases}
1, & (r(t)-(\tau_0+T))(\hat r(t)-(\tau_0+T))\ge 0\\
\frac{1}{3}, & \text{otherwise}
\end{cases}
$$

6. **参考速率控制：**

$$
\dot R(t)=
\begin{cases}
\sigma(t)\,H\,C, & q(t-\tau_0)<C\,T\\
\sigma(t)\,\frac{\ln\beta}{\tau_0}\,R(t), & q(t-\tau_0)\ge C\,T
\end{cases}
$$

---

## 8. 你后续如果要做稳定性分析，推荐的两个版本

- **版本 A（易分析）**：固定 $\tau_0$（常延迟），做平衡点与线性化（类似 TIMELY/DCQCN 论文的常见做法）。
- **版本 B（更真实）**：令 $\tau_0(t)=\tau_0+\frac{q(t)}{C}$（状态依赖延迟），更贴近“RTT 反馈延迟随排队变化”的现实，但推导会更难。

---

### 备注：关于资料可追溯性

我这份模型严格按你提出的“只保留参考速率 + 基准 RTT = $\tau_0$ + 与 TIMELY 记号对齐 + 用 $g$ 不用 $d$”的要求整理；如果你希望我把某篇论文里对应算法的每个步骤（比如跨阈值 /3 的具体条件、预测 RTT 的系数形式）逐行加上引用位置，请把那篇论文的 PDF 再上传一次（系统提示部分上传内容已过期，无法再次定位原文段落）。