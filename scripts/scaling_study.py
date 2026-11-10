"""Scaling study: runtime, throughput and peak memory of one simulated business day.

Usage: python scripts/scaling_study.py [--max-payments 500000]
Writes results/scaling.json. Hardware is recorded in the manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "results" / "scaling.json"

CHILD = r"""
import json, resource, sys, time, tracemalloc
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day
n, lv, ins = map(int, sys.argv[1:4])
t0 = time.perf_counter()
sc = generate_scenario(NexusPayConfig(n_institutions=n, payments_per_day=lv, instant_payments_per_day=ins,
                                      opening_liquidity_bp=600, credit_limit_bp=300), seed=1)
gen = time.perf_counter() - t0
t1 = time.perf_counter()
r = run_day(sc, SimulationSettings(policy="multilateral"))
sim = time.perf_counter() - t1
t2 = time.perf_counter()
ok = r.verify_replay()
rep = time.perf_counter() - t2
print(json.dumps({"institutions": n, "accounts": len(sc.accounts), "payments": len(sc.payments), "events": r.metrics["events"],
                  "generate_s": gen, "simulate_s": sim, "replay_s": rep, "replay_verified": ok,
                  "events_per_s": r.metrics["events"] / sim, "payments_per_s": len(sc.payments) / sim,
                  "lv_settlement_rate_value": r.metrics["large_value"]["settlement_rate_value"],
                  "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}))
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-payments", type=int, default=500_000)
    args = ap.parse_args()
    grid = [(16, 3_000, 2_000), (32, 12_000, 8_000), (64, 30_000, 20_000), (100, 60_000, 40_000), (100, 150_000, 100_000), (100, 300_000, 200_000)]
    rows = []
    for n, lv, ins in grid:
        if lv + ins > args.max_payments:
            continue
        out = subprocess.run([sys.executable, "-c", CHILD, str(n), str(lv), str(ins)], capture_output=True, text=True, check=True)
        row = json.loads(out.stdout.strip().splitlines()[-1])
        rows.append(row)
        print(json.dumps(row), flush=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"experiment": "single-day scaling, policy=multilateral, generator v2", "rows": rows, "manifest": {
        "python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
        "cpu_count": os.cpu_count(), "single_process": True,
        "note": "pure Python, one core; each row is a fresh subprocess so peak RSS is per row"}}, indent=1))


if __name__ == "__main__":
    main()
