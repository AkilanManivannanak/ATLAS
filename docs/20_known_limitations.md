# Known limitations and risk register

| Risk / limitation | Why it matters | Current treatment / next control |
|---|---|---|
| Synthetic data only | Results describe the model, not real payment systems | Every artifact and UI screen is labeled synthetic; no real data is ingested. |
| Rail archetypes are not replicas | Readers may over-interpret rail names | Archetypes plus a separate evidence/assumption registry (`RAIL_RULES`); no live connectivity. |
| Cost model weights are assumptions | Policy rankings can depend on weights | Documented `CostModel`; next: a sensitivity study across weights. |
| Generator lacks intraday autocorrelation | Forecast horizons barely matter; sequence models cannot show their value | Documented; next: Hawkes/ARMA arrival processes. |
| Netting heuristic gap on adversarial queues | Up to ~40% value left vs optimal | Exact MILP available and benchmarked; heuristic gap published. |
| 5-seed benchmark | Wide CIs; small effects may be missed | Extended preset (10 seeds × 11 stresses) exists; run before publication. |
| Scale not yet benchmarked at 100 banks / 500k payments | Runtime and behaviour at scale unknown | Generator supports it; profile before adding Rust or distributed infrastructure. |
| Game-theoretic results inconclusive | Equilibrium claims would be premature | Verdicts are three-valued and scoped. |
| Not implemented: auction mechanism, safe RL, LSTM/TFT/graph forecasters, camt messages, XSD validation, PostgreSQL/ClickHouse/MLflow, AI Decision Center | Blueprint scope remains | Listed in `PROJECT_STATUS.md` and `TASKS.md`; no doc claims them. |
| Cross-rail transfers are instantaneous | Real liquidity transfers have cutoffs and delays | Safety cutoff 15 minutes before close; next: modeled transfer latency. |
| Facility interest accrues to close regardless of early repayment | Slight overstatement of funding cost | Documented simplification. |
| Development-mode API | Open access if exposed | `/health` reports auth mode; set `ATLAS_API_KEYS` for any network deployment. |
| Docker images not built in the authoring environment | Container regressions possible | CI builds both images and health-checks the API on every push. |
| Float use | Analytics and costs use floats | Authoritative ledger state is integer-only and validated; floats appear only in metrics, sampling and solvers, and solver output is re-verified in integers. |
