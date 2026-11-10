"""NEXUS-PAY benchmark runner (``nexus-pay-bench-v1``).

Every arm (settlement policy, optionally with a controller) is run on the *same*
generated days and the *same* stress definitions, so differences between arms
are paired by seed and attributable to the arm (blueprint section 20: never
compare runs with different seeds and attribute the difference to policy).

Statistics: for each metric and arm we report the mean over seeds and a 95%
percentile-bootstrap CI of the paired difference against the reference arm, plus
the paired win rate. The bootstrap uses the project's deterministic RNG, so the
reported intervals are themselves reproducible.
"""

from __future__ import annotations

import json
import os
import platform
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.simulation.rng import DeterministicRandomStream, derive_stream_seed
from atlas.stress import build_scenario

BENCHMARK_VERSION = "nexus-pay-bench-v2"

# arm name -> (queue policy, controller, liquidity auction)
POLICY_ARMS: dict[str, tuple[str, str | None, str | None]] = {
    "fifo": ("fifo", None, None),
    "fifo_strict": ("fifo_strict", None, None),
    "priority": ("priority", None, None),
    "bilateral": ("bilateral", None, None),
    "multilateral": ("multilateral", None, None),
    "multilateral_milp": ("multilateral_milp", None, None),
    "auction_pay_as_bid": ("priority", None, "pay_as_bid"),
    "auction_uniform": ("priority", None, "uniform"),
    "rule_rebalancer": ("multilateral", "rule", None),
    "mpc": ("multilateral", "mpc", None),
    "mpc_queue_milp": ("multilateral", "mpc_full", None),
    "mpc_plus_auction": ("multilateral", "mpc", "uniform"),
}

METRICS = {
    "total_cost_minor": lambda m: m["costs_minor"]["total"],
    "lv_settlement_rate_value": lambda m: m["large_value"]["settlement_rate_value"],
    "lv_value_weighted_delay_s": lambda m: m["large_value"]["value_weighted_delay_s"],
    "lv_deadline_miss_value_minor": lambda m: m["large_value"]["deadline_miss_value_minor"],
    "instant_rejected": lambda m: m["counters"]["instant_rejected"],
    "liquidity_usage_minor": lambda m: m["liquidity"]["system_liquidity_usage_minor"],
    "peak_credit_minor": lambda m: m["liquidity"]["peak_intraday_credit_minor"],
    "liquidity_turnover": lambda m: m["liquidity"]["liquidity_turnover"],
    "runtime_s": lambda m: m["runtime_s"],
    "timed_deadline_misses": lambda m: m["by_kind"].get("timed", {}).get("deadline_miss_count", 0),
}
LOWER_IS_BETTER = {"total_cost_minor", "lv_value_weighted_delay_s", "lv_deadline_miss_value_minor", "instant_rejected",
                   "liquidity_usage_minor", "peak_credit_minor", "runtime_s", "timed_deadline_misses"}


@dataclass(frozen=True)
class BenchmarkConfig:
    name: str = "standard"
    scenario: NexusPayConfig = NexusPayConfig()          # generator v2 defaults: calibrated so ~97% settles on a normal day
    seeds: tuple[int, ...] = (11, 12, 13, 14, 15)
    stresses: tuple[str, ...] = ("baseline", "counterparty_delay", "liquidity_hoarding", "combined")
    arms: tuple[str, ...] = tuple(POLICY_ARMS)
    reference_arm: str = "priority"
    strategy: str = "early"
    workers: int = max(1, (os.cpu_count() or 1))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenario"] = self.scenario.to_dict()
        return d


