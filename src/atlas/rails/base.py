"""Shared contracts for synthetic payment-rail reference models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from atlas.domain import (
    AccountStatus,
    PaymentInstruction,
    PaymentStatus,
    SettlementAccount,
    SettlementResult,
    settle_cash_transfer,
    transition_payment,
)


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class AdmissionStatus(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RailAdmission:
    status: AdmissionStatus
    payment_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RailParticipant:
    participant_id: str
    currency: str
    eligible: bool = True
    transaction_limit_minor: int | None = None

    def __post_init__(self) -> None:
        if not self.participant_id.strip() or not self.currency.strip():
            raise ValueError("participant id and currency are required")
        if self.currency != self.currency.upper() or len(self.currency) != 3:
            raise ValueError("participant currency must be a three-letter uppercase code")
        if not isinstance(self.eligible, bool):
            raise TypeError("participant eligibility must be a bool")
        if self.transaction_limit_minor is not None and (
            not isinstance(self.transaction_limit_minor, int)
            or isinstance(self.transaction_limit_minor, bool)
            or self.transaction_limit_minor <= 0
        ):
            raise ValueError("participant transaction limit must be positive integer minor units")


@dataclass(frozen=True, slots=True)
class OperatingSchedule:
    """A configurable local-time window; overnight windows are anchored to service date."""

    timezone_name: str
    opening_time: time
    closing_time: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    holidays: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, TypeError) as exc:
            raise ValueError("schedule timezone must be a valid IANA name") from exc
        if self.opening_time.tzinfo is not None or self.closing_time.tzinfo is not None:
            raise ValueError("schedule times must be local wall-clock times without tzinfo")
        if not isinstance(self.weekdays, tuple) or not self.weekdays or any(
            not isinstance(day, int) or isinstance(day, bool) or day not in range(7) for day in self.weekdays
        ):
            raise ValueError("weekdays must be a non-empty tuple of values from 0 through 6")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("weekdays cannot contain duplicates")
        if not isinstance(self.holidays, frozenset) or any(not isinstance(day, date) or isinstance(day, datetime) for day in self.holidays):
            raise ValueError("holidays must be a frozenset of dates")

    def is_open(self, at: datetime) -> bool:
        _instant(at)
        local = at.astimezone(ZoneInfo(self.timezone_name))
        local_time = local.timetz().replace(tzinfo=None)
        if self.opening_time < self.closing_time:
            service_date = local.date()
            in_window = self.opening_time <= local_time < self.closing_time
        else:
            overnight = self.opening_time > self.closing_time
            if not overnight:
                return False
            if local_time >= self.opening_time:
                service_date = local.date() + timedelta(days=1)
                in_window = True
            elif local_time < self.closing_time:
                service_date = local.date()
                in_window = True
            else:
                return False
        return in_window and service_date.weekday() in self.weekdays and service_date not in self.holidays


class PaymentRail:
    """Validation shared by distinct rail algorithms; no live service connectivity."""

    def __init__(self, rail_id: str, currency: str, participants: Iterable[RailParticipant]) -> None:
        if not rail_id.strip() or not currency.strip() or currency != currency.upper() or len(currency) != 3:
            raise ValueError("rail id and three-letter uppercase currency are required")
        items = tuple(participants)
        if len({item.participant_id for item in items}) != len(items):
            raise ValueError("rail participants must be unique")
        if any(item.currency != currency for item in items):
            raise ValueError("participant currency must match rail currency")
        self.rail_id = rail_id
        self.currency = currency
        self.participants = MappingProxyType({item.participant_id: item for item in items})

    def common_rejection(
        self,
        payment: PaymentInstruction,
        sender: SettlementAccount | None,
        receiver: SettlementAccount | None,
        at: datetime,
        seen_instruction_ids: frozenset[str] = frozenset(),
    ) -> str | None:
        _instant(at)
        if payment.payment_rail_id != self.rail_id:
            return "payment rail identifier does not match adapter"
        if payment.currency != self.currency:
            return "payment currency is unsupported"
        if payment.status not in {
            PaymentStatus.CREATED,
            PaymentStatus.VALIDATED,
            PaymentStatus.QUEUED,
            PaymentStatus.ELIGIBILITY_CHECKED,
            PaymentStatus.RELEASED,
            PaymentStatus.SETTLEMENT_PENDING,
        }:
            return "payment is in a terminal or unsupported lifecycle state"
        if _instant(payment.created_at) > _instant(at):
            return "payment creation timestamp is in the future"
        if payment.instruction_id in seen_instruction_ids or payment.end_to_end_id in seen_instruction_ids:
            return "duplicate instruction or end-to-end identifier"
        if sender is None or receiver is None:
            return "settlement account is missing"
        if sender.account_id == receiver.account_id:
            return "sender and receiver accounts must differ"
        if payment.sender_account_id != sender.account_id or payment.receiver_account_id != receiver.account_id:
            return "payment account identifiers do not match supplied accounts"
        if payment.sender_institution_id != sender.institution_id or payment.receiver_institution_id != receiver.institution_id:
            return "payment institution identifiers do not match supplied accounts"
        if sender.payment_rail_id != self.rail_id or receiver.payment_rail_id != self.rail_id:
            return "settlement account rail does not match adapter"
        if sender.currency != self.currency or receiver.currency != self.currency:
            return "settlement account currency is unsupported"
        if sender.account_status != AccountStatus.ACTIVE or receiver.account_status != AccountStatus.ACTIVE:
            return "both settlement accounts must be active"
        for institution_id in (payment.sender_institution_id, payment.receiver_institution_id):
            participant = self.participants.get(institution_id)
            if participant is None or not participant.eligible:
                return f"participant {institution_id!r} is not eligible"
        sender_participant = self.participants[payment.sender_institution_id]
        if sender_participant.transaction_limit_minor is not None and payment.amount_minor > sender_participant.transaction_limit_minor:
            return f"payment exceeds participant {payment.sender_institution_id!r} transaction limit"
        return None

    @staticmethod
    def to_settlement_pending(payment: PaymentInstruction) -> PaymentInstruction:
        allowed = {
            PaymentStatus.CREATED: (PaymentStatus.VALIDATED, PaymentStatus.QUEUED, PaymentStatus.ELIGIBILITY_CHECKED, PaymentStatus.RELEASED, PaymentStatus.SETTLEMENT_PENDING),
            PaymentStatus.VALIDATED: (PaymentStatus.QUEUED, PaymentStatus.ELIGIBILITY_CHECKED, PaymentStatus.RELEASED, PaymentStatus.SETTLEMENT_PENDING),
            PaymentStatus.QUEUED: (PaymentStatus.ELIGIBILITY_CHECKED, PaymentStatus.RELEASED, PaymentStatus.SETTLEMENT_PENDING),
            PaymentStatus.ELIGIBILITY_CHECKED: (PaymentStatus.RELEASED, PaymentStatus.SETTLEMENT_PENDING),
            PaymentStatus.RELEASED: (PaymentStatus.SETTLEMENT_PENDING,),
            PaymentStatus.SETTLEMENT_PENDING: (),
        }
        if payment.status not in allowed:
            raise ValueError(f"terminal or unsupported payment status: {payment.status}")
        result = payment
        for target in allowed[payment.status]:
            result = transition_payment(result, target)
        return result

    def settle_one(
        self,
        payment: PaymentInstruction,
        sender: SettlementAccount,
        receiver: SettlementAccount,
        *,
        at: datetime,
        event_id: str,
        sequence_number: int,
        simulation_id: str,
        allow_intraday_credit: bool = False,
    ) -> SettlementResult:
        pending = self.to_settlement_pending(payment)
        return settle_cash_transfer(
            pending,
            sender,
            receiver,
            settled_at=at,
            event_id=event_id,
            sequence_number=sequence_number,
            simulation_id=simulation_id,
            correlation_id=payment.scenario_id or payment.end_to_end_id,
            allow_intraday_credit=allow_intraday_credit,
        )


__all__ = ["AdmissionStatus", "OperatingSchedule", "PaymentRail", "RailAdmission", "RailParticipant"]
