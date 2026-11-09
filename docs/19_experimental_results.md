# Experimental results

All numbers come from `results/` artifacts produced by this repository on synthetic data (Python 3.13.18, Linux x86_64, 2 vCPUs, 2026-11-09). Re-running the commands reproduces them; the benchmark CIs use a deterministic bootstrap.

## E2/E6 — Settlement policy and adaptive control (`results/benchmarks/standard.md`)
5 paired seeds; reference = `priority`. Total modeled cost (USD, mean) with the 95% CI of the paired difference:

| Arm | baseline | counterparty_delay | liquidity_hoarding | combined |
|---|---|---|---|---|
| priority (ref) | $14.50M | $14.74M | $15.12M | $17.20M |
| multilateral_milp | $14.22M [−0.48, −0.08] | $14.47M [−0.46, −0.08] | $15.11M [−0.56, +0.75] n.s. | $16.61M [−1.59, −0.03] |
| rule_rebalancer | $7.61M [−8.64, −5.17] | $7.73M [−8.60, −5.72] | $9.52M [−7.66, −3.44] | $10.72M [−8.27, −4.84] |
| mpc | $7.60M [−8.48, −5.21] | **$7.36M** [−9.03, −6.04] | $9.96M [−7.01, −3.19] | $10.71M [−7.87, −5.08] |
| mpc_queue_milp | **$7.56M** [−8.76, −5.00] | $7.49M [−8.49, −6.04] | **$9.41M** [−7.44, −3.63] | **$10.22M** [−8.65, −5.31] |

CIs are in $M and are for the paired difference vs `priority`. Bold = lowest mean in the column; the three controller arms are not statistically separated from each other on total cost.

Findings:
1. **Cross-rail liquidity rebalancing is the dominant lever.** MPC cuts modeled cost by ≈48% on baseline days, raises large-value value settled from 90.95% to 96.04% (+3.8 to +6.4pp), and cuts instant-payment rejections by ≈74% (48.8 → 12.6 per day). Every controller arm wins on all 5 seeds in every stress scenario. Mechanism: liquidity is stranded on the rail where a bank is a net receiver while it is short on another rail; own-account transfers fix the fragmentation.
2. **MPC vs the greedy rebalancer:** total cost is statistically indistinguishable, but MPC has ≈34% fewer instant rejections (12.6 vs 19.0), because its LP prices instant shortfalls explicitly. Under combined stress, adding the urgency-weighted queue MILP gives the lowest mean cost.
3. **Queue algorithms matter far less than liquidity placement.** Exact MILP netting is significantly better than priority (+0.07 to +0.35pp settled on baseline days) but worth only ≈2% of cost. Bilateral offsetting and the multilateral heuristic are statistically tied with each other.
4. **Strict FIFO** adds 4–8 minutes of value-weighted delay (significant) with no settlement gain.
5. **Safety:** the final MPC proposes zero actions the safety controller rejects in the reported runs. An earlier version proposed sequential transfers that breached the per-action share cap and post-cutoff transfers; the safety controller blocked them, and the controller was corrected.

## E1 — Forecasting (`results/forecasting.json`)
1-hour horizon, test days never seen in training:

| Model | MASE (in-dist.) | 90% PI coverage (in-dist.) | MASE (OOD) | Coverage (OOD) |
|---|---|---|---|---|
| ridge | **0.676** | 0.898 | 1.543 | 0.710 |
| gradient boosting | 0.698 | 0.902 | 1.576 | 0.714 |
| historical mean | 0.716 | 0.899 | 1.563 | 0.714 |
| seasonal naive | 0.966 | 0.889 | 1.700 | 0.748 |

Split-conformal intervals are well calibrated in distribution (≈0.90 vs nominal 0.90). Under a config shift (+50% volume, fatter tails), coverage collapses to ≈0.71: a documented failure mode that motivates drift monitoring. Gradient boosting does not beat ridge at this data size.

## E5 — Strategic behaviour (`results/game.json`)
6 paired seeds; profiles `early`, `conservative`, `recycler`; focal banks = largest and median. All three profiles are **inconclusive**: no tested unilateral deviation is profitable with a CI excluding zero, but the CIs are too wide to certify stability. `early` has the lowest system cost (≈$8.96M vs $10.26M conservative, $10.76M recycler). Showing that early release is socially optimal *and* an equilibrium needs more seeds; this is reported as an open question.

## Netting optimality (`results/netting_optimality.json`)
Random, deliberately gridlocked queues (20 instances per size):

| Obligations | Mean gap (heuristic v3) | Heuristic optimal | Heuristic ms | MILP ms |
|---|---|---|---|---|
| 10 | 13.4% | 50% | 0.13 | 6 |
| 50 | 30.7% | 0% | 0.84 | 51 |
| 100 | 40.3% | 0% | 1.17 | 159 |
| 200 | 37.6% | 0% | 2.64 | 651 |

The heuristic is fast but far from optimal on adversarial gridlock. The exact MILP solves 200-obligation queues in ≈0.65 s, which is practical at simulated queue sizes. On realistic simulated queues the gap shows up as only ≈0.2pp of settled value (E2).

## E8 — Operational resilience and replay
All 180 benchmark runs, all stress scenarios and all policies replay to the identical ledger state hash from their event logs. Tampering with one stored event is detected at its sequence number.

## Not yet run
E3 (speed vs stability frontier), E4 (auction mechanism, not implemented), E7 (safe RL vs MPC, RL not implemented), the 100-institution scale and the extended 10-seed × 11-stress preset.
