# Safe reinforcement learning (`atlas-safe-ppo-v2`)

**Status: implemented and evaluated** (`atlas.control.rl`, `scripts/train_safe_rl.py`, results in `results/safe_rl.json`).

## Problem
Every 5 minutes each bank chooses, per rail, a **buffer multiplier** b ∈ (0, 3): target cash = b × forecast need (the same need forecast the MPC uses), plus a **transfer aggressiveness** a ∈ (0, 1), the largest share of a source account's cash one move may take. Cash then moves from rails above target to rails below. Proposals are *not* pre-clipped to the safety limits; the policy has to learn to respect them.

## Algorithm
* PPO with clipped surrogate (ε = 0.2), GAE(γ = 0.995, λ = 0.95), Adam, gradient clipping.
* Parameter sharing across banks: one Gaussian policy (19 → 32 tanh → 5) applied per bank, with a shared team reward (cooperative multi-agent, MAPPO-style). Centralised critic on aggregate state.
* **Constraint:** Lagrangian constrained PPO. The cost signal is the number of a bank's own proposals the SafetyController rejected in that step, attributed to that bank's samples; λ is updated by dual ascent towards zero rejections. `constrained=False` gives plain PPO for ablation.
* **Reward:** −(modeled cost accrued in the step) = waiting value × delay rate + newly rejected instant value × penalty + PSR overdraft fee accrual, plus the unsettled-at-close penalty at the last step; scaled so that $1M = 1.
* Pure NumPy; analytic gradients verified against finite differences in tests.

## Protocol
* **Train:** 60 iterations × 8 episodes on fresh days (seeds ≥ 1000) under baseline, counterparty_delay, liquidity_withdrawal, rtgs_outage and haircut_shock.
* **Test:** 10 held-out seeds (9000–9009) under baseline and two stresses never seen in training (combined, liquidity_hoarding). The comparators are no controller, rule-based rebalancer and MPC, on identical days.
* Every evaluation run must replay exactly from its event log.

## Safety guarantees (independent of learning)
Every proposal passes `SafetyController` (`atlas-safety-v1`): own-account only, share cap, committed-cash protection, cutoff, rail availability. Rejected proposals are logged and never executed or repaired. A learned policy cannot reach the ledger any other way.

## History
`v1` (one action per rail, team-level constraint cost) did **not** learn: about 70% of its proposals were rejected and returns stayed flat. The fix in v2 was an explicit size action plus per-bank attribution of the constraint. Both versions are kept in the history for transparency.
