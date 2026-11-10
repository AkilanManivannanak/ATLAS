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
