"""Blueprint section 32 vertical slice, executed end to end.

1. two synthetic institutions  2. settlement accounts  3. a pacs.008 instruction
4. normalization/validation   5. RTGS admission       6. liquidity check
7. gross settlement           8. both accounts update 9. events persisted
10. replay reconstructs state  11. result exposed to API/UI
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from atlas.domain import (
    CurrencySpec,
    FinancialEvent,
    Institution,
    InstitutionOperationalStatus,
    InstitutionType,
    Money,
    PaymentInstruction,
    SettlementAccount,
)
from atlas.iso20022 import build_pacs008, normalize, to_payment_instruction
from atlas.ledger import Ledger
from atlas.rails import AdmissionStatus, OperatingSchedule, RailParticipant, RTGSRail
from atlas.store import EventStore


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    simulation_id: str
    institutions: tuple[Institution, ...]
    opening_accounts: tuple[SettlementAccount, ...]
    closing_accounts: tuple[SettlementAccount, ...]
    payment: PaymentInstruction
    admission_reason: str
    events: tuple[FinancialEvent, ...]
    live_state_hash: str
    replayed_state_hash: str
    chain_valid: bool
    message_sha256: str

    @property
    def replay_matches(self) -> bool:
        return self.live_state_hash == self.replayed_state_hash

    def to_dict(self) -> dict:
        return {
            "simulation_id": self.simulation_id,
            "institutions": [{"id": i.institution_id, "name": i.institution_name, "type": str(i.institution_type)} for i in self.institutions],
            "opening_accounts": {a.account_id: a.ledger_balance_minor for a in self.opening_accounts},
            "closing_accounts": {a.account_id: a.ledger_balance_minor for a in self.closing_accounts},
            "payment": {
                "payment_id": self.payment.payment_id, "status": str(self.payment.status),
                "amount_minor": self.payment.amount_minor, "currency": self.payment.currency,
                "source_message_id": self.payment.source_message_id, "schema": self.payment.message_schema_version,
            },
            "admission_reason": self.admission_reason,
            "events": [{"event_id": e.event_id, "type": e.event_type, "sequence": e.sequence_number, "payload": json.loads(e.payload_json)} for e in self.events],
            "live_state_hash": self.live_state_hash,
            "replayed_state_hash": self.replayed_state_hash,
            "replay_matches": self.replay_matches,
            "chain_valid": self.chain_valid,
            "message_sha256": self.message_sha256,
        }


def run_vertical_slice(
    store: EventStore | None = None,
    *,
    simulation_id: str = "vertical-slice-001",
    amount: str = "250000.00",
    at: datetime = datetime(2026, 1, 6, 15, 0, tzinfo=UTC),
) -> VerticalSliceResult:
    store = store or EventStore()
    usd = CurrencySpec("USD", 2)
    rail_id = "rtgs-usd"
    institutions = (
        Institution("bank-alpha", "Alpha Commercial Bank (synthetic)", InstitutionType.COMMERCIAL_BANK, "US",
                    "liq-standard", "fund-standard", "risk-moderate", InstitutionOperationalStatus.ACTIVE, at - timedelta(days=30)),
        Institution("bank-beta", "Beta Investment Bank (synthetic)", InstitutionType.INVESTMENT_BANK, "US",
                    "liq-standard", "fund-standard", "risk-moderate", InstitutionOperationalStatus.ACTIVE, at - timedelta(days=30)),
    )
    bics = {"ALPHUS33XXX": "bank-alpha", "BETAUS33XXX": "bank-beta"}
    opening = (
        SettlementAccount("acct-alpha-rtgs", "bank-alpha", rail_id, "USD", Money.from_major_units("1000000.00", usd).amount_minor),
        SettlementAccount("acct-beta-rtgs", "bank-beta", rail_id, "USD", Money.from_major_units("400000.00", usd).amount_minor),
    )
    accounts = {a.account_id: a for a in opening}
    xml = build_pacs008(
        "MSG-VS-0001", at,
        [{"end_to_end_id": "E2E-VS-0001", "amount": Money.from_major_units(amount, usd), "settlement_date": date(2026, 1, 6),
          "debtor_bic": "ALPHUS33XXX", "creditor_bic": "BETAUS33XXX"}],
    )
    message = normalize(xml)
    payment = to_payment_instruction(
        message, message.transactions[0], payment_rail_id=rail_id,
        institution_for_bic=bics.__getitem__,
        account_for_institution=lambda inst, rail: f"acct-{inst.split('-')[1]}-{rail.split('-')[0]}",
        scenario_id=simulation_id,
    )
    rail = RTGSRail(
        rail_id, "USD", (RailParticipant("bank-alpha", "USD"), RailParticipant("bank-beta", "USD")),
        OperatingSchedule("America/New_York", time(21), time(19)),
    )
    admission = rail.admit(payment, accounts[payment.sender_account_id], accounts[payment.receiver_account_id], at=at)
    events: list[FinancialEvent] = []
    if admission.status == AdmissionStatus.ACCEPTED:
        result = rail.process_queue([payment], accounts, at=at, simulation_id=simulation_id, sequence_number_start=store.head(simulation_id)[0])
        settled = result.settlements[0]
        accounts[settled.sender_account.account_id] = settled.sender_account
        accounts[settled.receiver_account.account_id] = settled.receiver_account
        payment = settled.payment
        events.append(settled.event)
        store.append_many(events)
    live = Ledger(accounts.values())
    replayed = Ledger.replay(opening, store.events(simulation_id))
    return VerticalSliceResult(
        simulation_id=simulation_id, institutions=institutions, opening_accounts=opening,
        closing_accounts=tuple(accounts.values()), payment=payment, admission_reason=admission.reason,
        events=tuple(events), live_state_hash=live.state_hash(), replayed_state_hash=replayed.state_hash(),
        chain_valid=store.verify_chain(simulation_id).valid, message_sha256=message.original_sha256,
    )
