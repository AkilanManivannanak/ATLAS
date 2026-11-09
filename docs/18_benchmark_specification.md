# NEXUS-PAY benchmark specification (`nexus-pay-bench-v1`)

**Data.** Synthetic days from `nexus-pay-gen-v1`. Nothing is observed banking data.

| Parameter (standard preset) | Value |
|---|---|
| Institutions | 16 (25% core, 6× activity) |
| Rails | RTGS, LSM, FedNow-style, RTP-style (RTP on ~75% of banks) |
| Payments / day | ≈3,000 large-value + ≈2,000 instant |
| Opening liquidity | 6% of each account's expected gross outflow (large-value); 25% for instant prefunding |
| RTGS intraday credit | 3% of expected gross outflow |
| Seeds | 11–15 (paired across all arms) |
| Stress scenarios | baseline, counterparty_delay, liquidity_hoarding, combined |
| Arms | fifo, fifo_strict, priority (reference), bilateral, multilateral, multilateral_milp, rule_rebalancer, mpc, mpc_queue_milp |
| Bank strategy | early |

The `extended` preset uses 10 seeds × 11 stress scenarios. The `smoke` preset runs in CI. The blueprint's 100-institution / 500k-payment scale is supported by the generator config but has **not** been benchmarked yet.

**Validity rule.** A row is written only if the run's ledger replays exactly from its event log (`verify_replay`); otherwise the benchmark aborts.

**Statistics.** Per (stress, arm, metric): mean over seeds; paired difference vs the reference arm; 95% percentile bootstrap (4,000 resamples, deterministic RNG); paired win rate. "Significant" means the CI excludes zero. With 5 seeds the intervals are wide; the extended preset should be used before publication.

**Recorded per row.** Seed, stress, arm, policy, controller, scenario fingerprint, final state hash, replay flag, events, all metrics, controller actions and safety rejections. **Manifest:** creation time, runtime, Python, platform, CPU count, workers.

Reproduce: `python -m atlas.benchmark --preset standard --out results/benchmarks`.
