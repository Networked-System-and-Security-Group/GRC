from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

import numpy as np


def _import_core():
    this_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(this_dir.parent))
    from dcqcn_refactored import Sender, SenderParams, Simulator, plot_senders_rc_and_alpha

    return Sender, SenderParams, Simulator, plot_senders_rc_and_alpha


@dataclass
class VirtualBottleNeckLiftWithTrace:
    """Virtual bottleneck with lift + tracing arrived_bytes and C*t.

    - Accumulates arrived bytes from t=0.
    - Enforces arrived_bytes(t) >= C*t by lifting; lifted bytes are counted as waste.
    - Queue estimate: q = max(0, arrived_bytes - C*t).
    """

    C_bps: float = 40e9
    pkt_bytes: int = 1024

    kmin_bytes: float = 5 * 1024
    kmax_bytes: float = 200 * 1024
    pmax: float = 0.2

    def __post_init__(self) -> None:
        self.pkt_bytes = int(self.pkt_bytes)
        self.kmin = float(self.kmin_bytes)
        self.kmax = float(self.kmax_bytes)
        self.pmax = float(self.pmax)

        self.C_bytes_per_s = float(self.C_bps / 8.0)

        self.t = 0.0
        self.arrived_bytes = 0.0
        self.waste_bytes = 0.0

        self.q_bytes = 0.0
        self.p_init = self._red_mark_prob(self.q_bytes)

        self.t_hist: np.ndarray | None = None
        self.q_hist: np.ndarray | None = None
        self.p_hist: np.ndarray | None = None

        self.arrived_hist: np.ndarray | None = None
        self.ct_hist: np.ndarray | None = None
        self.waste_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.t_hist = np.zeros(steps)
        self.q_hist = np.zeros(steps)
        self.p_hist = np.zeros(steps)

        self.arrived_hist = np.zeros(steps)
        self.ct_hist = np.zeros(steps)
        self.waste_hist = np.zeros(steps)

    def _red_mark_prob(self, q_bytes: float) -> float:
        if q_bytes <= self.kmin:
            return 0.00001
        if q_bytes >= self.kmax:
            return 0.99999
        return ((q_bytes - self.kmin) / (self.kmax - self.kmin)) * self.pmax

    def mark_prob(self) -> float:
        return self._red_mark_prob(self.q_bytes)

    def record(self, k: int, t: float) -> float:
        if (
            self.t_hist is None
            or self.q_hist is None
            or self.p_hist is None
            or self.arrived_hist is None
            or self.ct_hist is None
            or self.waste_hist is None
        ):
            raise RuntimeError("VirtualBottleNeckLiftWithTrace history not allocated")

        self.t = float(t)
        p = self.mark_prob()

        self.t_hist[k] = t
        self.q_hist[k] = self.q_bytes
        self.p_hist[k] = p

        self.arrived_hist[k] = self.arrived_bytes
        self.ct_hist[k] = self.C_bytes_per_s * t
        self.waste_hist[k] = self.waste_bytes

        return p

    def update(self, dt: float, senders: list["Sender"]) -> None:
        sum_RC_pkts_per_s = sum(s.RC for s in senders)
        self.arrived_bytes += float(sum_RC_pkts_per_s * self.pkt_bytes * dt)

        # Advance to next step time.
        self.t += float(dt)

        target = self.C_bytes_per_s * self.t
        if self.arrived_bytes < target:
            lift = target - self.arrived_bytes
            self.arrived_bytes = target
            self.waste_bytes += float(lift)

        self.q_bytes = float(max(0.0, self.arrived_bytes - target))


