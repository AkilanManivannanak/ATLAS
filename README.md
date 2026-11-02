# ATLAS-Σ

ATLAS-Σ is a research simulator for financial infrastructure. It models synthetic institutions, payment obligations, settlement resources, and disruptions. It does not connect to banks or payment networks and cannot execute real payments.

## Current status

Phase 1 financial domain foundation is complete. Phase 2 deterministic event simulation is complete; Phase 3 payment-rail models are next. See [PROJECT_STATUS.md](PROJECT_STATUS.md), [TASKS.md](TASKS.md), and [docs/](docs/) for scope and acceptance criteria.

## Development

Requires Python 3.12 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

The initial implementation uses only the Python standard library at runtime. Financial amounts are integer minor units; timestamps must be timezone-aware. No synthetic results are presented as observed financial data.
