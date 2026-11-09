# Security and governance

* **Authentication / RBAC:** `ATLAS_API_KEYS="key:role,..."` with roles `admin`, `researcher`, `treasury_operator`, `risk_analyst`, `auditor`. Permissions: read (all roles), simulate (admin/researcher/operator/analyst), benchmark (admin/researcher), admin. Keys are compared in constant time. With no keys configured the API runs in *development mode* and reports it in `/health`. Do not expose development mode on a network.
* **Input validation:** Pydantic models with bounds; the ISO parser rejects DTD/entity declarations; artifact names are restricted to alphanumerics, which blocks path traversal.
* **Separation of proposal and execution:** controllers propose, `SafetyController` validates, and only the simulator mutates the simulated ledger. Nothing touches real systems.
* **Provenance:** every run manifest records simulator version, event-ordering version, scenario fingerprint, generator version, seed, Python version, platform and controller. Events are hash-chained.
* **Containers:** non-root users in both images; health checks.
* **Model inventory:**

| Model | Version | Purpose | Validation |
|---|---|---|---|
| Gridlock heuristic | `gridlock-heuristic-v3` | queue netting | property tests vs brute force; optimality-gap study |
| Netting MILP | `netting-milp-highs-v1` | exact netting | equals brute force on random instances |
| MPC controller | `mpc-highs-v1` | cross-rail rebalancing + queue MILP | paired benchmark; zero-rejection target |
| Rule rebalancer | `rule-rebalancer-v1` | ablation baseline | paired benchmark |
| Forecasters | `atlas-forecast-v1` | net-outflow forecasting | scenario-level splits, conformal coverage, OOD test |
| Funding LP | `cvar-rockafellar-uryasev-v1` | pre-positioning | unit tests |

* **Not yet implemented:** secrets manager integration, dependency/container scanning in CI, a formal model validation report.
