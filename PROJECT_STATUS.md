# Project status

**Current stage:** Phase 1 — initial financial domain increment implemented; phase acceptance is still in progress.

## Completed

- Phase 0 repository discovery and architecture foundation.
- Python 3.12 package and pytest configuration.
- Immutable institution, settlement account, payment instruction, and event envelope records.
- Integer minor-unit fields, exact decimal conversion, timezone-aware timestamp validation, and payment transition registry.
- Risk register and documented assumptions/limitations.
- Initial charter, architecture, domain model, decisions, and task tracking.

## Verification

Initial run: `pytest -q` — 16 passed. Python 3.12 is installed, but its interpreter does not have pytest; the `pytest` executable in this environment ran the suite successfully.

## Known limitations

- The GitHub `main` branch remains unchanged; this foundation is published on `phase0-foundation` pending review.
- No API, persistence, event engine, rail models, frontend, collateral, agents, or benchmark has been implemented.
- Account resource formula and payment lifecycle are initial simulator conventions, not claims about live payment systems.
- No rail-specific rules are implemented; a source-linked rule registry will be needed when those models begin.

## Next tasks

Finish Phase 1 with currency precision metadata, financial resource reconciliation semantics, and a versioned/source-linked assumption registry; then move to Phase 2 deterministic simulation.
