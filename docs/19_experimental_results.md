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

## v0.7 additions

### Anomaly detection (`results/anomaly_detection.json`)
12 history days, 8 training days, 6 held-out days; 168 injected anomalies in 29,906 payments (0.56%); alert budget = top 1% of payments.

| Detector | PR-AUC | Caught at 1% alert rate | Precision |
|---|---|---|---|
| Hand-written robust-z rule | 0.350 | 41.7% | 23.4% |
| Isolation forest | 0.235 | 28.0% | 15.7% |
| Supervised gradient boosting | **0.708** | **76.8%** | 43.1% |

* The supervised model is far ahead on patterns it trained on, and nearly blind to patterns it did not: leave-one-typology-out recall is 0% to 13%. The rule catches duplicates, limit-hugging and new corridors at 100% without training.
* Amount spikes are hard for everyone (17%): with lognormal sizes (σ = 1.1) an 8-30× payment is not far out in the tail.
* Three typologies have only 6 test incidents each; their per-type figures are coarse.
* Labels are injected. This says nothing about performance on real fraud.

### Model inventory (`results/model_inventory.json`, `docs/model_cards/`)
7 models: 1 pass, 4 warn, 2 fail. The four forecasters warn because static intervals lose coverage under shift (≈71%); both anomaly models fail the unseen-pattern check. The checks are thresholds in code, so the statuses change if a re-run changes the evidence.

### Agent evaluation (`results/agent_evals.json`)
11 tasks (8 analysis, 2 execution requests, 1 out of scope). The deterministic planner passes 100%. The fabricating control fails every task where it changed a number (grounded 46%); the over-reaching control fails both execution requests (safe 82%). **No language model was evaluated.** The official MCP Python client (v2.3) connects to the server and calls tools; that check is manual, not in CI.

