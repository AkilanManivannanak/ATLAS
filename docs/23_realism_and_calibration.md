# Realism and calibration (v0.6)

What is grounded in public sources, what is calibrated, and what is still simplified.

## Source-backed parameters (recorded in `RAIL_RULES`, `atlas-rail-rules-v2`)
| Fact | Value in ATLAS | Source |
|---|---|---|
| FedNow network limit (credit transfers, returns) | $10M since 2025-11-12; participants pick lower limits | frbservices.org communication, Nov 2025 |
| RTP network transaction limit | $10M | The Clearing House press release, 2025 |
| Daylight overdraft fee | 50 bp/yr on the *uncollateralized* overdraft, minute-by-minute average over 1,291 minutes, ×21.5/24, /360; collateralized = 0 | Federal Reserve PSR guide (tested against its Figure V-I example) |
| Fedwire hours | overnight window to 7 p.m. ET on business days (configurable) | frbservices.org |
| FedNow accounting rollover | ≈7:01 p.m. ET | frbservices.org |

## Generator v2 (`nexus-pay-gen-v2`)
* **Balanced gross flows.** Expected bilateral flows are Sinkhorn-scaled so each bank's expected inflow ≈ outflow (with a configurable lognormal imbalance, default sd 0.1). Without this, v1 created structural liquidity sinks that no real system has.
* **Persistent relationships.** Heavy-tailed (lognormal, σ = 1) bilateral weights fixed by the topology seed, so the same counterparties dominate every day.
* **Autocorrelated activity.** Market-wide and bank-specific AR(1) factors (φ = 0.8) on 15-minute log-intensity plus a day-level volume shock (σ = 0.15).
* **Payment types.** Customer transfers (cutoff 18:00 ET), interbank transfers (until close 18:30), timed obligations with hard deadlines at 10:00 / 13:00 / 15:30 ET, instant payments.
* **Round-number clustering.** 15% of amounts are rounded to $100k (large-value) or $1k (instant).
* **No look-ahead.** Opening liquidity and credit lines are sized from the topology's *expected* outflow, not the realised day (v1 leaked the day's own volume).

## Simulator mechanics added
* Customer-transfer cutoff: held or queued customer payments expire at the cutoff.
* LSM closing-position funding: before the customer cutoff and before close, participants fund LSM net debits from their own RTGS cash, then the queue is netted.
* Collateralized vs uncollateralized intraday credit (60% of each line collateralized by default) with the PSR fee above.

## Calibration target
With generator defaults (opening liquidity 18% and credit 10% of expected gross outflow), a normal day under the priority queue settles roughly 97% of large-value value, and stress shows up first as delay (the combined scenario roughly doubles value-weighted delay). Real large-value systems settle essentially everything; ATLAS keeps a residual so that policies can be told apart. The `tight` preset (10% / 6%) is the stressed calibration.

## Known simplifications that matter
* **FedNow settles in Fed master accounts.** In reality FedNow and Fedwire share an institution's master account unless it designates a settlement agent, and FedNow participants have intraday credit under the same PSR terms as other Federal Reserve services. `SimulationSettings(fednow_shared_master=True)` models this: the FedNow opening pool is merged into the RTGS balance, a FedNow debit draws any shortfall from that balance (including intraday credit, recorded as a `MasterAccountTransfer` ledger event) and FedNow balances are swept back after every FedNow event. The default stays `False` so v0.6 results remain comparable; `results/shared_master.md` shows the headline conclusions hold under both models (docs/19). RTP (prefunded joint account) and the LSM (prefunded positions) stay separate pools, which is realistic.
* Instant rails run only inside the large-value business day, not 24/7.
* Intraday cross-rail transfers are instantaneous (subject to a 15-minute pre-close cutoff).
* No net debit caps, no $150 PSR waiver, no penalty-rate institutions, no default or insolvency.
