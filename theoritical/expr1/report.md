# Experiment 1 — Scaling check (steady-state)

**Question**

Verify the steady-state scaling law:

$$
\bar p \propto N^{4/3}
$$

**How**

- Run one simulation for each $N \in \{2,4,8,12,16,20\}$.
- Estimate steady state by averaging over the last 20ms to get $\bar p$ and $\bar q$.

**Result**

The measured points match $\bar p \propto N^{4/3}$ very well.

![](figs/dcqcn_scaling_p_fit.png)

**How to reproduce**

- Generate plot + fit data:
  - `python3 theoritical/expr1/dcqcn_scaling_fit_plot.py`
- (Optional) quick mean-only table:
  - `python3 theoritical/expr1/dcqcn_steady_state_exp.py`
