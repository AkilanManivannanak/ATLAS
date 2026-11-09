"""Mathematical optimization formulations with explicit status and diagnostics."""

from .funding import FundingPlan, FundingSource, OptimizationFailure, solve_cvar_funding, solve_deterministic_funding

__all__ = ["FundingPlan", "FundingSource", "OptimizationFailure", "solve_cvar_funding", "solve_deterministic_funding"]
