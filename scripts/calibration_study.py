"""Calibrate payment sizes to published Fed aggregates and re-test the headline result under the calibrated preset.

Usage: python scripts/calibration_study.py   ->  results/calibration.json
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.calibration import calibration_report, load_public, public_calibrated_config  # noqa: E402
from atlas.control import MPCController, RuleBasedRebalancer  # noqa: E402
from atlas.scenario import NexusPayConfig, generate_scenario  # noqa: E402
from atlas.sim import SimulationSettings, run_day  # noqa: E402
from atlas.stress import build_scenario  # noqa: E402

ARMS = {
    "priority": lambda: (SimulationSettings(policy="priority"), None),
    "rule_rebalancer": lambda: (SimulationSettings(policy="priority"), RuleBasedRebalancer()),
    "mpc_plus_auction": lambda: (SimulationSettings(policy="multilateral", auction="uniform"), MPCController()),
}


def main() -> None:
    t0 = time.perf_counter()
    report = calibration_report()
    seeds, stresses = (11, 12, 13, 14, 15), ("baseline", "combined")
    rows = []
    for label, cfg in (("default", NexusPayConfig()), ("calibrated", public_calibrated_config())):
        for stress in stresses:
            costs: dict[str, list[int]] = {a: [] for a in ARMS}
            settled: dict[str, list[float]] = {a: [] for a in ARMS}
            ok = True
            for seed in seeds:
                day = generate_scenario(cfg, seed=seed)
                for arm, make in ARMS.items():
                    settings, ctrl = make()
                    res = run_day(day, settings, build_scenario(stress), controller=ctrl)
                    ok &= res.verify_replay()
                    costs[arm].append(res.metrics["costs_minor"]["total"])
                    settled[arm].append(res.metrics["large_value"]["settlement_rate_value"])
            for arm in ARMS:
                diffs = [c / p - 1 for c, p in zip(costs[arm], costs["priority"])]
                rows.append({"preset": label, "stress": stress, "arm": arm, "mean_cost_minor": statistics.fmean(costs[arm]),
                             "mean_settled": statistics.fmean(settled[arm]), "mean_cost_change_vs_priority": statistics.fmean(diffs),
                             "wins_vs_priority": sum(1 for d in diffs if d < 0), "n": len(seeds), "replay_verified": ok})
            print(label, stress, {a: f"{statistics.fmean(c / p - 1 for c, p in zip(costs[a], costs['priority'])):+.0%}" for a in ARMS})
    out = report | {"public_data": load_public(), "headline_under_presets": rows,
                    "manifest": {"created_at": datetime.now(UTC).isoformat(), "runtime_s": round(time.perf_counter() - t0, 1),
                                 "python": platform.python_version(), "platform": platform.platform(), "seeds": list(seeds)}}
    (ROOT / "results" / "calibration.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("targets", "default", "calibrated", "scale")}, indent=1))


if __name__ == "__main__":
    main()
