# Financial domain model — foundation

## Implemented records

`Institution`, `SettlementAccount`, `PaymentInstruction`, and `FinancialEvent` are immutable typed records in `src/atlas/domain/models.py`. Identifiers are explicit. Account and payment amounts use integer minor units. Currency codes are uppercase three-letter strings. All timestamps require timezone awareness.

The account model distinguishes ledger balance, reserved balance, a configured intraday credit limit, and credit already used. Its current spendable-resource calculation is `ledger - reserved + credit_limit - credit_used`. It is a simplified simulator accounting convention, not a payment-system rule.

## Payment lifecycle

The transition registry allows only explicit transitions. Settled payments are terminal. A settlement timestamp is required exactly for a settled payment. A returned payment is terminal here; a future return flow must be modeled as a separate instruction/event rather than reversing finality.

## Current limitations and next work

No rail-specific eligibility, account-to-account settlement operation, durable event store, reconciliation, validation schemas, or currency minor-unit registry exists yet. Same currency is required for future transfers until an explicit FX model is designed. Domain records do not assert behavior of Fedwire, CHIPS, FedNow, or RTP.
