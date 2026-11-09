# Funding and collateral operations — Phase 4

## Scope

`atlas.liquidity` adds deterministic, immutable operations for facility draws and principal repayment, collateral inventory and allocation, delayed mobilization, revaluation, stress, and simple funding-cost calculation. Operations return new values plus `FinancialEvent` envelopes. The caller owns the resulting state and event persistence; this package has no database or implicit global state.

## Facility draws and repayment

`draw_funding` requires an eligible facility, an active same-institution/same-currency settlement account, unexpired maturity, and sufficient committed capacity. It credits account ledger cash and increases drawn and repayable principal by the same integer amount, with a `FundingDrawn` event. A facility with a collateral requirement also needs a matching requirement record and sufficient currently effective eligible collateral allocated to that facility.

`repay_funding` accepts only positive principal up to the repayable/drawn balance and requires unreserved account cash. It debits cash and decreases drawn and repayable principal equally, with a `FundingRepaid` event. It may be called after maturity to resolve an outstanding balance. Repayment does not release pledged collateral automatically; release is an explicit separate operation and cannot reduce coverage below the facility's outstanding principal requirement.

`calculate_simple_funding_cost` uses integer arithmetic over a declared annual rate and elapsed seconds. Its default day-count basis is 365 days, and fractional minor-unit interest rounds upward. The result is a calculation record only; interest posting, fees, compounding, and contractual schedules are not modeled.

## Collateral inventory

`CollateralInventory` is an immutable snapshot with unique asset and allocation IDs. Each asset's `encumbered_amount_minor` must equal the sum of remaining allocation records, which prevents double pledging within a valid inventory. Existing encumbrances must be loaded with their allocation records rather than added as an untracked amount.

Collateral moves through `UNMOBILIZED → PENDING → MOBILIZED`. A request emits `CollateralMobilizationRequested` and calculates its available time from the asset's configured delay. Completion before that time is rejected; successful completion emits `CollateralMobilized`. Only mobilized collateral can be allocated.

`CollateralRequirement` supplies an explicit maximum advance rate and optional allowed eligibility profiles. Allocation amounts are haircut-adjusted eligible-value minor units; this model requires the collateral owner and facility borrower to be the same institution. At draw time, effective collateral coverage is recalculated against current eligible value and conservatively prorated across active allocations if a valuation or haircut has caused a shortfall. Haircut rounding floors eligible value; required collateral rounds upward.

Allocation and release emit `CollateralEncumbered` and `CollateralReleased`. Release requires the current facility and requirement records and must preserve required coverage for outstanding drawn principal. Revaluation emits `CollateralRevalued`; a reduction can leave existing encumbrances short, which the inventory reports and subsequent draws cannot count. Stress scenarios explicitly add haircut basis points and mobilization-delay seconds and emit `CollateralStressApplied`.

## Accounting boundaries

- A facility draw creates settlement cash and corresponding facility principal; it does not consume the separate account intraday-credit line.
- Principal repayment reduces facility balances and settlement cash by equal amounts.
- Collateral is not cash or credit. Pledged eligible value supports only a facility whose configured collateral requirement matches the allocation.
- Event timestamps, IDs, simulation IDs, sequence numbers, and correlation IDs are supplied by the caller. The event stream is not durably stored here.
- No external lender, custodian, central bank, or market-price source is connected. Facility terms, advance rates, eligibility profiles, and stress settings are simulator inputs.

## Verification

Phase 4 acceptance: `pytest -q` — 61 passed. `python3 -m compileall -q src tests` and `git diff --check` passed. Tests cover facility eligibility/capacity/maturity, secured draw and repayment accounting, exact interest calculation, mobilization delays, duplicate pledge prevention, coverage-preserving release, haircut and valuation shortfall, and deterministic stress inputs.

## Deferred

Durable event storage, interest accrual posting, fees and compounding, maturity settlement automation, margin calls, forced liquidation, partial collateral substitution, multi-currency collateral, market-data ingestion, and optimization of collateral allocation remain future work.
