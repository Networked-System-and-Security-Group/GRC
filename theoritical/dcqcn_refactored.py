from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable

import numpy as np


# Matplotlib is optional here: some environments may have an ABI mismatch
# between a system-installed matplotlib and a newer NumPy.
HAS_MPL = False
try:
    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    HAS_MPL = True
except Exception:
    plt = None


SCRIPT_DIR = Path(__file__).resolve().parent

def delayed_uniform(
    k: int,
    tau: float,
    dt: float,
    xs: np.ndarray,
    x_init: float,
) -> float:
    """Get x(t - tau) from a uniform-sampled history using linear interpolation.

    Args:
        k: current step index (t = k * dt)
        tau: delay (seconds)
        dt: step size (seconds)
        xs: history array where xs[i] == x(i*dt)
        x_init: value to use for t < 0
    """
    if tau <= 0:
        return float(xs[k])

    d = tau / dt
    kd = k - d
    if kd <= 0:
        return float(x_init)

    k0 = int(np.floor(kd))
    k1 = k0 + 1

    if k0 < 0:
        return float(x_init)
    if k1 >= len(xs):
        return float(xs[-1])

    w = float(kd - k0)
    return float((1.0 - w) * xs[k0] + w * xs[k1])


def _log1m_clipped(p: np.ndarray | float, eps: float) -> np.ndarray:
    """Return log(1-p) with p clipped away from 0 and 1 for numerical safety."""
    p_arr = np.asarray(p, dtype=np.float64)
    p_arr = np.clip(p_arr, eps, 1.0 - 1e-15)
    return np.log1p(-p_arr)


def _safe_den_pos(den: np.ndarray, eps: float = 1e-300) -> np.ndarray:
    """Ensure denominator is strictly positive to avoid inf/nan."""
    return np.maximum(den, eps)


@dataclass
class SenderParams:
    # alpha update
    g: float = 1 / 256
    tau0: float = 55e-6

    # Eq.(8)(9) time scale
    tau: float = 55e-6

    # control-loop delay
    tau_star: float = 50e-6

    # increase mechanism
    RAI_bps: float = 40e6
    B_bytes: float = 10 * 1024 * 1024
    T: float = 55e-6
    F: int = 5


class BottleNeck:
    """Shared bottleneck queue q(t) and RED marking p(q)."""

    def __init__(
        self,
        C_bps: float = 40e9,
        pkt_bytes: int = 1024,
        kmin_bytes: float = 5 * 1024,
        kmax_bytes: float = 200 * 1024,
        pmax: float = 0.01,
        q0_bytes: float = 0.0,
    ):
        self.pkt_bytes = int(pkt_bytes)
        self.C_pkts = float(C_bps / (8 * self.pkt_bytes))

        self.kmin = float(kmin_bytes)
        self.kmax = float(kmax_bytes)
        self.pmax = float(pmax)

        self.q_bytes = float(q0_bytes)
        self.p_init = self._red_mark_prob(self.q_bytes)

        self.t_hist: np.ndarray | None = None
        self.q_hist: np.ndarray | None = None
        self.p_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.t_hist = np.zeros(steps)
        self.q_hist = np.zeros(steps)
        self.p_hist = np.zeros(steps)

    def _red_mark_prob(self, q_bytes: float) -> float:
        """RED marking probability p(q)."""
        if q_bytes <= self.kmin:
            return 0.00001
        if q_bytes >= self.kmax:
            return 0.99999
        return ((q_bytes - self.kmin) / (self.kmax - self.kmin)) * self.pmax

    def mark_prob(self) -> float:
        return self._red_mark_prob(self.q_bytes)

    def record(self, k: int, t: float) -> float:
        if self.t_hist is None or self.q_hist is None or self.p_hist is None:
            raise RuntimeError("BottleNeck history not allocated")

        p = self.mark_prob()
        self.t_hist[k] = t
        self.q_hist[k] = self.q_bytes
        self.p_hist[k] = p
        return p

    def update(self, dt: float, senders: list["Sender"]) -> None:
        """Update queue using current senders' RC (packets/s)."""
        sum_RC = sum(s.RC for s in senders)
        d_q = (sum_RC - self.C_pkts) * self.pkt_bytes  # bytes/s
        self.q_bytes = max(0.0, self.q_bytes + d_q * dt)


