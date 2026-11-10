# Known limitations and risk register

| Risk / limitation | Why it matters | Current treatment / next control |
|---|---|---|
| Synthetic data only | Results describe the model, not real payment systems | Every artifact and UI screen is labeled synthetic; no real data is ingested. |
| Rail archetypes are not replicas | Readers may over-interpret rail names | Archetypes plus a separate evidence/assumption registry (`RAIL_RULES`); no live connectivity. |
| Cost model weights are assumptions | Policy rankings can depend on weights | Documented `CostModel`; next: a sensitivity study across weights. |
| FedNow has its own liquidity pool | Real FedNow settles in the shared Fed master account; cross-rail fragmentation is overstated for FedNow | Documented in docs/23; next: shared-account option and re-test. |
| Instant rails only inside the business day | No weekend/overnight instant liquidity dynamics | Documented; next: 24/7 days. |
| Netting heuristic gap on adversarial queues | Up to ~40% value left vs optimal (LP rounding ~30%) | Exact MILP is fast enough for operational queue sizes (<1 s at 200); a 50 ms anytime MILP is exact to 50 obligations. Gaps published. |
| Seed counts | Standard preset 5 seeds; extended 10 | Both published; claims cite CIs. |
| Game-theoretic results partly inconclusive | Only "recycler is unstable" is established | Verdicts are three-valued and scoped; no Nash claim. |
| Safe RL ties but does not beat MPC | Learned control adds no cost advantage yet | Reported as such; runtime advantage only (no optimisation solve). |
| Auction loans cannot default | Lender incentives ignore credit risk | Unrepaid amounts roll overnight and are reported as exposure. |
| Not implemented: LSTM/TFT, XSD validation, PostgreSQL/ClickHouse/MLflow, generative LLM narration | Blueprint scope remains | Listed in `PROJECT_STATUS.md`; no doc claims them. |
| Cross-rail transfers are instantaneous | Real liquidity transfers have cutoffs and delays | Safety cutoff 15 minutes before close; next: modeled transfer latency. |
| Facility interest accrues to close regardless of early repayment | Slight overstatement of funding cost | Documented simplification. |
| Development-mode API | Open access if exposed | `/health` reports auth mode; set `ATLAS_API_KEYS` for any network deployment. |
| Docker images not built in the authoring environment | Container regressions possible | CI builds both images and health-checks the API on every push. |
| Float use | Analytics and costs use floats | Authoritative ledger state is integer-only and validated; floats appear only in metrics, sampling and solvers, and solver output is re-verified in integers. |
