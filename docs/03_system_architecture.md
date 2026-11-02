# System architecture — current implementation

ATLAS-Σ is a typed Python modular monolith. Implemented packages:

- `atlas.domain`: immutable institution/account/payment/collateral/facility/event records, exact money, ledger reconciliation, cash settlement, and versioned rule references.
- `atlas.simulation`: versioned event order, deterministic queue and clock, transaction-scoped handlers, named random streams, replay, and portable JSON checkpoints.
- `atlas.liquidity`: immutable facility draw/repayment operations, exact simple-interest calculation, collateral mobilization, allocation, release, valuation, and stress operations.

Planned boundaries remain institutions/accounts/payments, event simulation, payment rails, liquidity/collateral operations, agents, systemic risk, research, API, persistence, and UI. The domain foundation, deterministic simulation kernel, four synthetic rail archetypes, and core funding/collateral operations are implemented. No future subsystem is described as complete.

Use standard-library domain and simulation code to keep the financial core dependency-light. Add API or persistence libraries when the relevant increment is accepted and tested. Do not introduce distributed infrastructure before measured workload evidence.

See `DECISIONS.md` for recorded choices and `PROJECT_STATUS.md` for current scope.
