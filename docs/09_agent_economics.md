# Agent economics

## Family A — rule-based release strategies (`atlas.agents.strategies`)
A strategy sees only its own institution (`BankView`): held payments, its own cash and credit headroom per rail, inflows received since the last decision and in the last hour, its own historical inflow profile, and a stress signal. It cannot see other banks' queues.

| Strategy | Rule |
|---|---|
| `early` | Release everything immediately (cooperative benchmark). |
| `conservative` | Keep a cash buffer (default 50% of opening); release above it, or anything due within 15 minutes. |
| `priority` | Urgent payments immediately; others in 30-minute batches or when due within 20 minutes. |
| `recycler` | Spend received inflows plus a capped own-liquidity allowance (liquidity recycling). |
| `funding` | Release everything and draw an unsecured facility (via `draw_funding`) to cover the shortfall; interest is costed with `calculate_simple_funding_cost`. |
| `stress_responsive` | Early in normal conditions; switches to conservative when hourly inflows fall below 50% of the bank's own expectation or a stress signal is raised. |

Strategies only *propose* releases; rails still enforce every constraint.

## Family B — empirical liquidity game (`atlas.agents.game`)
Following the liquidity-timing game of Bech & Garratt (2003) and the empirical game-theoretic analysis method (Wellman, 2006): for each symmetric profile (all banks play *s*) a focal bank (largest and median) unilaterally deviates to *d* on the **same** generated day. The focal bank's own cost (delay + unsettled penalty + liquidity + credit, `institution_cost`) is compared across paired seeds.

Verdicts are three-valued: `unstable` (some deviation is profitable with a 95% CI above zero and a mean above ε), `empirical_epsilon_equilibrium` (every deviation's upper bound is below ε), or `inconclusive`. Claims are scoped to the tested focal banks and deviations and are **never** presented as proofs of Nash equilibrium.

## Family C — learning agents
Not implemented (see `14_safe_rl_design.md`).
