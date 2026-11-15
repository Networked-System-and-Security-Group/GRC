#!/usr/bin/env python3
"""Run the fixed-count closed-loop matrix on a configured ASIC testbed."""
import argparse
from itertools import product
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

from common import REPO_ROOT, RESULTS_DIR


def plan():
    for rep in range(1, 4):
        # Preserve the ordering of the experiment protocol.
        points = list(product((16, 32, 64), (1, 2, 4, 8, 16, 32, 64), (40000, 400000)))
        random.Random(20261115 + rep).shuffle(points)
        for slots, flows, iters in points:
            yield dict(rep=rep, slots=slots, flows=flows, iters=iters)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('plan', 'run'))
    args = ap.parse_args()
    points = list(plan())
    if args.action == 'plan':
        print(json.dumps(points, indent=2))
        return 0

    # Keep runs separate so rerunning this command never mixes repetitions.
    RESULTS_DIR.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='closed-loop-sweep-', dir=RESULTS_DIR))
    (root/'plan.json').write_text(json.dumps(points, indent=2))
    print(f'Results: {root}', flush=True)
    for i, p in enumerate(points, 1):
        print(f'{i}/{len(points)}: {p}', flush=True)
        cmd = [sys.executable, str(REPO_ROOT/'scripts/run.py'), '--config', f"paper-loop-hm-s{p['slots']}",
               '--iters', str(p['iters']), '--flows', str(p['flows']), '--rep', str(p['rep']),
               '--rawdir', str(root/'raw'), '--csv', str(root/'trials.csv')]
        for _ in range(3):
            if subprocess.run(cmd).returncode == 0:
                break
        else:
            print(f'Trial {i} failed after three attempts; see {root}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
