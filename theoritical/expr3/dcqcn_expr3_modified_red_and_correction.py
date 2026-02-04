from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys
from typing import Literal

import numpy as np


def _import_core():
    this_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(this_dir.parent))
    from dcqcn_refactored import (
        Sender,
        SenderParams,
        Simulator,
        plot_bottleneck_q_and_p,
        plot_senders_rc_and_alpha,
    )

    return Sender, SenderParams, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha


PModel = Literal["scheme1_kq_threshold", "scheme2_k_q_minus_kmin", "classic_red"]


@dataclass
class VirtualBottleNeckLiftReducedParams:
    """Virtual bottleneck with lift, but reduced-parameter p(q).

    Common virtual queue definition:
      q(t) = max(0, arrived_bytes(t) - C*t)

    Lift:
      if arrived_bytes(t) < C*t: arrived_bytes(t) <- C*t
      waste_bytes accumulates the lifted amount.

    Marking models (all clamp to [p_min, p_max]):
      - scheme1_kq_threshold: if q <= threshold: p=p_min else p = k*q
      - scheme2_k_q_minus_kmin: if q <= kmin: p=p_min else p = k*(q-kmin)

    Parameters you tune per run:
      - k_slope (1/bytes)
      - threshold_bytes or kmin_bytes

    Other constants (not treated as tunable "parameters" in this expr3):
      - p_min and p_max are fixed safety clamps.
    """

    C_bps: float = 40e9
    pkt_bytes: int = 1024

    p_model: PModel = "scheme2_k_q_minus_kmin"

    # For scheme1: threshold_bytes is the trigger threshold.
    threshold_bytes: float = 5 * 1024

    # For scheme2/classic_red: kmin_bytes is the RED lower threshold.
    kmin_bytes: float = 5 * 1024

    # For classic_red only (kept fixed in scheme3 script unless you change it):
    kmax_bytes: float = 200 * 1024
    pmax: float = 0.2

    # Slope for scheme1/scheme2
    k_slope: float = 1.0e-6

    p_min: float = 0.00001
    p_max: float = 0.99999

    def __post_init__(self) -> None:
        self.pkt_bytes = int(self.pkt_bytes)
        self.C_bytes_per_s = float(self.C_bps / 8.0)

        self.threshold_bytes = float(self.threshold_bytes)
        self.kmin_bytes = float(self.kmin_bytes)
        self.kmax_bytes = float(self.kmax_bytes)
        self.pmax = float(self.pmax)
        self.k_slope = float(self.k_slope)

        self.t = 0.0
        self.arrived_bytes = 0.0
        self.waste_bytes = 0.0

        self.q_bytes = 0.0
        self.p_init = self._mark_prob(self.q_bytes)

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

    def _clip_p(self, p: float) -> float:
        return float(np.clip(p, self.p_min, self.p_max))

    def _mark_prob(self, q_bytes: float) -> float:
        q = float(q_bytes)

        if self.p_model == "scheme1_kq_threshold":
            if q <= self.threshold_bytes:
                return self.p_min
            return self._clip_p(self.k_slope * q)

        if self.p_model == "scheme2_k_q_minus_kmin":
            if q <= self.kmin_bytes:
                return self.p_min
            return self._clip_p(self.k_slope * (q - self.kmin_bytes))

        if self.p_model == "classic_red":
            # Original RED (3 knobs) kept for scheme3 correction experiment.
            if q <= self.kmin_bytes:
                return self.p_min
            if q >= self.kmax_bytes:
                return self.p_max
            return self._clip_p(((q - self.kmin_bytes) / (self.kmax_bytes - self.kmin_bytes)) * self.pmax)

        raise ValueError(f"Unknown p_model: {self.p_model}")

    def mark_prob(self) -> float:
        return self._mark_prob(self.q_bytes)

    def record(self, k: int, t: float) -> float:
        if (
            self.t_hist is None
            or self.q_hist is None
            or self.p_hist is None
            or self.arrived_hist is None
            or self.ct_hist is None
            or self.waste_hist is None
        ):
            raise RuntimeError("history not allocated")

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

        self.t += float(dt)
        ct = self.C_bytes_per_s * self.t

        # Lift
        if self.arrived_bytes < ct:
            lift = ct - self.arrived_bytes
            self.arrived_bytes = ct
            self.waste_bytes += float(lift)

        self.q_bytes = float(max(0.0, self.arrived_bytes - ct))


