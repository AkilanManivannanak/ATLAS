# ATLAS-Σ tasks and acceptance criteria

## Phase 0 — repository discovery and architecture foundation

- [x] Inspect target folder and linked public GitHub repository.
- [x] Record initial project structure and scope.
- [x] Establish modular-monolith architecture decision.
- [x] Add project status, decision log, tasks, and initial architecture/domain documentation.
- [x] Establish Python packaging and pytest configuration.

Acceptance: repository can run its domain tests from a clean Python 3.12+ environment; docs distinguish implemented behavior from future scope.

## Phase 1 — financial domain foundation (complete)

- [x] Define immutable institution, account, payment, and event-envelope records.
- [x] Enforce integer minor-unit money, explicit currency, and aware timestamps.
- [x] Define explicit payment lifecycle transitions and settled finality.
- [x] Add tests for validation, transition, finality, and immutability.
- [x] Add explicit currency precision metadata and exact decimal-to-minor-unit conversion.
- [x] Document versioned simulator assumptions and initial risk register.
- [x] Complete institution, account, payment, collateral, funding-facility, and immutable event-envelope schemas.
- [x] Define account resource decomposition, reconciliation checks, and a cash-only settlement operation with event output.
- [x] Add immutable currency metadata and a versioned source/rule registry that separates official references from simulator assumptions.
- [x] Add tests for domain validation, ledger settlement, reconciliation, collateral/facility units, provenance, and registry versioning.

Acceptance: all phase tests pass; all required domain fields are represented; domain assumptions and limitations are documented; no binary float enters authoritative money state.

## Phase 2 — deterministic event simulation (complete)

- [x] Specify deterministic same-time event ordering and version it.
- [x] Implement seeded event queue, configurable clock, insertion ordering, and permitted cancellation.
- [x] Implement handler replay, canonical snapshots, restore, and state hashes.
- [x] Add isolated named random streams and handler failure rollback.
- [x] Test repeatability for identical initial state, seed, configuration, handler version, and event stream.
- [x] Review Phase 2 acceptance and document remaining limitations before adding rail adapters.

Phase 2 acceptance: `pytest -q` — 42 passed; `python3 -m compileall -q src tests` and `git diff --check` passed. The event engine is deterministic for the documented versioned event stream and handler contract. Durable event storage, business calendars, and rail adapters remain out of scope.

## Phase 3 — payment rail reference models (complete)

- [x] Add shared rail admission contracts with participant, account, currency, lifecycle, duplicate, and timestamp checks.
- [x] Add configurable overnight RTGS schedule, priority queue processing, cash constraints, and opt-in explicit intraday credit draws.
- [x] Add independent liquidity-saving settlement using atomic participant net positions, with one configured settlement account per participant within a cycle.
- [x] Add separate continuous instant models for FedNow-style rollover accounting and privately configured RTP-style limits.
- [x] Register source-backed public operating facts separately from simulator assumptions.
- [x] Test service availability, operating windows, holidays, duplicate rejection, liquidity constraints, settlement finality, and cycle accounting.
- [x] Document model boundaries, evidence, and deferred exception handling.

Phase 3 acceptance: `pytest -q` — 55 passed; `python3 -m compileall -q src tests` and `git diff --check` passed. These are synthetic archetypes and do not reproduce live network rules or connect to payment services. Durable queues, service-specific returns, ISO 20022 schemas, full holiday calendars, facility draw/repayment, and optimization of partial netting cycles remain out of scope.

## Phase 4 — funding and collateral operations (complete)

- [x] Implement facility draw/repayment as immutable operations with capacity, maturity, account, currency, and eligibility checks plus financial events.
- [x] Keep facility principal and account intraday credit as separate resources; require available cash for repayment.
- [x] Add explicit secured-facility collateral requirements, haircut-adjusted allocation, and current-coverage checks before draws.
- [x] Add collateral inventory with delayed mobilization, allocation/release, revaluation shortfalls, and no-double-pledge invariants.
- [x] Add configurable haircut/mobilization-delay stress and exact integer simple-interest calculation.
- [x] Document accounting identities, assumptions, tests, and deferred operations.

