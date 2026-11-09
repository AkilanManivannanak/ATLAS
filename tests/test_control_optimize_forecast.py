from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from atlas.control import MPCConfig, MPCController, RuleBasedRebalancer, SafetyController
from atlas.domain import PaymentInstruction, PaymentStatus, SettlementAccount
from atlas.forecast import RidgeForecaster, build_panel, evaluate, run_forecast_experiment
from atlas.optimize import FundingSource, OptimizationFailure, solve_cvar_funding, solve_deterministic_funding
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import Action, SimulationSettings, SystemView, run_day

NOW = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)
CFG = NexusPayConfig(n_institutions=8, payments_per_day=600, instant_payments_per_day=400, opening_liquidity_bp=600, credit_limit_bp=300)


def _view(accounts, rtgs_queue=(), lsm_queue=(), rail_up=None, now=NOW):
    return SystemView(now, NOW + timedelta(hours=3), {a.account_id: a for a in accounts}, tuple(rtgs_queue), tuple(lsm_queue), {},
                      rail_up or {"rtgs": True, "lsm": True, "fednow": True, "rtp": True}, {})


def _acct(inst, rail, bal):
    return SettlementAccount(f"{inst}:{rail}", inst, rail, "USD", bal)


def _queued(pid, s, r, amount):
    return PaymentInstruction(pid, f"e-{pid}", f"i-{pid}", s, r, f"{s}:rtgs", f"{r}:rtgs", "rtgs", "USD", amount, 1, NOW, NOW + timedelta(hours=1),
                              status=PaymentStatus.QUEUED)


def test_safety_accepts_feasible_and_rejects_infeasible_batches():
    accts = [_acct("A", "rtgs", 0), _acct("B", "rtgs", 0)]
    q = [_queued("p1", "A", "B", 100), _queued("p2", "B", "A", 100), _queued("p3", "A", "B", 5)]
    s = SafetyController()
    assert s.validate(Action("settle_batch", payment_ids=("p1", "p2")), _view(accts, q)).approved
    v = s.validate(Action("settle_batch", payment_ids=("p1", "p2", "p3")), _view(accts, q))
    assert not v.approved and "cash constraints" in v.reason
    assert not s.validate(Action("settle_batch", payment_ids=("zzz",)), _view(accts, q)).approved
    assert not s.validate(Action("settle_batch", payment_ids=("p1", "p1")), _view(accts, q)).approved
    assert not s.validate(Action("settle_batch", payment_ids=("p1", "p2")), _view(accts, q, rail_up={"rtgs": False})).approved
    assert not s.validate(Action("launch_missiles"), _view(accts, q)).approved


def test_safety_transfer_rules():
    accts = [_acct("A", "rtgs", 1_000), _acct("A", "fednow", 0), _acct("B", "rtgs", 1_000)]
    s = SafetyController()
    ok = Action("transfer", institution="A", from_rail="rtgs", to_rail="fednow", amount_minor=400)
    assert s.validate(ok, _view(accts)).approved
    assert "share limit" in s.validate(replace(ok, amount_minor=600), _view(accts)).reason
    assert not s.validate(replace(ok, institution="B"), _view(accts)).approved           # B has no fednow account
    assert not s.validate(replace(ok, amount_minor=0), _view(accts)).approved
    assert not s.validate(replace(ok, to_rail="rtgs"), _view(accts)).approved
    late = _view(accts, now=NOW + timedelta(hours=2, minutes=50))
    assert "cutoff" in s.validate(ok, late).reason
    committed = _view(accts, rtgs_queue=[_queued("p", "A", "B", 900)])
    assert "uncover queued" in s.validate(ok, committed).reason


@pytest.fixture(scope="module")
def tight_day():
    return generate_scenario(CFG, seed=21)


def test_mpc_runs_safely_and_replays(tight_day):
    base = run_day(tight_day, SimulationSettings(policy="multilateral"))
    mpc = MPCController(MPCConfig(enable_queue_milp=True))
    r = run_day(tight_day, SimulationSettings(policy="multilateral"), controller=mpc)
    assert r.verify_replay()
    assert r.metrics["counters"]["controller_actions"] > 0
    assert all(e["reason"] for e in r.controller_log)
    assert any(x["problem"] == "rebalance_lp" for x in mpc.solve_log)
    # transfers move cash between an institution's own rails only: total cash is conserved
    transfers = [e for e in r.events if e.event_type == "LiquidityAdjusted" and "intra-institution" in e.payload_json]
    assert len(transfers) % 2 == 0
    assert r.metrics["costs_minor"]["total"] <= base.metrics["costs_minor"]["total"]


def test_rule_rebalancer_runs(tight_day):
    r = run_day(tight_day, SimulationSettings(), controller=RuleBasedRebalancer())
    assert r.verify_replay() and r.manifest["controller"] == "rule-rebalancer-v1"


def test_cvar_funding_is_more_conservative_than_expected_value():
    sources = [FundingSource("reserves", 400, 5), FundingSource("secured", 600, 20, collateral_bp=10_000), FundingSource("unsecured", 500, 60)]
    scenarios = [100, 150, 200, 250, 300, 350, 400, 900, 1000, 1200]
    ev = solve_deterministic_funding(sources, scenarios, shortfall_cost_bp=500)
    cv = solve_cvar_funding(sources, scenarios, shortfall_cost_bp=500, alpha=0.9, risk_weight=0.8)
    assert sum(cv.allocations_minor.values()) >= sum(ev.allocations_minor.values())
    assert cv.expected_shortfall_minor <= ev.expected_shortfall_minor
    assert cv.allocations_minor["reserves"] >= cv.allocations_minor["unsecured"]   # cheapest source used first
    assert all(isinstance(v, int) for v in cv.allocations_minor.values())
    budget = solve_cvar_funding(sources, scenarios, alpha=0.9, risk_weight=0.8, collateral_budget_minor=100)
    assert budget.allocations_minor["secured"] <= 101


def test_funding_validation():
    with pytest.raises(ValueError):
        solve_cvar_funding([], [1])
    with pytest.raises(TypeError):
        solve_cvar_funding([FundingSource("a", 1, 1)], [1.5])
    assert issubclass(OptimizationFailure, RuntimeError)


def test_forecast_panel_and_conformal_coverage():
    cfg = NexusPayConfig(n_institutions=6, payments_per_day=600, instant_payments_per_day=0)
    panel = build_panel(cfg, list(range(10)), topology_seed=1)
    assert panel["days"].shape[0] == 10
    assert abs(panel["days"].sum()) < 1e-3   # net outflows across the system sum to zero each day
    r = evaluate(RidgeForecaster(), panel, list(range(6)), [6, 7], [8, 9], 2, mase_scale=1.0)
    assert 0.75 <= r["interval_coverage"] <= 1.0
    assert r["crps_approx"] > 0


def test_forecast_experiment_structure():
    cfg = NexusPayConfig(n_institutions=5, payments_per_day=300, instant_payments_per_day=0)
    res = run_forecast_experiment(cfg, train_seeds=(1, 2, 3, 4), val_seeds=(5, 6), test_seeds=(7, 8), horizons={"15m": 1}, include_gbm=False,
                                  ood_config=replace(cfg, payments_per_day=600))
    splits = {x["split"] for x in res["results"]}
    assert splits == {"test_in_distribution", "test_out_of_distribution"}
    assert set(res["splits"]["test_days"]).isdisjoint(res["splits"]["train_days"])