@dataclass
class VirtualBottleNeckPeriodicExpCorrection:
    """Virtual bottleneck without per-step lift; instead periodically correct arrived_bytes toward C*t.

    - Always accumulates arrived bytes from senders.
    - Virtual queue: q = max(0, arrived_bytes - C*t).
    - Every `corr_interval_s`, if arrived_bytes < C*t, do a smooth exponential correction:

        arrived <- C*t - (C*t - arrived) * exp(-corr_interval_s / tau_corr_s)

      The amount added is tracked as `waste_bytes`.

    Marking uses classic RED (kmin/kmax/pmax) with fixed defaults.

    Tunable knobs (2):
      - corr_interval_s
      - tau_corr_s
    """

    C_bps: float = 40e9
    pkt_bytes: int = 1024

    kmin_bytes: float = 5 * 1024
    kmax_bytes: float = 200 * 1024
    pmax: float = 0.2

    p_min: float = 0.00001
    p_max: float = 0.99999

    corr_interval_s: float = 1e-3
    tau_corr_s: float = 2e-3

    def __post_init__(self) -> None:
        self.pkt_bytes = int(self.pkt_bytes)
        self.C_bytes_per_s = float(self.C_bps / 8.0)

        self.kmin_bytes = float(self.kmin_bytes)
        self.kmax_bytes = float(self.kmax_bytes)
        self.pmax = float(self.pmax)

        self.corr_interval_s = float(self.corr_interval_s)
        self.tau_corr_s = float(self.tau_corr_s)
        if self.corr_interval_s <= 0:
            raise ValueError("corr_interval_s must be > 0")
        if self.tau_corr_s <= 0:
            raise ValueError("tau_corr_s must be > 0")

        self.t = 0.0
        self.arrived_bytes = 0.0
        self.waste_bytes = 0.0

        self.q_bytes = 0.0
        self.p_init = self._red_mark_prob(self.q_bytes)

        self._next_corr_t = 0.0

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

    def _clip_p(self, p: float) -> float:
        return float(np.clip(p, self.p_min, self.p_max))

    def _red_mark_prob(self, q_bytes: float) -> float:
        q = float(q_bytes)
        if q <= self.kmin_bytes:
            return self.p_min
        if q >= self.kmax_bytes:
            return self.p_max
        return self._clip_p(((q - self.kmin_bytes) / (self.kmax_bytes - self.kmin_bytes)) * self.pmax)

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
            raise RuntimeError("history not allocated")

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

        self.t += float(dt)
        ct = self.C_bytes_per_s * self.t

        # Periodic exponential correction (toward ct) if arrived < ct.
        if self.t + 1e-15 >= self._next_corr_t:
            self._next_corr_t += self.corr_interval_s
            if self.arrived_bytes < ct:
                gap = ct - self.arrived_bytes
                decay = float(np.exp(-self.corr_interval_s / self.tau_corr_s))
                new_gap = gap * decay
                new_arrived = ct - new_gap
                added = new_arrived - self.arrived_bytes
                if added > 0:
                    self.arrived_bytes = float(new_arrived)
                    self.waste_bytes += float(added)

        self.q_bytes = float(max(0.0, self.arrived_bytes - ct))


