from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Callable

import numpy as np

# Reuse the same uniform-delay interpolation helper.
#
# This file is often executed as a script (via validate_gscc_fluid.py), so we
# explicitly ensure the repo root is on sys.path to make `theoritical.*` imports
# work reliably.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from theoritical.dcqcn_refactored import delayed_uniform


# Matplotlib is optional here (same reason as dcqcn_refactored.py).
HAS_MPL = False
try:
    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    HAS_MPL = True
except Exception:
    plt = None


@dataclass
class GsccSenderParams:
    """Sender-side parameters for the GSCC refRate fluid model.

    Model equations are documented in `theoritical/gscc-model.md`.

    Units:
      - Time: seconds
      - Rates: bps
      - Queue: bits (as observed via q(t-...))
    """

    # Feedback delay / base RTT
    tau0_s: float = 55e-6

    # Update interval (epoch duration)
    tau_star_s: float = 50e-6

    # EWMA smoothing coefficient in g dynamics
    alpha: float = 0.2

    # Threshold offset T (theta = tau0 + T)
    T_s: float = 10e-6

    # Additive increase strength (A = H*C)
    H: float = 0.01

    # Multiplicative decrease factor per RTT (continuous decay kappa = ln(beta)/tau0)
    beta: float = 0.8

    # Cross-threshold cautious factor (TIMELY uses 1/3)
    cautious_factor: float = 1.0 / 3.0


class GsccBottleNeck:
    """Network-side plant: reflected fluid queue q(t) with capacity C.

    (E1) dq/dt = R - C with reflected boundary at q=0.

    Units:
      - q: bits
      - C: bps
    """

    def __init__(self, C_bps: float = 40e9, q0_bits: float = 0.0):
        self.C_bps = float(C_bps)
        self.q_bits = float(q0_bits)
        self.q_init = float(self.q_bits)

        self.t_hist: np.ndarray | None = None
        self.q_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.t_hist = np.zeros(steps)
        self.q_hist = np.zeros(steps)

    def record(self, k: int, t: float) -> None:
        if self.t_hist is None or self.q_hist is None:
            raise RuntimeError("BottleNeck history not allocated")
        self.t_hist[k] = t
        self.q_hist[k] = self.q_bits

    def _dq_dt(self, q_bits: float, R_total_bps: float) -> float:
        if q_bits > 0.0:
            return R_total_bps - self.C_bps
        return max(R_total_bps - self.C_bps, 0.0)

    def update(self, dt_s: float, senders: list["GsccSender"]) -> None:
        R_total = float(sum(s.R_bps for s in senders))
        dq = self._dq_dt(self.q_bits, R_total)
        self.q_bits = float(max(0.0, self.q_bits + dq * dt_s))


