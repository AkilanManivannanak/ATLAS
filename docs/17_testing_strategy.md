# Testing strategy

`pytest -q` runs 156 tests (unit, property-based, integration and API).

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
| API | lifecycle, replay, counterfactual, RBAC (401/403), structured errors, Prometheus metrics, analyst, camt.053 statements |
| Realism | generator v2 balanced flows, limits, no look-ahead, autocorrelation; PSR fee against the Fed's worked example; customer cutoff; LSM closing funding |
| Exactness of optimisations | dirty-set gross pass produces identical ledger hashes to the full rescan under stress |
| Market | auction clearing rules; property test of individual rationality and quantity conservation; interbank loan replay |
| Safe RL | MLP gradients vs finite differences; GAE; rollout, update, safety-filter logging; policy serialisation |
| Statements | every account's camt.053 reconciles to the ledger after a stressed, auction-enabled day |

CI (`.github/workflows/ci.yml`) runs ruff, the test suite on Python 3.12 and 3.13, a smoke benchmark (which fails if any row does not replay exactly), and the frontend typecheck and production build.
