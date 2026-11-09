# ATLAS-Σ

**A deterministic, event-sourced digital twin of multi-rail financial-market infrastructure.**
ATLAS-Σ simulates how money moves between institutions across four kinds of payment rail, how queues and liquidity interact under stress, and whether adaptive, safety-constrained control can settle more value with less liquidity. Every balance change is a hash-chained event, and every simulated day replays bit-for-bit.

> **Research simulator. All data is synthetic.** ATLAS-Σ does not connect to, replicate or claim the internal rules of Fedwire, CHIPS, FedNow or RTP. It cannot execute payments.

## Headline results (NEXUS-PAY `standard`, 180 runs, every run replay-verified)

16 synthetic banks, ≈5,000 payments a day, 5 paired seeds × 4 stress scenarios × 9 policy arms. Paired 95% bootstrap CIs vs the `priority` queue baseline:

| | Priority queue | MPC (cross-rail rebalancing) | Δ (95% CI) |
|---|---|---|---|
| Total modeled cost / day | $14.50M | $7.60M | −$8.48M … −$5.21M |
| Large-value value settled | 90.95% | 96.04% | +3.8 … +6.4 pp |
| Instant payments rejected / day | 48.8 | 12.6 | −41.0 … −32.4 |
| Win rate across seeds × stresses | — | 20 / 20 | |

The lesson is not a better queue algorithm. Exact MILP netting is significantly better than priority, but by only ≈2% of cost. The big lever is **liquidity fragmentation across rails**: banks are short on one rail while their cash sits idle on another. Full tables, the forecasting, game-theory and optimality-gap studies, and the negative results are in [`docs/19_experimental_results.md`](docs/19_experimental_results.md) and [`results/`](results/).

## What is implemented

| Layer | Highlights |
|---|---|
| Financial core | Immutable domain model, integer minor-unit money, explicit payment lifecycle with settled finality, collateral and funding facilities |
| Event engine | Versioned same-timestamp ordering contract, named SplitMix64 random streams, snapshot/restore/replay |
| Event store | Append-only SQLite, gap-free sequences, **SHA-256 hash chain**; tampering is located by sequence number |
| Ledger | Strict event fold (checks every event's before-balances) with a cash-conservation identity after every event |
| Rails | RTGS (priority/FIFO, intraday credit), liquidity-saving netting, FedNow-style and RTP-style instant archetypes |
| ISO 20022 | `pacs.008/009/004` normalization, structural validation, XXE-safe parsing, original-payload provenance |
| Simulator | Multi-rail business day (a ≈5,000-payment day runs in ≈1–4 s on 2 vCPUs), 6 settlement policies, liquidity bounds, cost model |
| Agents | Six release strategies; empirical liquidity-timing game with scoped, three-valued equilibrium verdicts |
| Stress | 10 named shock scenarios (outages, withdrawals, haircut cuts, hoarding, failure to pay, messaging delay, combined) |
| Network | Flow graph, Brandes betweenness, PageRank, Tarjan SCC gridlock detection, HHI (all checked against NetworkX) |
| Optimization | Exact 0-1 netting MILP (HiGHS), gridlock heuristic, CVaR funding LP (Rockafellar–Uryasev) |
| Control | Receding-horizon MPC (rebalancing LP + urgency-weighted queue MILP) behind a fail-closed **safety controller** |
| Forecasting | Ridge, gradient boosting and baselines; split-conformal intervals; whole-day splits; OOD test |
| Benchmark | NEXUS-PAY generator and paired-seed runner with deterministic bootstrap CIs and run manifests |
| API | FastAPI: simulations, events, replay verification, counterfactuals, network, optimization, ISO; RBAC; Prometheus `/metrics` |
| Command Center | Next.js + D3: network, rails, treasury, stress lab, optimization, adaptive control, research studio, audit |

Not implemented yet (and not claimed anywhere): auction-based liquidity provision, safe RL, LSTM/TFT/graph forecasters, camt messages and XSD validation, PostgreSQL/ClickHouse/MLflow, and the LLM decision assistant. See [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate        # Python 3.12+
pip install -r requirements-lock.txt && pip install --no-deps -e .
pytest -q                                                 # 133 tests

uvicorn atlas.api.app:app --port 8000                     # API + 4 demo runs; docs at http://localhost:8000/docs
cd frontend && npm ci && npm run dev                      # Command Center at http://localhost:3000
```

Or run everything in containers: `docker compose up --build` (add `--profile observability` for Prometheus on :9090 and Grafana on :3001).

```bash
python -m atlas.benchmark --preset standard --out results/benchmarks   # ≈3 min on 2 vCPUs
python scripts/generate_research_artifacts.py                          # forecasting, game, netting gap
```

```python
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day
from atlas.stress import build_scenario
from atlas.control import MPCController

day = generate_scenario(NexusPayConfig(opening_liquidity_bp=600, credit_limit_bp=300), seed=11)
result = run_day(day, SimulationSettings(policy="multilateral"), build_scenario("combined"), controller=MPCController())
assert result.verify_replay()          # ledger re-folded from the event log == live state
print(result.metrics["large_value"]["settlement_rate_value"], result.metrics["costs_minor"]["total"])
```

## Repository map

```text
src/atlas/      domain · simulation · rails · liquidity · ledger · store · iso20022 · scenario · sim
                settlement · agents · stress · network · control · optimize · forecast · benchmark · api · workflows
frontend/       Next.js Command Center (8 screens, all backed by the API)
results/        benchmark and research artifacts (JSON + Markdown), reproducible from the commands above
docs/           specifications 01–21 (architecture, ledger, rails, algorithms, formulations, results, limitations)
deploy/         Prometheus and Grafana provisioning
```

## Engineering principles

Financial correctness before visuals. Integer money only in authoritative state. Every state change is an event. Every run is reproducible from (config, seed, versions). Every optimized or learned action passes the safety controller. Every result is compared against a baseline with paired statistics. Nothing synthetic is presented as real. See [`DECISIONS.md`](DECISIONS.md) for the recorded architecture decisions (D-001 to D-018).

© Akilan Manivannan. All rights reserved.
