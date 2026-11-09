"""Typed financial domain records and explicit simulator accounting operations."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from .money import CurrencySpec


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _instant(value: datetime) -> datetime:
    """Normalize aware timestamps before comparing ambiguous local clock times."""
    return value.astimezone(UTC)


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_minor_units(*values: int) -> None:
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise TypeError("monetary amounts must be integer minor units")


class InstitutionType(StrEnum):
    COMMERCIAL_BANK = "commercial_bank"
    INVESTMENT_BANK = "investment_bank"
    CORRESPONDENT_BANK = "correspondent_bank"
    CENTRAL_BANK_MODEL = "central_bank_model"
    PAYMENT_INSTITUTION = "payment_institution"
    CLEARING_PARTICIPANT = "clearing_participant"


class InstitutionOperationalStatus(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class PaymentStatus(StrEnum):
    CREATED = "created"
    VALIDATED = "validated"
    QUEUED = "queued"
    ELIGIBILITY_CHECKED = "eligibility_checked"
    RELEASED = "released"
    SETTLEMENT_PENDING = "settlement_pending"
    SETTLED = "settled"
    REJECTED = "rejected"
    RETURNED = "returned"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


_PAYMENT_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.CREATED: frozenset({PaymentStatus.VALIDATED, PaymentStatus.REJECTED, PaymentStatus.CANCELLED}),
    PaymentStatus.VALIDATED: frozenset({PaymentStatus.QUEUED, PaymentStatus.REJECTED, PaymentStatus.CANCELLED}),
    PaymentStatus.QUEUED: frozenset({PaymentStatus.ELIGIBILITY_CHECKED, PaymentStatus.CANCELLED, PaymentStatus.EXPIRED, PaymentStatus.FAILED}),
    PaymentStatus.ELIGIBILITY_CHECKED: frozenset({PaymentStatus.RELEASED, PaymentStatus.QUEUED, PaymentStatus.REJECTED, PaymentStatus.EXPIRED}),
    PaymentStatus.RELEASED: frozenset({PaymentStatus.SETTLEMENT_PENDING, PaymentStatus.FAILED}),
    PaymentStatus.SETTLEMENT_PENDING: frozenset({PaymentStatus.SETTLED, PaymentStatus.FAILED}),
    PaymentStatus.SETTLED: frozenset(),
    PaymentStatus.REJECTED: frozenset(),
    PaymentStatus.RETURNED: frozenset(),
    PaymentStatus.CANCELLED: frozenset(),
    PaymentStatus.EXPIRED: frozenset(),
    PaymentStatus.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Institution:
    institution_id: str
    institution_name: str
    institution_type: InstitutionType
    jurisdiction: str
    liquidity_policy_id: str
    funding_policy_id: str
    risk_profile_id: str
    operational_status: InstitutionOperationalStatus
    created_at: datetime
    simulation_agent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.institution_type, InstitutionType):
            raise TypeError("institution_type must be an InstitutionType value")
        if not isinstance(self.operational_status, InstitutionOperationalStatus):
            raise TypeError("operational_status must be an InstitutionOperationalStatus value")
        for field_name in (
            "institution_id", "institution_name", "jurisdiction", "liquidity_policy_id", "funding_policy_id", "risk_profile_id"
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.simulation_agent_id is not None:
            _require_text(self.simulation_agent_id, "simulation_agent_id")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class SettlementAccount:
    """Cash and credit are separate; the available balance is derived in minor units."""

    account_id: str
    institution_id: str
    payment_rail_id: str
    currency: str
    ledger_balance_minor: int
    reserved_balance_minor: int = 0
    credit_limit_minor: int = 0
    intraday_credit_used_minor: int = 0
    account_status: AccountStatus = AccountStatus.ACTIVE
    last_reconciled_at: datetime | None = None
    availability_rule_id: str = "atlas.account.available_resources"
    availability_rule_version: int = 1

    def __post_init__(self) -> None:
        for field_name in ("account_id", "institution_id", "payment_rail_id", "availability_rule_id"):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.account_status, AccountStatus):
            raise TypeError("account_status must be an AccountStatus value")
        CurrencySpec(self.currency, 0)
        values = (self.ledger_balance_minor, self.reserved_balance_minor, self.credit_limit_minor, self.intraday_credit_used_minor)
        _require_minor_units(*values)
        if any(value < 0 for value in values):
            raise ValueError("account amounts must be non-negative integer minor units")
        if self.reserved_balance_minor > self.ledger_balance_minor:
            raise ValueError("reserved balance cannot exceed ledger cash")
        if self.intraday_credit_used_minor > self.credit_limit_minor:
            raise ValueError("intraday credit usage exceeds configured limit")
        if not isinstance(self.availability_rule_version, int) or isinstance(self.availability_rule_version, bool) or self.availability_rule_version <= 0:
            raise ValueError("availability rule version must be a positive integer")
        if self.last_reconciled_at is not None:
            _require_aware(self.last_reconciled_at, "last_reconciled_at")

    @property
    def cash_available_minor(self) -> int:
        """Ledger cash not reserved for another modeled obligation."""
        return self.ledger_balance_minor - self.reserved_balance_minor

    @property
    def undrawn_credit_minor(self) -> int:
        return self.credit_limit_minor - self.intraday_credit_used_minor

    @property
    def available_balance_minor(self) -> int:
        """Cash available plus undrawn account credit; facilities are not booked as cash."""
        return self.cash_available_minor + self.undrawn_credit_minor


@dataclass(frozen=True, slots=True)
class PaymentInstruction:
    payment_id: str
    end_to_end_id: str
    instruction_id: str
    sender_institution_id: str
    receiver_institution_id: str
    sender_account_id: str
    receiver_account_id: str
    payment_rail_id: str
    currency: str
    amount_minor: int
    priority: int
    created_at: datetime
    due_at: datetime
    status: PaymentStatus = PaymentStatus.CREATED
    requested_execution_at: datetime | None = None
    settlement_at: datetime | None = None
    source_message_id: str | None = None
    message_schema_version: str | None = None
    scenario_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "payment_id", "end_to_end_id", "instruction_id", "sender_institution_id", "receiver_institution_id",
            "sender_account_id", "receiver_account_id", "payment_rail_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.source_message_id is not None:
            _require_text(self.source_message_id, "source_message_id")
        if self.message_schema_version is not None:
            _require_text(self.message_schema_version, "message_schema_version")
        if (self.source_message_id is None) != (self.message_schema_version is None):
            raise ValueError("source message id and schema version must be supplied together")
        if self.scenario_id is not None:
            _require_text(self.scenario_id, "scenario_id")
        _require_minor_units(self.amount_minor)
        if self.amount_minor <= 0:
            raise ValueError("payment amount must be positive integer minor units")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("payment priority must be an integer")
        if self.priority < 0:
            raise ValueError("payment priority must be non-negative")
        if not isinstance(self.status, PaymentStatus):
            raise TypeError("status must be a PaymentStatus value")
        CurrencySpec(self.currency, 0)
        _require_aware(self.created_at, "created_at")
        _require_aware(self.due_at, "due_at")
        if _instant(self.due_at) < _instant(self.created_at):
            raise ValueError("due timestamp cannot precede payment creation")
        if self.requested_execution_at is not None:
            _require_aware(self.requested_execution_at, "requested_execution_at")
            if _instant(self.requested_execution_at) < _instant(self.created_at):
                raise ValueError("requested execution cannot precede payment creation")
        if self.settlement_at is not None:
            _require_aware(self.settlement_at, "settlement_at")
            if self.status != PaymentStatus.SETTLED:
                raise ValueError("settlement timestamp is only valid for a settled payment")
            if _instant(self.settlement_at) < _instant(self.created_at):
                raise ValueError("settlement timestamp cannot precede payment creation")
        if self.status == PaymentStatus.SETTLED and self.settlement_at is None:
            raise ValueError("settled payment requires settlement timestamp")


@dataclass(frozen=True, slots=True)
class CollateralAsset:
    collateral_id: str
    owner_institution_id: str
    asset_type: str
    nominal_value_minor: int
    market_value_minor: int
    haircut_basis_points: int
    currency: str
    encumbered_amount_minor: int
    eligibility_profile_id: str
    mobilization_delay_seconds: int
    valuation_at: datetime
    settlement_account_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("collateral_id", "owner_institution_id", "asset_type", "eligibility_profile_id"):
            _require_text(getattr(self, field_name), field_name)
        CurrencySpec(self.currency, 0)
        _require_minor_units(self.nominal_value_minor, self.market_value_minor, self.encumbered_amount_minor)
        if min(self.nominal_value_minor, self.market_value_minor, self.encumbered_amount_minor) < 0:
            raise ValueError("collateral values must be non-negative integer minor units")
        if not isinstance(self.haircut_basis_points, int) or isinstance(self.haircut_basis_points, bool) or not 0 <= self.haircut_basis_points <= 10_000:
            raise ValueError("haircut must be integer basis points from 0 through 10000")
        if not isinstance(self.mobilization_delay_seconds, int) or isinstance(self.mobilization_delay_seconds, bool) or self.mobilization_delay_seconds < 0:
            raise ValueError("mobilization delay must be non-negative integer seconds")
        _require_aware(self.valuation_at, "valuation_at")
        if self.settlement_account_id is not None:
            _require_text(self.settlement_account_id, "settlement_account_id")

    @property
    def eligible_value_minor(self) -> int:
        """Haircut-adjusted value, rounded down to the currency's minor unit."""
        return self.market_value_minor * (10_000 - self.haircut_basis_points) // 10_000

    @property
    def available_eligible_value_minor(self) -> int:
        return max(0, self.eligible_value_minor - self.encumbered_amount_minor)

    @property
    def collateral_shortfall_minor(self) -> int:
        """Amount by which existing pledges exceed current haircut-adjusted value."""
        return max(0, self.encumbered_amount_minor - self.eligible_value_minor)


