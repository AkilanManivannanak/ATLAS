# Safe reinforcement learning — status: NOT IMPLEMENTED

This document specifies the integration so the next increment cannot bypass existing guarantees.

* **Interface:** a learned policy implements the same `Controller.propose(SystemView) -> list[Action]` protocol as `MPCController`. Its action space is limited to `settle_batch` and own-account `transfer`.
* **Safety:** every action passes `SafetyController` (`atlas-safety-v1`). Rejections are logged with the model version and never executed or repaired.
* **Training data:** generated days only, split by whole scenario (train/validation/test seeds plus held-out stress scenarios and strategy mixes).
* **Baselines it must beat:** `priority`, `rule_rebalancer`, `mpc` on the NEXUS-PAY paired benchmark, with CIs.
* **Planned algorithms:** PPO, then constrained PPO with a Lagrangian on safety-rejection rate; MAPPO for per-bank agents.
* **Deployment:** none. No learned policy is ever connected to real systems.
