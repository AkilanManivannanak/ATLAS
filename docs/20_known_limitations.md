# Known limitations and initial risk register

| Risk | Why it matters | Current treatment / next control |
|---|---|---|
| Currency precision drift | Incorrect decimal conversion can create or destroy value. | Versioned currency registry requires explicit minor-unit exponents. Conversion rejects floats and excess precision. No default global currency metadata is assumed. |
| Account liquidity semantics | Credit, reservations, and ledger balances can be double counted if definitions are vague. | Account resource equation is documented. RTGS credit draws require explicit adapter configuration; facility draws are separate operations that update cash and principal together and do not consume the account credit line. |
| Rail rules mistaken for live behavior | Simplified models could be mistaken for actual network rules. | Four synthetic archetypes have explicit scope limits; source-backed facts and assumptions are registered separately. None connects to or reproduces a live service. |
| Nondeterministic replay | Random streams or event tie ordering can make research irreproducible. | Phase 2 now versions event ordering, isolates named seeded streams, and supports snapshot/replay. A durable store and cross-version migration remain future work. |
| Synthetic data confusion | Simulated values could be interpreted as observed financial data. | Product scope is synthetic-only and the README requires simulation labeling. |
| Overbuilding before validation | Large infrastructure can obscure domain defects. | Start with a modular monolith and add infrastructure only after evidence. |
| Incomplete provenance | Results cannot be reproduced without configuration and algorithm identity. | Event envelope has sequence/correlation/schema metadata; durable storage and run manifests remain future work. |
| Float values entering ledger state | Binary floating-point error may cause monetary reconciliation failures. | Domain amount fields use integer minor units; conversion rejects binary floats. Tests cover arithmetic and rejection behavior. |
| Liquidity-saving model bias | An all-or-nothing cycle may leave feasible subsets waiting. | The model currently settles only a fully feasible submitted cycle; partial subset search and optimization are future work. |
| Funding-cost simplification | Unposted interest can understate total facility obligations. | Exact simple interest is calculated with explicit rate, period, and day-count basis; accrual posting, fees, compounding, and repayment schedules are future work. |
| Collateral eligibility and policy | Generic rules could misstate actual lender terms. | Facility-specific profile lists and advance rates are explicit local configuration; no real eligibility schedule or facility agreement is inferred. Stress can create an exposed shortfall; margin calls and forced liquidation are not modeled. |
