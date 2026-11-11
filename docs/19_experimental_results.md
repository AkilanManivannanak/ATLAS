# Experimental results (v0.6)

All numbers come from `results/` artifacts produced by this repository on **synthetic** data (generator `nexus-pay-gen-v2`, Python 3.13.18, Linux x86_64, 2 vCPUs, 2026-11-10). Every simulation row is admitted only if its ledger replays exactly from its event log. Confidence intervals are 95%: percentile bootstrap of paired differences for the benchmark, Student-t elsewhere.

> v0.5 results (generator v1) are superseded and not comparable: v1 sized opening liquidity from the realised day and produced structural liquidity sinks (DECISIONS D-019).

## E2 / E6: settlement policy and adaptive control (`results/benchmarks/standard.md`)
16 banks, ≈5,200 payments/day, default (calibrated) liquidity, 5 paired seeds × 4 stresses × 12 arms = 240 runs, all replay-verified.

| Arm | Normal day: cost | Value settled | Instant rejected | Combined stress: cost | Value settled |
|---|---|---|---|---|---|
| Priority queue (reference) | $5.47M | 97.33% | 89.2 | $6.94M | 97.03% |
| Exact MILP netting | $5.47M (n.s.) | 97.33% | 89.2 | $6.94M (n.s.) | 97.03% |
| Rule-based treasury (realistic baseline) | $3.87M | 98.36% | 6.6 | $5.58M | 97.85% |
| MPC rebalancing | $3.84M | 98.37% | 5.2 | $5.68M | 97.75% |
| Liquidity auction (either rule) | $3.77M | 98.57% | 89.2 | $4.42M | 98.87% |
| **MPC + auction** | **$2.14M** | **99.55%** | **1.6** | **$3.35M** | **99.39%** |

Findings:
1. **The two liquidity levers are complementary.** Cross-rail rebalancing fixes *fragmentation* (cash on the wrong rail, which shows up as instant rejections); the auction fixes *distribution* (cash at the wrong bank). Together they cut modeled cost by 61% on normal days (CI −$4.63M to −$2.50M) and 52% under combined stress, winning on every seed. The combination is the cheapest arm under **all 27** alternative cost models (delay, unsettled and liquidity weights each ×0.25/×1/×4) in every stress scenario.
2. **MPC alone does not beat a realistic treasury rule.** Against the rule-based rebalancer, MPC's cost difference is −$0.02M [−0.18, +0.13] on normal days, n.s.; under liquidity hoarding it is slightly *worse* (+$0.05M [+0.01, +0.09]). The v0.5 claim that MPC dominated the queue baseline was a "doing treasury vs not doing treasury" effect. Adding the auction beats the rule-based treasury by $1.7–2.2M/day in every stress (significant).
3. **Queue algorithms are irrelevant at realistic liquidity.** Bilateral, multilateral heuristic and exact MILP netting are indistinguishable from the priority queue (identical costs): with balanced flows and calibrated liquidity there is almost no gridlock for netting to resolve. Strict FIFO is significantly worse under combined stress. Netting matters in the `tight` preset.
4. **Pay-as-bid and uniform price produce identical allocations** (same quantities matched); they differ only in prices (avg 0.25 vs 0.27 bp flat) and in incentives (E4).
5. **Trade-off:** MPC + auction raises peak intraday credit usage by ≈49% vs the priority queue (largely collateralized, so the PSR fee stays small). Timed-obligation deadline misses fall from 2.8 to 0.2 per normal day (20.0 → 14.2 under combined stress).

## Replication: extended preset (`results/benchmarks/extended.md`)
10 seeds (11–20; 16–20 are new, 11–15 are the standard-preset seeds) × 11 stress scenarios × 12 arms = 1,320 runs, all replay-verified (runtime 1,018 s on 2 vCPUs). Cost change vs the priority queue (all significant, win rate 100% unless stated):

