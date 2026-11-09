"""Safety controller: the only gate between an automated proposal and the ledger.

Every controller action (MPC, rule-based or learned) is validated here against
hard constraints in exact integer arithmetic. A rejected action is never
"repaired" or partially executed: it is logged with its reason and dropped, and
the simulator continues under the baseline policy. No learned or optimized
component can bypass this check, and no LLM is involved in validity decisions.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.domain import AccountStatus
from atlas.settlement import Obligation, is_feasible

SAFETY_VERSION = "atlas-safety-v1"
ALLOWED_TRANSFER_RAILS = ("rtgs", "lsm", "fednow", "rtp")


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    max_transfer_share_bp: int = 5_000      # at most half of a source account's free cash per action
    min_source_floor_minor: int = 0         # source must keep at least this much unreserved cash
    max_batch_size: int = 2_000
    transfer_cutoff_min_before_close: int = 15


@dataclass(frozen=True, slots=True)
class Verdict:
    approved: bool
    reason: str
    version: str = SAFETY_VERSION


class SafetyController:
    def __init__(self, limits: SafetyLimits = SafetyLimits()) -> None:
        self.limits = limits

    def validate(self, action, view) -> Verdict:
        try:
            if action.kind == "settle_batch":
                return self._batch(action, view)
            if action.kind == "transfer":
                return self._transfer(action, view)
            return Verdict(False, f"unknown action kind {action.kind!r}")
        except Exception as exc:  # validation must fail closed
            return Verdict(False, f"validation error: {exc}")

    def _batch(self, action, view) -> Verdict:
        ids = action.payment_ids
        if not ids:
            return Verdict(False, "empty settlement batch")
        if len(ids) != len(set(ids)):
            return Verdict(False, "duplicate payment ids in batch")
        if len(ids) > self.limits.max_batch_size:
            return Verdict(False, "batch exceeds maximum size")
        if not view.rail_up.get("rtgs", False):
            return Verdict(False, "rtgs rail unavailable")
        queued = {p.payment_id: p for p in view.rtgs_queue}
        missing = [i for i in ids if i not in queued]
        if missing:
            return Verdict(False, f"{len(missing)} payment(s) not in the rtgs central queue (settled, expired or unknown)")
        obligations = [Obligation(i, queued[i].sender_account_id, queued[i].receiver_account_id, queued[i].amount_minor) for i in ids]
        accts = {o.payer for o in obligations} | {o.payee for o in obligations}
        for a in accts:
            if view.accounts[a].account_status != AccountStatus.ACTIVE:
                return Verdict(False, f"account {a} is not active")
        available = {a: view.accounts[a].cash_available_minor for a in accts}
        if not is_feasible(obligations, available):
            return Verdict(False, "batch violates participant cash constraints")
        return Verdict(True, "feasible simultaneous settlement within unreserved cash")

    def _transfer(self, action, view) -> Verdict:
        amt = action.amount_minor
        if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
            return Verdict(False, "transfer amount must be positive integer minor units")
        if action.from_rail == action.to_rail:
            return Verdict(False, "source and destination rails must differ")
        if action.from_rail not in ALLOWED_TRANSFER_RAILS or action.to_rail not in ALLOWED_TRANSFER_RAILS:
            return Verdict(False, "unsupported rail for transfer")
        minutes_left = (view.close_at - view.now).total_seconds() / 60
        if minutes_left < self.limits.transfer_cutoff_min_before_close:
            return Verdict(False, "transfer cutoff reached")
        for rail in (action.from_rail, action.to_rail):
            if not view.rail_up.get(rail, False):
                return Verdict(False, f"{rail} rail unavailable")
        src_id, dst_id = f"{action.institution}:{action.from_rail}", f"{action.institution}:{action.to_rail}"
        src, dst = view.accounts.get(src_id), view.accounts.get(dst_id)
        if src is None or dst is None:
            return Verdict(False, "institution does not hold both settlement accounts")
        if src.institution_id != dst.institution_id:
            return Verdict(False, "transfers are restricted to an institution's own accounts")
        if src.account_status != AccountStatus.ACTIVE or dst.account_status != AccountStatus.ACTIVE:
            return Verdict(False, "both accounts must be active")
        if src.cash_available_minor - amt < self.limits.min_source_floor_minor:
            return Verdict(False, "transfer would breach the source cash floor")
        if amt * 10_000 > src.cash_available_minor * self.limits.max_transfer_share_bp:
            return Verdict(False, "transfer exceeds per-action share limit of source cash")
        # never strip cash already committed to the source rail's queued outgoing payments
        queue = view.rtgs_queue if action.from_rail == "rtgs" else view.lsm_queue if action.from_rail == "lsm" else ()
        committed = sum(p.amount_minor for p in queue if p.sender_account_id == src_id)
        if src.cash_available_minor - amt < min(committed, src.cash_available_minor):
            return Verdict(False, "transfer would uncover queued outgoing payments on the source rail")
        return Verdict(True, "own-account liquidity transfer within limits")