@dataclass(frozen=True, slots=True)
class FundingFacility:
    facility_id: str
    institution_id: str
    facility_type: str
    currency: str
    maximum_capacity_minor: int
    committed_capacity_minor: int
    drawn_amount_minor: int
    repayable_amount_minor: int
    annual_rate_basis_points: int
    collateral_requirements_id: str | None
    operating_hours_id: str
    maturity_at: datetime | None
    eligibility_status: bool

    def __post_init__(self) -> None:
        for field_name in ("facility_id", "institution_id", "facility_type", "operating_hours_id"):
            _require_text(getattr(self, field_name), field_name)
        CurrencySpec(self.currency, 0)
        _require_minor_units(self.maximum_capacity_minor, self.committed_capacity_minor, self.drawn_amount_minor, self.repayable_amount_minor)
        if min(self.maximum_capacity_minor, self.committed_capacity_minor, self.drawn_amount_minor, self.repayable_amount_minor) < 0:
            raise ValueError("facility amounts must be non-negative integer minor units")
        if self.committed_capacity_minor > self.maximum_capacity_minor:
            raise ValueError("committed capacity cannot exceed maximum capacity")
        if self.drawn_amount_minor > self.committed_capacity_minor:
            raise ValueError("drawn amount cannot exceed committed capacity")
        if self.repayable_amount_minor > self.drawn_amount_minor:
            raise ValueError("repayable amount cannot exceed drawn amount")
        if not isinstance(self.annual_rate_basis_points, int) or isinstance(self.annual_rate_basis_points, bool) or self.annual_rate_basis_points < 0:
            raise ValueError("annual rate must be non-negative integer basis points")
        if not isinstance(self.eligibility_status, bool):
            raise TypeError("eligibility_status must be a boolean")
        if self.collateral_requirements_id is not None:
            _require_text(self.collateral_requirements_id, "collateral_requirements_id")
        if self.maturity_at is not None:
            _require_aware(self.maturity_at, "maturity_at")

    @property
    def available_capacity_minor(self) -> int:
        return self.committed_capacity_minor - self.drawn_amount_minor


