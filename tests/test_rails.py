from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from atlas.domain import PaymentInstruction, PaymentStatus, SettlementAccount
from atlas.rails import (
    AdmissionStatus,
    FedNowCycleConfig,
    FedNowRail,
    LiquiditySavingRail,
    OperatingSchedule,
    RailParticipant,
    RTGSRail,
    RTPRail,
)
from atlas.rails.rules import RAIL_RULES


NOW = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
PARTICIPANTS = (RailParticipant("bank-a", "USD"), RailParticipant("bank-b", "USD"))


def account(account_id, institution_id, balance, rail_id, **changes):
    return SettlementAccount(
        account_id=account_id,
        institution_id=institution_id,
        payment_rail_id=rail_id,
        currency="USD",
        ledger_balance_minor=balance,
        **changes,
    )


def payment(payment_id, rail_id, sender_id="bank-a", receiver_id="bank-b", sender_account_id="acct-a", receiver_account_id="acct-b", amount=100, **changes):
    fields = dict(
        payment_id=payment_id,
        end_to_end_id=f"e2e-{payment_id}",
        instruction_id=f"instruction-{payment_id}",
        sender_institution_id=sender_id,
        receiver_institution_id=receiver_id,
        sender_account_id=sender_account_id,
        receiver_account_id=receiver_account_id,
        payment_rail_id=rail_id,
        currency="USD",
        amount_minor=amount,
        priority=1,
        created_at=NOW,
        due_at=NOW + timedelta(minutes=5),
    )
    fields.update(changes)
    return PaymentInstruction(**fields)


def fedwire_schedule(holidays=frozenset()):
    return OperatingSchedule("America/New_York", time(21), time(19), (0, 1, 2, 3, 4), holidays)


def test_overnight_schedule_respects_service_day_weekends_and_holidays():
    schedule = fedwire_schedule(frozenset({date(2026, 1, 6)}))
    assert schedule.is_open(datetime(2026, 1, 4, 21, 30, tzinfo=ZoneInfo("America/New_York")))
    assert not schedule.is_open(datetime(2026, 1, 5, 20, 0, tzinfo=ZoneInfo("America/New_York")))
    assert not schedule.is_open(datetime(2026, 1, 5, 21, 30, tzinfo=ZoneInfo("America/New_York")))
    with pytest.raises(ValueError, match="timezone-aware"):
        schedule.is_open(datetime(2026, 1, 5, 12))


def test_rtgs_queues_insufficient_cash_then_settles_by_priority_and_draws_only_configured_credit():
    rail = RTGSRail("rtgs-model", "USD", PARTICIPANTS, fedwire_schedule(), allow_intraday_credit=True)
    sender = account("acct-a", "bank-a", 50, "rtgs-model", credit_limit_minor=100)
    receiver = account("acct-b", "bank-b", 0, "rtgs-model")
    p1 = payment("p1", "rtgs-model", amount=80, priority=4)
    p2 = payment("p2", "rtgs-model", amount=80, priority=2)
    result = rail.process_queue((p2, p1), {"acct-a": sender, "acct-b": receiver}, at=NOW, simulation_id="sim-1")
    assert [item.payment.payment_id for item in result.settlements] == ["p1"]
    assert [item.payment_id for item in result.remaining_queue] == ["p2"]
    first = result.settlements[0]
    assert first.sender_account.ledger_balance_minor == 0
    assert first.sender_account.intraday_credit_used_minor == 30
    assert first.event.payload_json.find('"credit_draw_minor":30') >= 0
    assert result.admissions[0].payment_id == "p1"


