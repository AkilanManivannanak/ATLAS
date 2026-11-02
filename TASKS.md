# ATLAS-Σ tasks and acceptance criteria

## Phase 0 — repository discovery and architecture foundation

- [x] Inspect target folder and linked public GitHub repository.
- [x] Record initial project structure and scope.
- [x] Establish modular-monolith architecture decision.
- [x] Add project status, decision log, tasks, and initial architecture/domain documentation.
- [x] Establish Python packaging and pytest configuration.

Acceptance: repository can run its domain tests from a clean Python 3.12+ environment; docs distinguish implemented behavior from future scope.

## Phase 1 — financial domain foundation (in progress)

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

## Phase 2 — deterministic event simulation (next)

- [ ] Specify deterministic same-time event ordering and version it.
- [ ] Implement seeded event queue and simulation clock.
- [ ] Implement deterministic replay and snapshots.
- [ ] Test repeatability for identical initial state, seed, configuration, and event stream.