def _plot_arrived_vs_ct_and_waste(bn, out_path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    if bn.t_hist is None or bn.arrived_hist is None or bn.ct_hist is None or bn.waste_hist is None:
        raise RuntimeError("Missing trace history")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_per_mb = 1024.0 * 1024.0
    t_ms = bn.t_hist * 1e3
    arrived_mb = bn.arrived_hist / bytes_per_mb
    ct_mb = bn.ct_hist / bytes_per_mb
    waste_mb = bn.waste_hist / bytes_per_mb

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8, 6.2), sharex=True)

    ax0.plot(t_ms, arrived_mb, label="arrived_bytes(t)")
    ax0.plot(t_ms, ct_mb, label="C*t (service bytes)")
    ax0.set_ylabel("MB")
    ax0.set_title(title)
    ax0.grid(True, alpha=0.3)
    ax0.legend()

    ax1.plot(t_ms, waste_mb, label="waste_bytes(t)")
    ax1.axhline(0.0, color="k", linewidth=0.8, alpha=0.4)
    ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("MB")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def _plot_arr_minus_ct_kb(bn, out_path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
    import matplotlib.pyplot as plt

    if bn.t_hist is None or bn.arrived_hist is None or bn.ct_hist is None:
        raise RuntimeError("Missing trace history")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_ms = bn.t_hist * 1e3
    arr_minus_ct_kb = (bn.arrived_hist - bn.ct_hist) / 1024.0

    fig, ax = plt.subplots(1, 1, figsize=(8, 4.0))
    ax.plot(t_ms, arr_minus_ct_kb, label="arrived_bytes(t) - C*t")
    ax.axhline(0.0, color="k", linewidth=0.8, alpha=0.4)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("KB")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def _rc_convergence_metrics(out: dict, tail_ms: float = 20.0) -> dict:
    t_ms = np.asarray(out["t"], dtype=float) * 1e3
    t_end = float(t_ms[-1])
    mask = t_ms >= (t_end - tail_ms)

    metrics: dict[str, float] = {}
    for name, sd in out["senders"].items():
        rc_gbps = np.asarray(sd["RC_bps"], dtype=float) / 1e9
        tail = rc_gbps[mask]
        mean = float(np.mean(tail)) if tail.size else float(np.mean(rc_gbps))
        std = float(np.std(tail)) if tail.size else float(np.std(rc_gbps))
        cv = float(std / mean) if mean > 1e-12 else float("nan")
        metrics[f"{name}_rc_mean_gbps"] = mean
        metrics[f"{name}_rc_std_gbps"] = std
        metrics[f"{name}_rc_cv"] = cv

    return metrics


def _write_summary_csv(rows: list[dict], out_path: Path) -> None:
    if not rows:
        return

    # Stable column order: union of all keys, with common keys first.
    preferred = [
        "scheme",
        "p_model",
        "threshold_kb",
        "kmin_kb",
        "k_slope",
        "k_scale",
        "corr_interval_ms",
        "tau_corr_ms",
        "waste_mb",
    ]
    all_keys = set().union(*(r.keys() for r in rows))
    cols = [c for c in preferred if c in all_keys] + sorted([k for k in all_keys if k not in preferred])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(c, "")) for c in cols) + "\n")


