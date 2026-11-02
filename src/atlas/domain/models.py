"""Typed domain records with explicit units and lifecycle semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class InstitutionType(StrEnum):
    COMMERCIAL_BANK = "commercial_bank"
    INVESTMENT_BANK = "investment_bank"
    CORRESPONDENT_BANK = "correspondent_bank"
    CENTRAL_BANK_MODEL = "central_bank_model"
    PAYMENT_INSTITUTION = "payment_institution"
    CLEARING_PARTICIPANT = "clearing_participant"


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


def transition_payment(
    payment: PaymentInstruction,
    target: PaymentStatus,
    *,
    at: datetime | None = None,
) -> PaymentInstruction:
    """Return a new instruction in the target state, enforcing modeled transitions."""
    if target not in _PAYMENT_TRANSITIONS[payment.status]:
        raise ValueError(f"invalid payment transition: {payment.status} -> {target}")
    return PaymentInstruction(
        payment_id=payment.payment_id,
        sender_institution_id=payment.sender_institution_id,
        receiver_institution_id=payment.receiver_institution_id,
        sender_account_id=payment.sender_account_id,
        receiver_account_id=payment.receiver_account_id,
        payment_rail_id=payment.payment_rail_id,
        currency=payment.currency,
        amount_minor=payment.amount_minor,
        priority=payment.priority,
        created_at=payment.created_at,
        due_at=payment.due_at,
        status=target,
        settlement_at=(at if target == PaymentStatus.SETTLED else payment.settlement_at),
    )


@dataclass(frozen=True, slots=True)
class Institution:
    institution_id: str
    institution_name: str
    institution_type: InstitutionType
    jurisdiction: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.institution_id.strip() or not self.institution_name.strip():
            raise ValueError("institution id and name are required")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class SettlementAccount:
    """Account ledger values are integer minor units in the account currency."""

    account_id: str
    institution_id: str
    payment_rail_id: str
    currency: str
    ledger_balance_minor: int
    reserved_balance_minor: int = 0
    credit_limit_minor: int = 0
    intraday_credit_used_minor: int = 0
    status: AccountStatus = AccountStatus.ACTIVE

    def __post_init__(self) -> None:
        if not all((self.account_id, self.institution_id, self.payment_rail_id)):
            raise ValueError("account, institution, and rail ids are required")
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError("currency must be a three-letter uppercase code")
        values = (self.ledger_balance_minor, self.reserved_balance_minor, self.credit_limit_minor, self.intraday_credit_used_minor)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise TypeError("account amounts must be integer minor units")
        if any(value < 0 for value in values):
            raise ValueError("account amounts must be non-negative integer minor units")
        if self.reserved_balance_minor > self.ledger_balance_minor + self.intraday_credit_used_minor:
            raise ValueError("reserved balance exceeds funded ledger resources")
        if self.intraday_credit_used_minor > self.credit_limit_minor:
            raise ValueError("intraday credit usage exceeds configured limit")

    @property
    def available_balance_minor(self) -> int:
        """Spendable simulated resources, net of reservations and credit already used."""
        return self.ledger_balance_minor - self.reserved_balance_minor + self.credit_limit_minor - self.intraday_credit_used_minor


@dataclass(frozen=True, slots=True)
class PaymentInstruction:
    payment_id: str
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
    settlement_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all((self.payment_id, self.sender_institution_id, self.receiver_institution_id, self.sender_account_id, self.receiver_account_id, self.payment_rail_id)):
            raise ValueError("payment and participant/account/rail ids are required")
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("payment amount must be integer minor units")
        if self.amount_minor <= 0:
            raise ValueError("payment amount must be positive integer minor units")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("payment priority must be an integer")
        if self.priority < 0:
            raise ValueError("payment priority must be non-negative")
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError("currency must be a three-letter uppercase code")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.due_at, "due_at")
        if self.settlement_at is not None:
            _require_aware(self.settlement_at, "settlement_at")
            if self.status != PaymentStatus.SETTLED:
                raise ValueError("settlement timestamp is only valid for a settled payment")
        if self.status == PaymentStatus.SETTLED and self.settlement_at is None:
            raise ValueError("settled payment requires settlement timestamp")
        if self.settlement_at is not None and self.settlement_at < self.created_at:
            raise ValueError("settlement timestamp cannot precede payment creation")


@dataclass(frozen=True, slots=True)
class FinancialEvent:
    """Immutable event envelope; payload encoding and durable storage come later."""

    event_id: str
    event_type: str
    aggregate_id: str
    aggregate_type: str
    event_at: datetime
    sequence_number: int
    simulation_id: str
    correlation_id: str
    causation_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not all((self.event_id, self.event_type, self.aggregate_id, self.aggregate_type, self.simulation_id, self.correlation_id)):
            raise ValueError("event identifiers and types are required")
        _require_aware(self.event_at, "event_at")
        if not isinstance(self.sequence_number, int) or isinstance(self.sequence_number, bool) or not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise TypeError("event sequence and schema version must be integers")
        if self.sequence_number < 0 or self.schema_version <= 0:
            raise ValueError("event sequence must be non-negative and schema version positive")
