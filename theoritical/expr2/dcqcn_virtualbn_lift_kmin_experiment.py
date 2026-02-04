from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np


def _import_core():
    this_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(this_dir.parent))
    from dcqcn_refactored import Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha

    return Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha


@dataclass
class VirtualBottleNeckLift:
    """Virtual bottleneck with "lift" fix and waste accounting.

    Tracks cumulative arrived bytes from t=0. At time t, with rate C (bytes/s):

        q_virt(t) = max(0, arrived_bytes(t) - C*t)

    Fix (lift): if arrived_bytes(t) < C*t, we set arrived_bytes(t) := C*t.
    The lifted amount is accumulated into waste_bytes.

    Exposes the same interface as BottleNeck for Simulator compatibility.
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
        self.waste_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.t_hist = np.zeros(steps)
        self.q_hist = np.zeros(steps)
        self.p_hist = np.zeros(steps)
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
        if self.t_hist is None or self.q_hist is None or self.p_hist is None or self.waste_hist is None:
            raise RuntimeError("VirtualBottleNeckLift history not allocated")

        self.t = float(t)
        p = self.mark_prob()

        self.t_hist[k] = t
        self.q_hist[k] = self.q_bytes
        self.p_hist[k] = p
        self.waste_hist[k] = self.waste_bytes
        return p

    def update(self, dt: float, senders: list["Sender"]) -> None:
        # Accumulate arrived bytes during this step using current sender RC (packets/s).
        sum_RC_pkts_per_s = sum(s.RC for s in senders)
        self.arrived_bytes += float(sum_RC_pkts_per_s * self.pkt_bytes * dt)

        # Advance time to next step.
        self.t += float(dt)

        # Lift if arrived < C*t
        target = self.C_bytes_per_s * self.t
        if self.arrived_bytes < target:
            lift = target - self.arrived_bytes
            self.arrived_bytes = target
            self.waste_bytes += float(lift)

        # Virtual queue
        self.q_bytes = float(max(0.0, self.arrived_bytes - target))


def run_case(kmin_bytes: float, *, delta_bytes: float, out_dir: Path) -> dict:
    Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha = _import_core()

    pkt_bytes = 1024

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

    bn = VirtualBottleNeckLift(
        C_bps=40e9,
        pkt_bytes=pkt_bytes,
        kmin_bytes=float(kmin_bytes),
        kmax_bytes=float(kmin_bytes + delta_bytes),
        pmax=0.2,
    )

    sim = Simulator(bottleneck=bn, senders=senders, logger=None)
    out = sim.run(t_end=0.1, dt=2e-6, log_interval_s=None)

    # Attach waste stats for downstream reporting.
    out["waste_bytes_total"] = bn.waste_bytes
    out["kmin_bytes"] = float(kmin_bytes)
    out["kmax_bytes"] = float(kmin_bytes + delta_bytes)

    kmin_kb = int(round(float(kmin_bytes) / 1024.0))
    prefix = f"virtualbn_lift_kmin{kmin_kb}k"
    p1 = plot_bottleneck_q_and_p(out, out_dir=out_dir, prefix=prefix)
    p2 = plot_senders_rc_and_alpha(out, out_dir=out_dir, prefix=prefix)

    if p1 is not None:
        print(f"Saved figure: {p1.resolve()}")
    if p2 is not None:
        print(f"Saved figure: {p2.resolve()}")

    print(
        f"Kmin={int(kmin_bytes)}B Kmax={int(kmin_bytes + delta_bytes)}B | waste_bytes_total={bn.waste_bytes:.2f}"
    )

    return out


def main() -> int:
    this_dir = Path(__file__).resolve().parent
    out_dir = this_dir / "figs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep Kmax-Kmin constant (same as baseline: 200KB - 5KB = 195KB)
    delta_bytes = (200 * 1024) - (5 * 1024)

    cases = [5 * 1024, 50 * 1024]

    for kmin in cases:
        run_case(kmin, delta_bytes=delta_bytes, out_dir=out_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
