# System architecture — initial decision

Start as a typed Python modular monolith with domain boundaries for institutions/accounts/payments, event simulation, payment rails, liquidity and collateral, agents, risk, research, and API. Keep frontend and persistence as later adapters around those boundaries. The current implementation contains only the domain package and tests; none of the future components are represented as complete.

Use standard-library domain code at this stage to keep the financial core dependency-light. Add FastAPI/Pydantic or persistence libraries only when an API or storage increment is accepted and tested. Do not introduce distributed infrastructure before measured workload evidence.

See `DECISIONS.md` for recorded choices.