class GsccSender:
    """Sender-side controller: ref rate R(t) and normalized RTT gradient g(t)."""

    def __init__(
        self,
        name: str,
        params: GsccSenderParams,
        R0_bps: float,
        g0: float = 0.0,
    ):
        self.name = str(name)
        self.p = params

        self.R_bps = float(R0_bps)
        self.g = float(g0)

        self.R_init = float(self.R_bps)
        self.g_init = float(self.g)

        self.R_hist: np.ndarray | None = None
        self.g_hist: np.ndarray | None = None
        self.r_hist: np.ndarray | None = None
        self.rhat_hist: np.ndarray | None = None
        self.sigma_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.R_hist = np.zeros(steps)
        self.g_hist = np.zeros(steps)
        self.r_hist = np.zeros(steps)
        self.rhat_hist = np.zeros(steps)
        self.sigma_hist = np.zeros(steps)

    def record(self, k: int, dt_s: float, bn: GsccBottleNeck) -> None:
        if (
            self.R_hist is None
            or self.g_hist is None
            or self.r_hist is None
            or self.rhat_hist is None
            or self.sigma_hist is None
        ):
            raise RuntimeError(f"Sender {self.name} history not allocated")

        self.R_hist[k] = self.R_bps
        self.g_hist[k] = self.g

        r, rhat, sigma, _, _ = self._observe_and_compute(k, dt_s, bn)
        self.r_hist[k] = r
        self.rhat_hist[k] = rhat
        self.sigma_hist[k] = sigma

    def _sigma(self, r_s: float, rhat_s: float) -> float:
        theta = self.p.tau0_s + self.p.T_s
        if (r_s - theta) * (rhat_s - theta) >= 0.0:
            return 1.0
        return float(self.p.cautious_factor)

    def _observe_and_compute(
        self, k: int, dt_s: float, bn: GsccBottleNeck
    ) -> tuple[float, float, float, float, float]:
        if bn.q_hist is None:
            raise RuntimeError("BottleNeck history not allocated")

        q_tau0 = delayed_uniform(k, self.p.tau0_s, dt_s, bn.q_hist, bn.q_init)
        q_tau0_tau_star = delayed_uniform(
            k, self.p.tau0_s + self.p.tau_star_s, dt_s, bn.q_hist, bn.q_init
        )

        # (E2) RTT (seconds)
        r_s = self.p.tau0_s + (q_tau0 / bn.C_bps)

        # (E4) predicted RTT
        rhat_s = r_s + self.g * (self.p.tau0_s * self.p.tau0_s / self.p.tau_star_s)

        sigma = self._sigma(r_s, rhat_s)
        return float(r_s), float(rhat_s), float(sigma), float(q_tau0), float(q_tau0_tau_star)

    def _derivatives(self, k: int, dt_s: float, bn: GsccBottleNeck) -> tuple[float, float]:
        if self.p.tau0_s <= 0:
            raise ValueError("tau0_s must be > 0")
        if self.p.tau_star_s <= 0:
            raise ValueError("tau_star_s must be > 0")
        if not (0.0 < self.p.beta < 1.0):
            raise ValueError("beta must be in (0, 1)")

        r_s, rhat_s, sigma, q_tau0, q_tau0_tau_star = self._observe_and_compute(k, dt_s, bn)

        # (E3) normalized RTT gradient g(t)
        g_target = (q_tau0 - q_tau0_tau_star) / (bn.C_bps * self.p.tau0_s)
        d_g = (self.p.alpha / self.p.tau_star_s) * (-self.g + g_target)

        # (E6) reference rate control
        A = self.p.H * bn.C_bps
        kappa = float(np.log(self.p.beta) / self.p.tau0_s)  # negative
        q_thresh = bn.C_bps * self.p.T_s

        if q_tau0 < q_thresh:
            d_R = sigma * A
        else:
            d_R = sigma * kappa * self.R_bps

        return float(d_R), float(d_g)

    def update(self, k: int, dt_s: float, bn: GsccBottleNeck) -> None:
        dR, dg = self._derivatives(k, dt_s, bn)
        self.R_bps = float(max(0.0, self.R_bps + dR * dt_s))
        self.g = float(self.g + dg * dt_s)