def _common_senders(pkt_bytes: int = 1024):
    Sender, SenderParams, _, _, _ = _import_core()
    return [
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


def _run_and_plot(
    *,
    bn,
    senders,
    figs: Path,
    prefix: str,
    dt: float,
    t_end: float,
    log_to_file: bool = False,
    make_plots: bool = False,
) -> tuple[dict, Path | None]:
    _, _, Simulator, plot_bottleneck_q_and_p, plot_senders_rc_and_alpha = _import_core()

    log_path = figs / f"{prefix}_1ms.log"
    logger = None
    if log_to_file:
        with log_path.open("w", encoding="utf-8") as log_f:
            def logger(k: int, t: float, bn_obj, senders_obj, p: float) -> None:
                q_mb = bn_obj.q_bytes / (1024.0 * 1024.0)
                arrived_mb = bn_obj.arrived_bytes / (1024.0 * 1024.0)
                ct_mb = (bn_obj.C_bytes_per_s * t) / (1024.0 * 1024.0)
                arr_minus_ct_kb = (bn_obj.arrived_bytes - (bn_obj.C_bytes_per_s * t)) / 1024.0
                waste_mb = bn_obj.waste_bytes / (1024.0 * 1024.0)

                sender_parts = []
                for s in senders_obj:
                    rc_gbps = (s.RC * (8 * s.pkt_bytes)) / 1e9
                    sender_parts.append(f"{s.name}:RC={rc_gbps:.3f}Gbps a={s.alpha:.4f}")

                log_f.write(
                    f"t={t*1e3:7.3f}ms | q={q_mb:8.4f}MB p={p:7.5f} "
                    f"arr={arrived_mb:8.3f}MB ct={ct_mb:8.3f}MB (arr-ct)={arr_minus_ct_kb:9.3f}KB "
                    f"waste={waste_mb:8.3f}MB | "
                    + " ".join(sender_parts)
                    + "\n"
                )
                log_f.flush()

            sim = Simulator(bottleneck=bn, senders=senders, logger=logger)
            out = sim.run(t_end=t_end, dt=dt, log_interval_s=1e-3)
    else:
        sim = Simulator(bottleneck=bn, senders=senders, logger=None)
        out = sim.run(t_end=t_end, dt=dt, log_interval_s=None)

    if make_plots:
        # Standard plots
        plot_bottleneck_q_and_p(out, out_dir=figs, prefix=prefix)
        plot_senders_rc_and_alpha(out, out_dir=figs, prefix=prefix)

        # Arrived/Ct/waste + (arr-ct) KB
        _plot_arrived_vs_ct_and_waste(bn, figs / f"{prefix}_arrived_vs_ct.png", title=f"{prefix}: arrived_bytes vs C*t")
        _plot_arr_minus_ct_kb(bn, figs / f"{prefix}_arr_minus_ct.png", title=f"{prefix}: arrived_bytes - C*t")

    return out, log_path


def main() -> int:
    this_dir = Path(__file__).resolve().parent
    figs = this_dir / "figs"
    figs.mkdir(parents=True, exist_ok=True)

    dt = 2e-6
    # Keep it reasonably fast: we sweep many parameter combos.
    t_end = 0.05

    # Baseline slope from classic RED: pmax/(Kmax-Kmin)
    k0 = 0.2 / ((200 - 5) * 1024)

    summary_rows: list[dict] = []
    replay_queue: list[tuple[str, dict]] = []

    # -----------------
    # Scheme 1: p = k*q, only if q > threshold
    # -----------------
    for threshold_kb in [5, 50]:
        for k_scale in [0.5, 1.0, 2.0]:
            k = k0 * k_scale
            bn = VirtualBottleNeckLiftReducedParams(
                p_model="scheme1_kq_threshold",
                threshold_bytes=threshold_kb * 1024,
                k_slope=k,
            )
            senders = _common_senders(pkt_bytes=bn.pkt_bytes)
            prefix = f"expr3_s1_th{threshold_kb}k_kx{k_scale:g}"
            out, _ = _run_and_plot(
                bn=bn,
                senders=senders,
                figs=figs,
                prefix=prefix,
                dt=dt,
                t_end=t_end,
                log_to_file=False,
                make_plots=False,
            )

            m = _rc_convergence_metrics(out)
            row = {
                "scheme": "scheme1",
                "p_model": bn.p_model,
                "threshold_kb": threshold_kb,
                "k_slope": k,
                "k_scale": k_scale,
                "waste_mb": bn.waste_bytes / (1024.0 * 1024.0),
            }
            row.update(m)
            summary_rows.append(row)
            replay_queue.append(("scheme1", {"threshold_kb": threshold_kb, "k_scale": k_scale, "k": k}))

    # -----------------
    # Scheme 2: p = k*(q-Kmin)
    # -----------------
    for kmin_kb in [5, 50]:
        for k_scale in [0.5, 1.0, 2.0]:
            k = k0 * k_scale
            bn = VirtualBottleNeckLiftReducedParams(
                p_model="scheme2_k_q_minus_kmin",
                kmin_bytes=kmin_kb * 1024,
                k_slope=k,
            )
            senders = _common_senders(pkt_bytes=bn.pkt_bytes)
            prefix = f"expr3_s2_kmin{kmin_kb}k_kx{k_scale:g}"
            out, _ = _run_and_plot(
                bn=bn,
                senders=senders,
                figs=figs,
                prefix=prefix,
                dt=dt,
                t_end=t_end,
                log_to_file=False,
                make_plots=False,
            )

            m = _rc_convergence_metrics(out)
            row = {
                "scheme": "scheme2",
                "p_model": bn.p_model,
                "kmin_kb": kmin_kb,
                "k_slope": k,
                "k_scale": k_scale,
                "waste_mb": bn.waste_bytes / (1024.0 * 1024.0),
            }
            row.update(m)
            summary_rows.append(row)
            replay_queue.append(("scheme2", {"kmin_kb": kmin_kb, "k_scale": k_scale, "k": k}))

    # -----------------
    # Scheme 3: periodic exponential correction (no per-step lift)
    # -----------------
    for corr_interval_ms in [0.2, 1.0, 5.0]:
        for tau_corr_ms in [0.5, 2.0, 10.0]:
            bn = VirtualBottleNeckPeriodicExpCorrection(
                corr_interval_s=corr_interval_ms * 1e-3,
                tau_corr_s=tau_corr_ms * 1e-3,
                # Keep classic RED constants aligned with expr2 defaults.
                kmin_bytes=5 * 1024,
                kmax_bytes=200 * 1024,
                pmax=0.2,
            )
            senders = _common_senders(pkt_bytes=bn.pkt_bytes)
            prefix = f"expr3_s3_corr{corr_interval_ms:g}ms_tau{tau_corr_ms:g}ms"
            out, _ = _run_and_plot(
                bn=bn,
                senders=senders,
                figs=figs,
                prefix=prefix,
                dt=dt,
                t_end=t_end,
                log_to_file=False,
                make_plots=False,
            )

            m = _rc_convergence_metrics(out)
            row = {
                "scheme": "scheme3",
                "p_model": "classic_red",
                "corr_interval_ms": corr_interval_ms,
                "tau_corr_ms": tau_corr_ms,
                "waste_mb": bn.waste_bytes / (1024.0 * 1024.0),
            }
            row.update(m)
            summary_rows.append(row)
            replay_queue.append((
                "scheme3",
                {"corr_interval_ms": corr_interval_ms, "tau_corr_ms": tau_corr_ms},
            ))

    _write_summary_csv(summary_rows, figs / "expr3_summary.csv")

    # Re-run a small number of representative / best cases WITH plots and 1ms logs.
    # Criterion: smallest waste_mb per scheme.
    by_scheme: dict[str, list[dict]] = {"scheme1": [], "scheme2": [], "scheme3": []}
    for r in summary_rows:
        by_scheme[str(r["scheme"])].append(r)

    for scheme in ["scheme1", "scheme2", "scheme3"]:
        rows = sorted(by_scheme[scheme], key=lambda x: float(x.get("waste_mb", 1e99)))
        for top_idx, r in enumerate(rows[:2]):
            if scheme == "scheme1":
                threshold_kb = int(r["threshold_kb"])
                k_scale = float(r["k_scale"])
                k = float(r["k_slope"])
                bn = VirtualBottleNeckLiftReducedParams(
                    p_model="scheme1_kq_threshold",
                    threshold_bytes=threshold_kb * 1024,
                    k_slope=k,
                )
                senders = _common_senders(pkt_bytes=bn.pkt_bytes)
                prefix = f"expr3_best_s1_th{threshold_kb}k_kx{k_scale:g}_rank{top_idx+1}"
                _run_and_plot(bn=bn, senders=senders, figs=figs, prefix=prefix, dt=dt, t_end=0.1, log_to_file=True, make_plots=True)

            elif scheme == "scheme2":
                kmin_kb = int(r["kmin_kb"])
                k_scale = float(r["k_scale"])
                k = float(r["k_slope"])
                bn = VirtualBottleNeckLiftReducedParams(
                    p_model="scheme2_k_q_minus_kmin",
                    kmin_bytes=kmin_kb * 1024,
                    k_slope=k,
                )
                senders = _common_senders(pkt_bytes=bn.pkt_bytes)
                prefix = f"expr3_best_s2_kmin{kmin_kb}k_kx{k_scale:g}_rank{top_idx+1}"
                _run_and_plot(bn=bn, senders=senders, figs=figs, prefix=prefix, dt=dt, t_end=0.1, log_to_file=True, make_plots=True)

            else:
                corr_interval_ms = float(r["corr_interval_ms"])
                tau_corr_ms = float(r["tau_corr_ms"])
                bn = VirtualBottleNeckPeriodicExpCorrection(
                    corr_interval_s=corr_interval_ms * 1e-3,
                    tau_corr_s=tau_corr_ms * 1e-3,
                    kmin_bytes=5 * 1024,
                    kmax_bytes=200 * 1024,
                    pmax=0.2,
                )
                senders = _common_senders(pkt_bytes=bn.pkt_bytes)
                prefix = f"expr3_best_s3_corr{corr_interval_ms:g}ms_tau{tau_corr_ms:g}ms_rank{top_idx+1}"
                _run_and_plot(bn=bn, senders=senders, figs=figs, prefix=prefix, dt=dt, t_end=0.1, log_to_file=True, make_plots=True)

    print(f"Saved summary: {(figs / 'expr3_summary.csv').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