def _plot_arrived_vs_ct(bn: VirtualBottleNeckLiftWithTrace, out_path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    if bn.t_hist is None or bn.arrived_hist is None or bn.ct_hist is None or bn.waste_hist is None:
        raise RuntimeError("Missing trace history")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_ms = bn.t_hist * 1e3
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8, 6.2), sharex=True)

    ax0.plot(t_ms, bn.arrived_hist, label="arrived_bytes(t)")
    ax0.plot(t_ms, bn.ct_hist, label="C*t (service bytes)")
    ax0.set_ylabel("Bytes")
    ax0.set_title(title)
    ax0.grid(True, alpha=0.3)
    ax0.legend()

    ax1.plot(t_ms, bn.waste_hist, label="waste_bytes(t) (cumulative lift)")
    ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("Bytes")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def run_case(
    *,
    kmin_bytes: float,
    delta_bytes: float,
    dt: float,
    t_end: float,
) -> tuple[VirtualBottleNeckLiftWithTrace, dict]:
    Sender, SenderParams, Simulator, _ = _import_core()

    pkt_bytes = 1024

    # Keep other parameters consistent with previous experiments.
    senders = [
        Sender(
            name="sender_A",
            params=SenderParams(tau_star=20e-6),
            pkt_bytes=pkt_bytes,
            RC0_bps=40e9,
            RT0_bps=40e9,
            alpha0=0.0,
        ),
        Sender(
            name="sender_B",
            params=SenderParams(tau_star=50e-6),
            pkt_bytes=pkt_bytes,
            RC0_bps=40e9,
            RT0_bps=40e9,
            alpha0=0.0,
        ),
    ]

    bn = VirtualBottleNeckLiftWithTrace(
        C_bps=40e9,
        pkt_bytes=pkt_bytes,
        kmin_bytes=float(kmin_bytes),
        kmax_bytes=float(kmin_bytes + delta_bytes),
        pmax=0.2,
    )

    sim = Simulator(bottleneck=bn, senders=senders, logger=None)
    out = sim.run(t_end=t_end, dt=dt, log_interval_s=None)
    out["waste_bytes_total"] = bn.waste_bytes
    out["kmin_bytes"] = float(kmin_bytes)
    out["kmax_bytes"] = float(kmin_bytes + delta_bytes)
    return bn, out


def main() -> int:
    this_dir = Path(__file__).resolve().parent
    figs = this_dir / "figs"
    figs.mkdir(parents=True, exist_ok=True)

    # Keep Kmax-Kmin constant (same as baseline gap: 200KB - 5KB = 195KB)
    delta_bytes = (200 * 1024) - (5 * 1024)

    dt = 2e-6
    t_end = 0.1

    # Part A: arrived_bytes vs C*t figures for 5KB, 50KB, 500KB
    for kmin_kb in [5, 50, 500]:
        kmin = kmin_kb * 1024
        bn, out = run_case(kmin_bytes=kmin, delta_bytes=delta_bytes, dt=dt, t_end=t_end)

        # Sender dynamics plot (RC and alpha)
        _, _, _, plot_senders_rc_and_alpha = _import_core()
        plot_senders_rc_and_alpha(out, out_dir=figs, prefix=f"virtualbn_lift_kmin{kmin_kb}k")

        out_path = figs / f"virtualbn_lift_arrived_vs_ct_kmin{kmin_kb}k.png"
        _plot_arrived_vs_ct(
            bn,
            out_path,
            title=f"VirtualBN+Lift: arrived_bytes vs C*t (Kmin={kmin_kb}KB, Kmax={int((kmin + delta_bytes)/1024)}KB)",
        )
        print(f"Saved figure: {out_path}")
        print(f"Kmin={kmin_kb}KB waste_bytes_total={bn.waste_bytes:.2f}")

    # Part B: waste bytes for Kmin sweep and plot
    sweep_kmins_kb = [5, 50, 100, 200, 300, 400, 500]
    wastes = []
    for kmin_kb in sweep_kmins_kb:
        bn, _ = run_case(kmin_bytes=kmin_kb * 1024, delta_bytes=delta_bytes, dt=dt, t_end=t_end)
        wastes.append(bn.waste_bytes)

    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(7.2, 4.8))
    ax.plot(sweep_kmins_kb, np.array(wastes) / (1024 * 1024), marker="o")
    ax.set_xlabel("Kmin (KB)")
    ax.set_ylabel("Waste bytes total (MB)")
    ax.set_title("VirtualBN+Lift: waste bytes vs Kmin")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    waste_fig = figs / "virtualbn_lift_waste_vs_kmin.png"
    fig.savefig(waste_fig, dpi=220)
    plt.close(fig)

    npz_path = figs / "virtualbn_lift_waste_vs_kmin.npz"
    np.savez(npz_path, kmin_kb=np.array(sweep_kmins_kb, dtype=float), waste_bytes=np.array(wastes, dtype=float))

    print(f"Saved figure: {waste_fig}")
    print(f"Saved data: {npz_path}")

    print("Kmin_KB\twaste_MB")
    for k, w in zip(sweep_kmins_kb, wastes):
        print(f"{k}\t{w/(1024*1024):.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