@dataclass(frozen=True, slots=True)
class FinancialEvent:
    """Immutable event envelope with a JSON-object payload stored as canonical text."""

    event_id: str
    event_type: str
    aggregate_id: str
    aggregate_type: str
    event_at: datetime
    ingested_at: datetime
    sequence_number: int
    correlation_id: str
    simulation_id: str
    payload_json: str = "{}"
    causation_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field_name in ("event_id", "event_type", "aggregate_id", "aggregate_type", "correlation_id", "simulation_id"):
            _require_text(getattr(self, field_name), field_name)
        _require_aware(self.event_at, "event_at")
        _require_aware(self.ingested_at, "ingested_at")
        if _instant(self.ingested_at) < _instant(self.event_at):
            raise ValueError("ingestion timestamp cannot precede event timestamp")
        if not isinstance(self.sequence_number, int) or isinstance(self.sequence_number, bool) or self.sequence_number < 0:
            raise ValueError("event sequence number must be a non-negative integer")
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version <= 0:
            raise ValueError("event schema version must be a positive integer")
        def reject_float(_: str) -> None:
            raise ValueError("event payload cannot contain floating-point numbers")

        def reject_nonstandard_constant(_: str) -> None:
            raise ValueError("event payload cannot contain non-standard numeric constants")

        try:
            payload = json.loads(self.payload_json, parse_float=reject_float, parse_constant=reject_nonstandard_constant)
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("event payload must be valid JSON text") from exc
        if not isinstance(payload, dict):
            raise ValueError("event payload must encode a JSON object")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if self.payload_json != canonical:
            raise ValueError("event payload JSON must use canonical key ordering and separators")
        if self.causation_id is not None:
            _require_text(self.causation_id, "causation_id")


