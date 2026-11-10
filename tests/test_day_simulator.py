from collections import Counter

import pytest

from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import POLICIES, SimulationSettings, run_day
from atlas.store import EventStore
from atlas.stress import SCENARIO_LIBRARY, build_scenario

SMALL = NexusPayConfig(n_institutions=8, payments_per_day=500, instant_payments_per_day=300, opening_liquidity_bp=700, credit_limit_bp=300)


@pytest.fixture(scope="module")
def scenario():
    return generate_scenario(SMALL, seed=11)


def test_scenario_generation_is_deterministic_and_labeled():
    a, b = generate_scenario(SMALL, seed=3), generate_scenario(SMALL, seed=3)
    assert a.fingerprint() == b.fingerprint()
    assert generate_scenario(SMALL, seed=4).fingerprint() != a.fingerprint()
    assert a.summary()["data_origin"] == "synthetic" and a.summary()["observed_financial_data"] is False
    assert all(isinstance(p.amount_minor, int) and p.amount_minor > 0 for p in a.payments)
    assert all(a.open_at <= p.arrival_at <= a.close_at for p in a.payments)
    rtp_members = {i.institution_id for i in a.institutions if "rtp" in i.rails}
    assert all(p.sender in rtp_members and p.receiver in rtp_members for p in a.payments if p.rail == "rtp")


@pytest.mark.parametrize("policy", POLICIES)
def test_every_policy_replays_and_conserves(scenario, policy):
    r = run_day(scenario, SimulationSettings(policy=policy))
    assert r.verify_replay()
    seqs = [e.sequence_number for e in r.events]
    assert seqs == list(range(len(seqs)))
    statuses = Counter(p["status"] for p in r.payments)
    assert set(statuses) <= {"settled", "unsettled", "rejected"}
    settled_events = [e for e in r.events if e.event_type == "PaymentSettled"]
    ids = [e.aggregate_id for e in settled_events]
    assert len(ids) == len(set(ids))  # no payment settles twice
    lv = r.metrics["large_value"]
    assert 0 <= lv["settlement_rate_value"] <= 1


def test_same_seed_same_ledger_hash_different_seed_differs(scenario):
    s = SimulationSettings(policy="multilateral", strategy={"early": 1, "conservative": 1, "recycler": 1})
    a, b = run_day(scenario, s), run_day(scenario, s)
    assert a.final_state_hash == b.final_state_hash
    assert [e.payload_json for e in a.events] == [e.payload_json for e in b.events]
    c = run_day(generate_scenario(SMALL, seed=12), s)
    assert c.final_state_hash != a.final_state_hash


@pytest.mark.parametrize("name", sorted(SCENARIO_LIBRARY))
def test_every_stress_scenario_runs_and_replays(scenario, name):
    r = run_day(scenario, SimulationSettings(policy="priority"), build_scenario(name))
    assert r.verify_replay()
    assert r.stress["name"] == name


def test_stress_effects_are_directional(scenario):
    base = run_day(scenario, SimulationSettings(policy="priority"))
    outage = run_day(scenario, SimulationSettings(policy="priority"), build_scenario("failure_to_pay"))
    assert outage.metrics["large_value"]["settled_value_minor"] < base.metrics["large_value"]["settled_value_minor"]
    rail = run_day(scenario, SimulationSettings(policy="priority"), build_scenario("rtgs_outage"))
    assert rail.metrics["by_rail"]["rtgs"]["value_weighted_delay_s"] > base.metrics["by_rail"]["rtgs"]["value_weighted_delay_s"]
    assert any(e.event_type == "RailOutageStarted" for e in rail.events)


def test_credit_cut_never_breaches_usage(scenario):
    r = run_day(scenario, SimulationSettings(policy="priority"), build_scenario("haircut_shock"))
    assert any(e.event_type == "CreditLimitChanged" for e in r.events)
    assert r.verify_replay()


def test_conservative_strategy_trades_delay_for_liquidity(scenario):
    early = run_day(scenario, SimulationSettings(strategy="early"))
    cons = run_day(scenario, SimulationSettings(strategy="conservative"))
    assert cons.metrics["large_value"]["value_weighted_delay_s"] > early.metrics["large_value"]["value_weighted_delay_s"]


def test_funding_strategy_draws_and_repays_facility(scenario):
    r = run_day(scenario, SimulationSettings(strategy="funding", use_intraday_credit=False))
    types = Counter(e.event_type for e in r.events)
    assert types["FundingDrawn"] > 0
    assert r.metrics["costs_minor"]["facility_interest"] > 0
    assert r.verify_replay()


def test_results_persist_to_event_store(scenario):
    store = EventStore()
    r = run_day(scenario, SimulationSettings(), store=store)
    assert store.count(r.simulation_id) == len(r.events)
    assert store.verify_chain(r.simulation_id).valid


def test_reweighted_cost_reproduces_simulator_cost(scenario):
    from atlas.benchmark.runner import _run_one, reweight_cost
    for arm in ("priority", "auction_uniform", "rule_rebalancer"):
        row = _run_one((SMALL, 11, "combined", arm, "early"))
        assert abs(reweight_cost(row["raw"]) - row["total_cost_minor"]) <= 10