class Sender:
    """One sender with its own (RC, RT, alpha) state.

    Internal units:
      - RC, RT are stored in packets/s
      - alpha is dimensionless
    """

    def __init__(
        self,
        name: str,
        params: SenderParams,
        pkt_bytes: int,
        RC0_bps: float,
        RT0_bps: float,
        alpha0: float = 0.0,
    ):
        self.name = str(name)
        self.p = params
        self.pkt_bytes = int(pkt_bytes)

        self.RC = float(RC0_bps / (8 * self.pkt_bytes))
        self.RT = float(RT0_bps / (8 * self.pkt_bytes))
        self.alpha = float(alpha0)

        self.RC_init = float(self.RC)

        self.RC_hist: np.ndarray | None = None
        self.RT_hist: np.ndarray | None = None
        self.alpha_hist: np.ndarray | None = None

    def allocate_history(self, steps: int) -> None:
        self.RC_hist = np.zeros(steps)
        self.RT_hist = np.zeros(steps)
        self.alpha_hist = np.zeros(steps)

    def record(self, k: int) -> None:
        if self.RC_hist is None or self.RT_hist is None or self.alpha_hist is None:
            raise RuntimeError(f"Sender {self.name} history not allocated")

        self.RC_hist[k] = self.RC
        self.RT_hist[k] = self.RT
        self.alpha_hist[k] = self.alpha

    def status_str(self) -> str:
        rc_gbps = self.RC * (8 * self.pkt_bytes) / 1e9
        rt_gbps = self.RT * (8 * self.pkt_bytes) / 1e9
        return f"{self.name}: RC={rc_gbps:.3f}Gbps RT={rt_gbps:.3f}Gbps alpha={self.alpha:.4f}"

    def _derivatives(self, k: int, dt: float, bn: BottleNeck) -> tuple[float, float, float]:
        """Compute (dRC/dt, dRT/dt, dalpha/dt) at step k using delayed values."""
        if bn.p_hist is None:
            raise RuntimeError("BottleNeck history not allocated")
        if self.RC_hist is None:
            raise RuntimeError(f"Sender {self.name} history not allocated")

        eps = 1e-12

        # delayed p and delayed RC
        # Use NumPy scalars here to match the original numeric behavior and avoid
        # Python-float overflow in expressions like (1-p)**(-B).
        p_d = np.float64(delayed_uniform(k, self.p.tau_star, dt, bn.p_hist, bn.p_init))
        RC_d = np.float64(delayed_uniform(k, self.p.tau_star, dt, self.RC_hist, self.RC_init))

        p_eff = np.maximum(p_d, eps)

        # Work in log-domain for (1-p) to avoid overflow for negative exponents.
        log_u = _log1m_clipped(p_d, eps)  # u = 1-p, log_u <= 0

        # ---- common probabilities ----
        # Pi0 = 1 - u^(tau0*RC_d) = -expm1((tau0*RC_d)*log(u))
        y_pi0 = (self.p.tau0 * RC_d) * log_u
        y_pi = (self.p.tau * RC_d) * log_u
        Pi0 = -np.expm1(y_pi0)
        Pi = -np.expm1(y_pi)

        # convert params to packets-based thresholds
        RAI = self.p.RAI_bps / (8 * self.pkt_bytes)  # packets/s per event
        B_pkts = self.p.B_bytes / self.pkt_bytes  # packets

        # ---- Phi_B, Phi_T ----
        # Rewrite to avoid u^(-x):
        # 1 / (u^{-x} - 1) = u^x / (1 - u^x)
        # Use expm1 for stable 1 - exp(y): 1 - u^x = 1 - exp(x*log_u) = -expm1(x*log_u)
        y_B = B_pkts * log_u
        den_B = _safe_den_pos(-np.expm1(y_B))
        uB = np.exp(y_B)

        y_T = (self.p.T * RC_d) * log_u
        den_T = _safe_den_pos(-np.expm1(y_T))
        uT = np.exp(y_T)

        # ---- Phi_B, Phi_T ----
        # Phi_B = p * u^{(F+1)B} / (1 - u^B)
        # Phi_T = p * u^{(F+1)T*RC} / (1 - u^{T*RC})
        Phi_B = p_eff * np.exp((self.p.F + 1.0) * y_B) / den_B
        Phi_T = p_eff * np.exp((self.p.F + 1.0) * y_T) / den_T

        # ---- Omega_B, Omega_T ----
        Omega_B = (RC_d * p_d) * (uB / den_B)
        Omega_T = (RC_d * p_d) * (uT / den_T)

        # Eq.(7): alpha
        d_alpha = (self.p.g / self.p.tau0) * (Pi0 - self.alpha)

        # Eq.(8): RT
        d_RT = -((self.RT - self.RC) / self.p.tau) * Pi + (RAI * RC_d * Phi_B) + (RAI * RC_d * Phi_T)

        # Eq.(9): RC
        d_RC = -((self.RC * self.alpha) / (2.0 * self.p.tau)) * Pi + ((self.RT - self.RC) / 2.0) * Omega_B + (
            (self.RT - self.RC) / 2.0
        ) * Omega_T

        return float(d_RC), float(d_RT), float(d_alpha)

    def update(self, k: int, dt: float, bn: BottleNeck) -> None:
        dRC, dRT, dalpha = self._derivatives(k, dt, bn)

        self.RC = max(0.0, self.RC + dRC * dt)
        self.RT = max(0.0, self.RT + dRT * dt)
        self.alpha = float(np.clip(self.alpha + dalpha * dt, 0.0, 1.0))