@dataclass(frozen=True, slots=True)
class AccountReconciliation:
    account_id: str
    ledger_balance_minor: int
    reserved_balance_minor: int
    cash_available_minor: int
    credit_limit_minor: int
    intraday_credit_used_minor: int
    undrawn_credit_minor: int
    available_resources_minor: int


def reconcile_account(account: SettlementAccount) -> AccountReconciliation:
    """Return the documented resource decomposition and assert its identities."""
    cash_available = account.ledger_balance_minor - account.reserved_balance_minor
    undrawn_credit = account.credit_limit_minor - account.intraday_credit_used_minor
    available = cash_available + undrawn_credit
    if account.ledger_balance_minor != account.reserved_balance_minor + cash_available:
        raise AssertionError("cash ledger reconciliation failed")
    if account.credit_limit_minor != account.intraday_credit_used_minor + undrawn_credit:
        raise AssertionError("credit reconciliation failed")
    if account.available_balance_minor != available:
        raise AssertionError("available resources reconciliation failed")
    return AccountReconciliation(
        account_id=account.account_id,
        ledger_balance_minor=account.ledger_balance_minor,
        reserved_balance_minor=account.reserved_balance_minor,
        cash_available_minor=cash_available,
        credit_limit_minor=account.credit_limit_minor,
        intraday_credit_used_minor=account.intraday_credit_used_minor,
        undrawn_credit_minor=undrawn_credit,
        available_resources_minor=available,
    )


def transition_payment(
    payment: PaymentInstruction,
    target: PaymentStatus,
    *,
    at: datetime | None = None,
) -> PaymentInstruction:
    """Return a new instruction in the target state, enforcing modeled transitions."""
    if target not in _PAYMENT_TRANSITIONS[payment.status]:
        raise ValueError(f"invalid payment transition: {payment.status} -> {target}")
    return replace(payment, status=target, settlement_at=(at if target == PaymentStatus.SETTLED else None))


@dataclass(frozen=True, slots=True)
class SettlementResult:
    payment: PaymentInstruction
    sender_account: SettlementAccount
    receiver_account: SettlementAccount
    event: FinancialEvent