PRESETS = {
    "smoke": BenchmarkConfig(name="smoke", scenario=NexusPayConfig(n_institutions=8, payments_per_day=500, instant_payments_per_day=300,
                                                                   opening_liquidity_bp=600, credit_limit_bp=300),
                             seeds=(1, 2), stresses=("baseline", "combined"), arms=("priority", "multilateral", "mpc"), workers=1),
    "standard": BenchmarkConfig(),
    "tight": BenchmarkConfig(name="tight", scenario=NexusPayConfig(opening_liquidity_bp=1_000, credit_limit_bp=600)),
    "extended": BenchmarkConfig(name="extended", seeds=tuple(range(11, 21)),
                                stresses=("baseline", "counterparty_delay", "rtgs_outage", "liquidity_withdrawal", "funding_disruption",
                                          "haircut_shock", "failure_to_pay", "concentrated_outflows", "liquidity_hoarding",
                                          "messaging_failure", "combined")),
}


def _controller(kind: str | None):
    if kind is None:
        return None
    from atlas.control import MPCConfig, MPCController, RuleBasedRebalancer
    return {"rule": lambda: RuleBasedRebalancer(), "mpc": lambda: MPCController(MPCConfig(enable_queue_milp=False)),
            "mpc_full": lambda: MPCController(MPCConfig(enable_queue_milp=True))}[kind]()


def _run_one(args: tuple) -> dict:
    from atlas.sim import SimulationSettings, run_day
    scenario_cfg, seed, stress, arm, strategy = args
    policy, ctrl, auction = POLICY_ARMS[arm]
    sc = generate_scenario(scenario_cfg, seed=seed)
    r = run_day(sc, SimulationSettings(policy=policy, strategy=strategy, auction=auction), build_scenario(stress), controller=_controller(ctrl))
    if not r.verify_replay():  # a benchmark row is only valid if its ledger replays exactly
        raise RuntimeError(f"replay mismatch for seed={seed} stress={stress} arm={arm}")
    return {"seed": seed, "stress": stress, "arm": arm, "policy": policy, "controller": ctrl,
            "scenario_fingerprint": sc.fingerprint(), "final_state_hash": r.final_state_hash, "replay_verified": True,
            "events": r.metrics["events"], **{k: f(r.metrics) for k, f in METRICS.items()},
            "safety_rejections": r.metrics["counters"]["controller_rejected"], "controller_actions": r.metrics["counters"]["controller_actions"],
            "raw": r.metrics["raw"] | {"system_liquidity_usage_minor": r.metrics["liquidity"]["system_liquidity_usage_minor"],
                                      "facility_interest_minor": r.metrics["costs_minor"]["facility_interest"],
                                      "lv_value_minor": r.metrics["large_value"]["value_minor"]},
            "auction_principal_minor": r.metrics.get("auction", {}).get("principal_minor", 0)}


