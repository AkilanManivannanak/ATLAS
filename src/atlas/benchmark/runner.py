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

BENCHMARK_VERSION = "nexus-pay-bench-v1"

# arm name -> (policy, controller)
POLICY_ARMS: dict[str, tuple[str, str | None]] = {
    "fifo": ("fifo", None),
    "fifo_strict": ("fifo_strict", None),
    "priority": ("priority", None),
    "bilateral": ("bilateral", None),
    "multilateral": ("multilateral", None),
    "multilateral_milp": ("multilateral_milp", None),
    "rule_rebalancer": ("multilateral", "rule"),
    "mpc": ("multilateral", "mpc"),
    "mpc_queue_milp": ("multilateral", "mpc_full"),
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
}
LOWER_IS_BETTER = {"total_cost_minor", "lv_value_weighted_delay_s", "lv_deadline_miss_value_minor", "instant_rejected",
                   "liquidity_usage_minor", "peak_credit_minor", "runtime_s"}


@dataclass(frozen=True)
class BenchmarkConfig:
    name: str = "standard"
    scenario: NexusPayConfig = NexusPayConfig(opening_liquidity_bp=600, credit_limit_bp=300)
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
    policy, ctrl = POLICY_ARMS[arm]
    sc = generate_scenario(scenario_cfg, seed=seed)
    r = run_day(sc, SimulationSettings(policy=policy, strategy=strategy), build_scenario(stress), controller=_controller(ctrl))
    if not r.verify_replay():  # a benchmark row is only valid if its ledger replays exactly
        raise RuntimeError(f"replay mismatch for seed={seed} stress={stress} arm={arm}")
    return {"seed": seed, "stress": stress, "arm": arm, "policy": policy, "controller": ctrl,
            "scenario_fingerprint": sc.fingerprint(), "final_state_hash": r.final_state_hash, "replay_verified": True,
            "events": r.metrics["events"], **{k: f(r.metrics) for k, f in METRICS.items()},
            "safety_rejections": r.metrics["counters"]["controller_rejected"], "controller_actions": r.metrics["counters"]["controller_actions"]}


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
    return {
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