class Simulator:
    """Top-level orchestrator.

    Step order (per requirement):
      1) BottleNeck records p(q) and updates q using all Sender RC
      2) Each Sender updates itself using BottleNeck (and delayed histories)
    """

    def __init__(
        self,
        bottleneck: BottleNeck,
        senders: list[Sender],
        logger: Callable[[int, float, BottleNeck, list[Sender], float], None] | None = None,
    ):
        self.bn = bottleneck
        self.senders = list(senders)
        self.logger = logger

    def run(
        self,
        t_end: float = 0.01,
        dt: float = 2e-6,
        log_interval_s: float | None = 1e-3,
    ) -> dict:
        steps = int(np.ceil(t_end / dt)) + 1

        self.bn.allocate_history(steps)
        for s in self.senders:
            s.allocate_history(steps)

        ts = np.zeros(steps)

        log_every = None
        if log_interval_s is not None and log_interval_s > 0:
            log_every = max(1, int(round(log_interval_s / dt)))

        for k in range(steps):
            t = k * dt
            ts[k] = t

            # Record histories at time t (pre-update values)
            p = self.bn.record(k, t)
            for s in self.senders:
                s.record(k)

            if log_every is not None and (k % log_every == 0 or k == steps - 1):
                if self.logger is not None:
                    self.logger(k, t, self.bn, self.senders, p)

            # BottleNeck uses all Sender info to update itself
            self.bn.update(dt, self.senders)

            # Each Sender receives BottleNeck and updates itself
            for s in self.senders:
                s.update(k, dt, self.bn)

        out: dict = {
            "t": ts,
            "q_bytes": self.bn.q_hist.copy() if self.bn.q_hist is not None else None,
            "p": self.bn.p_hist.copy() if self.bn.p_hist is not None else None,
            "senders": {},
        }
        for s in self.senders:
            out["senders"][s.name] = {
                "RC_bps": s.RC_hist * (8 * s.pkt_bytes),
                "RT_bps": s.RT_hist * (8 * s.pkt_bytes),
                "alpha": s.alpha_hist.copy(),
            }
        return out


def plot_bottleneck_q_and_p(out: dict, out_dir: str | Path, prefix: str = "dcqcn") -> Path | None:
    """Plot q(t) (log-y) and p(t).

    Note: for log scale, we clamp q(t) to be at least 1.
    """
    if not HAS_MPL:
        return None

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    t_ms = out["t"] * 1e3
    q = np.asarray(out["q_bytes"], dtype=float)
    p = np.asarray(out["p"], dtype=float)

    bytes_per_mb = 1024.0 * 1024.0
    q_plot_mb = np.maximum(q, 1.0) / bytes_per_mb

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    ax1.plot(t_ms, q_plot_mb)
    ax1.set_yscale("log")
    ax1.set_ylim(bottom=1.0 / bytes_per_mb)
    ax1.set_ylabel("Queue (MB, log)")
    ax1.set_title("BottleNeck: q(t) and p(t)")

    ax2.plot(t_ms, p)
    ax2.set_xlabel("Time (ms)")
    ax2.set_ylabel("p(t)")

    fig.tight_layout()
    out_file = out_path / f"{prefix}_bottleneck.png"
    fig.savefig(out_file, dpi=200)
    plt.close(fig)
    return out_file


def plot_senders_rc_and_alpha(out: dict, out_dir: str | Path, prefix: str = "dcqcn") -> Path | None:
    """Plot per-sender RC(t) and alpha(t)."""
    if not HAS_MPL:
        return None

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    t_ms = out["t"] * 1e3
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)

    for name, sd in out["senders"].items():
        ax1.plot(t_ms, np.asarray(sd["RC_bps"], dtype=float) / 1e9, label=f"{name}: RC")
    ax1.set_ylabel("RC (Gbps)")
    ax1.set_title("Senders: RC(t) and alpha(t)")
    ax1.legend()

    for name, sd in out["senders"].items():
        ax2.plot(t_ms, sd["alpha"], label=f"{name}: alpha")
    ax2.set_xlabel("Time (ms)")
    ax2.set_ylabel("alpha")
    ax2.legend()

    fig.tight_layout()
    out_file = out_path / f"{prefix}_senders.png"
    fig.savefig(out_file, dpi=200)
    plt.close(fig)
    return out_file
