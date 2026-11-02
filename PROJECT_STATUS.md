# Project status

**Current stage:** Phase 2 complete; Phase 3 payment-rail models are next.

## Completed

- Phase 0 repository discovery and architecture foundation.
- Python 3.12 package and pytest configuration.
- Immutable institution, settlement account, payment instruction, collateral asset, funding facility, and event envelope records.
- Integer minor-unit fields, exact decimal conversion, timezone-aware timestamp validation, and payment transition registry.
- Account resource reconciliation and cash-only settlement operation with immutable event output.
- Versioned currency and rule registries; assumptions are separated from source-backed rules.
- Versioned deterministic event ordering, discrete-event queue, transactional handlers, replay, JSON snapshots, state hashes, and named random streams.
- Risk register and documented assumptions/limitations.
- Initial charter, architecture, domain model, decisions, and task tracking.

## Verification

Phase 2 run: `pytest -q` — 42 passed. `python3 -m compileall -q src tests` and `git diff --check` completed successfully.

## Known limitations

- The GitHub `main` branch remains unchanged; this foundation is published on `phase0-foundation` pending review.
- No durable event store, multi-day business calendars, payment-rail adapters, facility draw/repayment operations, API, frontend, agents, or benchmark has been implemented.
- Account resource formula and cash settlement operation are simulator conventions, not claims about live payment systems.
- No rail-specific rules, durable event store, multi-day business calendars, facility draw/repayment, API, frontend, or benchmark are implemented.

## Next tasks

Begin Phase 3 with independent payment-rail adapters. Verify and register each modeled operating rule before implementing it, then add rail-specific eligibility, liquidity, cutoff, duplicate, return, and outage tests.
