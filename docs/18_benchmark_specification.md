# NEXUS-PAY benchmark specification (`nexus-pay-bench-v2`)

**Data.** Synthetic days from `nexus-pay-gen-v2` (see `23_realism_and_calibration.md`). Nothing is observed banking data.

| Parameter (standard preset) | Value |
|---|---|
| Institutions | 16 (25% core, 6× activity) |
| Rails | RTGS, LSM, FedNow-style, RTP-style (RTP on ~75% of banks) |
| Payments / day | ≈3,000 large-value + ≈2,000 instant |
| Opening liquidity | 18% of each account's *expected* gross outflow (large-value); 25% for instant prefunding |
| RTGS intraday credit | 10% of expected gross outflow, 60% collateralized |
| Seeds | 11–15 (paired across all arms) |
| Stress scenarios | baseline, counterparty_delay, liquidity_hoarding, combined |
| Arms | fifo, fifo_strict, priority (reference), bilateral, multilateral, multilateral_milp, auction_pay_as_bid, auction_uniform, rule_rebalancer, mpc, mpc_queue_milp, mpc_plus_auction |
| Secondary reference | rule_rebalancer (the realistic treasury baseline) |
| Bank strategy | early |

The `extended` preset uses 10 seeds × 11 stress scenarios (1,320 runs); `tight` uses 10%/6% liquidity; `smoke` runs in CI. Scale (100 banks, 669k payments) is measured separately in `results/scaling.json`.

**Cost sensitivity.** Rows store cost-free raw quantities (value-seconds waited, late/unsettled/rejected value, liquidity usage, overdraft minute-sum, collateral used). `cost_sensitivity` re-ranks arms under 27 cost models (delay, unsettled and liquidity weights ×0.25/×1/×4); `reweight_cost` reproduces the simulator's cost to within rounding (tested).

**Validity rule.** A row is written only if the run's ledger replays exactly from its event log (`verify_replay`); otherwise the benchmark aborts.

**Statistics.** Per (stress, arm, metric): mean over seeds; paired difference vs the reference arm; 95% percentile bootstrap (4,000 resamples, deterministic RNG); paired win rate. "Significant" means the CI excludes zero. With 5 seeds the intervals are wide; the extended preset should be used before publication.

**Recorded per row.** Seed, stress, arm, policy, controller, scenario fingerprint, final state hash, replay flag, events, all metrics, controller actions and safety rejections. **Manifest:** creation time, runtime, Python, platform, CPU count, workers.

Reproduce: `python -m atlas.benchmark --preset standard --out results/benchmarks`.
