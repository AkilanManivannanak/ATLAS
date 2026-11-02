# Project status

**Current stage:** Phase 3 payment-rail reference models complete; Phase 4 liquidity and collateral operations are next.

## Completed

- Phase 0 repository discovery and architecture foundation.
- Python 3.12 package and pytest configuration.
- Immutable institution, settlement account, payment instruction, collateral asset, funding facility, and event envelope records.
- Integer minor-unit fields, exact decimal conversion, timezone-aware timestamp validation, and payment transition registry.
- Account resource reconciliation and settlement operation with cash-only default, explicit optional credit draw, and immutable event output.
- Versioned currency and rule registries; assumptions are separated from source-backed rules.
- Versioned deterministic event ordering, discrete-event queue, transactional handlers, replay, JSON snapshots, state hashes, and named random streams.
- Risk register and documented assumptions/limitations.
- Initial charter, architecture, domain model, decisions, and task tracking.
- Four independent synthetic rail archetypes: gross RTGS, atomic liquidity-saving cycle settlement, FedNow-style continuous instant, and independently configured RTP-style instant.
- Versioned rail evidence/assumption registry; RTGS opt-in credit draw and lifecycle-safe settlement events.

## Verification

Phase 3 run: `pytest -q` — 55 passed. `python3 -m compileall -q src tests` and `git diff --check` completed successfully.

## Known limitations

- The GitHub `main` branch remains unchanged; this foundation is published on `phase0-foundation` pending review.
- No durable event store, persistent rail queues, full holiday calendar service, service-specific return flows, ISO 20022 validation, facility draw/repayment operations, API, frontend, agents, or benchmark has been implemented.
- Account resource formula and cash settlement operation are simulator conventions, not claims about live payment systems.
- Rail models are simplified archetypes, not replicas of Fedwire, CHIPS, FedNow, or RTP. The liquidity-saving model requires a whole cycle to be feasible and does not search partial subsets.

## Next tasks

Begin Phase 4 with explicit funding draw/repayment events and collateral mobilization/encumbrance transitions, preserving the distinction between cash, credit, and eligible collateral.
