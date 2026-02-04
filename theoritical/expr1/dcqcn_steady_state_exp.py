from __future__ import annotations

from pathlib import Path
import sys

import numpy as np


def _import_core():
    # Ensure we can run from any cwd.
    this_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(this_dir.parent))
    from dcqcn_refactored import BottleNeck, Sender, SenderParams, Simulator

    return BottleNeck, Sender, SenderParams, Simulator


def run_one_case(
    n_flows: int,
    *,
    C_bps: float = 40e9,
    pkt_bytes: int = 1024,
    kmin_bytes: float = 5 * 1024,
    kmax_bytes: float = 200 * 1024,
    pmax: float = 0.2,
    dt: float = 2e-6,
    t_end: float = 0.12,
    stable_window_s: float = 0.02,
    tau_star: float = 50e-6,
) -> tuple[float, float]:
    """Run simulation and return (mean_p, mean_q_bytes) in the last window."""

    BottleNeck, Sender, SenderParams, Simulator = _import_core()

    senders = [
        Sender(
            name=f"sender_{i}",
            params=SenderParams(tau_star=tau_star),
            pkt_bytes=pkt_bytes,
            RC0_bps=C_bps,
            RT0_bps=C_bps,
            alpha0=0.0,
        )
        for i in range(n_flows)
    ]

    bn = BottleNeck(
        C_bps=C_bps,
        pkt_bytes=pkt_bytes,
        kmin_bytes=kmin_bytes,
        kmax_bytes=kmax_bytes,
        pmax=pmax,
        q0_bytes=0.0,
    )

    sim = Simulator(bottleneck=bn, senders=senders, logger=None)
    out = sim.run(t_end=t_end, dt=dt, log_interval_s=None)

    p = np.asarray(out["p"], dtype=float)
    q = np.asarray(out["q_bytes"], dtype=float)

    window_steps = max(1, int(round(stable_window_s / dt)))
    start = max(0, len(p) - window_steps)

    mean_p = float(np.mean(p[start:]))
    mean_q = float(np.mean(q[start:]))
    return mean_p, mean_q


def main() -> int:
    cases = [2, 4, 8, 16]

    # Experiment settings
    dt = 2e-6
    t_end = 0.12
    stable_window_s = 0.02

    print("Steady-state estimate using last 20ms window")
    print(f"dt={dt}s, t_end={t_end}s, window={stable_window_s}s")
    print("N_flows\tmean_p\t\tmean_queue_bytes")

    for n in cases:
        mean_p, mean_q = run_one_case(
            n,
            dt=dt,
            t_end=t_end,
            stable_window_s=stable_window_s,
        )
        print(f"{n}\t{mean_p:.6f}\t{mean_q:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