class GsccSimulator:
    """Top-level orchestrator (dcqcn_refactored-style).

    Step order (per step):
      1) BottleNeck records q(t) and updates q using all Sender R
      2) Each Sender records derived signals and updates itself using BottleNeck (and delays)
    """

    def __init__(
        self,
        bottleneck: GsccBottleNeck,
        senders: list[GsccSender],
        logger: Callable[[int, float, GsccBottleNeck, list[GsccSender]], None] | None = None,
    ):
        self.bn = bottleneck
        self.senders = list(senders)
        self.logger = logger

    def run(
        self,
        t_end_s: float = 0.05,
        dt_s: float = 1e-6,
        log_interval_s: float | None = 1e-3,
    ) -> dict:
        if dt_s <= 0:
            raise ValueError("dt_s must be > 0")

        steps = int(np.ceil(t_end_s / dt_s)) + 1

        self.bn.allocate_history(steps)
        for s in self.senders:
            s.allocate_history(steps)

        ts = np.zeros(steps)

        log_every = None
        if log_interval_s is not None and log_interval_s > 0:
            log_every = max(1, int(round(log_interval_s / dt_s)))

        for k in range(steps):
            t = k * dt_s
            ts[k] = t

            # Record histories at time t (pre-update values)
            self.bn.record(k, t)
            for s in self.senders:
                s.record(k, dt_s, self.bn)

            if log_every is not None and (k % log_every == 0 or k == steps - 1):
                if self.logger is not None:
                    self.logger(k, t, self.bn, self.senders)

            # BottleNeck uses all Sender info to update itself
            self.bn.update(dt_s, self.senders)

            # Each Sender receives BottleNeck and updates itself
            for s in self.senders:
                s.update(k, dt_s, self.bn)

        out: dict = {
            "t_s": ts,
            "q_bits": self.bn.q_hist.copy() if self.bn.q_hist is not None else None,
            "senders": {},
        }

        for s in self.senders:
            out["senders"][s.name] = {
                "R_bps": s.R_hist.copy() if s.R_hist is not None else None,
                "g": s.g_hist.copy() if s.g_hist is not None else None,
                "r_s": s.r_hist.copy() if s.r_hist is not None else None,
                "rhat_s": s.rhat_hist.copy() if s.rhat_hist is not None else None,
                "sigma": s.sigma_hist.copy() if s.sigma_hist is not None else None,
                "params": s.p,
            }
        return out


def plot_gscc_fluid(out: dict, out_dir: str | Path, prefix: str = "gscc_fluid") -> dict[str, Path] | None:
    if not HAS_MPL:
        return None

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    t_ms = np.asarray(out["t_s"], dtype=float) * 1e3
    q_kb = np.asarray(out["q_bits"], dtype=float) / 8.0 / 1024.0

    results: dict[str, Path] = {}

    # q and R
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    ax1.plot(t_ms, q_kb)
    ax1.set_ylabel("Queue q (KB)")
    ax1.set_title("GSCC fluid model: q(t), R(t)")

    for name, sd in out.get("senders", {}).items():
        ax2.plot(t_ms, np.asarray(sd["R_bps"], dtype=float) / 1e9, label=f"{name}: R")
    ax2.set_xlabel("Time (ms)")
    ax2.set_ylabel("Ref rate R (Gbps)")
    if len(out.get("senders", {})) > 1:
        ax2.legend()

    fig.tight_layout()
    p1 = out_path / f"{prefix}_q_R.png"
    fig.savefig(p1, dpi=200)
    plt.close(fig)
    results["q_R"] = p1

    # g and sigma
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    for name, sd in out.get("senders", {}).items():
        ax1.plot(t_ms, np.asarray(sd["g"], dtype=float), label=f"{name}: g")
    ax1.set_ylabel("g (normalized gradient)")
    ax1.set_title("GSCC fluid model: g(t), sigma(t)")
    if len(out.get("senders", {})) > 1:
        ax1.legend()

    for name, sd in out.get("senders", {}).items():
        ax2.plot(t_ms, np.asarray(sd["sigma"], dtype=float), label=f"{name}: sigma")
    ax2.set_xlabel("Time (ms)")
    ax2.set_ylabel("sigma")
    if len(out.get("senders", {})) > 1:
        ax2.legend()

    fig.tight_layout()
    p2 = out_path / f"{prefix}_g_sigma.png"
    fig.savefig(p2, dpi=200)
    plt.close(fig)
    results["g_sigma"] = p2

    # r and rhat
    fig, ax = plt.subplots(1, 1, figsize=(8, 4))
    for name, sd in out.get("senders", {}).items():
        ax.plot(t_ms, np.asarray(sd["r_s"], dtype=float) * 1e6, label=f"{name}: r")
        ax.plot(t_ms, np.asarray(sd["rhat_s"], dtype=float) * 1e6, label=f"{name}: r_hat")
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("RTT (us)")
    ax.set_title("GSCC fluid model: r(t) and r_hat(t)")
    ax.legend()

    fig.tight_layout()
    p3 = out_path / f"{prefix}_r_rhat.png"
    fig.savefig(p3, dpi=200)
    plt.close(fig)
    results["r_rhat"] = p3

    return results
