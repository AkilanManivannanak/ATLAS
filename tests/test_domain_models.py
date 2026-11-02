from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

import pytest

from atlas.domain import (
    AccountStatus,
    CollateralAsset,
    FinancialEvent,
    FundingFacility,
    Institution,
    InstitutionOperationalStatus,
    InstitutionType,
    PaymentInstruction,
    PaymentStatus,
    SettlementAccount,
    reconcile_account,
    settle_cash_transfer,
    transition_payment,
)

NOW = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)


def institution(institution_id="bank-a", **changes):
    fields = dict(
        institution_id=institution_id,
        institution_name="Bank A",
        institution_type=InstitutionType.COMMERCIAL_BANK,
        jurisdiction="US",
        liquidity_policy_id="liq-default-v1",
        funding_policy_id="fund-default-v1",
        risk_profile_id="risk-moderate-v1",
        operational_status=InstitutionOperationalStatus.ACTIVE,
        created_at=NOW,
    )
    fields.update(changes)
    return Institution(**fields)


def account(account_id, institution_id, balance, **changes):
    fields = dict(
        account_id=account_id,
        institution_id=institution_id,
        payment_rail_id="rail-rtgs-model",
        currency="USD",
        ledger_balance_minor=balance,
    )
    fields.update(changes)
    return SettlementAccount(**fields)


def payment(**changes):
    fields = dict(
        payment_id="p-1",
        end_to_end_id="e2e-1",
        instruction_id="instr-1",
        sender_institution_id="bank-a",
        receiver_institution_id="bank-b",
        sender_account_id="acct-a",
        receiver_account_id="acct-b",
        payment_rail_id="rail-rtgs-model",
        currency="USD",
        amount_minor=1250,
        priority=1,
        created_at=NOW,
        due_at=NOW + timedelta(minutes=5),
    )
    fields.update(changes)
    return PaymentInstruction(**fields)


def test_institution_includes_policies_risk_operational_state_and_agent():
    record = institution(simulation_agent_id="agent-7")
    assert record.liquidity_policy_id == "liq-default-v1"
    assert record.simulation_agent_id == "agent-7"


def test_institution_requires_aware_timestamp_and_policy_ids():
    with pytest.raises(ValueError, match="timezone-aware"):
        institution(created_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="funding_policy_id"):
        institution(funding_policy_id=" ")


def test_account_available_resources_separate_cash_reserves_and_credit():
    item = account("a", "bank", 10_000, reserved_balance_minor=2_000, credit_limit_minor=5_000, intraday_credit_used_minor=1_000)
    assert item.cash_available_minor == 8_000
    assert item.undrawn_credit_minor == 4_000
    assert item.available_balance_minor == 12_000
    result = reconcile_account(item)
    assert result.available_resources_minor == 12_000


def test_account_rejects_credit_usage_above_limit_and_reserves_above_cash():
    with pytest.raises(ValueError, match="credit usage"):
        account("a", "bank", 10_000, credit_limit_minor=5, intraday_credit_used_minor=6)
    with pytest.raises(ValueError, match="reserved balance"):
        account("a", "bank", 100, reserved_balance_minor=101)


def test_account_rejects_non_uppercase_currency_and_non_integer_balance():
    with pytest.raises(ValueError, match="currency"):
        account("a", "bank", 100, currency="usd")
    with pytest.raises(TypeError, match="integer minor units"):
        account("a", "bank", 10.5)


def test_payment_has_full_instruction_provenance_and_aware_timestamps():
    item = payment(source_message_id="msg-4", message_schema_version="pacs.008.001.10", scenario_id="scenario-2")
    assert item.end_to_end_id == "e2e-1"
    assert item.source_message_id == "msg-4"
    with pytest.raises(ValueError, match="timezone-aware"):
        payment(created_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="due timestamp"):
        payment(due_at=NOW - timedelta(seconds=1))


def test_payment_timestamp_validation_uses_absolute_instants_during_dst_fold():
    eastern = ZoneInfo("America/New_York")
    first_0130 = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=0)
    second_0130 = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=1)
    assert payment(created_at=first_0130, due_at=second_0130)
    with pytest.raises(ValueError, match="due timestamp"):
        payment(created_at=second_0130, due_at=first_0130)


def test_payment_rejects_float_and_nonpositive_amounts():
    with pytest.raises(TypeError, match="integer minor units"):
        payment(amount_minor=12.5)
    with pytest.raises(ValueError, match="positive"):
        payment(amount_minor=0)


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


def test_settlement_requires_pending_payment_and_cash_without_implicit_credit_draw():
    item = payment(status=PaymentStatus.SETTLEMENT_PENDING, amount_minor=50)
    sender = account("acct-a", "bank-a", 100, reserved_balance_minor=60, credit_limit_minor=50)
    receiver = account("acct-b", "bank-b", 40)
    with pytest.raises(ValueError, match="insufficient unreserved ledger cash"):
        settle_cash_transfer(item, sender, receiver, settled_at=NOW, event_id="ev-1", sequence_number=0, simulation_id="sim-1", correlation_id="corr-1")


