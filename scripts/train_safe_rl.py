"""E7: train constrained PPO and plain PPO, then evaluate against MPC and baselines on held-out data.

Training days: seeds 1000+, stresses {baseline, counterparty_delay, liquidity_withdrawal, rtgs_outage, haircut_shock}.
Held-out evaluation: seeds 9000-9009 (never trained on) under baseline plus two stresses the policy never saw
(combined, liquidity_hoarding). Writes results/safe_rl.json and results/policies/*.json.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from atlas.control import MPCConfig, MPCController, RuleBasedRebalancer
from atlas.control.rl import Policy, PPOConfig, RLController, ppo_update
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day
from atlas.stress import build_scenario

ROOT = Path(__file__).resolve().parents[1]
CFG = NexusPayConfig(n_institutions=10, payments_per_day=1_500, instant_payments_per_day=1_000, opening_liquidity_bp=1_200, credit_limit_bp=800)
TRAIN_STRESS = ("baseline", "counterparty_delay", "liquidity_withdrawal", "rtgs_outage", "haircut_shock")
EVAL_STRESS = ("baseline", "combined", "liquidity_hoarding")
EVAL_SEEDS = tuple(range(9000, 9010))


def rollout(args):
    pol_dict, seed, stress = args
    ctrl = RLController(Policy.from_dict(pol_dict))
    run_day(generate_scenario(CFG, seed=seed), SimulationSettings(policy="multilateral"), build_scenario(stress), controller=ctrl)
    return ctrl.traj


def evaluate(args):
    arm, pol_dict, seed, stress = args
    ctrl = {"none": lambda: None, "rule_rebalancer": RuleBasedRebalancer, "mpc": lambda: MPCController(MPCConfig(enable_queue_milp=False)),
            }.get(arm, lambda: RLController(Policy.from_dict(pol_dict), deterministic=True))()
    r = run_day(generate_scenario(CFG, seed=seed), SimulationSettings(policy="multilateral"), build_scenario(stress), controller=ctrl)
    assert r.verify_replay()
    m = r.metrics
    return {"arm": arm, "seed": seed, "stress": stress, "cost": m["costs_minor"]["total"], "settled": m["large_value"]["settlement_rate_value"],
            "instant_rejected": m["counters"]["instant_rejected"], "proposals": m["counters"]["controller_actions"],
            "safety_rejections": m["counters"]["controller_rejected"], "runtime_s": m["runtime_s"]}


def train(constrained: bool, iterations: int, episodes: int, seed: int, pool) -> tuple[Policy, list[dict]]:
    pol = Policy(PPOConfig(constrained=constrained, seed=seed))
    log = []
    ep_seed = 1000 + seed * 100_000
    for it in range(iterations):
        jobs = []
        for _ in range(episodes):
            jobs.append((pol.to_dict(), ep_seed, TRAIN_STRESS[ep_seed % len(TRAIN_STRESS)]))
            ep_seed += 1
        trajs = list(pool.map(rollout, jobs))
        stats = ppo_update(pol, trajs)
        ret = sum(sum(s.get("reward", 0.0) for s in t) for t in trajs) / len(trajs)
        log.append({"iteration": it, "mean_return": ret, **stats})
        print(f"{'C' if constrained else 'U'}PPO it {it:3d} return {ret:8.3f} rej/step {stats['mean_rejections_per_step']:.3f} lambda {stats['lambda']:.3f}", flush=True)
    return pol, log


def ci(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return [m, m - 2.262 * sd / math.sqrt(n), m + 2.262 * sd / math.sqrt(n)]   # t(0.975, 9)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=60)
    ap.add_argument("--episodes", type=int, default=8)
    args = ap.parse_args()
    t0 = time.perf_counter()
    (ROOT / "results" / "policies").mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(2) as pool:
        cppo, clog = train(True, args.iterations, args.episodes, 1, pool)
        uppo, ulog = train(False, args.iterations, args.episodes, 2, pool)
        (ROOT / "results" / "policies" / "safe_ppo_constrained.json").write_text(json.dumps(cppo.to_dict()))
        (ROOT / "results" / "policies" / "ppo_unconstrained.json").write_text(json.dumps(uppo.to_dict()))
        arms = {"none": None, "rule_rebalancer": None, "mpc": None, "ppo_constrained": cppo.to_dict(), "ppo_unconstrained": uppo.to_dict()}
        jobs = [(a, p, s, st) for a, p in arms.items() for s in EVAL_SEEDS for st in EVAL_STRESS]
        rows = list(pool.map(evaluate, jobs))
    summary = []
    for st in EVAL_STRESS:
        ref = {r["seed"]: r for r in rows if r["arm"] == "mpc" and r["stress"] == st}
        for a in arms:
            rs = [r for r in rows if r["arm"] == a and r["stress"] == st]
            summary.append({"stress": st, "arm": a, "held_out_stress": st not in TRAIN_STRESS,
                            "cost": ci([r["cost"] for r in rs]), "cost_diff_vs_mpc": ci([r["cost"] - ref[r["seed"]]["cost"] for r in rs]),
                            "settled": ci([r["settled"] for r in rs]), "instant_rejected": ci([r["instant_rejected"] for r in rs]),
                            "safety_rejection_rate": sum(r["safety_rejections"] for r in rs) / max(1, sum(r["proposals"] for r in rs)),
                            "wins_vs_mpc": sum(1 for r in rs if r["cost"] < ref[r["seed"]]["cost"])})
    out = {"experiment": "E7 safe RL vs MPC", "config": CFG.to_dict(), "train_stresses": TRAIN_STRESS, "eval_stresses": EVAL_STRESS,
           "eval_seeds": EVAL_SEEDS, "training": {"constrained": clog, "unconstrained": ulog}, "rows": rows, "summary": summary,
           "manifest": {"iterations": args.iterations, "episodes_per_iteration": args.episodes, "runtime_s": time.perf_counter() - t0,
                        "python": platform.python_version(), "platform": platform.platform(), "data_origin": "synthetic"}}
    (ROOT / "results" / "safe_rl.json").write_text(json.dumps(out, indent=1, default=list))
    for s in summary:
        print(f"{s['stress']:20s} {s['arm']:18s} cost ${s['cost'][0]/1e8:7.2f}M  vs MPC ${s['cost_diff_vs_mpc'][0]/1e8:+6.2f}M "
              f"[{s['cost_diff_vs_mpc'][1]/1e8:+.2f},{s['cost_diff_vs_mpc'][2]/1e8:+.2f}] settled {s['settled'][0]:.4f} rej {s['safety_rejection_rate']:.3f} wins {s['wins_vs_mpc']}/10")


if __name__ == "__main__":
    main()
