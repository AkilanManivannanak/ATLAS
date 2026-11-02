from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from atlas.domain import (
    AccountStatus,
    FinancialEvent,
    Institution,
    InstitutionType,
    PaymentInstruction,
    PaymentStatus,
    SettlementAccount,
    transition_payment,
)

NOW = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)


def payment(**changes):
    fields = dict(
        payment_id="p-1",
        sender_institution_id="bank-a",
        receiver_institution_id="bank-b",
        sender_account_id="acct-a",
        receiver_account_id="acct-b",
        payment_rail_id="rail-rtgs-model",
        currency="USD",
        amount_minor=1250,
        priority=1,
        created_at=NOW,
        due_at=NOW,
    )
    fields.update(changes)
    return PaymentInstruction(**fields)


def test_account_available_balance_uses_integer_minor_units_and_reservations():
    account = SettlementAccount("a", "bank", "rail", "USD", 10_000, 2_000, 5_000, 1_000)
    assert account.available_balance_minor == 12_000


def test_account_rejects_credit_usage_above_limit():
    with pytest.raises(ValueError, match="credit usage"):
        SettlementAccount("a", "bank", "rail", "USD", 10_000, credit_limit_minor=5, intraday_credit_used_minor=6)


def test_account_rejects_non_uppercase_currency():
    with pytest.raises(ValueError, match="currency"):
        SettlementAccount("a", "bank", "rail", "usd", 100)


def test_institution_requires_aware_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        Institution("bank", "Bank", InstitutionType.COMMERCIAL_BANK, "US", datetime(2026, 1, 1))


def test_payment_requires_positive_integer_minor_units():
    with pytest.raises(ValueError, match="positive"):
        payment(amount_minor=0)


def test_payment_requires_timezone_aware_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        payment(created_at=datetime(2026, 1, 1))


def test_payment_lifecycle_reaches_settled_and_preserves_finality():
    item = payment()
    for status in (
        PaymentStatus.VALIDATED,
        PaymentStatus.QUEUED,
        PaymentStatus.ELIGIBILITY_CHECKED,
        PaymentStatus.RELEASED,
        PaymentStatus.SETTLEMENT_PENDING,
    ):
        item = transition_payment(item, status)
    item = transition_payment(item, PaymentStatus.SETTLED, at=NOW)
    assert item.status is PaymentStatus.SETTLED
    assert item.settlement_at == NOW
    with pytest.raises(ValueError, match="invalid payment transition"):
        transition_payment(item, PaymentStatus.QUEUED)


def test_payment_rejects_settlement_timestamp_before_settled_state():
    with pytest.raises(ValueError, match="only valid"):
        payment(settlement_at=NOW)


def test_records_are_immutable():
    account = SettlementAccount("a", "bank", "rail", "USD", 100)
    with pytest.raises(FrozenInstanceError):
        account.ledger_balance_minor = 0


def test_event_requires_aware_timestamp_and_positive_schema_version():
    event = FinancialEvent("e1", "PaymentCreated", "p1", "payment", NOW, 0, "sim1", "c1")
    assert event.schema_version == 1
    with pytest.raises(ValueError, match="schema version"):
        FinancialEvent("e2", "PaymentCreated", "p1", "payment", NOW, 0, "sim1", "c1", schema_version=0)


def test_float_is_rejected_for_authoritative_amount():
    with pytest.raises(TypeError, match="integer minor units"):
        payment(amount_minor=12.5)


def test_settlement_cannot_precede_creation():
    with pytest.raises(ValueError, match="cannot precede"):
        payment(status=PaymentStatus.SETTLED, settlement_at=datetime(2026, 1, 4, tzinfo=timezone.utc))
