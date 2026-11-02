# Known limitations and initial risk register

| Risk | Why it matters | Current treatment / next control |
|---|---|---|
| Currency precision drift | Incorrect decimal conversion can create or destroy value. | Versioned currency registry requires explicit minor-unit exponents. Conversion rejects floats and excess precision. No default global currency metadata is assumed. |
| Account liquidity semantics | Credit, reservations, and ledger balances can be double counted if definitions are vague. | Account resource equation is documented and versioned as a simulator assumption. Cash settlement does not draw credit. Facility draw/repayment remains future work. |
| Rail rules mistaken for live behavior | Simplified models could be mistaken for actual network rules. | No rail behavior is implemented. Rule registry distinguishes sourced rules from internal assumptions; future rail rules require verified sources, dates, scope, and simplification notes. |
| Nondeterministic replay | Random streams or event tie ordering can make research irreproducible. | Phase 2 now versions event ordering, isolates named seeded streams, and supports snapshot/replay. A durable store and cross-version migration remain future work. |
| Synthetic data confusion | Simulated values could be interpreted as observed financial data. | Product scope is synthetic-only and the README requires simulation labeling. |
| Overbuilding before validation | Large infrastructure can obscure domain defects. | Start with a modular monolith and add infrastructure only after evidence. |
| Incomplete provenance | Results cannot be reproduced without configuration and algorithm identity. | Event envelope has sequence/correlation/schema metadata; durable storage and run manifests remain future work. |
| Float values entering ledger state | Binary floating-point error may cause monetary reconciliation failures. | Domain amount fields use integer minor units; conversion rejects binary floats. Tests cover arithmetic and rejection behavior. |
