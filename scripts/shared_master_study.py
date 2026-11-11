"""Does the cross-rail rebalancing result survive when FedNow shares the Fed master account?

v0.6 modeled FedNow with its own liquidity pool. In reality a FedNow participant settles in the
same Federal Reserve master account that Fedwire uses, with access to intraday credit under the
same PSR terms. This study reruns the key benchmark arms in both account models on the same
seeds and stresses and reports (a) each arm vs the priority queue and vs the rule-based treasury,
and (b) the paired effect of switching the account model for the same arm.
Writes results/shared_master.json and results/shared_master.md.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from atlas.benchmark.runner import BenchmarkConfig, _bootstrap_ci, paired_comparison, run_benchmark
from atlas.simulation.rng import derive_stream_seed

OUT = Path(__file__).resolve().parents[1] / "results"
ARMS = ("priority", "rule_rebalancer", "mpc", "auction_uniform", "mpc_plus_auction")
STRESSES = ("baseline", "liquidity_hoarding", "combined")
METRICS = ("total_cost_minor", "lv_settlement_rate_value", "instant_rejected")


def main() -> None:
    t0 = time.perf_counter()
    base = BenchmarkConfig(name="shared_master_study", arms=ARMS, stresses=STRESSES)
    runs = {}
    for shared in (False, True):
        cfg = replace(base, fednow_shared_master=shared)
        print(f"== fednow_shared_master={shared}", flush=True)
        runs[shared] = run_benchmark(cfg, progress=True)

    out: dict = {"config": base.to_dict(), "arms": ARMS, "stresses": STRESSES, "modes": {}}
    for shared, res in runs.items():
        key = "shared" if shared else "separate"
        rows = res["rows"]
        out["modes"][key] = {
            "all_replays_verified": all(r["replay_verified"] for r in rows),
            "vs_priority": [c for c in res["comparison"] if c["metric"] in METRICS],
            "vs_rule_rebalancer": [c for c in paired_comparison(rows, "rule_rebalancer") if c["metric"] in METRICS],
        }

    # paired effect of the account model itself, per arm and stress (same seed, same payments)
    sep = {(r["stress"], r["arm"], r["seed"]): r for r in runs[False]["rows"]}
    sha = {(r["stress"], r["arm"], r["seed"]): r for r in runs[True]["rows"]}
    switch = []
    for stress in STRESSES:
        for arm in ARMS:
            seeds = sorted(s for (st, a, s) in sep if st == stress and a == arm and (st, a, s) in sha)
            for metric in METRICS:
                diffs = [sha[(stress, arm, s)][metric] - sep[(stress, arm, s)][metric] for s in seeds]
                lo, hi = _bootstrap_ci(diffs, seed=derive_stream_seed(0, f"switch|{stress}|{arm}|{metric}"))
                ref = sum(sep[(stress, arm, s)][metric] for s in seeds) / len(seeds)
                md = sum(diffs) / len(diffs)
                switch.append({"stress": stress, "arm": arm, "metric": metric, "n": len(seeds), "separate_mean": ref,
                               "shared_mean": ref + md, "mean_diff": md, "ci95_diff": [lo, hi], "rel_diff": md / ref if ref else None,
                               "significant": lo > 0 or hi < 0})
    out["shared_minus_separate"] = switch
    out["runtime_s"] = round(time.perf_counter() - t0, 1)
    OUT.mkdir(exist_ok=True)
    (OUT / "shared_master.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    (OUT / "shared_master.md").write_text(render(out))
    print(render(out))


def _usd(minor: float) -> str:
    return f"${minor / 1e8:+.2f}M"


def render(out: dict) -> str:
    lines = ["# FedNow on a shared master account vs a separate pool", "",
             f"Seeds {out['config']['seeds']}, standard scenario, {len(out['arms'])} arms x {len(out['stresses'])} stresses x 2 account models; "
             f"all ledgers replay-verified: separate={out['modes']['separate']['all_replays_verified']}, "
             f"shared={out['modes']['shared']['all_replays_verified']}. 95% paired bootstrap CIs.", ""]
    for mode in ("separate", "shared"):
        lines += [f"## {mode.capitalize()} FedNow pool: cost vs priority queue / vs rule-based treasury", "",
                  "| Stress | Arm | Cost vs priority | Cost vs rule-based | Instant rejected |", "|---|---|---|---|---|"]
        vp = {(c["stress"], c["arm"], c["metric"]): c for c in out["modes"][mode]["vs_priority"]}
        vr = {(c["stress"], c["arm"], c["metric"]): c for c in out["modes"][mode]["vs_rule_rebalancer"]}
        for s in out["stresses"]:
            for a in out["arms"]:
                c, r, ir = vp[(s, a, "total_cost_minor")], vr[(s, a, "total_cost_minor")], vp[(s, a, "instant_rejected")]
                fp = "ref" if a == "priority" else f"{c['rel_diff'] * 100:+.0f}%{'' if c['significant'] else ' (n.s.)'}"
                fr = "ref" if a == "rule_rebalancer" else f"{_usd(r['mean_diff'])} [{_usd(r['ci95_diff'][0])}, {_usd(r['ci95_diff'][1])}]{'' if r['significant'] else ' n.s.'}"
                lines.append(f"| {s} | {a} | {fp} | {fr} | {ir['mean']:.1f} |")
        lines.append("")
    lines += ["## Effect of switching to the shared master account (same arm, same seeds)", "",
              "| Stress | Arm | Cost change | Instant rejected: separate -> shared |", "|---|---|---|---|"]
    sw = {(c["stress"], c["arm"], c["metric"]): c for c in out["shared_minus_separate"]}
    for s in out["stresses"]:
        for a in out["arms"]:
            c, ir = sw[(s, a, "total_cost_minor")], sw[(s, a, "instant_rejected")]
            lines.append(f"| {s} | {a} | {_usd(c['mean_diff'])} [{_usd(c['ci95_diff'][0])}, {_usd(c['ci95_diff'][1])}]"
                         f"{'' if c['significant'] else ' n.s.'} | {ir['separate_mean']:.1f} -> {ir['shared_mean']:.1f} |")
    lines += ["", f"Runtime {out['runtime_s']} s."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
