import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atlas.domain import PaymentInstruction, PaymentStatus, SettlementAccount, settle_cash_transfer
from atlas.ledger import Ledger, LedgerReplayError, adjustment_event, credit_limit_event, credit_repayment_event
from atlas.store import EventStore, EventStoreError
from atlas.workflows import run_vertical_slice

T0 = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)


def acct(account_id, inst, bal, credit=0):
    return SettlementAccount(account_id, inst, "rtgs", "USD", bal, credit_limit_minor=credit)


def pay(pid, s, r, amount, sa=None, ra=None):
    return PaymentInstruction(
        payment_id=pid, end_to_end_id=f"e2e-{pid}", instruction_id=f"i-{pid}", sender_institution_id=s,
        receiver_institution_id=r, sender_account_id=sa or f"a-{s}", receiver_account_id=ra or f"a-{r}",
        payment_rail_id="rtgs", currency="USD", amount_minor=amount, priority=1, created_at=T0,
        due_at=T0 + timedelta(hours=1), status=PaymentStatus.SETTLEMENT_PENDING,
    )


def settle(p, accounts, seq, credit=False):
    res = settle_cash_transfer(p, accounts[p.sender_account_id], accounts[p.receiver_account_id], settled_at=T0,
                               event_id=f"ev-{seq}", sequence_number=seq, simulation_id="sim", correlation_id="c",
                               allow_intraday_credit=credit)
    accounts[p.sender_account_id] = res.sender_account
    accounts[p.receiver_account_id] = res.receiver_account
    return res.event


def test_vertical_slice_end_to_end():
    result = run_vertical_slice()
    assert result.payment.status == PaymentStatus.SETTLED
    closing = {a.account_id: a.ledger_balance_minor for a in result.closing_accounts}
    assert closing == {"acct-alpha-rtgs": 75_000_000, "acct-beta-rtgs": 65_000_000}
    assert result.replay_matches and result.chain_valid
    assert result.payment.source_message_id == "MSG-VS-0001"
    assert result.payment.message_schema_version == "pacs.008.001.08"
    assert len(result.events) == 1 and result.events[0].event_type == "PaymentSettled"


def test_vertical_slice_insufficient_liquidity_queues_without_events():
    result = run_vertical_slice(amount="2000000.00")
    assert result.payment.status == PaymentStatus.CREATED
    assert result.events == () and "insufficient" in result.admission_reason
    assert result.replay_matches


def test_store_hash_chain_detects_tampering(tmp_path):
    path = tmp_path / "events.db"
    accounts = {a.account_id: a for a in (acct("a-x", "x", 1000), acct("a-y", "y", 1000))}
    store = EventStore(path)
    for i in range(5):
        store.append(settle(pay(f"p{i}", "x", "y", 10), accounts, i))
    assert store.verify_chain("sim").valid and store.verify_chain("sim").event_count == 5
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE financial_events SET payload_json = replace(payload_json, '\"amount_minor\":10', '\"amount_minor\":99') WHERE sequence_number=2")
    conn.commit()
    conn.close()
    check = EventStore(path).verify_chain("sim")
    assert not check.valid and check.first_invalid_sequence == 2 and check.reason == "record hash mismatch"


def test_store_rejects_gaps_and_conflicts_and_is_idempotent():
    store = EventStore()
    accounts = {a.account_id: a for a in (acct("a-x", "x", 1000), acct("a-y", "y", 1000))}
    e0 = settle(pay("p0", "x", "y", 10), accounts, 0)
    store.append(e0)
    store.append(e0)  # identical retry is a no-op
    assert store.count("sim") == 1
    e2 = settle(pay("p2", "x", "y", 10), accounts, 2)
    with pytest.raises(EventStoreError, match="sequence gap"):
        store.append(e2)
    with pytest.raises(EventStoreError, match="different content"):
        store.append(replace(e0, correlation_id="other"))


