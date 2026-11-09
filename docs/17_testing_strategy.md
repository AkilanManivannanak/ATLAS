# Testing strategy

`pytest -q` runs 133 tests (unit, property-based, integration and API).

| Layer | Examples |
|---|---|
| Domain and money | integer minor units, float rejection, lifecycle transitions, settled finality |
| Event engine | deterministic ordering, replay, snapshots, rollback on handler failure |
| Rails | windows, holidays, duplicates, limits, credit opt-in, cycle accounting |
| Event store | tamper detection by sequence, gap rejection, idempotent retry, atomic batch |
| Ledger | reordered events rejected, external-flow accounting, credit cut below usage refused |
| **Property (Hypothesis)** | random payment streams never overspend, never double-settle and replay to the same hash; heuristic always feasible; MILP equals brute-force optimum |
| ISO 20022 | round trips, eight malformed-message classes, XXE rejection |
| Simulator | every policy and every stress scenario replays; determinism of hashes; directional stress effects; funding draws |
| Control | safety accepts/rejects each rule; MPC runs with conserved cross-rail transfers and lower cost than its baseline |
| Analytics | betweenness, PageRank and SCCs equal NetworkX |
| API | lifecycle, replay, counterfactual, RBAC (401/403), structured errors, Prometheus metrics |

CI (`.github/workflows/ci.yml`) runs ruff, the test suite on Python 3.12 and 3.13, a smoke benchmark (which fails if any row does not replay exactly), and the frontend typecheck and production build.
