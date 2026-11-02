# Known limitations and initial risk register

| Risk | Why it matters | Current treatment / next control |
|---|---|---|
| Currency precision drift | Incorrect decimal conversion can create or destroy value. | Ledger amounts are integer minor units. Exponents must be supplied as reviewed configuration; no broad currency registry is asserted yet. Conversion rejects excess precision. |
| Account liquidity semantics | Credit, reservations, and ledger balances can be double counted if definitions are vague. | The initial available-resource formula is explicitly documented as a simulator convention. A resource reconciliation specification is required before settlement operations. |
| Rail rules mistaken for live behavior | Simplified models could be mistaken for actual network rules. | No rail behavior has been implemented; reference inspiration must not be represented as certification or integration. Future assumptions require versions, sources, and simplifications. |
| Nondeterministic replay | Random streams or event tie ordering can make research irreproducible. | Not implemented. Phase 2 must version event ordering and isolate seeded random streams. |
| Synthetic data confusion | Simulated values could be interpreted as observed financial data. | Product scope is synthetic-only and the README requires simulation labeling. |
| Overbuilding before validation | Large infrastructure can obscure domain defects. | Start with a modular monolith and add infrastructure only after evidence. |
| Incomplete provenance | Results cannot be reproduced without configuration and algorithm identity. | Event envelope has basic sequence/correlation/schema metadata; persistent provenance and run manifests remain future work. |
| Float values entering ledger state | Binary floating-point error may cause monetary reconciliation failures. | Amount fields and `Money` use integer minor units; decimal conversion rejects float input. Tests cover these guards. |
