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

`settle_cash_transfer` is an initial domain operation, not a rail adapter. It accepts only a `SETTLEMENT_PENDING` instruction and active, distinct sender/receiver accounts whose participant, account, currency, and rail identifiers match the instruction. It requires the sender to have enough unreserved ledger cash; it does not silently use undrawn credit. It creates new immutable account/payment values and a `PaymentSettled` event with canonical JSON before/after amounts. The original input values remain unchanged.

For successful settlement of amount `x`:

```text
sender_ledger_after = sender_ledger_before - x
receiver_ledger_after = receiver_ledger_before + x
sender + receiver ledger movement = 0
credit_draw = 0
```

Settlement finality is modeled by the terminal payment state. A return must be represented by a separate payment instruction.

## Reconciliation checks

`reconcile_account` checks:

- ledger = reserved + unreserved cash;
- credit limit = credit used + undrawn credit;
- available resources = unreserved cash + undrawn credit.

These are account decomposition invariants. Batch-wide event-store reconciliation is future work because no durable event store exists yet.
