# Optimization formulations

Every solve reports solver, status and runtime. Infeasible or failed solves are explicit (`OptimizationFailure`, HTTP 409) and never relax a hard constraint. Continuous solutions are converted to integer minor units conservatively and re-verified.

## 1. Partial netting (0-1 MILP, HiGHS)
`max Σ_p w_p v_p x_p  s.t.  Σ_{p:payer=a} v_p x_p − Σ_{p:payee=a} v_p x_p ≤ L_a  ∀a,  x ∈ {0,1}`. The weights `w_p` are 1 for the policy and an urgency weight for the MPC (`1 + 4·max(0, 1 − minutes_to_due/60) + 0.5·priority`).

## 2. MPC cross-rail rebalancing LP (per institution, every 5 minutes)
Variables: transfers `x_{r→r'} ≥ 0` between the institution's own rail accounts, and shortfalls `s_r ≥ 0`.
`min Σ_r pen_r s_r + c Σ x  s.t.  avail_r − Σ_{r'} x_{r→r'} + Σ_{r'} x_{r'→r} + s_r ≥ need_r ;  Σ_{r'} x_{r→r'} ≤ movable_r`
`need_r` = queued + held outgoing due within the 30-minute horizon, plus a 95% empirical quantile of recent instant outflow scaled to the horizon (a scenario approximation of the chance constraint). `movable_r` excludes cash committed to the rail's queued outgoing payments and caps total outflow at one third of free cash, which keeps every sequential action inside the safety controller's 50% per-action cap. Only the first step is applied (receding horizon). Penalties: instant 10, RTGS/LSM 3; transfer cost 0.01.

## 3. Stochastic funding pre-positioning (CVaR LP)
Rockafellar & Uryasev (2000):
`min Σ_k c_k y_k + (1−λ)·(1/S) Σ_s p u_s + λ·(η + 1/((1−α)S) Σ_s z_s)`
`s.t. u_s ≥ d_s − Σ_k y_k, z_s ≥ p u_s − η, 0 ≤ y_k ≤ cap_k, Σ_k h_k y_k ≤ C, u, z ≥ 0`.
The expected-value baseline plans against the scenario mean only. A test checks that the CVaR plan pre-positions at least as much and has no higher expected shortfall.

## 4. Cost model used in all evaluations (`CostModel`, research assumptions)
Delay 2 bp of value per hour of waiting; late settlement 10 bp; unsettled at close 100 bp; peak own-liquidity usage 5 bp/day; peak intraday credit 15 bp/day; rejected instant payments 100 bp; facility interest at the facility rate. These are parameters, not calibrated estimates of real costs; benchmark conclusions should be re-checked under alternative weights.