def test_rtgs_rejects_wrong_participant_duplicate_and_closed_window():
    rail = RTGSRail("rtgs-model", "USD", PARTICIPANTS, fedwire_schedule())
    sender = account("acct-a", "bank-a", 1_000, "rtgs-model")
    receiver = account("acct-b", "bank-b", 0, "rtgs-model")
    item = payment("p1", "rtgs-model")
    assert rail.admit(item, sender, receiver, at=NOW).status == AdmissionStatus.ACCEPTED
    assert rail.admit(item, sender, receiver, at=NOW, seen_instruction_ids=frozenset({item.instruction_id})).status == AdmissionStatus.REJECTED
    wrong = payment("p2", "unknown-rail")
    assert "rail identifier" in rail.admit(wrong, sender, receiver, at=NOW).reason
    closed = datetime(2026, 1, 5, 20, 0, tzinfo=ZoneInfo("America/New_York"))
    assert rail.admit(item, sender, receiver, at=closed).status == AdmissionStatus.REJECTED


def test_rtgs_credit_is_not_used_unless_explicitly_enabled():
    rail = RTGSRail("rtgs-model", "USD", PARTICIPANTS, fedwire_schedule())
    sender = account("acct-a", "bank-a", 50, "rtgs-model", credit_limit_minor=100)
    receiver = account("acct-b", "bank-b", 0, "rtgs-model")
    item = payment("p1", "rtgs-model", amount=80)
    assert rail.admit(item, sender, receiver, at=NOW).status == AdmissionStatus.QUEUED


def test_rtgs_rejects_invalid_credit_configuration_and_schedule_weekdays():
    with pytest.raises(TypeError, match="allow_intraday_credit"):
        RTGSRail("rtgs-model", "USD", PARTICIPANTS, fedwire_schedule(), allow_intraday_credit=1)
    with pytest.raises(TypeError, match="OperatingSchedule"):
        RTGSRail("rtgs-model", "USD", PARTICIPANTS, None)
    with pytest.raises(ValueError, match="weekdays"):
        OperatingSchedule("America/New_York", time(9), time(17), (True,))


def test_liquidity_cycle_atomically_settles_balanced_obligations_that_cannot_settle_gross():
    rail = LiquiditySavingRail("lsm-model", "USD", PARTICIPANTS)
    accounts = {
        "acct-a": account("acct-a", "bank-a", 0, "lsm-model"),
        "acct-b": account("acct-b", "bank-b", 0, "lsm-model"),
    }
    ab = payment("ab", "lsm-model", amount=100)
    ba = payment("ba", "lsm-model", sender_id="bank-b", receiver_id="bank-a", sender_account_id="acct-b", receiver_account_id="acct-a", amount=100)
    result = rail.process_cycle((ab, ba), accounts, at=NOW, simulation_id="sim-1", event_id="cycle-1", sequence_number=0)
    assert result.batch is not None
    assert [item.status for item in result.batch.payments] == [PaymentStatus.SETTLED, PaymentStatus.SETTLED]
    assert [(item.account_id, item.ledger_balance_minor) for item in result.batch.accounts] == [("acct-a", 0), ("acct-b", 0)]
    assert result.batch.gross_value_minor == 200
    assert result.batch.net_debit_value_minor == 0
    assert result.batch.event.event_type == "LiquiditySavingCycleSettled"


def test_liquidity_cycle_keeps_all_payments_queued_when_any_net_debit_is_unfunded():
    rail = LiquiditySavingRail("lsm-model", "USD", PARTICIPANTS)
    accounts = {
        "acct-a": account("acct-a", "bank-a", 0, "lsm-model"),
        "acct-b": account("acct-b", "bank-b", 0, "lsm-model"),
    }
    item = payment("one-way", "lsm-model", amount=100)
    result = rail.process_cycle((item,), accounts, at=NOW, simulation_id="sim-1", event_id="cycle-1", sequence_number=0)
    assert result.batch is None
    assert result.queued == (item,)
    assert accounts["acct-a"].ledger_balance_minor == 0


