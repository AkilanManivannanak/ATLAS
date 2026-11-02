# Financial domain model — Phase 1

## Implemented records

The immutable domain package represents institutions, settlement accounts, payment instructions, collateral assets, funding facilities, and financial event envelopes. Monetary values are integer minor units with explicit currency codes; currency precision comes from a versioned `CurrencyRegistry` and is never inferred. Timestamps are timezone-aware.

Institution records carry institution type, jurisdiction, policy identifiers, risk-profile identifier, operational status, optional simulation-agent identifier, and creation time. Account records distinguish cash ledger, reservations, credit limit, credit used, status, reconciliation timestamp, and the rule version used for availability. Payment records retain end-to-end and instruction identifiers, participant/account/rail IDs, execution/due/settlement times, message provenance, schema version, and scenario identifier.

Collateral haircuts use integer basis points and mobilization delay uses seconds. Funding rates use annual basis points. Facility capacity is split into maximum, committed, drawn, repayable, and derived available amounts. These are domain records only; facility draw and repayment operations are not implemented.

## Account resource convention

The simulator assumption `atlas.account.available_resources@1` is:

```text
cash_available = ledger_balance - reserved_balance
undrawn_credit = credit_limit - intraday_credit_used
available_resources = cash_available + undrawn_credit
```

Reservations cannot exceed ledger cash. Intraday credit used cannot exceed the configured limit. Undrawn credit is not booked as cash. This is an explicit simulator convention, not a claim about a particular payment rail or actual facility.

`reconcile_account` returns the components and verifies these identities. `settle_cash_transfer` implements a same-currency, same-rail, same-accounting-domain gross cash movement: it requires a settlement-pending payment, active accounts, matching payment/account identifiers, and sufficient unreserved ledger cash. It debits the sender and credits the receiver by equal integer minor units, marks the payment settled, and returns an immutable financial event with before/after balances. It deliberately does not draw credit. Rail eligibility and operating rules must be checked separately by a rail adapter; none exists yet.

## Collateral and facilities

Eligible collateral value is computed with conservative integer rounding:

```text
eligible_value_minor = floor(market_value_minor × (10,000 - haircut_bps) / 10,000)
available_eligible_value_minor = max(0, eligible_value_minor - encumbered_amount_minor)
```

Funding capacity available is `committed_capacity_minor - drawn_amount_minor`. An undrawn facility is not settlement cash. These formulas are simulator conventions and do not specify a real facility's rules.

## Payment lifecycle and events

The transition registry permits explicit transitions only; settled payments are terminal. Payment returns remain separate instructions/events. Event payloads are canonical JSON-object text so the frozen envelope does not retain a mutable dictionary. Events include event and ingestion timestamps, aggregate sequence, correlation/causation metadata, schema version, and simulation ID.

## Rule and source registry

`FinancialRuleRegistry` is immutable and versioned. Rule versions are append-only and increase monotonically. Official-source rules require an HTTPS source reference with title and retrieval date. Simulator assumptions require a rationale and cannot carry an official-source label. The default registry currently contains only the available-resource assumption. No payment-network rules have been modeled or claimed.

## Remaining scope

No rail-specific eligibility or operating schedule, durable event store/replay, facility draw/repayment, cross-currency settlement, or external message schema validation exists yet. Expected incoming payments do not enter account resources. Reference network names are not used as evidence that the implementation reproduces those networks.
