# Systemic risk and stress model

## Network analytics (`atlas.network`)
A directed, value-weighted flow graph is built from simulated payments; every edge keeps its payment ids and first/last timestamps (provenance). Metrics: in/out degree and strength, Brandes betweenness, value-weighted PageRank, Tarjan SCCs, density, reciprocity, HHI of sender and receiver value. A **systemic score** is the mean percentile rank of out-strength, PageRank and betweenness. `residual_gridlock_components` finds cyclic components among payments still unsettled at close. Hourly snapshots provide the temporal view. All algorithms are cross-checked against NetworkX in tests.

## Shock library (`atlas.stress`)
Times are minutes after the business-day open, so a shock definition is paired with any generated day.

| Scenario | Shocks |
|---|---|
| `counterparty_delay` | Largest core bank cannot send for 2 h (inflows continue: a liquidity sink). |
| `rtgs_outage` | RTGS unavailable for 90 min. |
| `liquidity_withdrawal` | 30% of large-value cash removed from every bank. |
| `funding_disruption` | Intraday credit lines cut 60%; periphery loses 20% of cash. |
| `haircut_shock` | Credit lines cut 50% (collateral revaluation). Never cut below credit in use. |
| `failure_to_pay` | Largest core bank stops sending for the rest of the day. |
| `concentrated_outflows` | 40 extra large outgoing instructions from the largest bank. |
| `liquidity_hoarding` | Half the banks switch to a 70%-buffer conservative strategy and raise a stress signal. |
| `messaging_failure` | LSM instructions delayed for 2 h. |
| `combined` | Counterparty outage + credit cut + hoarding + RTGS outage. |

Every shock is recorded as events (`RailOutageStarted/Ended`, `LiquidityAdjusted`, `CreditLimitChanged`, `StressSignalRaised`), so stressed runs replay exactly.

**Terminology.** The model measures delayed and unsettled value, liquidity shortfalls and cost. It does not model insolvency, default resolution or contagion of losses, and never reports "bank failure" or "systemic collapse".
