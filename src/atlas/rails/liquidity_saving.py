"""Atomic multilateral netting reference model for queued obligations."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Mapping

from atlas.domain import (
    AccountStatus,
    FinancialEvent,
    PaymentInstruction,
    PaymentStatus,
    SettlementAccount,
    reconcile_account,
    transition_payment,
)

from .base import AdmissionStatus, OperatingSchedule, PaymentRail, RailAdmission, RailParticipant, _instant


@dataclass(frozen=True, slots=True)
class NetSettlementBatch:
    payments: tuple[PaymentInstruction, ...]
    accounts: tuple[SettlementAccount, ...]
    event: FinancialEvent
    gross_value_minor: int
    net_debit_value_minor: int


@dataclass(frozen=True, slots=True)
class LiquidityCycleResult:
    batch: NetSettlementBatch | None
    queued: tuple[PaymentInstruction, ...]
    rejected: tuple[RailAdmission, ...]
    reason: str


class LiquiditySavingRail(PaymentRail):
    """Cycle netting archetype with one settlement account per participant in a cycle."""

    def __init__(
        self,
        rail_id: str,
        currency: str,
        participants: tuple[RailParticipant, ...],
        schedule: OperatingSchedule | None = None,
    ) -> None:
        super().__init__(rail_id, currency, participants)
        self.schedule = schedule

    def process_cycle(
        self,
        payments: tuple[PaymentInstruction, ...] | list[PaymentInstruction],
        accounts: Mapping[str, SettlementAccount],
        *,
        at: datetime,
        simulation_id: str,
        event_id: str,
        sequence_number: int,
        seen_instruction_ids: frozenset[str] = frozenset(),
        service_available: bool = True,
    ) -> LiquidityCycleResult:
        _instant(at)
        if not service_available:
            return LiquidityCycleResult(None, tuple(payments), (), "rail service is unavailable")
        if self.schedule is not None and not self.schedule.is_open(at):
            return LiquidityCycleResult(None, tuple(payments), (), "rail operating window is closed")
        if not payments:
            return LiquidityCycleResult(None, (), (), "cycle is empty")
        seen = set(seen_instruction_ids)
        unique_payment_ids: set[str] = set()
        unique_keys: set[str] = set()
        participant_accounts: dict[str, str] = {}
        rejected: list[RailAdmission] = []
        accepted: list[PaymentInstruction] = []
        for payment in payments:
            sender = accounts.get(payment.sender_account_id)
            receiver = accounts.get(payment.receiver_account_id)
            reason = self.common_rejection(payment, sender, receiver, at, frozenset(seen))
            if payment.payment_id in unique_payment_ids or payment.instruction_id in unique_keys or payment.end_to_end_id in unique_keys:
                reason = "duplicate identifier inside liquidity cycle"
            if reason is None:
                for participant_id, account_id in (
                    (payment.sender_institution_id, payment.sender_account_id),
                    (payment.receiver_institution_id, payment.receiver_account_id),
                ):
                    existing_account = participant_accounts.get(participant_id)
                    if existing_account is not None and existing_account != account_id:
                        reason = "liquidity cycle requires one settlement account per participant"
                        break
            if reason:
                rejected.append(RailAdmission(AdmissionStatus.REJECTED, payment.payment_id, reason))
                continue
            unique_payment_ids.add(payment.payment_id)
            unique_keys.update((payment.instruction_id, payment.end_to_end_id))
            participant_accounts[payment.sender_institution_id] = payment.sender_account_id
            participant_accounts[payment.receiver_institution_id] = payment.receiver_account_id
            accepted.append(payment)
        if rejected:
            return LiquidityCycleResult(None, tuple(payments), tuple(rejected), "cycle rejected atomically because it contains invalid instructions")
        if not accepted:
            return LiquidityCycleResult(None, (), (), "cycle has no eligible instructions")

        deltas: dict[str, int] = {}
        gross_value = 0
        for payment in accepted:
            deltas[payment.sender_account_id] = deltas.get(payment.sender_account_id, 0) - payment.amount_minor
            deltas[payment.receiver_account_id] = deltas.get(payment.receiver_account_id, 0) + payment.amount_minor
            gross_value += payment.amount_minor
        for account_id, delta in deltas.items():
            account = accounts[account_id]
            net_debit = max(0, -delta)
            if account.account_status != AccountStatus.ACTIVE:
                return LiquidityCycleResult(None, tuple(accepted), (), f"account {account_id!r} is not active")
            if account.cash_available_minor < net_debit:
                return LiquidityCycleResult(None, tuple(accepted), (), f"participant net debit exceeds available cash for account {account_id!r}")

        next_accounts = tuple(
            replace(accounts[account_id], ledger_balance_minor=accounts[account_id].ledger_balance_minor + delta)
            for account_id, delta in sorted(deltas.items())
        )
        for account in next_accounts:
            reconcile_account(account)
        settled_payments = tuple(
            transition_payment(self.to_settlement_pending(payment), PaymentStatus.SETTLED, at=at)
            for payment in accepted
        )
        payload = {
            "account_deltas_minor": {account_id: delta for account_id, delta in sorted(deltas.items())},
            "currency": self.currency,
            "gross_value_minor": gross_value,
            "net_debit_value_minor": sum(max(0, -delta) for delta in deltas.values()),
            "payment_ids": [payment.payment_id for payment in settled_payments],
            "rail_id": self.rail_id,
        }
        event = FinancialEvent(
            event_id=event_id,
            event_type="LiquiditySavingCycleSettled",
            aggregate_id=event_id,
            aggregate_type="settlement_cycle",
            event_at=at,
            ingested_at=at,
            sequence_number=sequence_number,
            correlation_id=f"{self.rail_id}:{event_id}",
            simulation_id=simulation_id,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        return LiquidityCycleResult(
            NetSettlementBatch(
                settled_payments,
                next_accounts,
                event,
                gross_value,
                sum(max(0, -delta) for delta in deltas.values()),
            ),
            (),
            (),
            "all obligations settled atomically using participant net positions",
        )


__all__ = ["LiquidityCycleResult", "LiquiditySavingRail", "NetSettlementBatch"]
