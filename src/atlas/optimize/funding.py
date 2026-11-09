"""Intraday funding pre-positioning under uncertain net outflows.

Decision: how much liquidity y_k to pre-position from each funding source k
(e.g. own reserves moved in, secured facility, unsecured facility) before the
day, given S equally likely net-outflow scenarios d_s (from the probabilistic
forecaster). Any scenario shortfall must be covered at an emergency rate.

Deterministic baseline (expected-value problem)::

    min  sum_k c_k y_k + p * max(0, mean(d) - sum_k y_k)

Risk-averse problem with Conditional Value-at-Risk of the shortfall cost
(Rockafellar & Uryasev, 2000, "Optimization of conditional value-at-risk",
Journal of Risk 2(3))::

    min   sum_k c_k y_k + (1-lambda) * (1/S) sum_s p*u_s + lambda * (eta + 1/((1-alpha) S) sum_s z_s)
    s.t.  u_s >= d_s - sum_k y_k,  u_s >= 0                  (shortfall in scenario s)
          z_s >= p*u_s - eta,       z_s >= 0                  (CVaR auxiliary)
          0 <= y_k <= cap_k,  optional collateral: sum_k h_k y_k <= C

Solved as an LP with HiGHS (scipy.optimize.linprog). Hard constraints are never
relaxed; an infeasible or failed solve raises ``OptimizationFailure`` carrying the
solver status. Amounts are returned as integer minor units (rounded *up* so the
plan never under-covers what the LP chose).
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field


class OptimizationFailure(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"optimization failed (status {status}): {message}")
        self.status = status
        self.message = message


@dataclass(frozen=True, slots=True)
class FundingSource:
    name: str
    capacity_minor: int
    cost_bp: int                    # cost per unit pre-positioned, basis points of amount
    collateral_bp: int = 0          # collateral consumed per unit drawn (haircut-adjusted), bp


@dataclass
class FundingPlan:
    allocations_minor: dict[str, int]
    objective_minor: float
    expected_shortfall_minor: float
    cvar_shortfall_cost_minor: float | None
    var_threshold_minor: float | None
    status: str
    solver: str
    runtime_ms: float
    formulation: str
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("allocations_minor", "objective_minor", "expected_shortfall_minor", "cvar_shortfall_cost_minor",
                                               "var_threshold_minor", "status", "solver", "runtime_ms", "formulation", "diagnostics")}


def _validate(sources: Sequence[FundingSource], scenarios: Sequence[int]) -> None:
    if not sources:
        raise ValueError("at least one funding source is required")
    if not scenarios:
        raise ValueError("at least one outflow scenario is required")
    if any(not isinstance(d, int) for d in scenarios):
        raise TypeError("scenario outflows must be integer minor units")
    if len({s.name for s in sources}) != len(sources):
        raise ValueError("duplicate funding source names")


def solve_cvar_funding(
    sources: Sequence[FundingSource],
    scenarios: Sequence[int],
    *,
    shortfall_cost_bp: int = 500,
    alpha: float = 0.95,
    risk_weight: float = 0.5,
    collateral_budget_minor: int | None = None,
) -> FundingPlan:
    import numpy as np
    from scipy.optimize import linprog

    _validate(sources, scenarios)
    if not 0 < alpha < 1 or not 0 <= risk_weight <= 1:
        raise ValueError("alpha must be in (0,1) and risk_weight in [0,1]")
    started = time.perf_counter()
    K, S = len(sources), len(scenarios)
    scale = max(1, max(abs(d) for d in scenarios), max(s.capacity_minor for s in sources))
    d = np.array(scenarios, dtype=float) / scale
    p = shortfall_cost_bp / 10_000
    # variable order: y(K), u(S), z(S), eta(1)
    n = K + 2 * S + 1
    c = np.zeros(n)
    c[:K] = [s.cost_bp / 10_000 for s in sources]
    c[K:K + S] = (1 - risk_weight) * p / S
    c[K + S:K + 2 * S] = risk_weight / ((1 - alpha) * S)
    c[-1] = risk_weight
    rows, rhs = [], []

    def row(**entries) -> None:
        r = np.zeros(n)
        for idx, val in entries.get("cells", []):
            r[idx] = val
        rows.append(r)
        rhs.append(entries["rhs"])

    for j in range(S):
        row(cells=[*((k, -1.0) for k in range(K)), (K + j, -1.0)], rhs=-d[j])            # -sum(y) - u_j <= -d_j
        row(cells=[(K + j, p), (K + S + j, -1.0), (n - 1, -1.0)], rhs=0.0)               # p*u_j - z_j - eta <= 0
    if collateral_budget_minor is not None:
        row(cells=[(k, src.collateral_bp / 10_000) for k, src in enumerate(sources)], rhs=collateral_budget_minor / scale)
    bounds = [(0, s.capacity_minor / scale) for s in sources] + [(0, None)] * (2 * S) + [(None, None)]
    res = linprog(c, A_ub=np.array(rows), b_ub=np.array(rhs), bounds=bounds, method="highs")
    if res.status != 0:
        raise OptimizationFailure(res.status, res.message)
    y = {s.name: min(s.capacity_minor, math.ceil(res.x[k] * scale - 1e-6)) for k, s in enumerate(sources)}
    total = sum(y.values())
    shortfalls = [max(0, dd - total) for dd in scenarios]
    tail = sorted((p * sf for sf in shortfalls), reverse=True)[: max(1, math.ceil((1 - alpha) * S))]
    return FundingPlan(
        y, float(res.fun) * scale, sum(shortfalls) / S, sum(tail) / len(tail), float(res.x[-1]) * scale, "optimal", "HiGHS",
        (time.perf_counter() - started) * 1000, "cvar-rockafellar-uryasev-v1",
        {"alpha": alpha, "risk_weight": risk_weight, "scenarios": S, "shortfall_cost_bp": shortfall_cost_bp,
         "binding_capacity": [s.name for s in sources if y[s.name] >= s.capacity_minor],
         "collateral_used_minor": sum(y[s.name] * s.collateral_bp // 10_000 for s in sources)},
    )


def solve_deterministic_funding(sources: Sequence[FundingSource], scenarios: Sequence[int], *, shortfall_cost_bp: int = 500,
                                collateral_budget_minor: int | None = None) -> FundingPlan:
    """Expected-value baseline: plan against the scenario mean only (risk_weight = 0 on a single mean scenario)."""
    mean = int(round(sum(scenarios) / len(scenarios)))
    plan = solve_cvar_funding(sources, [mean], shortfall_cost_bp=shortfall_cost_bp, alpha=0.5, risk_weight=0.0,
                              collateral_budget_minor=collateral_budget_minor)
    total = sum(plan.allocations_minor.values())
    shortfalls = [max(0, d - total) for d in scenarios]
    plan.expected_shortfall_minor = sum(shortfalls) / len(shortfalls)
    plan.formulation = "expected-value-v1"
    plan.cvar_shortfall_cost_minor = None
    return plan
