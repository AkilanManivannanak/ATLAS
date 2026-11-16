# API specification (v1)

Base: `/api/v1`. JSON everywhere; errors are `{"error": {"code", "message"}}`. Interactive docs at `/docs` (OpenAPI).

| Method & path | Permission | Purpose |
|---|---|---|
| `GET /health` | public | status, version, auth mode, event-store path |
| `GET /meta` | read | policies, strategies, controllers, stress library, benchmark arms |
| `GET /scenarios` | read | stress scenario library |
| `GET /vertical-slice` | read | run the end-to-end vertical slice |
| `POST /simulations` | simulate | run a business day (seed, size, liquidity, policy, strategy or mix, stress, controller incl. `safe_rl`, `auction`) |
| `GET /simulations` · `GET /simulations/{id}` | read | summaries; full metrics, timeseries, per-institution stats, controller log, manifest |
| `GET /simulations/{id}/payments` | read | filter by status, rail, institution; paginated |
| `GET /simulations/{id}/events` | read | hash-chained event log; filter by type; paginated |
| `POST /simulations/{id}/replay` | read | verify the chain and re-fold the ledger; compare state hashes and conservation |
| `GET /simulations/{id}/institutions[/{inst}]` | read | institution stats; counterparty exposures |
| `GET /simulations/{id}/network` | read | network report, hourly snapshots, residual gridlock |
| `GET /simulations/{id}/rails/{rail}` | read | rail metrics and timeseries |
| `POST /simulations/{id}/counterfactual` | simulate | paired re-run with explicit changed assumptions, plus diff |
| `POST /simulations/{id}/ask` | read | grounded analyst: deterministic answer, every number cited, cannot execute |
| `GET /simulations/{id}/statements/{account}` | read | camt.053 end-of-day statement from the event store + reconciliation to the ledger |
| `DELETE /simulations/{id}` | admin | drop from memory (events stay in the store) |
| `POST /optimization/funding` | simulate | CVaR and expected-value funding plans |
| `POST /optimization/netting` | simulate | heuristic / MILP / bilateral netting of supplied obligations |
| `POST /iso20022/normalize` | read | validate and normalize an XML message (`application/xml`) |
| `GET /benchmarks` · `GET /benchmarks/{name}` | read | benchmark artifacts |
| `GET /research/{forecasting,game,netting_optimality,auction,safe_rl,scaling}` | read | research artifacts |
| `GET /metrics` | public | Prometheus text exposition |

There is no payment-execution endpoint, because the system has no execution capability.

## v0.7 endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/ingest/template` | CSV header and three example rows |
| POST | `/api/v1/ingest/payments` | Run the twin on an uploaded payments CSV (optional balances CSV); returns the run summary and the ingest report |
| GET | `/api/v1/simulations/{id}/intraday-liquidity` | BCBS 248 monitoring tools for every institution |
| GET | `/api/v1/simulations/{id}/anomalies?top=25` | Payments ranked as most unusual (training-free detector) |
| GET | `/api/v1/governance/models` | Model inventory with tiers and validation checks |
| GET | `/api/v1/research/{anomaly_detection,agent_evals,calibration,shared_master}` | New result artifacts |

Uploaded files are held in memory for the run and are not written to disk by the API; the event store records the resulting ledger events as for any run. Counterfactuals on an uploaded day re-run the same payments; balance changes require a new upload.
