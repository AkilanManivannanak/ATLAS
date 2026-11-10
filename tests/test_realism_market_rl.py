import math
from collections import Counter
from dataclasses import replace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atlas.control.rl import MLP, Policy, PPOConfig, RLController, gae, ppo_update
from atlas.domain import SettlementAccount
from atlas.forecast import adaptive_interval_coverage, build_panel, learn_graph
from atlas.ledger import Ledger, LedgerReplayError, interbank_transfer_event
from atlas.market import Ask, Bid, clear_auction
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import CostModel, SimulationSettings, run_day
from atlas.stress import build_scenario

SMALL = NexusPayConfig(n_institutions=8, payments_per_day=700, instant_payments_per_day=400, opening_liquidity_bp=900, credit_limit_bp=600)


# ------------------------------------------------------------------ generator v2 realism
def test_generator_v2_types_limits_and_no_liquidity_lookahead():
    sc = generate_scenario(SMALL, seed=5)
    assert sc.generator_version == "nexus-pay-gen-v2"
    kinds = Counter(p.kind for p in sc.payments)
    assert set(kinds) == {"customer", "interbank", "timed", "instant"}
    cutoff_utc = [p for p in sc.payments if p.kind == "customer"]
    assert all(p.due_at <= max(q.due_at for q in cutoff_utc) for p in cutoff_utc)
    limits = {a.institution_id: a.participant_limit_minor for a in sc.accounts if a.rail == "fednow"}
    assert all(p.amount_minor <= limits[p.sender] for p in sc.payments if p.rail == "fednow")
    assert all(p.amount_minor <= SMALL.rtp_limit_minor for p in sc.payments if p.rail == "rtp")
    # opening balances depend on the topology only, never on the realised day
    other = generate_scenario(SMALL, seed=6, topology_seed=5)
    assert [a.opening_balance_minor for a in sc.accounts] == [a.opening_balance_minor for a in other.accounts]
    assert sc.fingerprint() != other.fingerprint()


def test_generator_v2_flows_are_balanced_and_v1_still_available():
    cfg = replace(SMALL, payments_per_day=6_000, instant_payments_per_day=0, flow_imbalance_milli=0, timed_share_bp=0)
    sc = generate_scenario(cfg, seed=3)
    out, inn = Counter(), Counter()
    for p in sc.payments:
        out[p.sender] += p.amount_minor
        inn[p.receiver] += p.amount_minor
    ratios = [inn[b] / out[b] for b in out]
    assert 0.6 < min(ratios) and max(ratios) < 1.6          # balanced in expectation; sampling noise only
    assert generate_scenario(replace(SMALL, generator="v1"), seed=3).generator_version == "nexus-pay-gen-v1"


def test_generator_v2_has_intraday_autocorrelation():
    panel = build_panel(replace(SMALL, payments_per_day=3_000, instant_payments_per_day=0), list(range(12)), 9, target="gross_outflow")
    d = panel["days"].sum(1)                                  # system gross outflow per bucket per day
    resid = d - d.mean(0)                                     # remove the deterministic intraday profile
    x, y = resid[:, :-1].ravel(), resid[:, 1:].ravel()
    assert np.corrcoef(x, y)[0, 1] > 0.2


