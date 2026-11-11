# Project status

**Version:** 0.6.0 · **Stage:** all ten blueprint phases implemented to a research-grade increment, including the previously missing auction mechanism, safe RL, decision center and 100-bank scale. Remaining gaps are listed below and in `docs/20_known_limitations.md`.

## Blueprint coverage

| Phase | Status |
|---|---|
| 1. Domain model | Done |
| 2. Multi-rail simulation | Done: four rails, business-day simulator, customer cutoff, LSM closing-position funding |
| 3. Event infrastructure | Done: hash-chained store, strict replay, ISO 20022 pacs.008/009/004 + camt.053 statements |
| 4. Agents | Done: six strategies; empirical game (16 seeds: recycler profile unstable); learning agents via safe RL |
| 5. Liquidity, collateral, forecasting | Done: PSR fee with collateralized/uncollateralized credit; six forecasters incl. graph-conditioned and neural; adaptive intervals. LSTM/TFT not implemented |
| 6. Network and stress | Done |
| 7. Market design and optimization | Done: liquidity auction (pay-as-bid, uniform) with incentive study; netting MILP + LP rounding + heuristic; CVaR LP; MPC |
| 8. Safe RL | Done: constrained PPO (v2) ties MPC on held-out days with 0% safety rejections; v1 failure documented |
| 9. Product | Done: API (analyst, statements, counterfactuals), 9-screen Command Center, Docker, CI, GitHub Pages explorer |
| 10. Validation | Done: standard (240 runs) and extended (1,320 runs, 11 stresses) benchmarks; headline result replicates in 11/11 stresses and 297/297 stress × cost-model cells; scaling to 669k payments |

## Verification (2026-11-10, Python 3.13.18, Linux x86_64, 2 vCPUs)
- `pytest -q`: **156 passed**. `ruff check src tests scripts`: clean. Frontend `tsc --noEmit` and `next build`: pass.
- All benchmark, auction, RL, game and scaling runs replay-verified.
- Not verified here: Docker image builds (no Docker daemon); CI builds them on push.

## Changed since v0.5 (results not comparable)
Generator v2 (realism fixes, D-019), PSR fee (D-020), LSM closing funding, customer cutoff, exact performance work (D-021: ≈3× faster), new arms (auction, MPC + auction), benchmark v2 with cost sensitivity.

## Known gaps
FedNow on its own pool by default (shared-master-account option available; controllers not yet aware of it); instant rails only inside the business day; no defaults, net debit caps or PSR waiver; LSTM/TFT absent; analyst is deterministic (no generative model); no PostgreSQL/ClickHouse/MLflow (deferred, D-016).

## Next tasks
1. Make MPC and the safe-RL controller aware of the shared FedNow master account (done: the option itself and the re-test, `results/shared_master.md`).
2. 24/7 instant-rail days and weekend liquidity.
3. Auction with collateralized loans and counterparty limits; incentive study for borrowers.
4. Multi-day panels with overnight funding and carry-over positions.
5. LSTM/TFT once a deep-learning framework is added to the dependency set.
