from __future__ import annotations

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--until", type=float, required=True)
    parser.add_argument("--count", type=int, default=0)
    args = parser.parse_args()

    inp = Path(args.input)
    out = Path(args.output)
    with inp.open() as f:
        n = int(f.readline().strip())
        flows = []
        for line in f:
            src, dst, pg, size, start = line.split()
            start_f = float(start)
            if start_f <= args.until:
                flows.append((int(src), int(dst), int(pg), int(size), start_f))
            if args.count > 0 and len(flows) >= args.count:
                break

    with out.open("w") as f:
        f.write(f"{len(flows)}\n")
        for src, dst, pg, size, start in flows:
            f.write(f"{src} {dst} {pg} {size} {start:.9f}\n")


if __name__ == "__main__":
    main()