| Stress | Rule-based treasury | MPC | Liquidity auction | **MPC + auction** | MPC + auction vs rule-based |
|---|---|---|---|---|---|
| baseline | −30% | −30% | −35% | **−60%** | −$1.67M [−2.65, −0.87] |
| combined | −22% | −21% | −40% | **−54%** | −$2.26M [−3.60, −1.21] |
| concentrated outflows | −25% | −25% | −48% | **−66%** | −$2.89M [−4.21, −1.60] |
| counterparty delay | −28% | −29% | −34% | **−57%** | −$1.70M [−2.68, −0.90] |
| failure to pay | −8% | −8% | −16% | **−26%** | −$4.77M [−6.98, −2.80] |
| funding disruption | −24% | −23% | −48% | **−67%** | −$3.37M [−4.95, −1.99] |
| haircut shock | −28% | −29% | −42% | **−64%** | −$2.34M [−3.51, −1.37] |
| liquidity hoarding | −26% | −25% | −36% | **−54%** | −$1.68M [−2.70, −0.86] |
| liquidity withdrawal | −25% | −25% | −40% | **−64%** | −$2.92M [−4.18, −1.81] |
| messaging failure | −26% | −27% | −33% | **−55%** | −$1.73M [−2.66, −0.97] |
| RTGS outage | −27% | −27% | −32% | **−56%** | −$1.71M [−2.72, −0.91] |

* All standard-preset conclusions replicate. MPC + auction ranks first under all 27 cost weightings in all 11 stresses (297/297).
* MPC vs the rule-based treasury: not significant in 10/11 stresses, slightly worse under liquidity hoarding (+$0.04M [+0.01, +0.06]), the same result as the standard preset.
* Netting (bilateral, heuristic, exact MILP) is indistinguishable from the priority queue in 10/11 stresses; the one significant effect is −1% under concentrated outflows.
* Failure-to-pay is the hardest case (savings shrink to 26%), plausibly because a failing bank's missing payments are a solvency-like shock that moving liquidity cannot replace.

## FedNow on the shared Fed master account (`results/shared_master.md`)
Same seeds (11–15), standard scenario, 5 arms × 3 stresses × 2 account models = 150 runs, all replay-verified. In the shared model FedNow draws on the RTGS balance and intraday credit, as the PSR policy allows.

| Stress | MPC + auction vs priority (separate → shared) | MPC + auction vs rule-based treasury (shared) | Rule-based vs priority (shared) | Instant rejected, priority queue (separate → shared) |
|---|---|---|---|---|
| baseline | −61% → **−59%** | −$1.60M [−2.02, −1.19] | −29% | 89.2 → 30.4 |
| liquidity hoarding | −56% → **−54%** | −$1.63M [−2.17, −1.20] | −25% | 89.2 → 30.2 |
| combined | −52% → **−51%** | −$2.11M [−2.72, −1.50] | −20% | 179.8 → 117.6 |

* **The headline conclusions survive the realistic account model.** MPC + auction stays the cheapest arm and beats the rule-based treasury by $1.6–2.1M/day in every stress; cross-rail rebalancing still saves 20–29% vs the priority queue, because RTP and the LSM remain prefunded pools.
* **Sharing the master account removes most FedNow rejections on its own** (about two thirds on normal days), but the cost effect is small (−$0.10M to +$0.02M for the priority queue) because instant payments are low in value.
* **One honest regression:** with MPC + auction, instant rejections rise from 1.6 to 12.4 per normal day and cost rises by $0.08M [+0.01, +0.19]. FedNow now competes with Fedwire and auction lending for the same balance, and the MPC still plans a separate FedNow buffer that the sweep returns to RTGS. Making the controllers aware of the shared account is the next task.

## E4: liquidity auction and incentives (`results/auction.json`)
8 paired seeds, tighter liquidity (10% / 6%), normal and combined days.

* **System effect:** the auction raises value settled by **+2.44 pp** [+1.35, +3.52] on normal days and **+3.21 pp** [+1.76, +4.66] under combined stress, and cuts cost by $3.3M / $4.2M per day. Average price ≈0.25–0.30 bp flat. About 60% of auction principal cannot be repaid from cash at close and rolls to overnight funding: a counterparty exposure the mechanism creates.
* **Incentives (focal = 3 largest lenders, each inflating its ask alone):**

| Ask inflation | Pay-as-bid: lender's profit change | Uniform price |
|---|---|---|
| +25% | **+$409 [+154, +664]**, profitable in 67% of cases | +$274 [−8, +556], n.s. |
| +50% | +$280 [−3, +563] (combined: **+$397 [+74, +720]**) | +$62, n.s. |
| +100% / +200% | 0 (priced out) | **−$235 [−344, −126]** (loses its trades) |

Pay-as-bid rewards mild shading, the textbook discriminatory-auction behaviour. Under uniform price, small shading is not significantly profitable and large shading is significantly unprofitable. Magnitudes are small (hundreds of dollars per lender-day) because intraday rates are fractions of a basis point; the *direction* is the finding. Neither mechanism is claimed incentive compatible.

## E7: safe RL vs MPC (`results/safe_rl.json`)
Constrained PPO (`atlas-safe-ppo-v2`) trained 60 × 8 episodes; evaluated on 10 held-out seeds (cost difference vs MPC, 95% CI):

