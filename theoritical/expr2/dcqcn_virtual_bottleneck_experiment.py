from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

import numpy as np


def _import_core():
    # Allow running from any cwd.
    this_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(this_dir.parent))
    from dcqcn_refactored import Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha

    return Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha


@dataclass
class VirtualBottleNeck:
    """Virtual bottleneck.

    It tracks cumulative arrived bytes from t=0. At time t, it estimates the queue as:

        q_est(t) = max(0, arrived_bytes(t) - C_bytes_per_s * t)

    and then feeds q_est into RED to get p(q_est).

    Interface matches what Simulator expects: allocate_history(), record(), update().
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

        self.q_bytes = 0.0
        self.p_init = self._red_mark_prob(self.q_bytes)

        self.t_hist: np.ndarray | None = None
        self.q_hist: np.ndarray | None = None
        self.p_hist: np.ndarray | None = None

        self.arrived_hist: np.ndarray | None = None
        self.ct_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.t_hist = np.zeros(steps)
        self.q_hist = np.zeros(steps)
        self.p_hist = np.zeros(steps)

        self.arrived_hist = np.zeros(steps)
        self.ct_hist = np.zeros(steps)

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
        ):
            raise RuntimeError("VirtualBottleNeck history not allocated")

        # Keep internal time consistent with Simulator time.
        self.t = float(t)

        p = self.mark_prob()
        self.t_hist[k] = t
        self.q_hist[k] = self.q_bytes
        self.p_hist[k] = p

        # Extra observability: arrived bytes vs service bytes (C*t)
        self.arrived_hist[k] = self.arrived_bytes
        self.ct_hist[k] = self.C_bytes_per_s * t
        return p

    def update(self, dt: float, senders: list["Sender"]) -> None:
        # Accumulate arrived bytes during this step using current sender RC.
        # RC is in packets/s.
        sum_RC_pkts_per_s = sum(s.RC for s in senders)
        self.arrived_bytes += float(sum_RC_pkts_per_s * self.pkt_bytes * dt)

        # Advance internal time by dt (next step time).
        self.t += float(dt)

        # Virtual queue estimate.
        q_est = self.arrived_bytes - self.C_bytes_per_s * self.t
        self.q_bytes = float(max(0.0, q_est))


def main() -> int:
    Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha = _import_core()

    out_dir = Path(__file__).resolve().parent / "figs"
    out_dir.mkdir(parents=True, exist_ok=True)

    pkt_bytes = 1024

    # Keep parameters consistent with the previous experiments.
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

    bn = VirtualBottleNeck(
        C_bps=40e9,
        pkt_bytes=pkt_bytes,
        kmin_bytes=5 * 1024,
        kmax_bytes=200 * 1024,
        pmax=0.2,
    )

    log_path = out_dir / "virtualbn_bn_1ms.log"
    print(f"Writing 1ms logs to: {log_path.resolve()}")
    with log_path.open("w", encoding="utf-8") as log_f:
        def logger(k: int, t: float, bn_obj: VirtualBottleNeck, senders_obj: list[Sender], p: float) -> None:
            q_mb = bn_obj.q_bytes / (1024.0 * 1024.0)
            arrived_mb = bn_obj.arrived_bytes / (1024.0 * 1024.0)
            ct_mb = (bn_obj.C_bytes_per_s * t) / (1024.0 * 1024.0)
            arr_minus_ct_kb = (bn_obj.arrived_bytes - (bn_obj.C_bytes_per_s * t)) / 1024.0

            sender_parts = []
            for s in senders_obj:
                rc_gbps = (s.RC * (8 * s.pkt_bytes)) / 1e9
                sender_parts.append(f"{s.name}:RC={rc_gbps:.3f}Gbps a={s.alpha:.4f}")

            log_f.write(
                f"t={t*1e3:7.3f}ms | q={q_mb:8.4f}MB p={p:7.5f} "
                f"arr={arrived_mb:8.3f}MB ct={ct_mb:8.3f}MB (arr-ct)={arr_minus_ct_kb:9.3f}KB | "
                + " ".join(sender_parts)
                + "\n"
            )
            log_f.flush()

        sim = Simulator(bottleneck=bn, senders=senders, logger=logger)
        out = sim.run(t_end=0.1, dt=2e-6, log_interval_s=1e-3)

    prefix = "virtualbn_bn"
    p1 = plot_bottleneck_q_and_p(out, out_dir=out_dir, prefix=prefix)
    p2 = plot_senders_rc_and_alpha(out, out_dir=out_dir, prefix=prefix)

    # Additional figure: arrived_bytes(t) and C*t
    p3 = None
    try:
        import matplotlib

        matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
        import matplotlib.pyplot as plt

        if bn.t_hist is not None and bn.arrived_hist is not None and bn.ct_hist is not None:
            t_ms = bn.t_hist * 1e3
            bytes_per_mb = 1024.0 * 1024.0
            arrived_mb = bn.arrived_hist / bytes_per_mb
            ct_mb = bn.ct_hist / bytes_per_mb
            arr_minus_ct_kb = (bn.arrived_hist - bn.ct_hist) / 1024.0  # (arrived_bytes - C*t) in KB

            # Figure 1: arrived vs C*t (MB)
            fig0, ax0 = plt.subplots(1, 1, figsize=(8, 4.8))
            ax0.plot(t_ms, arrived_mb, label="arrived_bytes(t)")
            ax0.plot(t_ms, ct_mb, label="C*t (service bytes)")
            ax0.set_xlabel("Time (ms)")
            ax0.set_ylabel("MB")
            ax0.set_title("VirtualBottleNeck: arrived bytes vs C*t")
            ax0.grid(True, alpha=0.3)
            ax0.legend()
            fig0.tight_layout()
            p3 = out_dir / "virtualbn_bn_vs_ct.png"
            fig0.savefig(p3, dpi=220)
            plt.close(fig0)

            # Figure 2: arrived_bytes - C*t (KB)
            fig1, ax1 = plt.subplots(1, 1, figsize=(8, 4.0))
            ax1.plot(t_ms, arr_minus_ct_kb, label="arrived_bytes(t) - C*t")
            ax1.axhline(0.0, color="k", linewidth=0.8, alpha=0.4)
            ax1.set_xlabel("Time (ms)")
            ax1.set_ylabel("KB")
            ax1.set_title("VirtualBottleNeck: arrived_bytes - C*t")
            ax1.grid(True, alpha=0.3)
            ax1.legend()
            fig1.tight_layout()
            p4 = out_dir / "virtualbn_bn_arr_minus_ct.png"
            fig1.savefig(p4, dpi=220)
            plt.close(fig1)
    except Exception:
        p3 = None

    if p1 is not None:
        print(f"Saved figure: {p1.resolve()}")
    if p2 is not None:
        print(f"Saved figure: {p2.resolve()}")
    if p3 is not None:
        print(f"Saved figure: {p3.resolve()}")
    if "p4" in locals() and p4 is not None:
        print(f"Saved figure: {p4.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