def test_successful_cash_settlement_updates_both_accounts_and_emits_event():
    item = payment(status=PaymentStatus.SETTLEMENT_PENDING, amount_minor=25)
    sender = account("acct-a", "bank-a", 100, reserved_balance_minor=20, credit_limit_minor=50)
    receiver = account("acct-b", "bank-b", 40)
    result = settle_cash_transfer(
        item, sender, receiver, settled_at=NOW, ingested_at=NOW + timedelta(milliseconds=10),
        event_id="ev-1", sequence_number=3, simulation_id="sim-1", correlation_id="corr-1",
    )
    assert result.payment.status is PaymentStatus.SETTLED
    assert result.sender_account.ledger_balance_minor == 75
    assert result.receiver_account.ledger_balance_minor == 65
    assert result.sender_account.available_balance_minor == 105
    payload = json.loads(result.event.payload_json)
    assert payload["amount_minor"] == 25
    assert payload["credit_draw_minor"] == 0
    assert result.event.sequence_number == 3


def test_settlement_checks_identity_rail_currency_status_and_finality():
    item = payment(status=PaymentStatus.SETTLEMENT_PENDING, amount_minor=10)
    sender = account("acct-a", "bank-a", 100)
    receiver = account("acct-b", "bank-b", 50)
    with pytest.raises(ValueError, match="same rail"):
        settle_cash_transfer(item, sender, account("acct-b", "bank-b", 50, payment_rail_id="rail-other"), settled_at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")
    with pytest.raises(ValueError, match="active"):
        settle_cash_transfer(item, sender, account("acct-b", "bank-b", 50, account_status=AccountStatus.FROZEN), settled_at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")
    settled = settle_cash_transfer(item, sender, receiver, settled_at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")
    with pytest.raises(ValueError, match="only settlement-pending"):
        settle_cash_transfer(settled.payment, settled.sender_account, settled.receiver_account, settled_at=NOW, event_id="e2", sequence_number=1, simulation_id="s", correlation_id="c")


def test_collateral_haircut_is_integer_and_available_value_is_conservative():
    asset = CollateralAsset("col-1", "bank-a", "security", 10_000, 10_001, 1_000, "USD", 500, "eligible-v1", 60, NOW)
    assert asset.eligible_value_minor == 9_000
    assert asset.available_eligible_value_minor == 8_500
    with pytest.raises(ValueError, match="basis points"):
        CollateralAsset("col-2", "bank-a", "security", 10, 10, 10_001, "USD", 0, "elig", 0, NOW)


def test_funding_facility_distinguishes_capacity_draw_and_repayable_amount():
    facility = FundingFacility("f-1", "bank-a", "modeled_facility", "USD", 10_000, 8_000, 2_000, 1_000, 500, "collateral-v1", "hours-v1", NOW + timedelta(days=1), True)
    assert facility.available_capacity_minor == 6_000
    with pytest.raises(ValueError, match="committed capacity"):
        FundingFacility("f-2", "bank-a", "modeled_facility", "USD", 100, 101, 0, 0, 0, None, "hours-v1", None, True)


def test_financial_event_validates_payload_and_timestamps():
    event = FinancialEvent("e1", "PaymentCreated", "p1", "payment", NOW, NOW, 0, "c1", "sim1", '{"amount_minor":1}')
    assert event.schema_version == 1
    with pytest.raises(ValueError, match="JSON object"):
        FinancialEvent("e2", "PaymentCreated", "p1", "payment", NOW, NOW, 0, "c1", "sim1", "[]")
    with pytest.raises(ValueError, match="ingestion timestamp"):
        FinancialEvent("e3", "PaymentCreated", "p1", "payment", NOW, NOW - timedelta(seconds=1), 0, "c1", "sim1")


def test_records_are_immutable():
    item = account("a", "bank", 100)
    with pytest.raises(FrozenInstanceError):
        item.ledger_balance_minor = 0


def test_payment_source_message_id_and_schema_version_are_paired():
    with pytest.raises(ValueError, match="supplied together"):
        payment(source_message_id="message-only")


def test_domain_enums_reject_unvalidated_strings():
    with pytest.raises(TypeError, match="InstitutionType"):
        institution(institution_type="commercial_bank")
    with pytest.raises(TypeError, match="AccountStatus"):
        account("a", "bank-a", 10, account_status="active")


def test_financial_event_rejects_floating_point_and_noncanonical_payloads():
    with pytest.raises(ValueError, match="valid JSON"):
        FinancialEvent("e4", "Metric", "a1", "account", NOW, NOW, 0, "c1", "sim1", '{"amount":1.5}')
    with pytest.raises(ValueError, match="canonical"):
        FinancialEvent("e5", "PaymentCreated", "p1", "payment", NOW, NOW, 0, "c1", "sim1", '{ "amount_minor" : 1 }')
