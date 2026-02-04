# Experiment 2 — Virtual BottleNeck (and Lift)

**Purpose**

Test a *virtual bottleneck* queue estimator and observe convergence vs oscillation.

**Virtual queue definition**

Let `arrived_bytes(t)` be cumulative arrived bytes from time 0 to `t`. With link rate `C` (bytes/s):

$$
q_{virt}(t) = \max\bigl(0,\; arrived\_bytes(t) - C\,t \bigr)
$$

Feed $q_{virt}(t)$ into RED to obtain $p(t)$.

**Observations**

Arrived bytes vs service bytes ($C\cdot t$), with waste bytes plotted together.

Units used in plots:

- Queue / arrived / waste: **MB**
- Sender rate (RC): **Gbps**

For this experiment, define the signed difference:

$$
\Delta(t) = arrived\_bytes(t) - C\,t
$$

![](figs/virtualbn_bn_vs_ct.png)

`arrived_bytes(t) - C*t` (KB):

![](figs/virtualbn_bn_arr_minus_ct.png)

Per-sender dynamics (RC and alpha):

![](figs/virtualbn_bn_senders.png)

**Conclusion**

Under this virtual-queue formulation, sender rates show persistent oscillations rather than converging to a stable steady state.

---

## VirtualBN + Lift (arrived bytes >= C·t)

**Idea**

When the cumulative arrived bytes is smaller than service bytes (`C*t`), instead of letting the estimator create a negative queue and then clamping to 0, we *lift*:

$$
\mathrm{if}\; arrived\_bytes(t) < C\,t:\quad arrived\_bytes(t) \leftarrow C\,t
$$

We track the total lifted amount as **waste bytes** (cumulative lift), and plot it together with arrived-vs-ct.

**Arrived bytes vs C·t and per-sender dynamics (two flows)**

Kmin=5KB:

![](figs/virtualbn_lift_arrived_vs_ct_kmin5k.png)

`arrived_bytes(t) - C*t` (KB):

![](figs/virtualbn_lift_arr_minus_ct_kmin5k.png)

![](figs/virtualbn_lift_kmin5k_senders.png)

Kmin=50KB:

![](figs/virtualbn_lift_arrived_vs_ct_kmin50k.png)

`arrived_bytes(t) - C*t` (KB):

![](figs/virtualbn_lift_arr_minus_ct_kmin50k.png)

![](figs/virtualbn_lift_kmin50k_senders.png)

Kmin=500KB:

![](figs/virtualbn_lift_arrived_vs_ct_kmin500k.png)

`arrived_bytes(t) - C*t` (KB):

![](figs/virtualbn_lift_arr_minus_ct_kmin500k.png)

![](figs/virtualbn_lift_kmin500k_senders.png)

**Waste bytes sweep**

Measured total waste (this run):

| Kmin (KB) | waste (MB) |
|---:|---:|
| 5 | 54.3371 |
| 50 | 54.7694 |
| 100 | 55.2153 |
| 200 | 55.6335 |
| 300 | 55.9165 |
| 400 | 56.0991 |
| 500 | 56.1014 |

![](figs/virtualbn_lift_waste_vs_kmin.png)

**How to reproduce**

- Base VirtualBN:
	- `python3 theoritical/expr2/dcqcn_virtual_bottleneck_experiment.py`
- VirtualBN + Lift + sweep:
	- `python3 theoritical/expr2/dcqcn_virtualbn_lift_kmin_sweep_experiment3.py`
