from __future__ import annotations

import os
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
    """Return (mean_p, mean_q_bytes) averaged over the last stable_window_s."""

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


def fit_fixed_exponent(N: np.ndarray, p: np.ndarray, exponent: float) -> tuple[float, float]:
    """Fit p ≈ a*N^exponent (least squares in p-space). Return (a, R2)."""
    x = N**exponent
    a = float((p @ x) / (x @ x))
    p_hat = a * x
    ss_res = float(np.sum((p - p_hat) ** 2))
    ss_tot = float(np.sum((p - float(np.mean(p))) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return a, r2


def fit_free_exponent(N: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Fit p ≈ c*N^b via log-log linear regression. Return (b, c)."""
    b, logc = np.polyfit(np.log(N), np.log(p), 1)
    c = float(np.exp(logc))
    return float(b), c


def plot_scaling(
    N: np.ndarray,
    p: np.ndarray,
    a: float,
    exponent: float,
    out_path: Path,
) -> Path:
    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)

    N_grid = np.linspace(float(np.min(N)), float(np.max(N)), 300)
    p_fit = a * (N_grid**exponent)

    fig, ax = plt.subplots(1, 1, figsize=(7.2, 4.8))
    ax.plot(N_grid, p_fit, label=rf"fit: $p={a:.3e}\,N^{{{exponent:.3f}}}$")
    ax.scatter(N, p, label="measured (steady-state mean)", zorder=3)

    ax.set_xlabel("Number of concurrent flows N")
    ax.set_ylabel("Steady-state mean p")
    ax.set_title(r"Steady-state scaling check: $p \propto N^{4/3}$")
    ax.grid(True, alpha=0.3)
    ax.legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)
    return out_path


def main() -> int:
    Ns = np.array([2, 4, 8, 12, 16, 20], dtype=float)

    # Simulation settings
    dt = 2e-6
    t_end = 0.12
    stable_window_s = 0.02

    # Network/RED settings
    C_bps = 40e9
    pkt_bytes = 1024
    kmin_bytes = 5 * 1024
    kmax_bytes = 200 * 1024
    pmax = 0.2

    # Sender settings
    tau_star = 50e-6

    mean_ps: list[float] = []
    mean_qs: list[float] = []

    for n in Ns.astype(int):
        mp, mq = run_one_case(
            int(n),
            C_bps=C_bps,
            pkt_bytes=pkt_bytes,
            kmin_bytes=kmin_bytes,
            kmax_bytes=kmax_bytes,
            pmax=pmax,
            dt=dt,
            t_end=t_end,
            stable_window_s=stable_window_s,
            tau_star=tau_star,
        )
        mean_ps.append(mp)
        mean_qs.append(mq)

    mean_p = np.array(mean_ps, dtype=float)
    mean_q = np.array(mean_qs, dtype=float)

    exponent = 4.0 / 3.0
    a, r2 = fit_fixed_exponent(Ns, mean_p, exponent)
    b_free, c_free = fit_free_exponent(Ns, mean_p)

    # Print results
    print("Steady-state estimate using last 20ms window")
    print(f"dt={dt}s, t_end={t_end}s, window={stable_window_s}s")
    print("N\tmean_p\t\tmean_queue_bytes")
    for n, mp, mq in zip(Ns.astype(int), mean_p, mean_q):
        print(f"{n}\t{mp:.6f}\t{mq:.2f}")

    print("\nFixed exponent fit: p ≈ a*N^(4/3)")
    print(f"a = {a:.10e}")
    print(f"R2 = {r2:.10f}")

    print("\nFree exponent log-log fit: p ≈ c*N^b")
    print(f"b = {b_free:.6f}")
    print(f"c = {c_free:.10e}")

    # Save npz data for notes/reuse
    out_dir = Path(__file__).resolve().parent
    figs_dir = out_dir / "figs"
    figs_dir.mkdir(parents=True, exist_ok=True)
    npz_path = figs_dir / "dcqcn_scaling_data.npz"
    np.savez(
        npz_path,
        Ns=Ns,
        mean_p=mean_p,
        mean_q=mean_q,
        dt=dt,
        t_end=t_end,
        stable_window_s=stable_window_s,
        C_bps=C_bps,
        pkt_bytes=pkt_bytes,
        kmin_bytes=kmin_bytes,
        kmax_bytes=kmax_bytes,
        pmax=pmax,
        tau_star=tau_star,
        a=a,
        r2=r2,
        b_free=b_free,
        c_free=c_free,
    )
    print(f"\nSaved data: {npz_path}")

    fig_path = figs_dir / "dcqcn_scaling_p_fit.png"
    plot_scaling(Ns, mean_p, a, exponent, fig_path)
    print(f"Saved figure: {fig_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
