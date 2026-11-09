# Settlement algorithms

| Policy | Description |
|---|---|
| `fifo` | Submission order with bypass: a payment that cannot settle is skipped. |
| `fifo_strict` | Head-of-line blocking per sender. |
| `priority` | Priority, then deadline, then submission order (benchmark reference). |
| `bilateral` | `priority` + periodic bilateral offsetting of the residual queue. |
| `multilateral` | `priority` + periodic partial multilateral netting (`gridlock-heuristic-v3`). |
| `multilateral_milp` | `priority` + exact 0-1 netting with HiGHS. |

Gross passes repeat until no payment settles in a pass, so inflows recycle within the tick.

## Partial multilateral netting
Choose subset S maximizing settled value subject to `L_a + inflow_S(a) - outflow_S(a) ≥ 0` for all accounts (0-1 program; NP-hard in general).
* **Heuristic v3:** best of (a) iterative removal of the lowest-priority/latest/largest outgoing payment of each short account, (b) best-fit removal (smallest payment that covers the deficit, within the lowest priority class), (c) growth from the bilateral-offset selection. Each is repaired by greedy reinsertion. References: Güntzer, Jungnickel & Leclerc (1998), EJOR 106(1); Bech & Soramäki (2001), Bank of Finland DP 9/2001.
* **Exact:** `scipy.optimize.milp` (HiGHS), optional urgency weights. Results are re-verified in integer arithmetic.
* A property test checks on random instances that the MILP equals the brute-force optimum and that the heuristic is always feasible and between bilateral and optimal.

## Market design (auction)
The auction-based liquidity mechanism in blueprint §15 is **not implemented** in this increment.