| Stress | No controller | Rule-based | Constrained PPO | Plain PPO | PPO proposals rejected by safety |
|---|---|---|---|---|---|
| baseline | +$0.70M [+0.27, +1.14] | −$0.04M n.s. | **−$0.00M [−0.06, +0.05]** | +$0.04M n.s. | **0.0%** (plain: 0.5%) |
| combined *(never trained on)* | +$1.31M | +$0.05M n.s. | +$0.04M [−0.16, +0.25] | +$0.04M n.s. | **0.0%** (plain: 0.2%) |
| liquidity_hoarding *(never trained on)* | +$1.05M | +$0.19M n.s. | +$0.24M [−0.09, +0.56] | +$0.13M n.s. | **0.0%** (plain: 0.4%) |

The constrained policy learns to **match MPC** without solving an optimisation problem at runtime, generalises to unseen stresses without a significant loss, and drives safety rejections to zero (from ≈2 per step at initialisation). It does not beat MPC. v1 of the agent did not learn at all (≈70% of proposals rejected); see `docs/14_safe_rl_design.md`.

## E1: forecasting (`results/forecasting.json`)
Target: a bank's large-value gross outflow per 15 minutes; whole-day splits (12 train / 4 val / 4 test); OOD = +50% volume, fatter tails, more volatile market factor.

| Model | MASE 15 min | MASE 1 h | 90% PI coverage (1 h, in-dist.) | OOD static | OOD adaptive |
|---|---|---|---|---|---|
| neural window (MLP) | **0.773** | **0.823** | 88.9% | 71.4% | 88.2% |
| gradient boosting | 0.778 | 0.853 | 88.5% | 73.2% | 88.2% |
| graph-conditioned ridge | 0.780 | 0.832 | 88.8% | 71.1% | 88.2% |
| ridge | 0.783 | 0.829 | 88.6% | 70.9% | 88.2% |
| historical mean | 0.822 | 0.839 | 89.0% | 75.4% | 88.4% |
| seasonal naive | 1.013 | 1.037 | 89.6% | 78.2% | 88.8% |

Every learned model beats naive, but they are close to each other: the neural model is best by a hair at short horizons, and the learned dependency graph adds little. Static conformal intervals are calibrated in distribution and **collapse to ≈71% under shift**; causal online tracking restores ≈88%. The price is width: at the 4-hour horizon the adaptive intervals become very wide (feedback arrives late), which is reported, not hidden.

## E5: strategic behaviour (`results/game.json`)
16 paired seeds; everyone plays early / conservative / recycler; focal = largest and median bank.
* **Recycler is unstable:** the largest bank gains by unilaterally switching to early (+$0.13M [+0.04, +0.21]) or conservative (+$0.12M [+0.03, +0.22]).
* **Early** has the lowest system cost ($4.78M vs $5.08M conservative, $5.69M recycler); no profitable deviation found, but the CIs do not certify an ε-equilibrium (**inconclusive**). The same holds for conservative.
* Claims are scoped to the tested deviations; no Nash equilibrium is asserted.

## Netting optimality (`results/netting_optimality.json`)
Adversarial random gridlock, 20 instances per size; gap = value left unsettled vs the exact HiGHS MILP.

| Obligations | Heuristic v3 | LP rounding + local search | MILP, 50 ms budget | Exact MILP time |
|---|---|---|---|---|
| 10 | 13.4% | 9.9% | 0.0% | 6 ms |
| 50 | 30.7% | 22.3% | 0.0% | 34 ms |
| 100 | 40.3% | 32.9% | 19.4% | 135 ms |
| 200 | 37.6% | 30.4% | 27.0% | 744 ms |

A real bug was found while building this: the local search could select one obligation twice. Every netting output is now asserted duplicate-free, and the property test covers all four algorithms against brute force. The 50 ms anytime MILP is exact up to 50 obligations; for operational queue sizes, the exact solver is fast enough.

## Scaling (`results/scaling.json`)
See the README chart: a single CPU core simulates and replay-verifies a 100-bank day of several hundred thousand payments in minutes, with near-linear runtime.

## E8: resilience and replay
All benchmark, auction, RL, game and scaling runs replay to the identical ledger state hash from their event logs. Every account's camt.053 statement reconciles to the ledger.

## Not yet run
E3 (speed vs stability frontier as a dedicated sweep), cost-model calibration against observed data (none available by design), controllers that are aware of the shared FedNow master account.
