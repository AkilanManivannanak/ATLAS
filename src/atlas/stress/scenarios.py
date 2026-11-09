"""Stress shocks applied inside the day simulator.

Every shock has explicit timing, targets and parameters, and is recorded as
financial or operational events so a stressed run is fully replayable. Times are
expressed as minutes after the scenario's business-day open so the same stress
definition can be paired with any generated day (paired-seed experiments).

Terminology is deliberately conservative: a participant that stops sending is an
"operational outage" or "failure to pay" in the model. ATLAS does not model
insolvency, resolution or bank failure, and never reports them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class Shock:
    kind: str = field(init=False, default="shock")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RailOutage(Shock):
    rail: str
    start_min: int
    end_min: int
    kind: str = field(init=False, default="rail_outage")


@dataclass(frozen=True, slots=True)
class ParticipantOutage(Shock):
    """Institution cannot send on any rail during the window; inflows still arrive (liquidity sink)."""

    institution: str            # an institution id, or "@largest" for the largest core bank
    start_min: int
    end_min: int                # use a value past close for "rest of day" (failure to pay)
    kind: str = field(init=False, default="participant_outage")


@dataclass(frozen=True, slots=True)
class LiquidityWithdrawal(Shock):
    """Remove a share of current cash from large-value accounts of the targeted institutions."""

    at_min: int
    share_bp: int
    target: str = "@all"        # "@all", "@core", "@periphery" or an institution id
    rails: tuple[str, ...] = ("rtgs", "lsm")
    kind: str = field(init=False, default="liquidity_withdrawal")


@dataclass(frozen=True, slots=True)
class CreditLineCut(Shock):
    """Collateral revaluation / haircut increase modeled as a cut to RTGS intraday credit lines.

    A line is never cut below credit already in use (no silent breach); the
    shortfall shows up as reduced headroom for the rest of the day.
    """

    at_min: int
    cut_bp: int
    target: str = "@all"
    kind: str = field(init=False, default="credit_line_cut")


@dataclass(frozen=True, slots=True)
class ConcentratedOutflows(Shock):
    institution: str
    at_min: int
    count: int
    amount_multiplier: int = 4
    kind: str = field(init=False, default="concentrated_outflows")


@dataclass(frozen=True, slots=True)
class LiquidityHoarding(Shock):
    """A share of institutions switch to a conservative release strategy (stress signal raised)."""

    at_min: int
    share_bp: int
    buffer_bp: int = 7_000
    kind: str = field(init=False, default="liquidity_hoarding")


@dataclass(frozen=True, slots=True)
class MessagingDelay(Shock):
    """Instructions arriving in the window on the rail are held until the window ends."""

    rail: str
    start_min: int
    end_min: int
    kind: str = field(init=False, default="messaging_delay")


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    description: str
    shocks: tuple[Shock, ...]

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "shocks": [s.to_dict() for s in self.shocks]}


SCENARIO_LIBRARY: dict[str, Callable[[], StressScenario]] = {
    "baseline": lambda: StressScenario("baseline", "No shocks.", ()),
    "counterparty_delay": lambda: StressScenario(
        "counterparty_delay", "Largest core bank cannot send for 2 hours mid-morning (operational outage).",
        (ParticipantOutage("@largest", 120, 240),)),
    "rtgs_outage": lambda: StressScenario(
        "rtgs_outage", "RTGS rail unavailable for 90 minutes.", (RailOutage("rtgs", 180, 270),)),
    "liquidity_withdrawal": lambda: StressScenario(
        "liquidity_withdrawal", "30% of large-value cash withdrawn from all banks at 10:00.",
        (LiquidityWithdrawal(120, 3_000),)),
    "funding_disruption": lambda: StressScenario(
        "funding_disruption", "Intraday credit lines cut by 60% at 09:00 and periphery banks lose 20% of cash.",
        (CreditLineCut(60, 6_000), LiquidityWithdrawal(60, 2_000, target="@periphery"))),
    "haircut_shock": lambda: StressScenario(
        "haircut_shock", "Collateral haircut increase: credit lines cut by 50% at 11:00.", (CreditLineCut(180, 5_000),)),
    "failure_to_pay": lambda: StressScenario(
        "failure_to_pay", "Largest core bank stops sending for the rest of the day from 11:00.",
        (ParticipantOutage("@largest", 180, 10_000),)),
    "concentrated_outflows": lambda: StressScenario(
        "concentrated_outflows", "Largest core bank receives 40 extra large outgoing instructions at 13:00.",
        (ConcentratedOutflows("@largest", 300, 40),)),
    "liquidity_hoarding": lambda: StressScenario(
        "liquidity_hoarding", "Half of institutions switch to conservative release at 09:30.",
        (LiquidityHoarding(90, 5_000),)),
    "messaging_failure": lambda: StressScenario(
        "messaging_failure", "LSM rail messaging delayed for 2 hours.", (MessagingDelay("lsm", 150, 270),)),
    "combined": lambda: StressScenario(
        "combined", "Counterparty outage + credit cut + hoarding + RTGS outage.",
        (ParticipantOutage("@largest", 120, 300), CreditLineCut(120, 4_000), LiquidityHoarding(150, 4_000),
         RailOutage("rtgs", 330, 360))),
}


def build_scenario(name: str) -> StressScenario:
    try:
        return SCENARIO_LIBRARY[name]()
    except KeyError as exc:
        raise ValueError(f"unknown stress scenario {name!r}; choose from {sorted(SCENARIO_LIBRARY)}") from exc
