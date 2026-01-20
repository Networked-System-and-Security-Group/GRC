from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from theoritical.gscc_fluid.gscc_fluid_model import (
    GsccBottleNeck,
    GsccSender,
    GsccSenderParams,
    GsccSimulator,
    plot_gscc_fluid,
)


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "figs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Sanity-validation configuration using the user's requested topology/control params.
    #
    # NOTE on thresholds:
    # In `gscc-model.md`, the RTT threshold is modeled as theta = tau0 + T.
    # The user's "RTT阈值=1ms" is interpreted as the offset T (i.e., queueing-delay
    # threshold), since base RTT is tau0=4ms.
    C_bps = 400e9
    sender_p = GsccSenderParams(
        tau0_s=4e-3,
        tau_star_s=1e-3,
        alpha=0.5,
        T_s=1e-3,
        H=1.0 / 16.0,
        beta=0.4,
    )

    bn = GsccBottleNeck(C_bps=C_bps, q0_bits=0.0)
    s0 = GsccSender(
        name="S",
        params=sender_p,
        R0_bps=1.2 * C_bps,
        g0=0.0,
    )

    sim = GsccSimulator(bottleneck=bn, senders=[s0])
    out = sim.run(
        # Larger base RTT (4ms) => slower transient; simulate longer.
        t_end_s=0.5,
        dt_s=1e-5,
        log_interval_s=None,
    )

    # Quick numeric checks (not a formal proof):
    t = out["t_s"]
    q = out["q_bits"]
    R = out["senders"]["S"]["R_bps"]

    tail = t >= (t[-1] - 0.01)
    R_tail = R[tail]

    R_mean = float(np.mean(R_tail))
    R_std = float(np.std(R_tail))
    R_cv = float(R_std / max(R_mean, 1e-12))

    summary_txt = (
        f"C={C_bps/1e9:.3f}Gbps\n"
        f"Final R={R[-1]/1e9:.3f}Gbps, final q={q[-1]/8/1024:.3f}KB\n"
        f"Tail(10ms) R_mean={R_mean/1e9:.3f}Gbps R_cv={R_cv:.4f}\n"
    )
    (out_dir / "gscc_fluid_summary.txt").write_text(summary_txt)

    figs = plot_gscc_fluid(out, out_dir=out_dir, prefix="gscc_fluid")

    # Always print a minimal pointer (useful if running interactively)
    print(summary_txt.strip())
    if figs is None:
        print("matplotlib unavailable: skipped plotting")
    else:
        for _, path in figs.items():
            print(path)


if __name__ == "__main__":
    main()
