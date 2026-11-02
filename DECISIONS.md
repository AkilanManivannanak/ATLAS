# Architecture and modeling decisions

## D-001 — Modular monolith first

**Decision:** Begin with a typed Python modular monolith.

**Reason:** Domain and settlement correctness must be validated before operational distribution is justified. Clear package boundaries allow later extraction if measured needs support it.

**Alternatives considered:** Immediate microservices, Kafka/Flink/Kubernetes, Rust kernel. Deferred because no workload measurements justify their costs.

## D-002 — Integer minor units for authoritative money

**Decision:** Store monetary amounts as integer minor units and retain an explicit currency code.

**Reason:** Avoid binary floating-point arithmetic in ledger state.

**Limitation:** Currency exponent metadata and multi-currency conversion are not yet modeled.

## D-003 — Immutable domain records and explicit lifecycle transitions

**Decision:** Use frozen dataclasses and a closed payment transition registry.

**Reason:** Make mutation and terminal finality visible and testable.

## D-004 — Synthetic-only research scope

**Decision:** No external payment execution or live financial data integration is in scope for the initial simulator.

**Reason:** The blueprint defines a simulated research environment and requires synthetic data to be represented honestly.

## D-005 — Explicit currency precision and versioned rule registry

**Decision:** Currency exponents are configuration data in a versioned registry; simulator rules are immutable records with monotonically increasing versions and explicit evidence classification.

**Reason:** Avoid implicit currency precision and prevent modeled assumptions from being presented as official network rules.

**Limitation:** The initial registry has no global currency catalogue and no payment-rail rule. Such rules must be sourced and tested before rail behavior is implemented.

## D-006 — Settlement uses cash only until facilities are modeled

**Decision:** The initial gross cash transfer requires sufficient unreserved ledger cash and never silently draws account credit.

**Reason:** An undrawn facility is not settlement cash. Credit draw must be an explicit, separately recorded funding operation.

**Limitation:** The settlement operation does not yet use credit or validate rail-specific operating rules.
