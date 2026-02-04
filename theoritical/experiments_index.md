# Theoretical DCQCN Experiments Index

This folder contains a small set of theoretical DCQCN experiments.


## Experiment 1 — Steady-state scaling

- What: verify $\bar p \propto N^{4/3}$ under steady-state averaging.
- Conclusion: the measured points fit $\bar p \propto N^{4/3}$ very well.
- Details: [expr1/report.md](expr1/report.md)

## Experiment 2 — Virtual BottleNeck

- What: replace physical queue with virtual estimate $q_{virt}(t)=\max(0, arrived\_bytes(t)-C\,t)$ and observe dynamics; also evaluate the Lift variant.
- Conclusion: with this virtual queue, sender rates show persistent oscillations (no stable convergence observed); Lift introduces measurable waste (lifted bytes).
- Details: [expr2/report.md](expr2/report.md)

## Experiment 3 — Reduced-parameter RED + Alternative to Lift

- What: simplify marking probability to reduce tunable parameters (two-parameter variants), and test a periodic exponential correction as an alternative to per-step Lift.
- Goal: reduce waste bytes and check whether sender rates converge.
- Details: [expr3/report.md](expr3/report.md)
