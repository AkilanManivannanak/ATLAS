# Phase 3 — payment rail reference models

## Scope and model boundary

`src/atlas/rails/` contains four independent, deterministic rail archetypes. These are synthetic research models with no network connectivity and no authority to execute real payments. Public sources inform limited operating facts; the implemented mechanics are explicitly marked as simulator assumptions in `src/atlas/rails/rules.py` and `RAIL_RULES`.

Every adapter validates the rail and currency identifiers, payment lifecycle, active and matching settlement accounts, participant eligibility, transaction limits, duplicate instruction keys, and aware timestamps before settlement. Account and payment inputs are immutable. Gross and instant settlement uses `settle_cash_transfer`, which updates ledger cash and emits a `FinancialEvent`. Credit use is opt-in and the exact draw is reflected in both account state and the settlement event.

## Rail models

| Model | Implemented behavior | Explicit boundary |
|---|---|---|
| `RTGSRail` | Configurable overnight/local schedule, weekday and holiday inputs, gross queue ordering by priority, due time, creation time and ID; cash-only by default; optional configured intraday credit draw | This is not a complete Fedwire schedule. Holiday dates, cutoff distinctions, extensions, and Federal Reserve exception handling remain configurable or unmodeled. The announced Sunday-through-Friday/weekday-holiday expansion targeted for 2028 or 2029 is not assumed active. |
| `LiquiditySavingRail` | Atomic multilateral cycle settlement. Each participant must use one settlement account in a cycle; the cycle settles only when every participant account can cover its positive net debit in unreserved cash. One cycle event records all account deltas and payment IDs. | Public CHIPS descriptions establish liquidity-saving matching/offsetting at a high level. This all-or-nothing net-position cycle is an ATLAS baseline, not the proprietary CHIPS algorithm; no partial cycle search, contributions, or bilateral matching is included. |
| `FedNowRail` | Always-open instant cash settlement unless a scenario injects an outage; separately configurable service-day rollover metadata (default 19:01 America/New_York) | The public service documents 24-hour processing and an approximate 7:01 p.m. ET accounting rollover. LMT windows, participant procedures, and service exceptions are not implemented. The cycle date does not stop processing. |
| `RTPRail` | Independent instant cash model with separately configured participant eligibility and sender-side transaction limits; outage injection and immediate confirmation through settlement result | No limit, participant list, or detailed operating rule is hard-coded from public marketing material. This is not a clone of proprietary RTP rules. |

The models share validation and accounting helpers only. Queue policy, service clock, limit configuration, and settlement behavior remain rail-specific. FedNow and RTP both use the common cash transfer primitive after independent checks; their configuration and operating logic are separate.

## Evidence and rule versions

- Federal Reserve Financial Services, [Fedwire Funds Service operating hours](https://www.frbservices.org/resources/financial-services/wires/fedwire-funds-service-national-settlement-service-operating-hours/), retrieved 2026-11-01. The public page describes the overnight opening and 7 p.m. ET close on funds-transfer business days, with exceptions and changes addressed by the source.
- Federal Reserve Financial Services, [Fedwire and NSS resource center](https://www.frbservices.org/resources/financial-services/wires/fedwire-funds-service-national-settlement-service-resource-center/), retrieved 2026-11-01. The Reserve Banks announced an intended Sunday-through-Friday expansion including weekday holidays for 2028 or 2029, with voluntary participant use. The configurable schedule does not treat that future expansion as active.
- The Clearing House, [CHIPS overview](https://www.theclearinghouse.org/payment-systems/chips), retrieved 2026-11-01. The public description refers to continuous intraday settlement and liquidity-saving matching/offsetting. It does not publish the proprietary algorithm used in this model.
- Federal Reserve Financial Services, [FedNow operating hours](https://www.frbservices.org/resources/financial-services/fednow-service-resources/fednow-service-operating-hours/), retrieved 2026-11-01. The public page documents continuous service operation and an approximate 7:01 p.m. ET cycle rollover; this model treats rollover as accounting metadata.
- The Clearing House, [RTP overview](https://www.theclearinghouse.org/payment-systems/rtp), retrieved 2026-11-01. The public description supports an around-the-clock instant-payment archetype; configured participant limits are local simulator inputs.

`RAIL_RULES` records each public source separately from each implementation assumption. A source-backed general fact is not treated as evidence for an unmodeled detail.

## Accounting and lifecycle invariants

- Authoritative amounts remain integer minor units.
- Gross RTGS cannot consume credit unless `allow_intraday_credit=True`; if enabled, only the cash shortfall is drawn and `intraday_credit_used_minor` increases by that amount.
- Instant settlement uses unreserved cash only. Insufficient cash is rejected immediately instead of silently using credit.
- A liquidity-saving cycle is all-or-nothing and uses one settlement account per participant. Its net debit checks preserve non-negative unreserved balances, and account deltas sum to zero across the cycle.
- Every settled instruction reaches `SETTLED` through the existing explicit lifecycle. A terminal payment cannot be resubmitted.
- Returns are not modeled as reversal of final settlement; a return instruction/event flow remains future work.

## Verification

Phase 3 acceptance: `pytest -q` — 55 passed. Tests cover schedule boundaries, holidays and timezone validation; participant and duplicate rejection; priority queue processing; insufficient liquidity and explicit credit; all-or-nothing multilateral netting; instant availability and injected outage; cycle rollover; and rule evidence classification.

## Remaining work

Rail queues are currently passed as in-memory collections and are not automatically scheduled into `SimulationEngine`. The schedule calendar requires caller-supplied holidays. Liquidity-saving cycles do not search for a feasible subset when the whole cycle is infeasible. ISO 20022 schemas, network-specific returns, out-of-order message reconciliation, persistent idempotency, facility draw/repay events, and benchmark performance remain unimplemented.
