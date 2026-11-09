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

**Limitation:** The initial domain registry has no global currency catalogue. Rail evidence and assumptions now live in a separate `RAIL_RULES` registry; source facts remain limited and do not establish a network replica.

## D-006 — Settlement uses cash only until facilities are modeled

**Decision:** The initial gross cash transfer requires sufficient unreserved ledger cash by default. A rail adapter may explicitly opt into drawing only the required intraday credit shortfall.

**Reason:** An undrawn facility is not settlement cash. Credit draw must be explicit and recorded in account and settlement state.

**Limitation:** Credit draws are not yet linked to facility accounting or a separate funding draw event. Rail validation is synthetic and configurable.

## D-007 — Version event ordering and phase ties

**Decision:** Event order is timestamp, documented phase priority, insertion order, then event ID. The current contract is `atlas-event-order-v1`.

**Reason:** Same-time event effects must be stable and auditable across replays.

**Limitation:** This order is an ATLAS simulator convention. It must not be presented as a real payment network's internal ordering.

## D-008 — Atomic event-handler effects

**Decision:** Handlers return a new JSON state. Newly scheduled events and random draws are staged and committed with state only after the handler succeeds. A failed handler halts the engine; recovery uses a prior snapshot.

**Reason:** Avoid partial account/state changes and hidden retry behavior.

## D-009 — Named stable random streams

**Decision:** Each named stream is derived from the master seed and stream name and uses SplitMix64 integer draws. Stream state is included in snapshots.

**Reason:** A change in one participant's draws must not shift another participant's random sequence.

**Limitation:** Stream algorithm changes require a new simulator version; no random values are converted into authoritative monetary floats.

## D-010 — Separate rail archetypes and preserve evidence boundaries

**Decision:** Implement RTGS, liquidity-saving, and two distinct instant-payment archetypes behind shared validation contracts, with independent queue/clock/limit behavior. Keep public-source facts separate from explicit simulator assumptions.

**Reason:** The blueprint requires rail heterogeneity, while public descriptions do not justify claims to reproduce all production rules or proprietary mechanisms.

**Limitation:** Rail queues are in-memory inputs; the liquidity-saving baseline is an all-or-nothing cycle; network-specific returns and detailed message rules are future work.

## D-011 — Separate facility principal, cash, and collateral

**Decision:** A facility draw increases facility principal and credits account ledger cash as one immutable operation. Collateral allocations are separately tracked in an immutable inventory, are limited by haircut-adjusted eligible value, and are checked against configured facility advance-rate requirements.

**Reason:** Undrawn commitments, drawn cash, intraday credit, and pledged collateral represent different resources and must not be added together or reused across facilities.

**Limitation:** Advance rates and eligibility profiles are local assumptions. Interest is calculated but not posted; margin calls, forced liquidation, and persistent event storage remain future work.

## D-012 — In-process day simulator that earns replay through the ledger fold

**Decision:** The multi-rail business-day simulator (`atlas.sim`) keeps state in process and reuses the versioned `atlas-event-order-v1` contract, instead of running every event through the generic JSON-state `SimulationEngine`.

**Reason:** The generic engine serializes the entire state on every event, which is ideal for auditing small models but makes a 5,000-payment day quadratic in practice. The day simulator gets the same guarantee a different way: every balance change is a `FinancialEvent` folded by the strict `Ledger`, which checks the event's *before* values and the cash-conservation identity. Live state therefore *is* the fold of the log, and `SimulationResult.verify_replay()` re-folds the log from opening balances and must reproduce the final state hash. Every benchmark row is rejected unless this holds.

**Alternatives considered:** Optimizing the generic engine (structural sharing); a Rust kernel. Deferred: the measured runtime (≈1–4 s per simulated day on 2 vCPUs) does not justify them yet.

## D-013 — Append-only SQLite event store with a SHA-256 hash chain

**Decision:** `atlas.store.EventStore` stores events append-only with per-simulation gap-free sequences and `record_hash = sha256(prev_hash || canonical_record)`.

**Reason:** Tamper evidence and deterministic reconstruction with a standard-library dependency. The hash is computed over canonical JSON, so a PostgreSQL implementation of the same contract will produce identical chains.

## D-014 — Partial netting: polynomial heuristic for operations, exact MILP as reference

**Decision:** Queue netting uses `gridlock-heuristic-v3` (best of priority removal, best-fit removal and bilateral-seeded growth, each repaired by greedy reinsertion). An exact 0-1 program solved by HiGHS is available as a policy (`multilateral_milp`) and as the optimality reference.

**Reason:** The heuristic is dependency-free and fast; the MILP quantifies how much it leaves on the table. Both outputs are re-verified in exact integer arithmetic before any settlement.

**Limitation:** On adversarial random gridlocked queues the heuristic's optimality gap is large (see `results/netting_optimality.json`); on simulated queues the practical difference is small (see benchmark). This is reported, not hidden.

## D-015 — All controller actions pass a fail-closed safety controller

**Decision:** Controllers (MPC, rule-based, any future learned policy) can only *propose* `settle_batch` or own-account `transfer` actions. `SafetyController` validates each in integer arithmetic (queue membership, joint feasibility, share caps, committed cash, cutoff, rail availability). Rejected actions are logged and dropped, never repaired or partially executed.

**Reason:** Blueprint principles 7 and 15. No optimizer or model can change the ledger without passing the same hard constraints.

## D-016 — Defer PostgreSQL, ClickHouse, MinIO, MLflow and streaming

**Decision:** Docker Compose runs only the API and the web UI, with Prometheus/Grafana behind an `observability` profile. Event storage is SQLite on a volume; research artifacts are versioned JSON in `results/`.

**Reason:** Blueprint section 4: do not introduce infrastructure for appearance. No current workload needs a second database, an object store or a stream processor. Each will be added with a measured reason and the same event-store contract.

## D-017 — Paired-seed benchmark with deterministic bootstrap intervals

**Decision:** Every benchmark arm runs on identical generated days and stress definitions; comparisons are paired differences with 95% percentile-bootstrap intervals generated from the project RNG.

**Reason:** Blueprint section 20 forbids attributing seed-to-seed variation to a policy. Deterministic bootstrap streams make the reported intervals themselves reproducible.

## D-018 — Safe RL deferred; interface ready

**Decision:** PPO/MAPPO/constrained RL are not implemented in this increment. The controller protocol and safety filter they would plug into are implemented and tested.

**Reason:** The blueprint requires the simulator, baselines and optimizer to be validated first. They now are; RL is the next research increment and will be reported against the MPC baseline.
