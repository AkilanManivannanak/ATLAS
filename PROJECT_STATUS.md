# Project status

**Current stage:** Phase 1 complete; Phase 2 deterministic event simulation is next.

## Completed

- Phase 0 repository discovery and architecture foundation.
- Python 3.12 package and pytest configuration.
- Immutable institution, settlement account, payment instruction, collateral asset, funding facility, and event envelope records.
- Integer minor-unit fields, exact decimal conversion, timezone-aware timestamp validation, and payment transition registry.
- Account resource reconciliation and cash-only settlement operation with immutable event output.
- Versioned currency and rule registries; assumptions are separated from source-backed rules.
- Risk register and documented assumptions/limitations.
- Initial charter, architecture, domain model, decisions, and task tracking.

## Verification

Phase 1 run: `pytest -q` — 29 passed. `python3 -m compileall -q src tests` completed successfully.

## Known limitations

- The GitHub `main` branch remains unchanged; this foundation is published on `phase0-foundation` pending review.
- No API, persistence, event engine, rail models, frontend, collateral, agents, or benchmark has been implemented.
- Account resource formula and cash settlement operation are simulator conventions, not claims about live payment systems.
- No rail-specific rules, durable event store/replay, facility draw/repayment, API, frontend, or benchmark are implemented.

## Next tasks

Start Phase 2: specify deterministic same-time event ordering, then implement seeded scheduling, event replay, and snapshots with acceptance tests.
