# Experiment 3 — Reduced-parameter RED + Alternative to Lift

Goal: reduce the number of RED parameters and reduce **waste bytes**, while watching whether sender rates converge.

We reuse the same **virtual bottleneck** definition as expr2:

- `arrived_bytes(t)`: cumulative arrived bytes from time 0
- `C*t`: service bytes
- Virtual queue:  
  $$ q(t) = \max(0,\; arrived\_bytes(t) - C\,t) $$

We plot:
- Queue/arrived/waste in **MB**
- Sender rate (RC) in **Gbps**
- `arrived_bytes(t) - C*t` in **KB**

Outputs are written into `theoritical/expr3/figs/`.

---

## Scheme 1 (2 params): `p = k*q` with threshold

Marking rule:

- if `q <= threshold`: `p = p_min`
- else: `p = clamp(k*q, p_min, p_max)`

Parameters:
- `threshold`
- `k`

---

## Scheme 2 (2 params): `p = k*(q - Kmin)`

Marking rule:

- if `q <= Kmin`: `p = p_min`
- else: `p = clamp(k*(q-Kmin), p_min, p_max)`

Parameters:
- `Kmin`
- `k`

---

## Scheme 3 (2 params): periodic exponential correction (no per-step Lift)

Instead of enforcing `arrived_bytes(t) >= C*t` every step (Lift), we do a periodic correction.

Every `corr_interval`, if `arrived_bytes < C*t`, we move it toward `C*t` smoothly:

$$
arrived \leftarrow C\,t - (C\,t - arrived)\,\exp(-corr\_interval/\tau_{corr})
$$

The bytes added by this correction are accumulated as `waste_bytes`.

Parameters:
- `corr_interval`
- `tau_corr`

(For marking probability `p(q)`, we keep the classic RED constants aligned with expr2.)

---

## How to run

- Run all cases and generate a summary CSV (and plot/log a few best cases per scheme):
  - `python3 theoritical/expr3/dcqcn_expr3_modified_red_and_correction.py`

It writes a summary table:
- `theoritical/expr3/figs/expr3_summary.csv`

Columns include:
- `waste_mb`
- per-sender RC mean/std/CV over the last 20ms (a simple convergence indicator)

Notes:
- The script sweeps multiple parameter combinations for each scheme.
- To keep runtime reasonable, it only generates full figures and 1ms log files for a small number of best cases (lowest `waste_mb`) per scheme.

---

## Representative results (one per scheme)

Below are representative (best-ranked by `waste_mb` in this run) cases for each scheme. Each case records the parameters and key metrics from `theoritical/expr3/figs/expr3_summary.csv`, and includes the corresponding plots/logs.

### Scheme 1 representative

Case: `expr3_best_s1_th5k_kx0.5_rank1`

Parameters:
- `threshold = 5 KB`
- `k_scale = 0.5` (effective `k_slope = 5.00801282051282e-07`)

Key metrics:
- `waste_mb = 53.4335`
- Sender A RC: mean `19.9725 Gbps`, CV `0.00877`
- Sender B RC: mean `19.9407 Gbps`, CV `0.00883`

Artifacts:
- 1ms log: `theoritical/expr3/figs/expr3_best_s1_th5k_kx0.5_rank1_1ms.log`

![scheme1 bottleneck](figs/expr3_best_s1_th5k_kx0.5_rank1_bottleneck.png)
![scheme1 senders](figs/expr3_best_s1_th5k_kx0.5_rank1_senders.png)
![scheme1 arrived vs ct](figs/expr3_best_s1_th5k_kx0.5_rank1_arrived_vs_ct.png)
![scheme1 arrived minus ct](figs/expr3_best_s1_th5k_kx0.5_rank1_arr_minus_ct.png)

### Scheme 2 representative

Case: `expr3_best_s2_kmin5k_kx0.5_rank1`

Parameters:
- `Kmin = 5 KB`
- `k_scale = 0.5` (effective `k_slope = 5.00801282051282e-07`)

Key metrics:
- `waste_mb = 53.2743`
- Sender A RC: mean `20.0019 Gbps`, CV `0.00842`
- Sender B RC: mean `19.9780 Gbps`, CV `0.00844`

Artifacts:
- 1ms log: `theoritical/expr3/figs/expr3_best_s2_kmin5k_kx0.5_rank1_1ms.log`

![scheme2 bottleneck](figs/expr3_best_s2_kmin5k_kx0.5_rank1_bottleneck.png)
![scheme2 senders](figs/expr3_best_s2_kmin5k_kx0.5_rank1_senders.png)
![scheme2 arrived vs ct](figs/expr3_best_s2_kmin5k_kx0.5_rank1_arrived_vs_ct.png)
![scheme2 arrived minus ct](figs/expr3_best_s2_kmin5k_kx0.5_rank1_arr_minus_ct.png)

### Scheme 3 representative

Case: `expr3_best_s3_corr0.2ms_tau10ms_rank1`

Parameters:
- `corr_interval = 0.2 ms`
- `tau_corr = 10 ms`

Key metrics:
- `waste_mb = 52.7817`
- Sender A RC: mean `19.0401 Gbps`, CV `0.22929`
- Sender B RC: mean `19.0385 Gbps`, CV `0.22937`

Artifacts:
- 1ms log: `theoritical/expr3/figs/expr3_best_s3_corr0.2ms_tau10ms_rank1_1ms.log`

![scheme3 bottleneck](figs/expr3_best_s3_corr0.2ms_tau10ms_rank1_bottleneck.png)
![scheme3 senders](figs/expr3_best_s3_corr0.2ms_tau10ms_rank1_senders.png)
![scheme3 arrived vs ct](figs/expr3_best_s3_corr0.2ms_tau10ms_rank1_arrived_vs_ct.png)
![scheme3 arrived minus ct](figs/expr3_best_s3_corr0.2ms_tau10ms_rank1_arr_minus_ct.png)
