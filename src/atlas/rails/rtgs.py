"""Gross, one-payment-at-a-time settlement reference model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from atlas.domain import PaymentInstruction, SettlementAccount, SettlementResult

from .base import AdmissionStatus, OperatingSchedule, PaymentRail, RailAdmission, RailParticipant


@dataclass(frozen=True, slots=True)
class RTGSProcessResult:
    settlements: tuple[SettlementResult, ...]
    remaining_queue: tuple[PaymentInstruction, ...]
    admissions: tuple[RailAdmission, ...]


class RTGSRail(PaymentRail):
    """A configurable gross-settlement archetype; it is not a live network adapter."""

    def __init__(
        self,
        rail_id: str,
        currency: str,
        participants: tuple[RailParticipant, ...],
        schedule: OperatingSchedule,
        *,
        allow_intraday_credit: bool = False,
    ) -> None:
        super().__init__(rail_id, currency, participants)
        if not isinstance(schedule, OperatingSchedule):
            raise TypeError("schedule must be an OperatingSchedule")
        if not isinstance(allow_intraday_credit, bool):
            raise TypeError("allow_intraday_credit must be a bool")
        self.schedule = schedule
        self.allow_intraday_credit = allow_intraday_credit

    def admit(
        self,
        payment: PaymentInstruction,
        sender: SettlementAccount | None,
        receiver: SettlementAccount | None,
        *,
        at: datetime,
        seen_instruction_ids: frozenset[str] = frozenset(),
        service_available: bool = True,
    ) -> RailAdmission:
        reason = self.common_rejection(payment, sender, receiver, at, seen_instruction_ids)
        if reason:
            return RailAdmission(AdmissionStatus.REJECTED, payment.payment_id, reason)
        if not service_available:
            return RailAdmission(AdmissionStatus.REJECTED, payment.payment_id, "rail service is unavailable")
        if not self.schedule.is_open(at):
            return RailAdmission(AdmissionStatus.REJECTED, payment.payment_id, "rail operating window is closed")
        assert sender is not None
        permitted = sender.cash_available_minor + (sender.undrawn_credit_minor if self.allow_intraday_credit else 0)
        if permitted < payment.amount_minor:
            return RailAdmission(AdmissionStatus.QUEUED, payment.payment_id, "insufficient permitted settlement resources")
        return RailAdmission(AdmissionStatus.ACCEPTED, payment.payment_id, "eligible for gross settlement")

    def process_queue(
        self,
        payments: tuple[PaymentInstruction, ...] | list[PaymentInstruction],
        accounts: Mapping[str, SettlementAccount],
        *,
        at: datetime,
        simulation_id: str,
        sequence_number_start: int = 0,
        seen_instruction_ids: frozenset[str] = frozenset(),
        service_available: bool = True,
    ) -> RTGSProcessResult:
        if not isinstance(sequence_number_start, int) or isinstance(sequence_number_start, bool) or sequence_number_start < 0:
            raise ValueError("sequence number start must be a non-negative integer")
        if not self.schedule.is_open(at) or not service_available:
            admissions = tuple(
                RailAdmission(AdmissionStatus.QUEUED, item.payment_id, "rail unavailable; payment remains queued")
                for item in payments
            )
            return RTGSProcessResult((), tuple(payments), admissions)
        ordered = sorted(
            payments,
            key=lambda item: (-item.priority, item.due_at.astimezone(UTC), item.created_at.astimezone(UTC), item.payment_id),
        )
        current_accounts = dict(accounts)
        settlements: list[SettlementResult] = []
        remaining: list[PaymentInstruction] = []
        admissions: list[RailAdmission] = []
        observed = set(seen_instruction_ids)
        for payment in ordered:
            sender = current_accounts.get(payment.sender_account_id)
            receiver = current_accounts.get(payment.receiver_account_id)
            admission = self.admit(
                payment, sender, receiver, at=at, seen_instruction_ids=frozenset(observed), service_available=True
            )
            admissions.append(admission)
            observed.update((payment.instruction_id, payment.end_to_end_id))
            if admission.status == AdmissionStatus.QUEUED:
                remaining.append(payment)
                continue
            if admission.status == AdmissionStatus.REJECTED:
                continue
            assert sender is not None and receiver is not None
            try:
                result = self.settle_one(
                    payment,
                    sender,
                    receiver,
                    at=at,
                    event_id=f"{self.rail_id}:{payment.payment_id}:{sequence_number_start + len(settlements)}",
                    sequence_number=sequence_number_start + len(settlements),
                    simulation_id=simulation_id,
                    allow_intraday_credit=self.allow_intraday_credit,
                )
            except ValueError as exc:
                if "insufficient" in str(exc):
                    remaining.append(payment)
                    admissions[-1] = RailAdmission(AdmissionStatus.QUEUED, payment.payment_id, str(exc))
                    continue
                raise
            settlements.append(result)
            current_accounts[sender.account_id] = result.sender_account
            current_accounts[receiver.account_id] = result.receiver_account
        return RTGSProcessResult(tuple(settlements), tuple(remaining), tuple(admissions))


__all__ = ["RTGSProcessResult", "RTGSRail"]
