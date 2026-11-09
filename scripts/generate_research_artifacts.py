"""Regenerate the research artifacts served by the API (results/*.json).

Usage: python scripts/generate_research_artifacts.py [--quick]
All outputs are produced from synthetic data by this repository's code.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from atlas.agents.game import deviation_analysis
from atlas.forecast import run_forecast_experiment
from atlas.scenario import NexusPayConfig
from atlas.settlement import Obligation, partial_netting_heuristic, partial_netting_milp
from atlas.simulation.rng import DeterministicRandomStream, derive_stream_seed

OUT = Path(__file__).resolve().parents[1] / "results"


def manifest(t0: float) -> dict:
    return {"created_at": datetime.now(timezone.utc).isoformat(), "runtime_s": time.perf_counter() - t0, "python": platform.python_version(),
            "platform": platform.platform(), "machine": platform.machine(), "data_origin": "synthetic"}


def netting_optimality(sizes=(10, 25, 50, 100, 200), instances=20, seed=99) -> dict:
    """Optimality gap of the gridlock heuristic vs the exact HiGHS MILP on random gridlocked queues."""
    t0 = time.perf_counter()
    rows = []
    for n_obl in sizes:
        gaps, h_ms, m_ms, statuses = [], [], [], []
        for k in range(instances):
            rng = DeterministicRandomStream(derive_stream_seed(seed, f"netting:{n_obl}:{k}"))
            n_acc = max(4, n_obl // 5)
            obs = []
            for i in range(n_obl):
                a = rng.randbelow(n_acc)
                b = (a + 1 + rng.randbelow(n_acc - 1)) % n_acc
                obs.append(Obligation(f"o{i}", f"A{a}", f"A{b}", 1_000 + rng.randbelow(99_000), 1 + rng.randbelow(2), None, i))
            avail = {f"A{i}": rng.randbelow(60_000) for i in range(n_acc)}
            h = partial_netting_heuristic(obs, avail)
            m = partial_netting_milp(obs, avail, time_limit_s=10)
            gaps.append(0.0 if m.gross_value_minor == 0 else 1 - h.gross_value_minor / m.gross_value_minor)
            h_ms.append(h.runtime_ms)
            m_ms.append(m.runtime_ms)
            statuses.append(m.status)
        rows.append({"obligations": n_obl, "instances": instances, "mean_gap": sum(gaps) / len(gaps), "max_gap": max(gaps),
                     "share_heuristic_optimal": sum(1 for g in gaps if g <= 1e-12) / len(gaps),
                     "heuristic_ms_mean": sum(h_ms) / len(h_ms), "milp_ms_mean": sum(m_ms) / len(m_ms),
                     "milp_optimal_share": statuses.count("optimal") / len(statuses)})
    return {"experiment": "netting optimality gap (gridlock-heuristic-v2 vs netting-milp-highs-v1)", "rows": rows, "manifest": manifest(t0)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    t0 = time.perf_counter()
    cfg = NexusPayConfig(n_institutions=12, payments_per_day=2_000, instant_payments_per_day=0)
    fc = run_forecast_experiment(cfg, ood_config=replace(cfg, payments_per_day=3_000, large_value_sigma_milli=1_400), include_gbm=not args.quick)
    fc["manifest"] = manifest(t0)
    (OUT / "forecasting.json").write_text(json.dumps(fc, indent=1))
    print("forecasting done")

    t0 = time.perf_counter()
    game = deviation_analysis(("early", "conservative", "recycler"), seeds=(101, 102, 103) if args.quick else (101, 102, 103, 104, 105, 106))
    game["manifest"] = manifest(t0)
    (OUT / "game.json").write_text(json.dumps(game, indent=1))
    print("game done")

    nett = netting_optimality(instances=5 if args.quick else 20)
    (OUT / "netting_optimality.json").write_text(json.dumps(nett, indent=1))
    print("netting done")


if __name__ == "__main__":
    main()
