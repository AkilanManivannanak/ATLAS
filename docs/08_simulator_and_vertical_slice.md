# Event store, ledger replay, ISO 20022 and the multi-rail day simulator

## Vertical slice (blueprint §32, "third")
`atlas.workflows.run_vertical_slice()` executes the required end-to-end path: two synthetic institutions → settlement accounts → a synthetic `pacs.008.001.08` message → normalization/validation → RTGS admission and liquidity check → gross settlement → both accounts updated → `PaymentSettled` event appended to the hash-chained store → the ledger rebuilt by replay and compared by state hash. It is exposed at `GET /api/v1/vertical-slice` and tested in `tests/test_store_ledger.py`.

## Event store (`atlas-event-store-v1`)
* Append-only SQLite table keyed by `(simulation_id, sequence_number)`; gap-free sequences are enforced at append time.
* `record_hash = sha256(prev_hash || canonical_record_json)`; genesis `prev_hash` is 64 zeros. `verify_chain` detects edits, deletions and reordering (test: a single tampered payload is located by sequence number).
* `append_many` is atomic. Re-appending an identical event is an idempotent no-op; a conflicting event with the same id is rejected.

## Strict ledger (`atlas.ledger.Ledger`)
Ledger-affecting events: `PaymentSettled`, `LiquiditySavingCycleSettled`, `FundingDrawn`, `FundingRepaid`, `LiquidityAdjusted`, `CreditLimitChanged`, `IntradayCreditRepaid`. Each carries before/after values; the fold checks *before* against current state and re-derives *after* from the amounts. Netting deltas must sum to zero. After every event:

`Σ ledger_balance = opening_total + external_net_flow`

where only explicitly external events (credit draws/repayments, facility draws/repayments, liquidity adjustments) change `external_net_flow`. Own-account cross-rail transfers are a pair of `LiquidityAdjusted` events that net to zero.

## ISO 20022 normalization (`atlas-iso20022-normalizer-v1`)
Supported definitions: `pacs.008.001.08`, `pacs.009.001.08`, `pacs.004.001.10`. Checks: namespace/definition, required elements, Max35Text identifiers, BICFI format, UUIDv4 UETR, ISO dates with offsets, currency registry and minor-unit precision, `NbOfTxs`, `TtlIntrBkSttlmAmt` = sum of transactions, duplicate end-to-end ids, distinct agents. DOCTYPE/ENTITY declarations are rejected before parsing (XXE / entity expansion). The exact original bytes and their SHA-256 are retained. **Not implemented:** official XSD validation, camt messages, market-infrastructure usage guidelines. Returns (`pacs.004`) are normalized as separate instructions, never as reversals of a settled payment.

## Day simulator (`atlas-day-sim-v1`)
Event phases follow `atlas-event-order-v1`: rail state (10) → shocks (20) → arrivals (30) → controller (40) → settlement (50) → bank decisions (60) → monitoring (70). One-minute ticks.

| Rail | Mechanics in the simulator |
|---|---|
| RTGS | Banks release held payments; the central queue is processed every tick by the policy (`fifo`, `fifo_strict`, `priority`); optional collateralised intraday credit; `bilateral`/`multilateral`/`multilateral_milp` policies add periodic netting of the residual queue (cash only). |
| LSM | Released obligations wait for a netting cycle every 15 minutes (heuristic or MILP), cash only, atomic per cycle. |
| FedNow-style / RTP-style | Settle on arrival through the existing rail adapters or reject (insufficient prefunded cash, participant limit, outage, sender outage). RTP has its own participant subset and limit. |

Metrics: settlement rate by value and count, mean/p95/value-weighted delay, deadline misses, liquidity usage per account (deepest cumulative net *payment* outflow, Leinonen & Soramäki), upper/lower bounds, peak intraday credit, gridlock ticks, netting volumes, instant rejections, controller actions and safety rejections, and a cost decomposition (`CostModel`, all integer minor units).