### Calibration to published statistics (`results/calibration.json`)
| | Published | Twin, default | Twin, calibrated |
|---|---|---|---|
| Large-value mean | $5.28M (Fedwire Funds 2025) | $4.66M (−11.8%) | $5.27M (−0.2%) |
| Instant mean | $33.7k (FedNow Q3 2026 and RTP Q1 2026, weighted by the twin's rail split) | $24.9k (−26.1%) | $34.1k (+1.3%) |

Re-running three arms under the calibrated sizes leaves the headline unchanged (MPC + auction −60% normal, −53% combined, 5 seeds), which is expected: liquidity is sized relative to flows, so results are scale-free. Only means are published; distribution shape, network and timing stay assumptions.

### Browser lab
`atlas.lab.run_lab` under Pyodide 0.27.7 in headless Chromium: a 12-bank, 2,424-payment day in 1.1-1.4 s; a 4,855-payment uploaded CSV in 2.2 s; ledger replay verified in the page.

## v0.8 additions

### Deep-learning forecasters (`results/deep_forecasting.json`)
GRU and a 2-layer Transformer encoder in PyTorch 2.15.0+cu132 on CPU; same splits, scoring and conformal intervals as the classical models; 8 test days. MASE is scaled within each training size, so compare down a column, not across.

| Model | 15 min, 12 training days | 15 min, 60 training days | 1 h, 60 days | 90% PI coverage (1 h) |
|---|---|---|---|---|
| GRU (PyTorch) | 0.698 | 0.702 | 0.761 | 88.8% |
| Transformer (PyTorch) | 0.705 | 0.711 | 0.758 | 89.1% |
| Gradient boosting | 0.746 | 0.726 | 0.782 | 89.1% |
| Ridge | 0.743 | 0.745 | 0.787 | 88.9% |
| Seasonal naive | 0.965 | 1.332 | 1.373 | 88.7% |

* With 60 training days the GRU is the best model at both horizons, about 6% better than ridge at 15 minutes. With 12 days the margin is smaller. The gain is real but modest.
* Held-out loss is nearly flat while training loss falls: the models extract little beyond the first epochs. Early stopping uses held-out training days only.
* Single seed, CPU, synthetic days from one topology, not tested under distribution shift.

### Rulebook retrieval (`results/retrieval_eval.json`)
170 passages from the specifications, decisions, model cards and data notes; 20 labelled questions (file-level relevance).

| Method | Right source first | In top 3 | MRR |
|---|---|---|---|
| BM25 (used) | 80% | 90% | 0.854 |
| Term overlap baseline | 75% | 100% | 0.850 |

The labels were revised once after the first run showed correct answers in files the first labelling had missed, so these figures are optimistic. BM25 and plain overlap are close on a corpus this small; BM25 is kept because it ranks short exact passages (the glossary) higher. Retrieval is extractive: passages are quoted with file, heading and line.

### Agent evaluation, with red-team tasks (`results/agent_evals.json`)
15 tasks: 9 analysis (one inside a prompt-injection wrapper), 1 rulebook citation, 3 execution requests (one with a fake "system override"), 1 budget flood, 1 out of scope. Planner 100%; fabricating control 53%; over-reaching control 80%. **Still no language model evaluated.**

### Anomaly model validation extras (`results/anomaly_detection.json`)
* Permutation importance (drop in PR-AUC): limit_proximity 0.60, time_surprise 0.27, log_amount 0.25. The model leans heavily on one feature that only two typologies exercise.
* Robustness: PR-AUC 0.71 clean, 0.62 with 5% input noise, 0.53 with 10%, 0.36 with 20%. It degrades quickly.

### Model inventory
9 models: 3 pass (GRU, Transformer, constrained PPO), 4 warn, 2 fail.

## v0.9 additions

### Detectors on real labelled fraud (`results/real_fraud.json`)
ULB credit-card fraud dataset: 284,807 transactions over two days, 492 confirmed frauds (0.173%). Time-ordered split; test = last 20% (56,962 transactions, 75 frauds); alert budget 0.5% (285 alerts).

| Detector | PR-AUC | Frauds caught | Precision of alerts |
|---|---|---|---|
| Gradient boosting | 0.810 | 63 of 75 | 22.1% |
| Logistic regression | 0.747 | 64 of 75 | 22.5% |
| Isolation forest (unsupervised) | 0.042 | 13 of 75 | 4.6% |
| Rule: largest amounts | 0.001 | 1 of 75 | 0.4% |

* Supervised models catch about 84% of real frauds while a person reviews 0.5% of transactions (about 4.5 alerts per fraud caught). The unsupervised isolation forest catches 17%, and amount alone is useless.
* **Split optimism:** the same gradient-boosting model scores PR-AUC 0.846 on a shuffled split against 0.810 when tested on the future: +0.036 from leakage across time.
* **Drift:** feature V1 has PSI 1.46 between train and test (above 0.25 counts as shifted), inside two days.
* **Robustness:** PR-AUC 0.810 clean, 0.797 with noise of 0.25 standard deviations on every feature, 0.768 at 0.5.
* **Scope:** card fraud with PCA-anonymised features, from 2013. It validates the detector families and the evaluation method on real labels. It does not validate the twin's corridor, burst and fan-in features, which cannot be built on this data. Only 75 frauds are in the test window, so one fraud is 1.3 points of recall.

### A language model trained from scratch as tool router (`results/tool_router.json`)
Byte-level Transformer encoder, 95,192 parameters, trained on CPU in 15 minutes on 10,000 template-generated questions with noise. Test A: 1,500 questions from templates held out of training. Test B: 42 hand-written questions, six of them using synonyms the training data never contains.

| Router | A: intent | A: exact route | B: intent | B: exact route |
|---|---|---|---|---|
| Transformer (trained here) | 77% | 71% | 74% | 71% |
| TF-IDF + logistic regression | 96% | 90% | 86% | 81% |
| Keyword rules | 91% | 69% | 86% | 79% |

* **The trained Transformer is the worst of the three.** A character n-gram model with logistic regression is clearly the best on unseen templates and slightly the best on hand-written questions. At this data size, learned byte embeddings generalise worse than n-gram counts.
* As an agent on the 15 tasks: learned router 87% (fails settled_normal, injection_in_data), keyword planner 100%. Safety stays at 100% because no tool can execute, not because the router is right.
* All three routers were written or trained by the same author as both test sets, so even test B is not independent. No pretrained language model is involved.

### Optimiser in the browser lab
MPC + uniform-price auction under combined stress, 12 banks, in headless Chromium on Pyodide 0.27.7 with scipy 1.14 (WebAssembly): 5 s for the day, ledger replay verified, cost −67% against the priority queue on that day. numpy and scipy (about 23 MB) load only when the optimiser is selected.

### Hosted-inference contract
`GET /ping` and `POST /invocations` score a batch of payments statelessly (tested in `tests/test_v09.py`). Not deployed to a cloud account.

## Not yet run
E3 (speed vs stability frontier as a dedicated sweep), cost-model calibration against observed data (none available by design), controllers that are aware of the shared FedNow master account.
