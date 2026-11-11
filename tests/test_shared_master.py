"""FedNow on the Fed master account shared with RTGS (SimulationSettings.fednow_shared_master)."""
from collections import Counter
from datetime import UTC, datetime

import pytest

from atlas.domain import SettlementAccount
from atlas.ledger import Ledger, LedgerReplayError, master_account_transfer_event
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings
from atlas.sim.day import DaySimulator
from atlas.stress import build_scenario

SMALL = NexusPayConfig(n_institutions=8, payments_per_day=700, instant_payments_per_day=600, opening_liquidity_bp=900, credit_limit_bp=600)
AT = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)
META = dict(at=AT, simulation_id="t", correlation_id="c", causation_id=None)


def _run(shared: bool, seed: int = 3):
    sim = DaySimulator(generate_scenario(SMALL, seed=seed), SimulationSettings(policy="multilateral", fednow_shared_master=shared),
                       build_scenario("baseline"))
    return sim, sim.run()


def test_shared_master_merges_opening_pool_and_replays_exactly():
    sim, r = _run(True)
    assert r.verify_replay()
    sc = generate_scenario(SMALL, seed=3)
    spec = {a.account_id: a.opening_balance_minor for a in sc.accounts}
    for a in r.opening_accounts:
        if a.payment_rail_id == "fednow":
            assert a.ledger_balance_minor == 0
        if a.payment_rail_id == "rtgs":
            assert a.ledger_balance_minor == spec[a.account_id] + spec[f"{a.institution_id}:fednow"]
    # total opening liquidity is unchanged: the pools are merged, not created
    assert sum(a.ledger_balance_minor for a in r.opening_accounts) == sum(spec.values())
    # after every FedNow event the FedNow view is swept back to the master balance
    assert all(sim.ledger.account(f"{i}:fednow").ledger_balance_minor == 0 for i in sim.institutions)


def test_shared_master_removes_fragmentation_rejections():
    sim_sep, _ = _run(False)
    sim_sha, _ = _run(True)
    rej = lambda sim: Counter(m["rail"] for m in sim.meta.values() if m["status"] == "rejected")
    assert rej(sim_sha)["fednow"] < rej(sim_sep)["fednow"]
    assert sim_sha.counters.get("master_account_moves_minor", 0) > 0
    assert sim_sep.counters.get("master_account_moves_minor", 0) == 0


def test_master_transfer_draws_only_the_shortfall_as_credit():
    src = SettlementAccount("b1:rtgs", "b1", "rtgs", "USD", 100, credit_limit_minor=500)
    dst = SettlementAccount("b1:fednow", "b1", "fednow", "USD", 0)
    with pytest.raises(ValueError):
        master_account_transfer_event(src, dst, 300, "x", event_id="e0", sequence_number=0, **META)
    s2, d2, ev = master_account_transfer_event(src, dst, 300, "x", allow_intraday_credit=True, event_id="e0", sequence_number=0, **META)
    assert (s2.ledger_balance_minor, s2.intraday_credit_used_minor, d2.ledger_balance_minor) == (0, 200, 300)
    led = Ledger([src, dst]).apply_all([ev])
    assert led.account("b1:rtgs") == s2 and led.account("b1:fednow").ledger_balance_minor == 300
    led.verify_totals()


def test_master_transfer_refuses_other_institutions_and_tampered_events():
    a = SettlementAccount("b1:rtgs", "b1", "rtgs", "USD", 1_000)
    b = SettlementAccount("b2:fednow", "b2", "fednow", "USD", 0)
    with pytest.raises(ValueError):
        master_account_transfer_event(a, b, 10, "x", event_id="e0", sequence_number=0, **META)
    c = SettlementAccount("b1:fednow", "b1", "fednow", "USD", 0)
    _, _, ev = master_account_transfer_event(a, c, 10, "x", event_id="e0", sequence_number=0, **META)
    tampered = ev.__class__(**{**{f: getattr(ev, f) for f in ev.__dataclass_fields__},
                               "payload_json": ev.payload_json.replace('"amount_minor":10', '"amount_minor":5000')})
    with pytest.raises(LedgerReplayError):
        Ledger([a, c]).apply_all([tampered])
