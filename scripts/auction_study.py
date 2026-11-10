"""E4: auction-based liquidity coordination and its incentive properties.

For each mechanism, seed and stress: (a) system outcome with vs without the auction;
(b) for the three largest truthful lenders, the change in their own auction profit when
they alone shade their ask by +25% .. +200% (paired seed: identical payments).
Writes results/auction.json.
"""
from __future__ import annotations

import json
import math
import platform
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day
from atlas.stress import build_scenario

OUT = Path(__file__).resolve().parents[1] / "results" / "auction.json"
CFG = NexusPayConfig(opening_liquidity_bp=1200, credit_limit_bp=800)
SEEDS = tuple(range(201, 209))
STRESSES = ("baseline", "combined")
SHADES = (2_500, 5_000, 10_000, 20_000)


def summary(r) -> dict:
    m = r.metrics
    return {"settled": m["large_value"]["settlement_rate_value"], "delay_s": m["large_value"]["value_weighted_delay_s"],
            "cost": m["costs_minor"]["total"], "auction": {k: v for k, v in m.get("auction", {}).items() if k != "rounds"}}


def job(args):
    seed, stress, mech, shading = args
    sc = generate_scenario(CFG, seed=seed)
    r = run_day(sc, SimulationSettings(policy="priority", auction=mech, auction_shading_bp=shading), build_scenario(stress))
    assert r.verify_replay()
    return args, summary(r)


def ci(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, m - 2.365 * sd / math.sqrt(n), m + 2.365 * sd / math.sqrt(n)   # t(0.975, 7)


def main() -> None:
    t0 = time.perf_counter()
    base_jobs = [(s, st, mech, ()) for s in SEEDS for st in STRESSES for mech in (None, "pay_as_bid", "uniform")]
    with ProcessPoolExecutor(2) as ex:
        base = dict(ex.map(job, base_jobs))
    dev_jobs = []
    focal = {}
    for s in SEEDS:
        for st in STRESSES:
            for mech in ("pay_as_bid", "uniform"):
                lent = base[(s, st, mech, ())]["auction"]["lender_principal_minor"]
                top = sorted(lent, key=lambda k: (-lent[k], k))[:3]
                focal[(s, st, mech)] = top
                dev_jobs += [(s, st, mech, ((f, sh),)) for f in top for sh in SHADES]
    with ProcessPoolExecutor(2) as ex:
        dev = dict(ex.map(job, dev_jobs))
    system = []
    for st in STRESSES:
        for mech in (None, "pay_as_bid", "uniform"):
            rows = [base[(s, st, mech, ())] for s in SEEDS]
            ref = [base[(s, st, None, ())] for s in SEEDS]
            system.append({"stress": st, "mechanism": mech or "none",
                           "settled_mean": sum(r["settled"] for r in rows) / len(rows),
                           "delay_min_mean": sum(r["delay_s"] for r in rows) / len(rows) / 60,
                           "cost_mean_minor": sum(r["cost"] for r in rows) / len(rows),
                           "settled_diff_ci": ci([a["settled"] - b["settled"] for a, b in zip(rows, ref)]),
                           "cost_diff_ci_minor": ci([a["cost"] - b["cost"] for a, b in zip(rows, ref)]),
                           "avg_rate_cbp": (sum((r["auction"].get("avg_rate_cbp") or 0) for r in rows) / len(rows)) if mech else None,
                           "principal_mean_minor": (sum(r["auction"].get("principal_minor", 0) for r in rows) / len(rows)) if mech else None,
                           "rolled_overnight_mean_minor": (sum(r["auction"].get("rolled_overnight_minor", 0) for r in rows) / len(rows)) if mech else None})
    incentives = []
    for st in STRESSES:
        for mech in ("pay_as_bid", "uniform"):
            for sh in SHADES:
                gains, rel = [], []
                for s in SEEDS:
                    for f in focal[(s, st, mech)]:
                        truthful = base[(s, st, mech, ())]["auction"]["lender_profit_minor"].get(f, 0)
                        shaded = dev[(s, st, mech, ((f, sh),))]["auction"]["lender_profit_minor"].get(f, 0)
                        gains.append(shaded - truthful)
                        rel.append((shaded - truthful) / truthful if truthful > 0 else 0.0)
                m, lo, hi = ci(gains)
                incentives.append({"stress": st, "mechanism": mech, "shade_bp": sh, "n": len(gains), "mean_gain_minor": m, "ci95": [lo, hi],
                                   "mean_rel_gain": sum(rel) / len(rel), "share_profitable": sum(1 for g in gains if g > 0) / len(gains),
                                   "profitable_deviation": lo > 0})
    OUT.write_text(json.dumps({"experiment": "E4 liquidity auction", "config": CFG.to_dict(), "seeds": list(SEEDS), "system": system,
                               "incentives": incentives, "manifest": {"runtime_s": time.perf_counter() - t0, "python": platform.python_version(),
                                                                      "platform": platform.platform(), "data_origin": "synthetic"}}, indent=1))
    print(json.dumps(system, indent=1)[:3000])
    for i in incentives:
        print(i["stress"], i["mechanism"], i["shade_bp"], round(i["mean_gain_minor"] / 100), [round(x / 100) for x in i["ci95"]], round(i["share_profitable"], 2), round(i["mean_rel_gain"], 3))


if __name__ == "__main__":
    main()
