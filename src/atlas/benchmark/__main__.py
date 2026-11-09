"""CLI: ``python -m atlas.benchmark --preset standard --out results/benchmarks``."""

from __future__ import annotations

import argparse
from dataclasses import replace

from .runner import PRESETS, run_benchmark, write_report


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the NEXUS-PAY benchmark (synthetic data only).")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    ap.add_argument("--out", default="results/benchmarks")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    cfg = PRESETS[args.preset]
    if args.workers:
        cfg = replace(cfg, workers=args.workers)
    result = run_benchmark(cfg, progress=True)
    j, m = write_report(result, args.out)
    print(f"wrote {j} and {m}")


if __name__ == "__main__":
    main()
