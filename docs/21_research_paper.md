# Paper outline (draft; results-backed sections only)

**ATLAS-Σ: Adaptive Multi-Rail Settlement Control under Endogenous Liquidity Strategies.** An agent-based digital twin for liquidity efficiency, settlement resilience and systemic risk.

1. **Introduction.** Liquidity fragmentation across co-existing RTGS, liquidity-saving and instant rails.
2. **Related work.** RTGS liquidity simulation (Leinonen & Soramäki; Bech & Soramäki), the liquidity-timing game (Bech & Garratt), clearing algorithms (Güntzer et al.), MPC, CVaR optimization, conformal prediction.
3. **Simulator.** Event-sourced ledger with hash-chained replay; four rail archetypes; agents; shocks (§08–10).
4. **Methods.** Netting MILP and heuristic; MPC rebalancing LP; CVaR funding; forecasting with conformal intervals (§11–13).
5. **Benchmark.** NEXUS-PAY, paired seeds and bootstrap statistics (§18).
6. **Results.** E1, E2/E6, E5, netting optimality, E8 (§19).
7. **Limitations** (§20).

Contribution claims are restricted to the experimentally supported finding: in this model, adaptive cross-rail liquidity rebalancing dominates queue-algorithm choice. No novelty is claimed for the individual techniques. Sections for E3, E4 and E7 will be written only after those experiments exist.
