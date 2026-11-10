# System architecture — current implementation

ATLAS-Σ is a typed Python modular monolith with a Next.js command center. The financial core is **standard-library only**; numerical libraries are confined to optimization, forecasting and the API.

```text
             ISO 20022 (pacs.008/009/004) ──► atlas.iso20022  normalize · validate · provenance
                                                   │
 NEXUS-PAY generator ──► atlas.scenario ──► atlas.sim.DaySimulator ◄── atlas.agents (release strategies)
                                                   │      ▲              atlas.stress (shock library)
                         rails: atlas.rails (RTGS · LSM · FedNow-style · RTP-style archetypes)
                         queues: atlas.settlement (bilateral · gridlock heuristic · exact MILP)
                         control: atlas.control (MPC · rule rebalancer)  ──► SafetyController ──┐
                                                   │                                           │ approved only
                                                   ▼                                           ▼
                    FinancialEvent stream ──► atlas.ledger.Ledger (strict fold, conservation check)
                                                   │
                                                   ▼
                    atlas.store.EventStore (SQLite, append-only, SHA-256 hash chain) ──► replay / audit
                                                   │
 analytics: atlas.network (graph, centrality, SCC gridlock) · atlas.forecast (conformal) · atlas.optimize (CVaR LP)
 research:  atlas.benchmark (paired seeds, bootstrap CIs) · atlas.agents.game (empirical game analysis)
 delivery:  atlas.api (FastAPI, RBAC, /metrics) ──► frontend/ (Next.js, D3)  · docker compose · Prometheus/Grafana profile
```

| Package | Responsibility | External deps |
|---|---|---|
| `atlas.domain` | Immutable institution/account/payment/collateral/facility/event records, exact money, lifecycle state machine, cash settlement primitive | none |
| `atlas.simulation` | Versioned event ordering (`atlas-event-order-v1`), generic transactional engine with snapshot/replay, named SplitMix64 streams | none |
| `atlas.rails` | Four independent rail archetypes and rule/evidence registry | none |
| `atlas.liquidity` | Facility draw/repay, interest, collateral inventory, mobilization, stress | none |
| `atlas.ledger` | Event-sourced ledger: strict before/after checks and cash-conservation identity | none |
| `atlas.store` | Append-only hash-chained event store (`atlas-event-store-v1`) | sqlite3 (stdlib) |
| `atlas.iso20022` | Hardened XML parsing, structural validation, canonical normalization, builders | none |
| `atlas.scenario` | NEXUS-PAY synthetic workload generator (`nexus-pay-gen-v1`) | none |
| `atlas.sim` | Multi-rail business-day simulator (`atlas-day-sim-v1`), metrics and costs | none (SciPy only for MILP policy) |
| `atlas.settlement` | Netting algorithms | SciPy/HiGHS for the exact MILP |
| `atlas.agents` | Rule-based strategies; empirical game analysis | none |
| `atlas.stress` | Shock types and the named scenario library | none |
| `atlas.network` | Flow graph, Brandes betweenness, PageRank, Tarjan SCC, HHI | none |
| `atlas.control` | Safety controller, MPC and rule-based controllers | SciPy/HiGHS (MPC) |
| `atlas.optimize` | CVaR / expected-value funding LPs | NumPy, SciPy/HiGHS |
| `atlas.forecast` | Forecasters, conformal intervals, scenario-level splits | NumPy, scikit-learn (GBM) |
| `atlas.benchmark` | Benchmark runner, paired bootstrap statistics, reports | none |
| `atlas.market` | Sealed-bid intraday liquidity auction (pay-as-bid, uniform) | none |
| `atlas.control.rl` | Constrained PPO (Lagrangian), NumPy | NumPy |
| `atlas.analyst` | Grounded Q&A over simulation results (cited, cannot execute) | none |
| `atlas.iso20022.camt` | camt.053 statements built from events, reconciliation | none |
| `atlas.api` | REST API, RBAC, Prometheus text metrics | FastAPI, Pydantic, Uvicorn |

Infrastructure that the blueprint lists but the measured workload does not yet need (Kafka/Flink, ClickHouse, PostgreSQL, MinIO, MLflow, Kubernetes, a Rust kernel) is intentionally absent; see `DECISIONS.md` D-001 and D-016.