# ------------------------------------------------------------------ simulator realism
def test_psr_fee_matches_the_published_formula():
    sim_cost = CostModel()
    # $1.8bn of summed per-minute uncollateralized overdraft -> the Fed guide's example daily charge of $17.29
    minute_sum = 1_800_000_000_00
    num = minute_sum * sim_cost.psr_fee_bp_annual * sim_cost.psr_fedwire_hours_x10
    fee = -(-num // (sim_cost.psr_day_minutes * 10_000 * 240 * 360))
    assert fee == 1735          # ATLAS uses the unrounded effective daily rate (0.0000124421...) -> $17.35
    # The Fed guide's Figure V-I rounds the daily rate to 0.0000124 and reports $17.29 for the same overdrafts.
    assert round(1_394_268 * 0.0000124, 2) == 17.29 and minute_sum // 100 // 1291 == 1_394_268


def test_customer_cutoff_and_lsm_closing_funding():
    sc = generate_scenario(SMALL, seed=8)
    r = run_day(sc, SimulationSettings(policy="priority"))
    assert r.verify_replay()
    from datetime import datetime
    from zoneinfo import ZoneInfo
    cutoff = datetime.combine(SMALL.business_date, SMALL.customer_cutoff, ZoneInfo("America/New_York"))
    kinds = {p.payment_id: p.kind for p in sc.payments}
    settled_customer = [p for p in r.payments if kinds[p["payment_id"]] == "customer" and p["status"] == "settled"]
    assert settled_customer and all(datetime.fromisoformat(p["settled_at"]) <= cutoff for p in settled_customer)
    reasons = Counter(p["reason"] for p in r.payments if p["status"] == "unsettled")
    assert all("customer" in k or "close" in k for k in reasons)
    assert "by_kind" in r.metrics and "timed" in r.metrics["by_kind"]
    off = run_day(sc, SimulationSettings(policy="priority", lsm_final_cycle_min_before_close=0))
    assert r.metrics["by_rail"]["lsm"]["settlement_rate_value"] >= off.metrics["by_rail"]["lsm"]["settlement_rate_value"]


@pytest.mark.parametrize("policy", ["fifo", "priority", "multilateral"])
def test_dirty_set_gross_pass_is_exact(policy):
    import atlas.sim.day as D
    sc = generate_scenario(SMALL, seed=2)
    a = run_day(sc, SimulationSettings(policy=policy), build_scenario("combined")).final_state_hash
    orig = D.DaySimulator._gross_pass

    class Everything(set):
        def __contains__(self, k):
            return True

        def clear(self):
            pass

    def no_skip(self, at):
        self._dirty = Everything()
        return orig(self, at)

    D.DaySimulator._gross_pass = no_skip
    try:
        b = run_day(sc, SimulationSettings(policy=policy), build_scenario("combined")).final_state_hash
    finally:
        D.DaySimulator._gross_pass = orig
    assert a == b


# ------------------------------------------------------------------ auction
def test_auction_clearing_rules():
    asks = [Ask("L1", 100, 2), Ask("L2", 100, 5), Ask("L3", 100, 9)]
    bids = [Bid("B1", 150, 8), Bid("B2", 100, 4)]
    pab = clear_auction(asks, bids, "pay_as_bid")
    uni = clear_auction(asks, bids, "uniform")
    assert pab.matched_quantity_minor == uni.matched_quantity_minor == 150
    assert {t.rate_cbp for t in pab.trades} == {2, 5}
    assert uni.clearing_rate_cbp == 5 and all(t.rate_cbp == 5 for t in uni.trades)
    assert clear_auction([Ask("L", 10, 9)], [Bid("B", 10, 3)]).trades == ()
    with pytest.raises(ValueError):
        clear_auction([Ask("X", 10, 1)], [Bid("X", 10, 3)])


@settings(max_examples=60, deadline=None)
@given(asks=st.lists(st.tuples(st.integers(1, 500), st.integers(0, 30)), min_size=1, max_size=6),
       bids=st.lists(st.tuples(st.integers(1, 500), st.integers(0, 30)), min_size=1, max_size=6),
       mech=st.sampled_from(["pay_as_bid", "uniform"]))
def test_property_auction_is_individually_rational_and_conserves_quantity(asks, bids, mech):
    A = [Ask(f"L{i}", q, r) for i, (q, r) in enumerate(asks)]
    B = [Bid(f"B{i}", q, r) for i, (q, r) in enumerate(bids)]
    res = clear_auction(A, B, mech)
    lent, borrowed = Counter(), Counter()
    for t in res.trades:
        lent[t.lender] += t.quantity_minor
        borrowed[t.borrower] += t.quantity_minor
        assert {a.lender: a.min_rate_cbp for a in A}[t.lender] <= t.rate_cbp <= {b.borrower: b.max_rate_cbp for b in B}[t.borrower]
    assert all(lent[a.lender] <= a.quantity_minor for a in A)
    assert all(borrowed[b.borrower] <= b.quantity_minor for b in B)
    assert sum(lent.values()) == res.matched_quantity_minor


def test_interbank_transfer_replays_and_rejects_overdraft():
    a, b = SettlementAccount("x:rtgs", "x", "rtgs", "USD", 500), SettlementAccount("y:rtgs", "y", "rtgs", "USD", 0)
    meta = dict(at=__import__("datetime").datetime(2026, 1, 6, tzinfo=__import__("datetime").UTC), event_id="e0", sequence_number=0,
                simulation_id="s", correlation_id="c", causation_id=None)
    a2, b2, ev = interbank_transfer_event(a, b, 300, "auction loan drawdown", loan_id="L0", **meta)
    led = Ledger.replay((a, b), [ev])
    assert led.account("y:rtgs").ledger_balance_minor == 300 and led.total_ledger_minor() == 500
    with pytest.raises(ValueError):
        interbank_transfer_event(a, b, 600, "x", loan_id="L1", **meta)
    with pytest.raises(LedgerReplayError):
        Ledger.replay((replace(a, ledger_balance_minor=100), b), [ev])


def test_auction_in_simulator_replays_and_helps_settlement():
    sc = generate_scenario(SMALL, seed=4)
    base = run_day(sc, SimulationSettings(policy="priority"))
    for mech in ("pay_as_bid", "uniform"):
        r = run_day(sc, SimulationSettings(policy="priority", auction=mech))
        assert r.verify_replay()
        au = r.metrics["auction"]
        assert au["mechanism"] == mech and au["auctions_held"] > 0
        assert r.metrics["large_value"]["settled_value_minor"] >= base.metrics["large_value"]["settled_value_minor"]
    shaded = run_day(sc, SimulationSettings(policy="priority", auction="pay_as_bid", auction_shading_bp=(("bank-000", 10_000),)))
    assert shaded.verify_replay()


# ------------------------------------------------------------------ safe RL
def test_mlp_gradients_match_finite_differences():
    rng = np.random.default_rng(0)
    m = MLP(5, 7, 3, rng, out_scale=1.0)
    x, w = rng.normal(size=(4, 5)), rng.normal(size=(4, 3))
    out, cache = m.forward(x)
    grads = MLP.backward(m.params(), cache, w)
    for P, G in zip(m.params(), grads):
        for flat in range(min(3, P.size)):
            i = np.unravel_index(flat, P.shape)
            old = P[i]
            P[i] = old + 1e-6
            up = float((m.forward(x)[0] * w).sum())
            P[i] = old - 1e-6
            down = float((m.forward(x)[0] * w).sum())
            P[i] = old
            assert abs((up - down) / 2e-6 - G[i]) < 1e-5


def test_gae_matches_discounted_returns_when_lambda_one():
    r, v = np.array([1.0, 0.0, 2.0]), np.zeros(3)
    assert np.allclose(gae(r, v, 0.5, 1.0), [1 + 0 + 0.25 * 2, 0 + 0.5 * 2, 2])


def test_rl_controller_rollout_update_and_safety_filter():
    pol = Policy(PPOConfig(seed=3))
    ctrl = RLController(pol)
    r = run_day(generate_scenario(SMALL, seed=9), SimulationSettings(policy="multilateral"), controller=ctrl)
    assert r.verify_replay()
    steps = [s for s in ctrl.traj if "reward" in s]
    assert steps and all(math.isfinite(s["reward"]) for s in steps)
    rejected = [e for e in r.controller_log if not e["approved"]]
    assert len(rejected) == r.metrics["counters"]["controller_rejected"]     # rejected proposals are logged, never executed
    stats = ppo_update(pol, [ctrl.traj])
    assert stats["samples"] > 0 and stats["lambda"] >= 0
    restored = Policy.from_dict(pol.to_dict())
    assert np.allclose(restored.pi.W1, pol.pi.W1)


def test_learned_graph_and_adaptive_intervals():
    panel = build_panel(replace(SMALL, instant_payments_per_day=0), list(range(6)), 4)
    g = learn_graph(panel, range(4))
    assert all(abs(sum(w for _, w in v) - 1) < 1e-9 for v in g.values() if v)
    y = np.concatenate([np.zeros(50), np.full(50, 10.0)])
    keys = [(0, 0, b) for b in range(100)]
    cov, width = adaptive_interval_coverage(y, np.zeros(100), keys, 1, w0=1.0, alpha=0.1, eta=0.5)
    assert cov > 0.5 and width > 2.0         # the interval widens after the shift instead of staying stuck
