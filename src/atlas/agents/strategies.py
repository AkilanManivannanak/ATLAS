"""Rule-based release strategies (blueprint agent family A).

A strategy sees only its own institution's information (``BankView``): its held
payments, its own settlement-account resources and the inflows it has already
received. It cannot see other banks' queues — this information asymmetry is what
makes liquidity coordination a strategic problem (Bech & Garratt, 2003, "The
intraday liquidity management game", Journal of Economic Theory 109(2)).

Strategies only *propose* releases. The simulator still enforces every rail rule
and liquidity constraint; a released payment that cannot settle waits in the
central queue. Strategies are deterministic functions of the view.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class HeldPayment:
    payment_id: str
    rail: str
    amount_minor: int
    priority: int
    due_at: datetime
    arrival_at: datetime


@dataclass(frozen=True, slots=True)
class BankView:
    institution_id: str
    now: datetime
    held: tuple[HeldPayment, ...]
    cash_available_minor: dict[str, int]       # rail -> unreserved cash
    undrawn_credit_minor: dict[str, int]       # rail -> undrawn intraday credit
    opening_balance_minor: dict[str, int]      # rail -> opening balance
    inflow_since_last_minor: dict[str, int]    # rail -> settled inflows since previous decision
    inflow_last_hour_minor: int
    expected_inflow_last_hour_minor: int       # from the bank's own historical profile (may be 0)
    queued_outflow_minor: dict[str, int]       # rail -> value already released but unsettled
    stress_signal: bool = False


class ReleaseStrategy:
    name = "base"
    family = "rule_based"

    def params(self) -> dict:
        return {}

    def decide(self, view: BankView) -> list[str]:  # pragma: no cover - interface
        raise NotImplementedError

    @staticmethod
    def _ordered(view: BankView) -> list[HeldPayment]:
        return sorted(view.held, key=lambda p: (-p.priority, p.due_at, p.arrival_at, p.payment_id))

    @staticmethod
    def _due_soon(p: HeldPayment, now: datetime, margin: timedelta) -> bool:
        return p.due_at - now <= margin


@dataclass
class EarlySettlement(ReleaseStrategy):
    """Release every payment immediately (the cooperative / 'pay early' benchmark)."""

    name: str = "early"

    def decide(self, view: BankView) -> list[str]:
        return [p.payment_id for p in self._ordered(view)]


@dataclass
class LiquidityConservative(ReleaseStrategy):
    """Keep a cash buffer; release only what fits above it, unless the deadline is near."""

    buffer_bp: int = 5_000
    deadline_margin_min: int = 15
    name: str = "conservative"

    def params(self) -> dict:
        return {"buffer_bp": self.buffer_bp, "deadline_margin_min": self.deadline_margin_min}

    def decide(self, view: BankView) -> list[str]:
        margin = timedelta(minutes=self.deadline_margin_min)
        budget = {
            rail: view.cash_available_minor.get(rail, 0) - view.queued_outflow_minor.get(rail, 0)
            - view.opening_balance_minor.get(rail, 0) * self.buffer_bp // 10_000
            for rail in view.cash_available_minor
        }
        out = []
        for p in self._ordered(view):
            if self._due_soon(p, view.now, margin):
                out.append(p.payment_id)
                budget[p.rail] = budget.get(p.rail, 0) - p.amount_minor
            elif budget.get(p.rail, 0) >= p.amount_minor:
                out.append(p.payment_id)
                budget[p.rail] -= p.amount_minor
        return out


@dataclass
class PriorityDriven(ReleaseStrategy):
    """Urgent payments immediately; others in timed batches or when close to deadline."""

    batch_every_min: int = 30
    deadline_margin_min: int = 20
    name: str = "priority"

    def params(self) -> dict:
        return {"batch_every_min": self.batch_every_min, "deadline_margin_min": self.deadline_margin_min}

    def decide(self, view: BankView) -> list[str]:
        batch = (view.now.hour * 60 + view.now.minute) % self.batch_every_min == 0
        margin = timedelta(minutes=self.deadline_margin_min)
        return [p.payment_id for p in self._ordered(view)
                if p.priority >= 2 or batch or self._due_soon(p, view.now, margin)]


@dataclass
class LiquidityEfficient(ReleaseStrategy):
    """Liquidity recycling: spend received inflows plus a small own-liquidity allowance."""

    own_allowance_bp: int = 2_500
    deadline_margin_min: int = 15
    name: str = "recycler"
    _spent_own: dict = field(default_factory=dict, repr=False)

    def params(self) -> dict:
        return {"own_allowance_bp": self.own_allowance_bp, "deadline_margin_min": self.deadline_margin_min}

    def decide(self, view: BankView) -> list[str]:
        margin = timedelta(minutes=self.deadline_margin_min)
        budget = {}
        for rail, opening in view.opening_balance_minor.items():
            allowance = opening * self.own_allowance_bp // 10_000
            budget[rail] = view.inflow_since_last_minor.get(rail, 0) + max(0, allowance - self._spent_own.get(rail, 0))
        out = []
        for p in self._ordered(view):
            cash_ok = view.cash_available_minor.get(p.rail, 0) - view.queued_outflow_minor.get(p.rail, 0) >= p.amount_minor
            if self._due_soon(p, view.now, margin) or (budget.get(p.rail, 0) >= p.amount_minor and cash_ok):
                out.append(p.payment_id)
                used = min(budget.get(p.rail, 0), p.amount_minor)
                inflow = view.inflow_since_last_minor.get(p.rail, 0)
                self._spent_own[p.rail] = self._spent_own.get(p.rail, 0) + max(0, used - inflow)
                budget[p.rail] = budget.get(p.rail, 0) - p.amount_minor
        return out


@dataclass
class FundingDependent(ReleaseStrategy):
    """Release everything; the simulator lets this bank draw its funding facility when short."""

    name: str = "funding"
    uses_facility: bool = True

    def decide(self, view: BankView) -> list[str]:
        return [p.payment_id for p in self._ordered(view)]


@dataclass
class StressResponsive(ReleaseStrategy):
    """Pay early in normal conditions; switch to conservative when inflows dry up or stress is signalled."""

    inflow_shortfall_bp: int = 5_000
    conservative: LiquidityConservative = field(default_factory=lambda: LiquidityConservative(buffer_bp=6_000))
    name: str = "stress_responsive"

    def params(self) -> dict:
        return {"inflow_shortfall_bp": self.inflow_shortfall_bp, "buffer_bp": self.conservative.buffer_bp}

    def decide(self, view: BankView) -> list[str]:
        expected = view.expected_inflow_last_hour_minor
        dried_up = expected > 0 and view.inflow_last_hour_minor * 10_000 < expected * self.inflow_shortfall_bp
        if view.stress_signal or dried_up:
            return self.conservative.decide(view)
        return [p.payment_id for p in self._ordered(view)]


STRATEGY_REGISTRY: dict[str, Callable[..., ReleaseStrategy]] = {
    "early": EarlySettlement,
    "conservative": LiquidityConservative,
    "priority": PriorityDriven,
    "recycler": LiquidityEfficient,
    "funding": FundingDependent,
    "stress_responsive": StressResponsive,
}


def make_strategy(name: str, **params) -> ReleaseStrategy:
    try:
        return STRATEGY_REGISTRY[name](**params)
    except KeyError as exc:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGY_REGISTRY)}") from exc


def assign_strategies(institutions: Sequence[str], mix: dict[str, int] | str, seed: int = 0) -> dict[str, ReleaseStrategy]:
    """Assign strategies: a single name for all, or a {name: count-weight} mix applied round-robin by sorted id."""
    if isinstance(mix, str):
        return {i: make_strategy(mix) for i in institutions}
    names: list[str] = []
    for name, weight in sorted(mix.items()):
        names.extend([name] * weight)
    if not names:
        raise ValueError("strategy mix is empty")
    ordered = sorted(institutions)
    offset = seed % len(names)
    return {inst: make_strategy(names[(k + offset) % len(names)]) for k, inst in enumerate(ordered)}
