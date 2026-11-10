"""Strict event-sourced ledger.

Every ledger-affecting event carries *before* and *after* values. Replay checks the
*before* values against the current folded state, so a reordered, missing or
tampered event is detected instead of silently producing a different balance.

Accounting identity enforced after every event::

    sum(ledger_balance) == opening_total + external_net_flow

Settlements (gross or netted) move cash between accounts and leave the total
unchanged. Only explicitly external events (facility draws/repayments, liquidity
adjustments, intraday credit draws/repayments) change the total, and each one
records its amount.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime

from atlas.domain import FinancialEvent, SettlementAccount, reconcile_account

LEDGER_EVENT_TYPES = frozenset(
    {
        "PaymentSettled",
        "LiquiditySavingCycleSettled",
        "FundingDrawn",
        "FundingRepaid",
        "LiquidityAdjusted",
        "CreditLimitChanged",
        "IntradayCreditRepaid",
        "InterbankLoanTransfer",
    }
)


class LedgerReplayError(ValueError):
    """Raised when an event is inconsistent with the folded ledger state."""


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class Ledger:
    def __init__(self, accounts: Iterable[SettlementAccount]) -> None:
        self._accounts: dict[str, SettlementAccount] = {}
        for account in accounts:
            if account.account_id in self._accounts:
                raise ValueError(f"duplicate account {account.account_id!r}")
            reconcile_account(account)
            self._accounts[account.account_id] = account
        self.opening_total_minor = sum(a.ledger_balance_minor for a in self._accounts.values())
        self._running_total = self.opening_total_minor   # updated by exact deltas; full recount in verify_totals()
        self.external_net_flow_minor = 0
        self.applied_count = 0
        self.ignored_count = 0
        self._last_sequence: dict[str, int] = {}

    # ----------------------------------------------------------------- queries
    def account(self, account_id: str) -> SettlementAccount:
        try:
            return self._accounts[account_id]
        except KeyError as exc:
            raise KeyError(f"unknown account {account_id!r}") from exc

    @property
    def accounts(self) -> Mapping[str, SettlementAccount]:
        return dict(self._accounts)

    def total_ledger_minor(self) -> int:
        return sum(a.ledger_balance_minor for a in self._accounts.values())

    def verify_totals(self) -> None:
        """Full O(accounts) recount; the per-event check uses the incrementally maintained total."""
        if self.total_ledger_minor() != self._running_total:
            raise LedgerReplayError("running ledger total diverged from the account recount")
        self.check_conservation()

    def snapshot_dict(self) -> dict[str, dict[str, int | str]]:
        return {
            account_id: {
                "currency": a.currency,
                "ledger_balance_minor": a.ledger_balance_minor,
                "reserved_balance_minor": a.reserved_balance_minor,
                "credit_limit_minor": a.credit_limit_minor,
                "intraday_credit_used_minor": a.intraday_credit_used_minor,
                "account_status": str(a.account_status),
            }
            for account_id, a in sorted(self._accounts.items())
        }

    def state_hash(self) -> str:
        return hashlib.sha256(_canonical(self.snapshot_dict()).encode("utf-8")).hexdigest()

    # ----------------------------------------------------------------- folding
    def put(self, account: SettlementAccount) -> None:
        """Replace an account during live simulation (state already validated by the operation)."""
        if account.account_id not in self._accounts:
            raise KeyError(f"unknown account {account.account_id!r}")
        reconcile_account(account)
        self._running_total += account.ledger_balance_minor - self._accounts[account.account_id].ledger_balance_minor
        self._accounts[account.account_id] = account

    def _set(self, account_id: str, **changes: int) -> None:
        current = self.account(account_id)
        updated = replace(current, **changes)
        reconcile_account(updated)
        self._running_total += updated.ledger_balance_minor - current.ledger_balance_minor
        self._accounts[account_id] = updated

    def _expect(self, account_id: str, field: str, expected: int, event: FinancialEvent) -> None:
        actual = getattr(self.account(account_id), field)
        if actual != expected:
            raise LedgerReplayError(
                f"event {event.event_id!r} ({event.event_type}) expects {account_id}.{field}={expected}, ledger has {actual}"
            )

    def apply(self, event: FinancialEvent) -> bool:
        """Fold one event. Returns True when the event changed ledger state."""
        last = self._last_sequence.get(event.simulation_id)
        if last is not None and event.sequence_number <= last:
            raise LedgerReplayError(f"event {event.event_id!r} is out of sequence order")
        self._last_sequence[event.simulation_id] = event.sequence_number
        if event.event_type not in LEDGER_EVENT_TYPES:
            self.ignored_count += 1
            return False
        p = json.loads(event.payload_json)
        kind = event.event_type
        if kind == "PaymentSettled":
            s, r = p["sender_account_id"], p["receiver_account_id"]
            self._expect(s, "ledger_balance_minor", p["sender_ledger_before_minor"], event)
            self._expect(s, "intraday_credit_used_minor", p["sender_credit_used_before_minor"], event)
            self._expect(r, "ledger_balance_minor", p["receiver_ledger_before_minor"], event)
            amount, draw = p["amount_minor"], p["credit_draw_minor"]
            if p["sender_ledger_after_minor"] != p["sender_ledger_before_minor"] + draw - amount:
                raise LedgerReplayError(f"event {event.event_id!r} sender arithmetic does not reconcile")
            if p["receiver_ledger_after_minor"] != p["receiver_ledger_before_minor"] + amount:
                raise LedgerReplayError(f"event {event.event_id!r} receiver arithmetic does not reconcile")
            self._set(s, ledger_balance_minor=p["sender_ledger_after_minor"], intraday_credit_used_minor=p["sender_credit_used_after_minor"])
            self._set(r, ledger_balance_minor=p["receiver_ledger_after_minor"])
            self.external_net_flow_minor += draw
        elif kind == "LiquiditySavingCycleSettled":
            deltas: dict[str, int] = p["account_deltas_minor"]
            if sum(deltas.values()) != 0:
                raise LedgerReplayError(f"event {event.event_id!r} netting deltas do not sum to zero")
            for account_id, delta in deltas.items():
                self._set(account_id, ledger_balance_minor=self.account(account_id).ledger_balance_minor + delta)
        elif kind in ("FundingDrawn", "FundingRepaid", "LiquidityAdjusted"):
            account_id = p["account_id"]
            before, after = p["account_ledger_before_minor"], p["account_ledger_after_minor"]
            self._expect(account_id, "ledger_balance_minor", before, event)
            self._set(account_id, ledger_balance_minor=after)
            self.external_net_flow_minor += after - before
        elif kind == "CreditLimitChanged":
            account_id = p["account_id"]
            self._expect(account_id, "credit_limit_minor", p["credit_limit_before_minor"], event)
            self._set(account_id, credit_limit_minor=p["credit_limit_after_minor"])
        elif kind == "InterbankLoanTransfer":
            src, dst, amount = p["from_account_id"], p["to_account_id"], p["amount_minor"]
            if src == dst or amount <= 0:
                raise LedgerReplayError(f"event {event.event_id!r} is not a valid interbank transfer")
            self._expect(src, "ledger_balance_minor", p["from_ledger_before_minor"], event)
            self._expect(dst, "ledger_balance_minor", p["to_ledger_before_minor"], event)
            if self.account(src).cash_available_minor < amount:
                raise LedgerReplayError(f"event {event.event_id!r} transfers more than the sender's unreserved cash")
            self._set(src, ledger_balance_minor=p["from_ledger_before_minor"] - amount)
            self._set(dst, ledger_balance_minor=p["to_ledger_before_minor"] + amount)
        elif kind == "IntradayCreditRepaid":
            account_id = p["account_id"]
            self._expect(account_id, "ledger_balance_minor", p["account_ledger_before_minor"], event)
            self._expect(account_id, "intraday_credit_used_minor", p["credit_used_before_minor"], event)
            self._set(
                account_id,
                ledger_balance_minor=p["account_ledger_after_minor"],
                intraday_credit_used_minor=p["credit_used_after_minor"],
            )
            self.external_net_flow_minor += p["account_ledger_after_minor"] - p["account_ledger_before_minor"]
        self.check_conservation()
        self.applied_count += 1
        return True

    def apply_all(self, events: Iterable[FinancialEvent]) -> Ledger:
        for event in events:
            self.apply(event)
        return self

    def record_external(self, delta_minor: int) -> None:
        """Live-simulation hook used when an operation (already validated) moved cash externally."""
        self.external_net_flow_minor += delta_minor

    def check_conservation(self) -> None:
        total = self._running_total
        expected = self.opening_total_minor + self.external_net_flow_minor
        if total != expected:
            raise LedgerReplayError(f"cash conservation violated: ledger total {total} != expected {expected}")

    @classmethod
    def replay(cls, opening_accounts: Iterable[SettlementAccount], events: Iterable[FinancialEvent]) -> Ledger:
        ledger = cls(opening_accounts).apply_all(events)
        ledger.verify_totals()
        return ledger


# ---------------------------------------------------------------- event makers
def _event(event_type: str, aggregate_id: str, payload: dict, *, at: datetime, event_id: str, sequence_number: int,
           simulation_id: str, correlation_id: str, causation_id: str | None) -> FinancialEvent:
    return FinancialEvent(
        event_id=event_id, event_type=event_type, aggregate_id=aggregate_id, aggregate_type="settlement_account",
        event_at=at, ingested_at=at, sequence_number=sequence_number, correlation_id=correlation_id,
        simulation_id=simulation_id, payload_json=_canonical(payload), causation_id=causation_id,
    )


def adjustment_event(account: SettlementAccount, delta_minor: int, reason: str, **meta) -> tuple[SettlementAccount, FinancialEvent]:
    """External liquidity change (e.g. modeled withdrawal/injection). Never creates negative cash."""
    if not isinstance(delta_minor, int) or isinstance(delta_minor, bool):
        raise TypeError("delta must be integer minor units")
    after = account.ledger_balance_minor + delta_minor
    if after < account.reserved_balance_minor:
        raise ValueError("liquidity adjustment would reduce cash below reserved balance")
    updated = replace(account, ledger_balance_minor=after)
    payload = {
        "account_id": account.account_id, "currency": account.currency, "delta_minor": delta_minor, "reason": reason,
        "account_ledger_before_minor": account.ledger_balance_minor, "account_ledger_after_minor": after,
    }
    return updated, _event("LiquidityAdjusted", account.account_id, payload, **meta)


def credit_limit_event(account: SettlementAccount, new_limit_minor: int, reason: str, **meta) -> tuple[SettlementAccount, FinancialEvent]:
    """Change an intraday credit line. A cut below current usage is refused (no silent breach)."""
    if new_limit_minor < account.intraday_credit_used_minor:
        raise ValueError("credit limit cannot be cut below credit already in use")
    updated = replace(account, credit_limit_minor=new_limit_minor)
    payload = {
        "account_id": account.account_id, "reason": reason,
        "credit_limit_before_minor": account.credit_limit_minor, "credit_limit_after_minor": new_limit_minor,
    }
    return updated, _event("CreditLimitChanged", account.account_id, payload, **meta)


def credit_repayment_event(account: SettlementAccount, **meta) -> tuple[SettlementAccount, FinancialEvent] | None:
    """Repay as much intraday credit as unreserved cash permits (end-of-day sweep)."""
    amount = min(account.intraday_credit_used_minor, account.cash_available_minor)
    if amount <= 0:
        return None
    updated = replace(
        account,
        ledger_balance_minor=account.ledger_balance_minor - amount,
        intraday_credit_used_minor=account.intraday_credit_used_minor - amount,
    )
    payload = {
        "account_id": account.account_id, "amount_minor": amount,
        "account_ledger_before_minor": account.ledger_balance_minor, "account_ledger_after_minor": updated.ledger_balance_minor,
        "credit_used_before_minor": account.intraday_credit_used_minor, "credit_used_after_minor": updated.intraday_credit_used_minor,
    }
    return updated, _event("IntradayCreditRepaid", account.account_id, payload, **meta)


def interbank_transfer_event(src: SettlementAccount, dst: SettlementAccount, amount_minor: int, purpose: str, *, loan_id: str,
                             **meta) -> tuple[SettlementAccount, SettlementAccount, FinancialEvent]:
    """Cash-only transfer between two institutions' accounts on the same rail (loan drawdown or repayment)."""
    if src.account_id == dst.account_id or src.payment_rail_id != dst.payment_rail_id or src.currency != dst.currency:
        raise ValueError("interbank transfer requires distinct accounts on the same rail and currency")
    if not isinstance(amount_minor, int) or amount_minor <= 0:
        raise ValueError("transfer amount must be positive integer minor units")
    if src.cash_available_minor < amount_minor:
        raise ValueError("insufficient unreserved cash for interbank transfer")
    new_src = replace(src, ledger_balance_minor=src.ledger_balance_minor - amount_minor)
    new_dst = replace(dst, ledger_balance_minor=dst.ledger_balance_minor + amount_minor)
    payload = {"loan_id": loan_id, "purpose": purpose, "amount_minor": amount_minor, "from_account_id": src.account_id,
               "to_account_id": dst.account_id, "from_ledger_before_minor": src.ledger_balance_minor,
               "to_ledger_before_minor": dst.ledger_balance_minor}
    return new_src, new_dst, _event("InterbankLoanTransfer", loan_id, payload, **meta)
