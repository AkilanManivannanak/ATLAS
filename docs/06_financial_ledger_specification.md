# Financial ledger semantics — Phase 1

## Units and precision

- Authoritative monetary fields are signed only where explicitly stated; current account, collateral, facility, and payment amounts are non-negative integer minor units.
- Every amount is paired with an uppercase three-letter currency code.
- A `CurrencyRegistry` version carries explicit minor-unit exponents. `Money.from_major_units` accepts a decimal string or `Decimal`, rejects floats, and rejects excess precision instead of rounding.
- Collateral haircut and annual facility rate use integer basis points (1 basis point = 1/10,000); mobilization delay uses integer seconds. Encumbered collateral amounts are represented in haircut-adjusted eligible-value minor units.

## Account decomposition

```text
cash_available_minor = ledger_balance_minor - reserved_balance_minor
undrawn_credit_minor = credit_limit_minor - intraday_credit_used_minor
available_balance_minor = cash_available_minor + undrawn_credit_minor
```

The record enforces `reserved_balance_minor <= ledger_balance_minor` and `intraday_credit_used_minor <= credit_limit_minor`. The formula is registered as simulator assumption `atlas.account.available_resources`, version 1. A funding facility not drawn into an account is not counted as ledger cash.

## Cash settlement operation

`settle_cash_transfer` is an accounting primitive called by the rail adapters. It accepts only a `SETTLEMENT_PENDING` instruction and active, distinct sender/receiver accounts whose participant, account, currency, and rail identifiers match. Cash-only is the default. An adapter may explicitly enable intraday credit, in which case the exact cash shortfall is drawn, account credit usage is updated, and the event records the draw. It returns immutable account/payment values and a canonical `PaymentSettled` event. The original input values remain unchanged.

For cash-only settlement of amount `x`:

```text
sender_ledger_after = sender_ledger_before - x
receiver_ledger_after = receiver_ledger_before + x
sender + receiver ledger movement = 0
credit_draw = 0
```

When explicitly enabled and cash is short by `d`, the sender's ledger changes by `d - x`, the receiver's ledger changes by `x`, `intraday_credit_used` increases by `d`, and the event records `credit_draw_minor = d`. The two settlement accounts' combined ledger change is therefore `d`, representing newly drawn account credit. This account-level credit line remains distinct from a `FundingFacility` draw.

## Facility funding operations

`draw_funding` validates facility eligibility, institution/currency matching, committed capacity, maturity, and any configured collateral requirement. A successful draw increases the facility's drawn and repayable principal and credits the selected settlement account by the same integer minor-unit amount, emitting `FundingDrawn`. `repay_funding` reduces both principal fields and debits unreserved account cash, emitting `FundingRepaid`. Interest is not silently folded into principal. `calculate_simple_funding_cost` applies a declared annual basis-point rate and elapsed seconds using integer arithmetic, rounds any fractional minor unit upward, and returns a calculation record without posting it.

## Collateral operations

`CollateralInventory` is an immutable ledger that rejects duplicate asset/allocation identifiers and requires each asset's encumbered eligible value to equal its active allocation records. Mobilization has explicit requested, pending, and mobilized states; collateral cannot be allocated before its configured delay elapses. Allocations use haircut-adjusted eligible value and an explicit `CollateralRequirement` maximum advance rate. Facility draws check current effective coverage; a price/haircut change can expose shortfall and block additional borrowing. Release checks that remaining collateral still covers drawn facility principal. Configurable stress scenarios add haircuts and mobilization delay. These are simulator policies, not production facility terms.

Settlement finality is modeled by the terminal payment state. A return must be represented by a separate payment instruction.

## Reconciliation checks

`reconcile_account` checks:

- ledger = reserved + unreserved cash;
- credit limit = credit used + undrawn credit;
- available resources = unreserved cash + undrawn credit.

These are account decomposition invariants. Batch-wide event-store reconciliation is future work because no durable event store exists yet.