def test_store_append_many_is_atomic():
    store = EventStore()
    accounts = {a.account_id: a for a in (acct("a-x", "x", 1000), acct("a-y", "y", 1000))}
    e0 = settle(pay("p0", "x", "y", 10), accounts, 0)
    bad = settle(pay("p5", "x", "y", 10), accounts, 5)
    with pytest.raises(EventStoreError):
        store.append_many([e0, bad])
    assert store.count("sim") == 0


def test_ledger_replay_rejects_reordered_events():
    opening = (acct("a-x", "x", 100), acct("a-y", "y", 0))
    accounts = {a.account_id: a for a in opening}
    e0 = settle(pay("p0", "x", "y", 60), accounts, 0)
    e1 = settle(pay("p1", "y", "x", 30), accounts, 1)
    assert Ledger.replay(opening, [e0, e1]).account("a-x").ledger_balance_minor == 70
    reordered = [replace(e1, sequence_number=0), replace(e0, sequence_number=1)]
    with pytest.raises(LedgerReplayError):
        Ledger.replay(opening, reordered)


def test_ledger_external_events_and_conservation():
    opening = (acct("a-x", "x", 100, credit=50), acct("a-y", "y", 0))
    accounts = {a.account_id: a for a in opening}
    meta = lambda seq: dict(at=T0, event_id=f"x-{seq}", sequence_number=seq, simulation_id="sim", correlation_id="c", causation_id=None)
    events = [settle(pay("p0", "x", "y", 130), accounts, 0, credit=True)]
    assert accounts["a-x"].intraday_credit_used_minor == 30
    accounts["a-x"], ev = adjustment_event(accounts["a-x"], 40, "injection", **meta(1))
    events.append(ev)
    accounts["a-x"], ev = credit_repayment_event(accounts["a-x"], **meta(2))
    events.append(ev)
    accounts["a-x"], ev = credit_limit_event(accounts["a-x"], 10, "haircut shock", **meta(3))
    events.append(ev)
    ledger = Ledger.replay(opening, events)
    assert ledger.account("a-x").intraday_credit_used_minor == 0
    assert ledger.account("a-x").ledger_balance_minor == 10
    assert ledger.account("a-x").credit_limit_minor == 10
    assert ledger.total_ledger_minor() == ledger.opening_total_minor + ledger.external_net_flow_minor


def test_credit_limit_cannot_be_cut_below_usage():
    a = replace(acct("a-x", "x", 0, credit=100), intraday_credit_used_minor=80)
    with pytest.raises(ValueError):
        credit_limit_event(a, 50, "shock", at=T0, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c", causation_id=None)


@settings(max_examples=60, deadline=None)
@given(
    balances=st.lists(st.integers(0, 10_000), min_size=3, max_size=6),
    flows=st.lists(st.tuples(st.integers(0, 5), st.integers(0, 5), st.integers(1, 5_000)), max_size=60),
)
def test_property_random_payment_streams_conserve_cash_and_replay(balances, flows):
    """No account overspends, no payment double-settles, replay reproduces live state exactly."""
    n = len(balances)
    opening = tuple(acct(f"a-b{i}", f"b{i}", bal) for i, bal in enumerate(balances))
    accounts = {a.account_id: a for a in opening}
    events, settled = [], set()
    store = EventStore()
    for k, (s, r, amount) in enumerate(flows):
        s, r = s % n, r % n
        if s == r:
            continue
        p = pay(f"p{k}", f"b{s}", f"b{r}", amount)
        if accounts[p.sender_account_id].cash_available_minor < amount:
            with pytest.raises(ValueError):
                settle(p, dict(accounts), len(events))
            continue
        ev = settle(p, accounts, len(events))
        assert p.payment_id not in settled
        settled.add(p.payment_id)
        events.append(ev)
        assert all(a.ledger_balance_minor >= 0 for a in accounts.values())
    store.append_many(events)
    replayed = Ledger.replay(opening, store.events("sim"))
    assert replayed.state_hash() == Ledger(accounts.values()).state_hash()
    assert replayed.total_ledger_minor() == sum(balances)
    assert store.verify_chain("sim").valid
