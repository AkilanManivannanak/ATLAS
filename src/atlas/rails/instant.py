"""Independent continuous instant-payment reference models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from atlas.domain import PaymentInstruction, SettlementAccount, SettlementResult

from .base import AdmissionStatus, PaymentRail, RailAdmission, RailParticipant, _instant


@dataclass(frozen=True, slots=True)
class FedNowCycleConfig:
    timezone_name: str = "America/New_York"
    rollover_time: time = time(19, 1)

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone_name)
        except Exception as exc:
            raise ValueError("cycle timezone must be a valid IANA name") from exc
        if self.rollover_time.tzinfo is not None:
            raise ValueError("cycle rollover must be a local wall-clock time")


@dataclass(frozen=True, slots=True)
class InstantSettlement:
    admission: RailAdmission
    settlement: SettlementResult | None


class FedNowRail(PaymentRail):
    """Continuous instant model with an explicit configurable accounting-cycle rollover."""

    def __init__(
        self,
        rail_id: str,
        currency: str,
        participants: tuple[RailParticipant, ...],
        cycle: FedNowCycleConfig = FedNowCycleConfig(),
    ) -> None:
        super().__init__(rail_id, currency, participants)
        self.cycle = cycle

    def service_day(self, at: datetime) -> date:
        local = _instant(at).astimezone(ZoneInfo(self.cycle.timezone_name))
        return local.date() + timedelta(days=int(local.timetz().replace(tzinfo=None) >= self.cycle.rollover_time))

    def submit(
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
        assert sender is not None
        if sender.cash_available_minor < payment.amount_minor:
            return RailAdmission(AdmissionStatus.REJECTED, payment.payment_id, "instant settlement requires sufficient unreserved cash")
        return RailAdmission(AdmissionStatus.ACCEPTED, payment.payment_id, "eligible for instant cash settlement")

    def settle(
        self,
        payment: PaymentInstruction,
        sender: SettlementAccount,
        receiver: SettlementAccount,
        *,
        at: datetime,
        event_id: str,
        sequence_number: int,
        simulation_id: str,
        seen_instruction_ids: frozenset[str] = frozenset(),
        service_available: bool = True,
    ) -> InstantSettlement:
        admission = self.submit(
            payment, sender, receiver, at=at, seen_instruction_ids=seen_instruction_ids, service_available=service_available
        )
        result = None
        if admission.status == AdmissionStatus.ACCEPTED:
            result = self.settle_one(
                payment, sender, receiver, at=at, event_id=event_id,
                sequence_number=sequence_number, simulation_id=simulation_id,
            )
        return InstantSettlement(admission, result)


class RTPRail(PaymentRail):
    """Independent private instant model with participant-specific configured limits."""

    def __init__(self, rail_id: str, currency: str, participants: tuple[RailParticipant, ...]) -> None:
        super().__init__(rail_id, currency, participants)

    def submit(
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
        assert sender is not None
        if sender.cash_available_minor < payment.amount_minor:
            return RailAdmission(AdmissionStatus.REJECTED, payment.payment_id, "instant settlement requires sufficient unreserved cash")
        return RailAdmission(AdmissionStatus.ACCEPTED, payment.payment_id, "eligible under configured private-rail limits")

    def settle(
        self,
        payment: PaymentInstruction,
        sender: SettlementAccount,
        receiver: SettlementAccount,
        *,
        at: datetime,
        event_id: str,
        sequence_number: int,
        simulation_id: str,
        seen_instruction_ids: frozenset[str] = frozenset(),
        service_available: bool = True,
    ) -> InstantSettlement:
        admission = self.submit(
            payment, sender, receiver, at=at, seen_instruction_ids=seen_instruction_ids, service_available=service_available
        )
        settlement = None
        if admission.status == AdmissionStatus.ACCEPTED:
            settlement = self.settle_one(
                payment, sender, receiver, at=at, event_id=event_id,
                sequence_number=sequence_number, simulation_id=simulation_id,
            )
        return InstantSettlement(admission, settlement)


__all__ = ["FedNowCycleConfig", "FedNowRail", "InstantSettlement", "RTPRail"]