Phase 4 acceptance: `pytest -q` — 61 passed; `python3 -m compileall -q src tests` and `git diff --check` passed. Interest is calculated but not accrued into facility balances; full contractual schedules, margin calls, forced liquidation, and collateral optimization remain out of scope.

## Phase 5 — vertical slice, persistence and messaging (complete)
- [x] Append-only hash-chained event store with tamper detection, gap rejection, idempotent retry and atomic batches.
- [x] Strict event-sourced ledger with before-value checks and a cash-conservation identity.
- [x] ISO 20022 pacs.008/009/004 normalization with provenance and XXE-safe parsing.
- [x] End-to-end vertical slice, exposed via API and tested.

Acceptance: property test, where random payment streams replay to an identical hash and never overspend or double-settle, passes.

## Phase 6 — multi-rail simulation, agents and systemic risk (complete)
- [x] NEXUS-PAY generator; business-day simulator over four rails; six settlement policies.
- [x] Six release strategies; empirical liquidity-timing game with scoped verdicts.
- [x] Ten stress scenarios recorded as events; network analytics cross-checked with NetworkX.

Acceptance: every policy and every stress scenario replays exactly; same seed gives the same hash and a different seed gives a different one.

## Phase 7 — optimization and market design (partially complete)
- [x] Partial netting heuristic v3 and exact MILP; optimality-gap study.
- [x] CVaR funding LP with expected-value baseline.
- [ ] Auction-based liquidity provision.

## Phase 8 — adaptive control (partially complete)
- [x] Safety controller (fail-closed) and MPC rebalancing + queue MILP; rule-based ablation.
- [ ] Safe RL (PPO / constrained PPO) behind the safety controller.

## Phase 9 — product and infrastructure (complete for this increment)
- [x] FastAPI service with RBAC, structured errors, counterfactuals, replay verification and Prometheus metrics.
- [x] Next.js Command Center with eight API-backed screens.
- [x] Dockerfiles, compose with observability profile, CI (ruff, tests on 3.12/3.13, smoke benchmark, frontend build, docker build).

## Phase 10 — scientific validation (first results published)
- [x] NEXUS-PAY `standard` benchmark with paired bootstrap CIs; forecasting, game and netting artifacts.
- [ ] Extended preset, cost-weight sensitivity, 100-institution scale, E3/E4/E7.

## v0.6 — realism, missing components, weak results (complete)
- [x] Verified rail parameters from official sources (FedNow $10M, RTP $10M, Fed PSR fee) and recorded them in `RAIL_RULES` v2.
- [x] Generator v2: balanced flows, persistent relationships, autocorrelated activity, payment types, no liquidity look-ahead.
- [x] Simulator: PSR fee, collateralized credit, customer cutoff, LSM closing-position funding, per-bank FedNow limits.
- [x] Exact performance work (≈3×); scaling study to 100 banks / 669k payments.
- [x] Liquidity auction (pay-as-bid, uniform) + E4 incentive study.
- [x] Constrained PPO (v1 failed, v2 ties MPC) + E7 held-out evaluation.
- [x] LP-rounding netting; duplicate-selection bug fixed; MILP tolerance fix.
- [x] Graph-conditioned and neural forecasters; adaptive conformal intervals.
- [x] Game with 16 seeds (recycler unstable).
- [x] camt.053 statements reconciled to the ledger; grounded analyst; Decision Center screen.
- [x] Benchmark v2: auction arms, cost-free raw quantities, 27-model cost sensitivity, extended preset.
- [x] Visual README (dark/light figures, Mermaid, demo GIF), GitHub Pages explorer.

Acceptance: 152 tests pass; every published run replay-verified; every source-backed parameter cited; negative results (RL v1, MPC ≈ rule-based treasury, netting irrelevant at realistic liquidity) reported.
