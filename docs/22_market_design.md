# Market design: intraday liquidity auction (`atlas-liquidity-auction-v1`)

**Purpose.** Resolve RTGS gridlock by moving *idle* liquidity from institutions that hold it to institutions whose released payments are stuck, at a price, without a central bank injection.

## Mechanism
Every `auction_interval_min` (15) minutes while the RTGS queue is non-empty:

| Side | Who | Quantity | Price |
|---|---|---|---|
| Bid (borrower) | queued RTGS outflow > cash + undrawn credit | the shortfall | willingness to pay = delay cost avoided (`delay_bp_per_hour × hours_left / 2`) + `late_penalty_bp` if a queued payment is due within 30 min |
| Ask (lender) | free cash ≥ $1M after queued payments and held payments due within 60 min | ≤ 50% of free cash | true reservation cost `1 + 6 × committed/cash` bp (assumption), times `(1 + shading)` in incentive experiments |

Clearing (`atlas.market.clear_auction`): asks ascending, bids descending, quantity matched while ask ≤ bid. **Pay-as-bid:** each unit trades at the lender's own ask. **Uniform:** every unit trades at the highest accepted ask. Individual rationality (ask ≤ price ≤ bid) is asserted in integers for every trade; a property test checks it and quantity conservation on random books.

Loans move cash as `InterbankLoanTransfer` events (strict before-balance checks in the ledger, conservation preserved). At close, borrowers repay principal + flat interest from cash; any shortfall is reported as **rolled to overnight funding** (counterparty exposure), not as a loss, because the model has no default mechanism.

## Incentive analysis (E4)
Neither rule is assumed incentive-compatible: discriminatory auctions reward ask shading, and uniform-price multi-unit auctions are not strategy-proof for a marginal seller. `scripts/auction_study.py` measures it. For each of the three largest truthful lenders on each paired seed, that lender alone inflates its ask by 25/50/100/200%, and we record the change in *its own* profit (interest received − true cost × principal). Results: `results/auction.json`, `docs/19_experimental_results.md`.

## Limitations
Willingness to pay and reservation costs are modeled, not estimated. Bids are truthful (only lender manipulation is studied). No collateral, credit limits or counterparty risk pricing between banks. Not a description of any operating market.