def test_liquidity_cycle_rejects_duplicate_or_ineligible_inputs_atomically():
    rail = LiquiditySavingRail("lsm-model", "USD", PARTICIPANTS)
    accounts = {
        "acct-a": account("acct-a", "bank-a", 1_000, "lsm-model"),
        "acct-b": account("acct-b", "bank-b", 0, "lsm-model"),
    }
    item = payment("one", "lsm-model")
    result = rail.process_cycle((item, item), accounts, at=NOW, simulation_id="sim-1", event_id="cycle-1", sequence_number=0)
    assert result.batch is None
    assert result.rejected
    assert accounts["acct-a"].ledger_balance_minor == 1_000


def test_liquidity_cycle_requires_one_settlement_account_per_participant():
    rail = LiquiditySavingRail("lsm-model", "USD", PARTICIPANTS)
    accounts = {
        "acct-a": account("acct-a", "bank-a", 100, "lsm-model"),
        "acct-a-alt": account("acct-a-alt", "bank-a", 100, "lsm-model"),
        "acct-b": account("acct-b", "bank-b", 0, "lsm-model"),
    }
    first = payment("first", "lsm-model", amount=10)
    second = payment("second", "lsm-model", amount=10, sender_account_id="acct-a-alt")
    result = rail.process_cycle((first, second), accounts, at=NOW, simulation_id="sim-1", event_id="cycle", sequence_number=0)
    assert result.batch is None
    assert result.queued == (first, second)
    assert "one settlement account" in result.rejected[0].reason


def test_fednow_is_continuous_and_has_configurable_cycle_day_rollover():
    rail = FedNowRail("fednow-model", "USD", PARTICIPANTS, FedNowCycleConfig())
    assert rail.service_day(datetime(2026, 1, 5, 19, 0, tzinfo=ZoneInfo("America/New_York"))) == date(2026, 1, 5)
    assert rail.service_day(datetime(2026, 1, 5, 19, 1, tzinfo=ZoneInfo("America/New_York"))) == date(2026, 1, 6)
    sender = account("acct-a", "bank-a", 1_000, "fednow-model")
    receiver = account("acct-b", "bank-b", 0, "fednow-model")
    item = payment("instant", "fednow-model")
    assert rail.submit(item, sender, receiver, at=NOW).status == AdmissionStatus.ACCEPTED
    assert rail.submit(item, sender, receiver, at=NOW, service_available=False).status == AdmissionStatus.REJECTED


def test_rtp_uses_its_own_configured_participant_limits_and_immediate_settlement():
    rtp = RTPRail("rtp-model", "USD", (RailParticipant("bank-a", "USD", transaction_limit_minor=99), RailParticipant("bank-b", "USD", transaction_limit_minor=500)))
    sender = account("acct-a", "bank-a", 1_000, "rtp-model")
    receiver = account("acct-b", "bank-b", 0, "rtp-model")
    item = payment("private-instant", "rtp-model", amount=100)
    result = rtp.settle(item, sender, receiver, at=NOW, event_id="rtp-e1", sequence_number=0, simulation_id="sim-1")
    assert result.admission.status == AdmissionStatus.REJECTED
    allowed = payment("private-instant-2", "rtp-model", amount=99)
    result = rtp.settle(allowed, sender, receiver, at=NOW, event_id="rtp-e2", sequence_number=1, simulation_id="sim-1")
    assert result.settlement is not None
    assert result.settlement.payment.status == PaymentStatus.SETTLED


def test_rail_rules_registry_distinguishes_official_facts_from_model_assumptions():
    assert len(RAIL_RULES.rules) == 9
    assert RAIL_RULES.get("atlas.rail.lsm.atomic_net_cycle").basis.value == "simulator_assumption"
    assert RAIL_RULES.get("atlas.rail.fednow.continuous_cycle_source").source.url.startswith("https://www.frbservices.org/")
    expansion = RAIL_RULES.get("atlas.rail.rtgs.announced_operating_day_expansion")
    assert expansion.basis.value == "official_source"
    assert "2028 or 2029" in expansion.summary
