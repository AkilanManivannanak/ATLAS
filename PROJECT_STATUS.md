# Project status

**Version:** 0.5.0 · **Current stage:** blueprint Phases 0–7 and 9–10 implemented to a first research-grade increment; Phase 8 (safe RL) and the auction mechanism are not started.

## Completed
- Phases 0–4 (prior increments): domain foundation, deterministic event engine, four rail archetypes, funding and collateral operations.
- Vertical slice (blueprint §32): ISO message → RTGS settlement → hash-chained store → replay → API → UI.
- Append-only SHA-256 hash-chained event store; strict event-sourced ledger with a conservation identity.
- ISO 20022 normalization for pacs.008.001.08, pacs.009.001.08 and pacs.004.001.10.
- NEXUS-PAY synthetic workload generator (fixed-topology multi-day panels supported).
- Multi-rail business-day simulator with 6 settlement policies, liquidity bounds and a cost model.
- Partial multilateral netting: gridlock heuristic v3, bilateral offsetting, exact HiGHS MILP.
- Six rule-based bank strategies and an empirical liquidity-timing game analysis.
- Ten stress scenarios, all recorded as events and replayable.
- Network analytics (betweenness, PageRank, SCC gridlock, HHI) cross-checked against NetworkX.
- Safety controller, MPC controller, rule-based rebalancer; CVaR funding LP.
- Forecasting baselines with split-conformal intervals and in-distribution and OOD tests.
- NEXUS-PAY benchmark runner with paired bootstrap CIs; `standard` results published.
- FastAPI service with RBAC and Prometheus metrics; Next.js Command Center (8 screens).
- Dockerfiles, docker compose (+ observability profile), GitHub Actions CI.

## Verification (2026-11-09, Python 3.13.18, Linux x86_64)
- `pytest -q`: **133 passed**. `ruff check src tests`: clean.
- `npm run typecheck` and `npm run build`: pass.
- Benchmark `standard`: 180/180 runs replay-verified.
- **Not verified in the authoring environment:** Docker image builds (no Docker daemon available). The CI `docker` job builds both images and health-checks the API on push.

## Not implemented / known gaps
Safe RL (PPO/MAPPO/constrained); auction-based liquidity mechanism; LSTM/TFT/graph forecasters; camt messages and XSD validation; PostgreSQL/ClickHouse/MinIO/MLflow/Kafka (deferred by D-016); LLM decision assistant; benchmarks at the 100-institution / 500k-payment scale and the extended preset; cost-weight sensitivity study. See `docs/20_known_limitations.md`.

## Next tasks
1. Run the `extended` preset (10 seeds × 11 stresses) and a cost-weight sensitivity study.
2. Scale profiling at 100 institutions; introduce acceleration only where profiling justifies it.
3. Auction-based liquidity provision (E4) with an incentive analysis.
4. Constrained PPO behind the existing safety controller (E7), benchmarked against MPC.
5. Arrival processes with intraday autocorrelation, then sequence forecasters (LSTM/TFT).
