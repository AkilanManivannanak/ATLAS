# ATLAS-Σ

ATLAS-Σ is a research simulator for financial infrastructure. It models synthetic institutions, payment obligations, settlement resources, and disruptions. It does not connect to banks or payment networks and cannot execute real payments.

## Current status

Phases 1–4 are complete: financial domain foundation, deterministic event simulation, four synthetic payment-rail archetypes, and funding/collateral operations. These models do not connect to live services or claim to reproduce proprietary payment-system rules. See [PROJECT_STATUS.md](PROJECT_STATUS.md), [TASKS.md](TASKS.md), and [docs/](docs/) for scope and acceptance criteria.

## Development

Requires Python 3.12 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

The initial implementation uses only the Python standard library at runtime. Financial amounts are integer minor units; timestamps must be timezone-aware. No synthetic results are presented as observed financial data.