def _bootstrap_ci(diffs: Sequence[float], *, seed: int, n_boot: int = 4000) -> tuple[float, float]:
    if len(diffs) < 2:
        return (diffs[0], diffs[0]) if diffs else (0.0, 0.0)
    rng = DeterministicRandomStream(derive_stream_seed(seed, "bootstrap"))
    n = len(diffs)
    means = sorted(sum(diffs[rng.randbelow(n)] for _ in range(n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def paired_comparison(rows: list[dict], reference: str, *, seed: int = 0) -> list[dict]:
    out = []
    groups: dict[tuple[str, str], dict[int, dict]] = {}
    for r in rows:
        groups.setdefault((r["stress"], r["arm"]), {})[r["seed"]] = r
    stresses = sorted({r["stress"] for r in rows})
    arms = sorted({r["arm"] for r in rows})
    for stress in stresses:
        ref = groups.get((stress, reference), {})
        for arm in arms:
            cur = groups.get((stress, arm), {})
            seeds = sorted(set(ref) & set(cur))
            for metric in METRICS:
                vals = [cur[s][metric] for s in seeds]
                diffs = [cur[s][metric] - ref[s][metric] for s in seeds]
                lo, hi = _bootstrap_ci(diffs, seed=derive_stream_seed(seed, f"{stress}|{arm}|{metric}")) if arm != reference else (0.0, 0.0)
                better = (lambda d: d < 0) if metric in LOWER_IS_BETTER else (lambda d: d > 0)
                ref_mean = sum(ref[s][metric] for s in seeds) / len(seeds) if seeds else 0.0
                mean_diff = sum(diffs) / len(diffs) if diffs else 0.0
                out.append({
                    "stress": stress, "arm": arm, "metric": metric, "n": len(seeds), "mean": sum(vals) / len(vals) if vals else None,
                    "reference_mean": ref_mean, "mean_diff": mean_diff, "ci95_diff": [lo, hi],
                    "rel_diff": mean_diff / ref_mean if ref_mean else None,
                    "win_rate": sum(1 for d in diffs if better(d)) / len(diffs) if diffs and arm != reference else None,
                    "significant": arm != reference and (lo > 0 or hi < 0),
                    "direction": "lower_is_better" if metric in LOWER_IS_BETTER else "higher_is_better",
                })
    return out


def run_benchmark(cfg: BenchmarkConfig = BenchmarkConfig(), *, progress: bool = False) -> dict:
    started = time.perf_counter()
    jobs = [(cfg.scenario, seed, stress, arm, cfg.strategy) for seed in cfg.seeds for stress in cfg.stresses for arm in cfg.arms]
    rows: list[dict] = []
    if cfg.workers > 1:
        with ProcessPoolExecutor(max_workers=cfg.workers) as pool:
            for i, row in enumerate(pool.map(_run_one, jobs, chunksize=1)):
                rows.append(row)
                if progress:
                    print(f"[{i + 1}/{len(jobs)}] {row['stress']:22s} {row['arm']:18s} seed={row['seed']} cost={row['total_cost_minor']}", flush=True)
    else:
        for i, job in enumerate(jobs):
            rows.append(_run_one(job))
            if progress:
                print(f"[{i + 1}/{len(jobs)}] {job[2]} {job[3]} seed={job[1]}", flush=True)
    rows.sort(key=lambda r: (r["stress"], r["arm"], r["seed"]))
    comparison = paired_comparison(rows, cfg.reference_arm)
    secondary = paired_comparison(rows, "rule_rebalancer") if "rule_rebalancer" in cfg.arms else []
    return {
        "comparison_vs_rule_rebalancer": [c for c in secondary if c["metric"] in ("total_cost_minor", "lv_settlement_rate_value", "instant_rejected")],
        "cost_sensitivity": cost_sensitivity({"rows": rows}),
        "benchmark_version": BENCHMARK_VERSION, "name": cfg.name, "config": cfg.to_dict(), "rows": rows, "comparison": comparison,
        "manifest": {
            "created_at": datetime.now(UTC).isoformat(), "runtime_s": time.perf_counter() - started, "runs": len(rows),
            "python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor() or "unknown", "cpu_count": os.cpu_count(), "workers": cfg.workers,
            "data_origin": "synthetic (NEXUS-PAY generator); not observed financial data",
            "all_replays_verified": all(r["replay_verified"] for r in rows),
        },
    }


def _fmt_money(v: float) -> str:
    return f"${v / 100 / 1e6:,.2f}M"


def write_report(result: dict, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jpath = out / f"{result['name']}.json"
    jpath.write_text(json.dumps(result, indent=1, sort_keys=True))
    m = result["manifest"]
    lines = [
        f"# NEXUS-PAY benchmark: `{result['name']}`", "",
        f"*{BENCHMARK_VERSION}. {m['runs']} runs, all ledger replays verified: **{m['all_replays_verified']}**. "
        f"Runtime {m['runtime_s']:.1f}s on {m['machine']} / {m['cpu_count']} CPUs / Python {m['python']} ({m['platform']}).*", "",
        f"Data: {m['data_origin']}. Seeds: {list(result['config']['seeds'])}. Reference arm: `{result['config']['reference_arm']}`.", "",
        "Cells show the mean over seeds; brackets give the 95% bootstrap CI of the paired difference vs the reference arm. "
        "Bold = CI excludes zero.", "",
    ]
    comp = result["comparison"]
    for stress in sorted({c["stress"] for c in comp}):
        lines += [f"## Stress: `{stress}`", "", "| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |",
                  "|---|---|---|---|---|---|"]
        for arm in sorted({c["arm"] for c in comp if c["stress"] == stress}):
            get = {c["metric"]: c for c in comp if c["stress"] == stress and c["arm"] == arm}

            def cell(metric: str, fmt, get=get) -> str:
                c = get[metric]
                s = fmt(c["mean"])
                if c["arm"] != result["config"]["reference_arm"]:
                    lo, hi = c["ci95_diff"]
                    s += f" [{fmt(lo) if metric != 'lv_settlement_rate_value' else f'{lo*100:+.2f}pp'}, {fmt(hi) if metric != 'lv_settlement_rate_value' else f'{hi*100:+.2f}pp'}]"
                    if c["significant"]:
                        s = f"**{s}**"
                return s
            wr = get["total_cost_minor"]["win_rate"]
            lines.append(f"| `{arm}` | {cell('total_cost_minor', _fmt_money)} | {cell('lv_settlement_rate_value', lambda v: f'{v*100:.2f}%')} | "
                         f"{cell('lv_value_weighted_delay_s', lambda v: f'{v/60:.1f} min')} | {cell('instant_rejected', lambda v: f'{v:.1f}')} | "
                         f"{'—' if wr is None else f'{wr*100:.0f}%'} |")
        lines.append("")
    mpath = out / f"{result['name']}.md"
    mpath.write_text("\n".join(lines))
    return jpath, mpath


def reweight_cost(raw: dict, *, delay_bp_per_hour: float = 2, late_penalty_bp: float = 10, unsettled_penalty_bp: float = 100,
                  liquidity_bp_per_day: float = 5, psr_fee_bp_annual: float = 50, collateral_bp_per_day: float = 1) -> float:
    """Recompute the modeled cost of one run under alternative weights (minor units), from cost-free raw quantities."""
    return (raw["settled_value_seconds"] * delay_bp_per_hour / (3600 * 10_000)
            + raw["late_settled_value_minor"] * late_penalty_bp / 10_000
            + (raw["unsettled_value_minor"] + raw["instant_rejected_value_minor"]) * unsettled_penalty_bp / 10_000
            + raw["system_liquidity_usage_minor"] * liquidity_bp_per_day / 10_000
            + raw["uncollateralized_overdraft_minute_sum"] * psr_fee_bp_annual * 21.5 / 24 / 360 / 10_000 / 1291
            + raw["peak_collateralized_credit_minor"] * collateral_bp_per_day / 10_000
            + raw.get("facility_interest_minor", 0))


def cost_sensitivity(result: dict, arms: Sequence[str] | None = None, multipliers: Sequence[float] = (0.25, 1.0, 4.0)) -> dict:
    """Rank arms under every combination of delay / unsettled / liquidity weight multipliers (27 cost models).

    Reports, per stress, how often each arm has the lowest mean cost and its mean rank. A finding that
    holds only under the default weights is flagged by a low win share.
    """
    import itertools
    rows = result["rows"]
    arms = list(arms or sorted({r["arm"] for r in rows}))
    out = {}
    for stress in sorted({r["stress"] for r in rows}):
        wins = {a: 0 for a in arms}
        ranks = {a: [] for a in arms}
        models = list(itertools.product(multipliers, multipliers, multipliers))
        for md, mu, ml in models:
            means = {}
            for a in arms:
                rs = [r for r in rows if r["stress"] == stress and r["arm"] == a]
                means[a] = sum(reweight_cost(r["raw"], delay_bp_per_hour=2 * md, late_penalty_bp=10 * md, unsettled_penalty_bp=100 * mu,
                                             liquidity_bp_per_day=5 * ml) for r in rs) / len(rs)
            order = sorted(arms, key=lambda a: means[a])
            wins[order[0]] += 1
            for k, a in enumerate(order):
                ranks[a].append(k + 1)
        out[stress] = {"cost_models": len(models), "win_share": {a: wins[a] / len(models) for a in arms},
                       "mean_rank": {a: sum(ranks[a]) / len(ranks[a]) for a in arms}}
    return {"multipliers": list(multipliers), "dimensions": ["delay+late", "unsettled+instant rejection", "liquidity"], "by_stress": out}
