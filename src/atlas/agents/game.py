"""Empirical liquidity-timing game (blueprint agent family B).

Setting. Following Bech & Garratt (2003), each bank chooses *when* to release
payments; paying early costs own liquidity, delaying costs delay penalties and
free-rides on others' liquidity. Rather than assume a closed-form game, ATLAS
estimates payoffs by simulation ("empirical game-theoretic analysis",
Wellman, 2006, AAAI): for a symmetric profile in which every bank plays ``s``,
a focal bank unilaterally deviates to ``d`` and we measure the change in *its
own* cost on paired seeds (identical payment schedules).

Claim discipline. A profile is reported as an *empirical epsilon-equilibrium for
the tested focal banks and deviations* when no tested deviation lowers the focal
bank's mean cost by more than epsilon AND the upper 95% bound of the gain is
below epsilon. This is evidence about the sampled deviations, not a proof of a
Nash equilibrium of the full game, and results are labeled that way.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from atlas.agents.strategies import make_strategy
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim.day import CostModel, DaySimulator, SimulationSettings


def institution_cost(stats: dict, cost: CostModel) -> int:
    """Own cost of one bank in minor units (same parameters as the system cost model)."""
    sent = stats["sent_value_minor"]
    settled = int(sent * stats["settlement_rate_value"])
    delay = int(settled * stats["value_weighted_delay_s"]) * cost.delay_bp_per_hour // (3600 * 10_000)
    unsettled = (sent - settled) * cost.unsettled_penalty_bp // 10_000
    liquidity = stats["liquidity_usage_minor"] * cost.liquidity_bp_per_day // 10_000
    credit = stats["peak_credit_minor"] * cost.credit_bp_per_day // 10_000
    return delay + unsettled + liquidity + credit


def _mean_ci(xs: Sequence[float]) -> tuple[float, float, float]:
    n = len(xs)
    mean = sum(xs) / n
    if n < 2:
        return mean, mean, mean
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    t = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262}.get(n, 1.96)
    half = t * sd / math.sqrt(n)
    return mean, mean - half, mean + half


@dataclass(frozen=True)
class DeviationResult:
    profile: str
    deviation: str
    focal: str
    mean_gain_minor: float     # positive = deviating lowers the focal bank's cost
    ci_low: float
    ci_high: float
    seeds: tuple[int, ...]


def _run(sc, strategy_map: dict[str, str], policy: str, cost: CostModel):
    sim = DaySimulator(sc, SimulationSettings(policy=policy, strategy="early", cost=cost))
    sim.strategies = {i: make_strategy(name) for i, name in strategy_map.items()}
    return sim.run()


def deviation_analysis(
    strategies: Sequence[str] = ("early", "conservative"),
    *,
    config: NexusPayConfig = NexusPayConfig(n_institutions=10, payments_per_day=900, instant_payments_per_day=300,
                                            opening_liquidity_bp=600, credit_limit_bp=300),
    seeds: Sequence[int] = (101, 102, 103),
    focal: Sequence[str] = ("@largest", "@median"),
    policy: str = "priority",
    cost: CostModel = CostModel(),
    epsilon_bp_of_cost: int = 100,
) -> dict:
    rows: list[DeviationResult] = []
    system: dict[str, list[int]] = {s: [] for s in strategies}
    focal_cost: dict[str, dict[str, list[int]]] = {}
    for seed in seeds:
        sc = generate_scenario(config, seed=seed)
        order = sorted(sc.institutions, key=lambda i: (i.size_weight, i.institution_id))
        resolve = {"@largest": order[-1].institution_id, "@median": order[len(order) // 2].institution_id, "@smallest": order[0].institution_id}
        focal_ids = [resolve.get(f, f) for f in focal]
        insts = [i.institution_id for i in sc.institutions]
        for s in strategies:
            base = _run(sc, {i: s for i in insts}, policy, cost)
            system[s].append(base.metrics["costs_minor"]["total"])
            base_stats = {x["institution_id"]: x for x in base.per_institution}
            for f_label, f in zip(focal, focal_ids):
                focal_cost.setdefault(s, {}).setdefault(f_label, []).append(institution_cost(base_stats[f], cost))
                for d in strategies:
                    if d == s:
                        continue
                    dev = _run(sc, {i: (d if i == f else s) for i in insts}, policy, cost)
                    dev_stats = {x["institution_id"]: x for x in dev.per_institution}
                    gain = institution_cost(base_stats[f], cost) - institution_cost(dev_stats[f], cost)
                    rows.append(DeviationResult(s, d, f_label, gain, 0, 0, (seed,)))
    # aggregate across seeds
    table = []
    verdicts = {}
    for s in strategies:
        stable, broken = True, False
        for f_label in focal:
            base_mean = sum(focal_cost[s][f_label]) / len(focal_cost[s][f_label])
            eps = abs(base_mean) * epsilon_bp_of_cost / 10_000
            for d in strategies:
                if d == s:
                    continue
                gains = [r.mean_gain_minor for r in rows if r.profile == s and r.deviation == d and r.focal == f_label]
                mean, lo, hi = _mean_ci(gains)
                profitable = mean > eps and lo > 0
                if hi > eps:
                    stable = False
                broken = broken or profitable
                table.append({"profile": s, "deviation": d, "focal": f_label, "mean_gain_minor": mean, "ci95": [lo, hi],
                              "epsilon_minor": eps, "profitable_deviation": profitable, "n_seeds": len(gains)})
        verdicts[s] = {
            "verdict": "unstable" if broken else ("empirical_epsilon_equilibrium" if stable else "inconclusive"),
            "empirical_epsilon_equilibrium": stable,
            "mean_system_cost_minor": sum(system[s]) / len(system[s]),
            "claim_scope": "tested focal banks and listed deviations only; not a proof of Nash equilibrium",
        }
    costs = {s: v["mean_system_cost_minor"] for s, v in verdicts.items()}
    stable = [s for s, v in verdicts.items() if v["empirical_epsilon_equilibrium"]]
    best = min(costs, key=costs.get)
    return {
        "strategies": list(strategies), "seeds": list(seeds), "policy": policy, "cost_model": cost.to_dict(),
        "deviations": table, "profiles": verdicts, "socially_best_profile": best,
        "efficiency_gap": {s: costs[s] / costs[best] for s in stable} if stable else {},
        "method": "empirical game-theoretic analysis with paired seeds (Wellman 2006); payoffs = own modeled cost",
    }