def settle_cash_transfer(
    payment: PaymentInstruction,
    sender_account: SettlementAccount,
    receiver_account: SettlementAccount,
    *,
    settled_at: datetime,
    event_id: str,
    sequence_number: int,
    simulation_id: str,
    correlation_id: str,
    ingested_at: datetime | None = None,
    allow_intraday_credit: bool = False,
) -> SettlementResult:
    """Settle a same-currency, same-rail transfer with an explicit optional credit draw.

    Rail eligibility and operating rules must be checked by the calling rail adapter.
    Credit remains unused unless the caller explicitly opts in; only the exact cash
    shortfall is drawn, and it is recorded in account state and the financial event.
    """
    if payment.status != PaymentStatus.SETTLEMENT_PENDING:
        raise ValueError("only settlement-pending payments can settle")
    if sender_account.account_id == receiver_account.account_id:
        raise ValueError("sender and receiver accounts must differ")
    if payment.sender_account_id != sender_account.account_id or payment.receiver_account_id != receiver_account.account_id:
        raise ValueError("payment account identifiers do not match supplied accounts")
    if payment.sender_institution_id != sender_account.institution_id or payment.receiver_institution_id != receiver_account.institution_id:
        raise ValueError("payment institution identifiers do not match supplied accounts")
    if sender_account.account_status != AccountStatus.ACTIVE or receiver_account.account_status != AccountStatus.ACTIVE:
        raise ValueError("both settlement accounts must be active")
    if sender_account.currency != receiver_account.currency or payment.currency != sender_account.currency:
        raise ValueError("payment and both accounts must use the same currency")
    if sender_account.payment_rail_id != receiver_account.payment_rail_id or payment.payment_rail_id != sender_account.payment_rail_id:
        raise ValueError("payment and both accounts must use the same rail")
    _require_aware(settled_at, "settled_at")
    if _instant(settled_at) < _instant(payment.created_at):
        raise ValueError("settlement timestamp cannot precede payment creation")
    if not isinstance(allow_intraday_credit, bool):
        raise TypeError("allow_intraday_credit must be a bool")
    cash_shortfall = max(0, payment.amount_minor - sender_account.cash_available_minor)
    credit_draw_minor = cash_shortfall if allow_intraday_credit else 0
    if credit_draw_minor > sender_account.undrawn_credit_minor:
        raise ValueError("insufficient unreserved ledger cash and permitted intraday credit")
    if cash_shortfall and not allow_intraday_credit:
        raise ValueError("insufficient unreserved ledger cash; credit draws are not implicit")

    next_sender = replace(
        sender_account,
        ledger_balance_minor=sender_account.ledger_balance_minor + credit_draw_minor - payment.amount_minor,
        intraday_credit_used_minor=sender_account.intraday_credit_used_minor + credit_draw_minor,
    )
    next_receiver = replace(receiver_account, ledger_balance_minor=receiver_account.ledger_balance_minor + payment.amount_minor)
    next_payment = transition_payment(payment, PaymentStatus.SETTLED, at=settled_at)
    payload = {
        "payment_id": payment.payment_id,
        "currency": payment.currency,
        "amount_minor": payment.amount_minor,
        "sender_account_id": sender_account.account_id,
        "sender_ledger_before_minor": sender_account.ledger_balance_minor,
        "sender_ledger_after_minor": next_sender.ledger_balance_minor,
        "sender_credit_used_before_minor": sender_account.intraday_credit_used_minor,
        "sender_credit_used_after_minor": next_sender.intraday_credit_used_minor,
        "receiver_account_id": receiver_account.account_id,
        "receiver_ledger_before_minor": receiver_account.ledger_balance_minor,
        "receiver_ledger_after_minor": next_receiver.ledger_balance_minor,
        "credit_draw_minor": credit_draw_minor,
    }
    event = FinancialEvent(
        event_id=event_id,
        event_type="PaymentSettled",
        aggregate_id=payment.payment_id,
        aggregate_type="payment",
        event_at=settled_at,
        ingested_at=ingested_at or settled_at,
        sequence_number=sequence_number,
        correlation_id=correlation_id,
        simulation_id=simulation_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )
    reconcile_account(next_sender)
    reconcile_account(next_receiver)
    return SettlementResult(next_payment, next_sender, next_receiver, event)
