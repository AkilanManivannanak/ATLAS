"""Deterministic multi-rail business-day simulator (``atlas-day-sim-v1``).

Architecture (see docs/05_event_engine_design.md and DECISIONS.md D-012):

* Uses the versioned ``atlas-event-order-v1`` contract: events are ordered by
  (UTC timestamp, EventPhase, insertion order). The generic ``SimulationEngine``
  serializes the full state on every event for auditability; this simulator keeps
  state in process for throughput, and earns the same guarantee differently:
  every balance change is a ``FinancialEvent`` folded by the strict ``Ledger``,
  so the live state *is* the fold of the event log and replay must match it.
* Rails: RTGS (gross, priority/FIFO queue, optional intraday credit), LSM
  (periodic partial multilateral netting, cash only), FedNow-style and
  RTP-style instant rails (settle on arrival or reject). Rail validation reuses
  ``atlas.rails`` and settlement reuses ``settle_cash_transfer``.
* Bank agents decide when to release held large-value payments; the settlement
  policy decides how the RTGS central queue is processed; an optional controller
  (MPC) proposes actions that must pass the ``SafetyController``.
"""

from __future__ import annotations

import heapq
import json
import platform
import time as _time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from atlas.agents.strategies import BankView, HeldPayment, LiquidityConservative, ReleaseStrategy, assign_strategies
from atlas.domain import (
    FinancialEvent,
    FundingFacility,
    PaymentInstruction,
    PaymentStatus,
    SettlementAccount,
    settle_cash_transfer,
    transition_payment,
)
from atlas.ledger import Ledger, adjustment_event, credit_limit_event, credit_repayment_event
from atlas.liquidity import calculate_simple_funding_cost, draw_funding, repay_funding
from atlas.rails import FedNowRail, LiquiditySavingRail, PaymentRail, RailParticipant, RTPRail
from atlas.scenario import Scenario
from atlas.settlement import Obligation, bilateral_offsets, partial_netting_heuristic, partial_netting_milp
from atlas.simulation.events import EventPhase
from atlas.simulation.rng import DeterministicRandomStream, derive_stream_seed
from atlas.store import EventStore
from atlas.stress import (
    ConcentratedOutflows,
    CreditLineCut,
    LiquidityHoarding,
    LiquidityWithdrawal,
    MessagingDelay,
    ParticipantOutage,
    RailOutage,
    StressScenario,
)

SIMULATOR_VERSION = "atlas-day-sim-v1"
POLICIES = ("fifo", "fifo_strict", "priority", "bilateral", "multilateral", "multilateral_milp")
LARGE_VALUE = ("rtgs", "lsm")
INSTANT = ("fednow", "rtp")


@dataclass(frozen=True, slots=True)
class CostModel:
    """Research cost parameters (assumptions, documented in docs/13_optimization_formulation.md)."""

    delay_bp_per_hour: int = 2          # cost per hour a payment waits after arrival, bp of value
    late_penalty_bp: int = 10           # one-off penalty for settling after due time
    unsettled_penalty_bp: int = 100     # penalty for value left unsettled at close
    liquidity_bp_per_day: int = 5       # cost of peak own-liquidity usage
    credit_bp_per_day: int = 15         # cost of peak intraday credit usage

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SimulationSettings:
    policy: str = "priority"
    strategy: str | dict = "early"
    tick_min: int = 1
    decision_interval_min: int = 1
    rtgs_netting_every_min: int = 15
    lsm_cycle_min: int = 15
    lsm_algorithm: str = "heuristic"          # heuristic | milp
    use_intraday_credit: bool = True
    facility_capacity_bp: int = 2_000         # unsecured facility size vs expected outflow (funding strategy only)
    facility_rate_bp: int = 550
    snapshot_every_min: int = 15
    controller_interval_min: int = 5
    cost: CostModel = CostModel()

    def __post_init__(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"unknown policy {self.policy!r}; choose from {POLICIES}")
        if self.lsm_algorithm not in ("heuristic", "milp"):
            raise ValueError("lsm_algorithm must be 'heuristic' or 'milp'")
        for name in ("tick_min", "decision_interval_min", "rtgs_netting_every_min", "lsm_cycle_min", "snapshot_every_min", "controller_interval_min"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass(frozen=True, slots=True)
class Action:
    """Controller proposal. kinds: 'settle_batch' (payment_ids) | 'transfer' (institution, from_rail, to_rail, amount_minor)."""

    kind: str
    payment_ids: tuple[str, ...] = ()
    institution: str = ""
    from_rail: str = ""
    to_rail: str = ""
    amount_minor: int = 0
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class SystemView:
    now: datetime
    close_at: datetime
    accounts: dict[str, SettlementAccount]
    rtgs_queue: tuple[PaymentInstruction, ...]
    lsm_queue: tuple[PaymentInstruction, ...]
    held: dict[str, tuple[HeldPayment, ...]]
    rail_up: dict[str, bool]
    instant_outflow_history: dict[str, list[int]]   # account -> per-controller-interval instant outflow so far


class Controller(Protocol):
    name: str

    def propose(self, view: SystemView) -> list[Action]: ...


@dataclass
class SimulationResult:
    simulation_id: str
    scenario_summary: dict
    settings: dict
    stress: dict
    metrics: dict
    per_institution: list[dict]
    timeseries: list[dict]
    payments: list[dict]
    opening_accounts: tuple[SettlementAccount, ...]
    events: tuple[FinancialEvent, ...]
    final_state_hash: str
    manifest: dict
    controller_log: list[dict] = field(default_factory=list)

    def verify_replay(self) -> bool:
        return Ledger.replay(self.opening_accounts, self.events).state_hash() == self.final_state_hash

    def to_dict(self, *, include_payments: bool = False, include_events: bool = False) -> dict:
        d = {
            "simulation_id": self.simulation_id, "scenario": self.scenario_summary, "settings": self.settings,
            "stress": self.stress, "metrics": self.metrics, "per_institution": self.per_institution,
            "timeseries": self.timeseries, "final_state_hash": self.final_state_hash, "manifest": self.manifest,
            "controller_log": self.controller_log[-500:],
        }
        if include_payments:
            d["payments"] = self.payments
        if include_events:
            d["events"] = [{"seq": e.sequence_number, "type": e.event_type, "at": e.event_at.isoformat(),
                            "aggregate": e.aggregate_id, "payload": json.loads(e.payload_json)} for e in self.events]
        return d


def _minute_of(open_at: datetime, at: datetime) -> int:
    return int((at - open_at).total_seconds() // 60)


class DaySimulator:
    def __init__(
        self,
        scenario: Scenario,
        settings: SimulationSettings = SimulationSettings(),
        stress: StressScenario | None = None,
        *,
        simulation_id: str | None = None,
        controller: Controller | None = None,
        safety: Any | None = None,
        store: EventStore | None = None,
    ) -> None:
        self.sc = scenario
        self.settings = settings
        self.stress = stress or StressScenario("baseline", "No shocks.", ())
        self.simulation_id = simulation_id or f"{scenario.scenario_id}:{settings.policy}:{self.stress.name}"
        self.controller = controller
        self.store = store
        if controller is not None and safety is None:
            from atlas.control.safety import SafetyController
            safety = SafetyController()
        self.safety = safety
        self.open_at, self.close_at = scenario.open_at, scenario.close_at

        # ---- accounts / ledger
        self.opening = tuple(
            SettlementAccount(a.account_id, a.institution_id, a.rail, "USD", a.opening_balance_minor,
                              credit_limit_minor=a.credit_limit_minor if settings.use_intraday_credit else 0)
            for a in scenario.accounts
        )
        self.ledger = Ledger(self.opening)
        self.inst_rails = {i.institution_id: i.rails for i in scenario.institutions}
        self.institutions = sorted(self.inst_rails)
        self.largest = max(scenario.institutions, key=lambda i: (i.size_weight, i.institution_id)).institution_id

        # ---- rails (reuse validated archetypes)
        parts = lambda rail: tuple(RailParticipant(i, "USD", transaction_limit_minor=(
            scenario.config.fednow_limit_minor if rail == "fednow" else scenario.config.rtp_limit_minor if rail == "rtp" else None))
            for i in self.institutions if rail in self.inst_rails[i])
        self.rails: dict[str, PaymentRail] = {
            "rtgs": PaymentRail("rtgs", "USD", parts("rtgs")),
            "lsm": LiquiditySavingRail("lsm", "USD", parts("lsm")),
            "fednow": FedNowRail("fednow", "USD", parts("fednow")),
            "rtp": RTPRail("rtp", "USD", parts("rtp")),
        }
        self.rtgs_netting = LiquiditySavingRail("rtgs", "USD", parts("rtgs"))
        self.rail_up = {r: True for r in self.rails}

        # ---- strategies / facilities
        self.strategies: dict[str, ReleaseStrategy] = assign_strategies(self.institutions, settings.strategy, scenario.seed)
        self.stress_signal: set[str] = set()
        expected_out: dict[str, int] = {}
        for p in scenario.payments:
            if p.rail == "rtgs":
                expected_out[p.sender] = expected_out.get(p.sender, 0) + p.amount_minor
        self.facilities: dict[str, FundingFacility] = {
            i: FundingFacility(f"fac-{i}", i, "unsecured_intraday", "USD", max(1, expected_out.get(i, 0) * settings.facility_capacity_bp // 10_000),
                               max(1, expected_out.get(i, 0) * settings.facility_capacity_bp // 10_000), 0, 0,
                               settings.facility_rate_bp, None, "rtgs-hours", None, True)
            for i in self.institutions
        }
        self.facility_draw_times: dict[str, list[tuple[datetime, int]]] = {i: [] for i in self.institutions}

        # ---- state
        self.events: list[FinancialEvent] = []
        self.seq = 0
        self.heap: list[tuple] = []
        self.order = 0
        self.payments: dict[str, PaymentInstruction] = {}
        self.meta: dict[str, dict] = {}
        self.held: dict[str, dict[str, HeldPayment]] = {i: {} for i in self.institutions}
        self.queue: dict[str, dict[str, int]] = {"rtgs": {}, "lsm": {}}  # pid -> submitted_seq
        self.submitted = 0
        self.seen_ids: set[str] = set()
        self.blocked_senders: dict[str, tuple[int, int]] = {}
        self.messaging_delay: dict[str, tuple[int, int]] = {}
        self.inflow_since_last: dict[str, dict[str, int]] = {i: {} for i in self.institutions}
        self.inflow_log: dict[str, list[tuple[datetime, int]]] = {i: [] for i in self.institutions}
        self.cum_net: dict[str, int] = {a.account_id: 0 for a in self.opening}
        self.min_cum_net: dict[str, int] = {a.account_id: 0 for a in self.opening}
        self.peak_credit: dict[str, int] = {a.account_id: 0 for a in self.opening}
        self.timeseries: list[dict] = []
        self.counters = {"netting_cycles": 0, "netting_value_minor": 0, "netting_cash_used_minor": 0, "gridlock_ticks": 0,
                         "instant_rejected": 0, "instant_rejected_value_minor": 0, "rejected": 0, "controller_actions": 0,
                         "controller_rejected": 0, "transfers_minor": 0, "facility_drawn_minor": 0, "facility_interest_minor": 0}
        self.controller_log: list[dict] = []
        self.instant_outflow_hist: dict[str, list[int]] = {a.account_id: [] for a in self.opening if a.payment_rail_id in INSTANT}
        self._instant_out_window: dict[str, int] = {}
        self.extra_payments: list = []
        self.expected_inflow_hour = self._expected_inflow_profile()

    # ------------------------------------------------------------------ utils
    def _push(self, at: datetime, phase: EventPhase, kind: str, data: Any = None) -> None:
        heapq.heappush(self.heap, (at.timestamp(), int(phase), self.order, kind, data))
        self.order += 1

    def _emit(self, event_type: str, aggregate_id: str, aggregate_type: str, at: datetime, payload: dict,
              causation_id: str | None = None) -> FinancialEvent:
        ev = FinancialEvent(
            event_id=f"{self.simulation_id}#{self.seq}", event_type=event_type, aggregate_id=aggregate_id,
            aggregate_type=aggregate_type, event_at=at, ingested_at=at, sequence_number=self.seq,
            correlation_id=self.simulation_id, simulation_id=self.simulation_id,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")), causation_id=causation_id,
        )
        return self._commit(ev)

    def _commit(self, ev: FinancialEvent) -> FinancialEvent:
        before = {k: self.ledger.account(k).ledger_balance_minor for k in self._touched(ev)}
        self.ledger.apply(ev)
        for k, b in before.items():
            acct = self.ledger.account(k)
            if ev.event_type in ("PaymentSettled", "LiquiditySavingCycleSettled"):
                delta = acct.ledger_balance_minor - b
                if ev.event_type == "PaymentSettled":
                    p = json.loads(ev.payload_json)
                    if k == p["sender_account_id"]:
                        delta = -p["amount_minor"]
                self.cum_net[k] += delta
                self.min_cum_net[k] = min(self.min_cum_net[k], self.cum_net[k])
            self.peak_credit[k] = max(self.peak_credit[k], acct.intraday_credit_used_minor)
        self.events.append(ev)
        self.seq += 1
        return ev

    @staticmethod
    def _touched(ev: FinancialEvent) -> list[str]:
        if ev.event_type == "PaymentSettled":
            p = json.loads(ev.payload_json)
            return [p["sender_account_id"], p["receiver_account_id"]]
        if ev.event_type == "LiquiditySavingCycleSettled":
            return sorted(json.loads(ev.payload_json)["account_deltas_minor"])
        if ev.event_type in ("FundingDrawn", "FundingRepaid", "LiquidityAdjusted", "CreditLimitChanged", "IntradayCreditRepaid"):
            return [json.loads(ev.payload_json)["account_id"]]
        return []

    def _acct(self, inst: str, rail: str) -> str:
        return f"{inst}:{rail}"

    def _resolve(self, target: str) -> list[str]:
        if target == "@largest":
            return [self.largest]
        tiers = {i.institution_id: i.tier for i in self.sc.institutions}
        if target == "@all":
            return list(self.institutions)
        if target in ("@core", "@periphery"):
            return [i for i in self.institutions if tiers[i] == target[1:]]
        if target not in self.inst_rails:
            raise ValueError(f"unknown stress target {target!r}")
        return [target]

    def _expected_inflow_profile(self) -> dict[str, dict[int, int]]:
        """Each bank's expected large-value inflow per hour (from the scenario's own schedule, i.e. its 'typical day')."""
        prof: dict[str, dict[int, int]] = {i: {} for i in self.institutions}
        for p in self.sc.payments:
            if p.rail in LARGE_VALUE:
                h = _minute_of(self.open_at, p.arrival_at) // 60
                prof[p.receiver][h] = prof[p.receiver].get(h, 0) + p.amount_minor
        return prof

    # ------------------------------------------------------------- scheduling
    def _schedule(self) -> None:
        for p in self.sc.payments:
            self._push(p.arrival_at, EventPhase.PAYMENT_ARRIVAL, "arrival", p)
        rng = DeterministicRandomStream(derive_stream_seed(self.sc.seed, f"stress:{self.stress.name}"))
        for k, s in enumerate(self.stress.shocks):
            if isinstance(s, RailOutage):
                self._push(self.open_at + timedelta(minutes=s.start_min), EventPhase.SYSTEM_STATE, "rail_down", s.rail)
                self._push(self.open_at + timedelta(minutes=s.end_min), EventPhase.SYSTEM_STATE, "rail_up", s.rail)
            elif isinstance(s, ParticipantOutage):
                for inst in self._resolve(s.institution):
                    self.blocked_senders[inst] = (s.start_min, s.end_min)
            elif isinstance(s, MessagingDelay):
                self.messaging_delay[s.rail] = (s.start_min, s.end_min)
            elif isinstance(s, (LiquidityWithdrawal, CreditLineCut, LiquidityHoarding)):
                self._push(self.open_at + timedelta(minutes=s.at_min), EventPhase.FUNDING_AND_COLLATERAL, "shock", s)
            elif isinstance(s, ConcentratedOutflows):
                from atlas.scenario.nexus_pay import ScenarioPayment
                inst = self._resolve(s.institution)[0]
                others = [i for i in self.institutions if i != inst]
                at = self.open_at + timedelta(minutes=s.at_min)
                for j in range(s.count):
                    recv = others[rng.randbelow(len(others))]
                    amt = self.sc.config.large_value_median_minor * s.amount_multiplier * (75 + rng.randbelow(50)) // 100
                    sp = ScenarioPayment(f"{inst}-rtgs-shock{k}-{j:03d}", "rtgs", inst, recv, amt,
                                         at + timedelta(seconds=j), min(self.close_at, at + timedelta(minutes=60)), 1)
                    self.extra_payments.append(sp)
                    self._push(sp.arrival_at, EventPhase.PAYMENT_ARRIVAL, "arrival", sp)
        t = self.open_at
        minute = 0
        while t <= self.close_at:
            s = self.settings
            if minute % s.tick_min == 0:
                self._push(t, EventPhase.SETTLEMENT, "settle", minute)
            if self.controller is not None and minute % s.controller_interval_min == 0:
                self._push(t, EventPhase.ELIGIBILITY_AND_QUEUE, "control", minute)
            if minute % s.decision_interval_min == 0:
                self._push(t, EventPhase.PARTICIPANT_DECISION, "decide", minute)
            if minute % s.snapshot_every_min == 0:
                self._push(t, EventPhase.MONITORING_AND_SNAPSHOT, "snapshot", minute)
            t += timedelta(minutes=1)
            minute += 1
        self._push(self.close_at, EventPhase.MONITORING_AND_SNAPSHOT, "close", None)

    # ------------------------------------------------------------------- run
    def run(self) -> SimulationResult:
        started = _time.perf_counter()
        self._schedule()
        while self.heap:
            ts, phase, _, kind, data = heapq.heappop(self.heap)
            at = datetime.fromtimestamp(ts, tz=self.open_at.tzinfo)
            getattr(self, f"_on_{kind}")(at, data)
        if self.store is not None:
            self.store.append_many(self.events)
        return self._result(_time.perf_counter() - started)

    # -------------------------------------------------------------- handlers
    def _on_rail_down(self, at: datetime, rail: str) -> None:
        self.rail_up[rail] = False
        self._emit("RailOutageStarted", rail, "payment_rail", at, {"rail_id": rail})

    def _on_rail_up(self, at: datetime, rail: str) -> None:
        self.rail_up[rail] = True
        self._emit("RailOutageEnded", rail, "payment_rail", at, {"rail_id": rail})

    def _on_shock(self, at: datetime, s: Any) -> None:
        meta = lambda: dict(at=at, event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                            simulation_id=self.simulation_id, correlation_id=self.simulation_id, causation_id=None)
        if isinstance(s, LiquidityWithdrawal):
            for inst in self._resolve(s.target):
                for rail in s.rails:
                    if rail not in self.inst_rails[inst]:
                        continue
                    acct = self.ledger.account(self._acct(inst, rail))
                    cut = acct.cash_available_minor * s.share_bp // 10_000
                    if cut > 0:
                        _, ev = adjustment_event(acct, -cut, "stress:liquidity_withdrawal", **meta())
                        self._commit(ev)
        elif isinstance(s, CreditLineCut):
            for inst in self._resolve(s.target):
                acct = self.ledger.account(self._acct(inst, "rtgs"))
                target = max(acct.intraday_credit_used_minor, acct.credit_limit_minor * (10_000 - s.cut_bp) // 10_000)
                if target != acct.credit_limit_minor:
                    _, ev = credit_limit_event(acct, target, "stress:credit_line_cut", **meta())
                    self._commit(ev)
        elif isinstance(s, LiquidityHoarding):
            rng = DeterministicRandomStream(derive_stream_seed(self.sc.seed, "stress:hoarding"))
            pool = list(self.institutions)
            n = len(pool) * s.share_bp // 10_000
            chosen = []
            for _ in range(n):
                chosen.append(pool.pop(rng.randbelow(len(pool))))
            for inst in sorted(chosen):
                self.strategies[inst] = LiquidityConservative(buffer_bp=s.buffer_bp)
                self.stress_signal.add(inst)
            self._emit("StressSignalRaised", "system", "stress", at, {"institutions": sorted(chosen), "kind": "liquidity_hoarding"})

    def _blocked(self, inst: str, at: datetime) -> bool:
        w = self.blocked_senders.get(inst)
        m = _minute_of(self.open_at, at)
        return w is not None and w[0] <= m < w[1]

    def _make_instruction(self, p) -> PaymentInstruction:
        return PaymentInstruction(
            payment_id=p.payment_id, end_to_end_id=f"E2E-{p.payment_id}", instruction_id=f"INS-{p.payment_id}",
            sender_institution_id=p.sender, receiver_institution_id=p.receiver,
            sender_account_id=self._acct(p.sender, p.rail), receiver_account_id=self._acct(p.receiver, p.rail),
            payment_rail_id=p.rail, currency="USD", amount_minor=p.amount_minor, priority=min(p.priority, 2),
            created_at=p.arrival_at, due_at=max(p.due_at, p.arrival_at), scenario_id=self.sc.scenario_id,
        )

    def _on_arrival(self, at: datetime, p: Any) -> None:
        delay = self.messaging_delay.get(p.rail)
        m = _minute_of(self.open_at, at)
        if delay and delay[0] <= m < delay[1] and p.payment_id not in self.meta:
            self.meta[p.payment_id] = {"rail": p.rail, "sender": p.sender, "receiver": p.receiver, "amount": p.amount_minor,
                                       "arrival": p.arrival_at, "due": p.due_at, "priority": p.priority, "status": "delayed"}
            self._push(self.open_at + timedelta(minutes=delay[1]), EventPhase.PAYMENT_ARRIVAL, "arrival", p)
            return
        pay = self._make_instruction(p)
        if p.payment_id in self.seen_ids and self.meta.get(p.payment_id, {}).get("status") != "delayed":
            self.counters["rejected"] += 1
            self._emit("PaymentRejected", p.payment_id, "payment", at, {"payment_id": p.payment_id, "reason": "duplicate payment id"})
            return
        self.seen_ids.add(p.payment_id)
        self.meta[p.payment_id] = {"rail": p.rail, "sender": p.sender, "receiver": p.receiver, "amount": p.amount_minor,
                                   "arrival": p.arrival_at, "due": p.due_at, "priority": p.priority, "status": "created",
                                   "settled_at": None}
        self.payments[p.payment_id] = pay
        if p.rail in INSTANT:
            self._instant(at, pay)
        else:
            self.held[p.sender][p.payment_id] = HeldPayment(p.payment_id, p.rail, p.amount_minor, p.priority, p.due_at, p.arrival_at)

    def _reject(self, at: datetime, pay: PaymentInstruction, reason: str, instant: bool = False) -> None:
        self.payments[pay.payment_id] = transition_payment(pay, PaymentStatus.REJECTED) if pay.status in (PaymentStatus.CREATED, PaymentStatus.VALIDATED) else pay
        self.meta[pay.payment_id]["status"] = "rejected"
        self.meta[pay.payment_id]["reason"] = reason
        self.counters["rejected"] += 1
        if instant:
            self.counters["instant_rejected"] += 1
            self.counters["instant_rejected_value_minor"] += pay.amount_minor
        self._emit("PaymentRejected", pay.payment_id, "payment", at, {"payment_id": pay.payment_id, "rail_id": pay.payment_rail_id,
                                                                     "amount_minor": pay.amount_minor, "reason": reason})

    def _instant(self, at: datetime, pay: PaymentInstruction) -> None:
        rail = self.rails[pay.payment_rail_id]
        if self._blocked(pay.sender_institution_id, at):
            return self._reject(at, pay, "sender operational outage", instant=True)
        sender = self.ledger.accounts.get(pay.sender_account_id)
        receiver = self.ledger.accounts.get(pay.receiver_account_id)
        res = rail.settle(pay, sender, receiver, at=at, event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                          simulation_id=self.simulation_id, service_available=self.rail_up[pay.payment_rail_id])  # type: ignore[attr-defined]
        if res.settlement is None:
            return self._reject(at, pay, res.admission.reason, instant=True)
        self._settled(at, res.settlement)
        self._instant_out_window[pay.sender_account_id] = self._instant_out_window.get(pay.sender_account_id, 0) + pay.amount_minor

    def _settled(self, at: datetime, settlement) -> None:
        self._commit(settlement.event)
        pay = settlement.payment
        self.payments[pay.payment_id] = pay
        m = self.meta[pay.payment_id]
        m["status"], m["settled_at"] = "settled", at
        self._inflow(pay.receiver_institution_id, pay.payment_rail_id, pay.amount_minor, at)

    def _inflow(self, inst: str, rail: str, amount: int, at: datetime) -> None:
        d = self.inflow_since_last[inst]
        d[rail] = d.get(rail, 0) + amount
        if rail in LARGE_VALUE:
            self.inflow_log[inst].append((at, amount))

    # -- decisions
    def _view(self, inst: str, at: datetime) -> BankView:
        rails = [r for r in self.inst_rails[inst] if r in LARGE_VALUE]
        accts = {r: self.ledger.account(self._acct(inst, r)) for r in rails}
        queued = {r: 0 for r in rails}
        for r in rails:
            for pid in self.queue[r]:
                if self.meta[pid]["sender"] == inst:
                    queued[r] += self.meta[pid]["amount"]
        log = self.inflow_log[inst]
        hour_ago = at - timedelta(hours=1)
        while log and log[0][0] < hour_ago:
            log.pop(0)
        inflow_hour = sum(a for t, a in log if t >= hour_ago)
        h = _minute_of(self.open_at, at) // 60
        expected = self.expected_inflow_hour[inst].get(h - 1, 0) if h >= 1 else 0
        opening = {a.payment_rail_id: a.ledger_balance_minor for a in self.opening if a.institution_id == inst and a.payment_rail_id in rails}
        return BankView(inst, at, tuple(self.held[inst].values()), {r: a.cash_available_minor for r, a in accts.items()},
                        {r: a.undrawn_credit_minor for r, a in accts.items()}, opening, dict(self.inflow_since_last[inst]),
                        inflow_hour, expected, queued, inst in self.stress_signal)

    def _on_decide(self, at: datetime, minute: int) -> None:
        for inst in self.institutions:
            if not self.held[inst] or self._blocked(inst, at):
                self.inflow_since_last[inst] = {}
                continue
            strategy = self.strategies[inst]
            view = self._view(inst, at)
            release = strategy.decide(view)
            self.inflow_since_last[inst] = {}
            if getattr(strategy, "uses_facility", False):
                self._maybe_draw(inst, at, release)
            for pid in release:
                hp = self.held[inst].pop(pid, None)
                if hp is None:
                    continue
                self._release(at, self.payments[pid])

    def _maybe_draw(self, inst: str, at: datetime, release: list[str]) -> None:
        need = sum(self.held[inst][pid].amount_minor for pid in release if pid in self.held[inst] and self.held[inst][pid].rail == "rtgs")
        acct = self.ledger.account(self._acct(inst, "rtgs"))
        queued = sum(self.meta[pid]["amount"] for pid in self.queue["rtgs"] if self.meta[pid]["sender"] == inst)
        shortfall = need + queued - acct.available_balance_minor
        fac = self.facilities[inst]
        amount = min(shortfall, fac.available_capacity_minor)
        if amount <= 0:
            return
        op = draw_funding(fac, acct, amount, at=at, event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                          simulation_id=self.simulation_id, correlation_id=self.simulation_id)
        self.facilities[inst] = op.facility
        self._commit(op.event)
        self.facility_draw_times[inst].append((at, amount))
        self.counters["facility_drawn_minor"] += amount

    def _release(self, at: datetime, pay: PaymentInstruction) -> None:
        rail = self.rails[pay.payment_rail_id]
        reason = rail.common_rejection(pay, self.ledger.accounts.get(pay.sender_account_id),
                                       self.ledger.accounts.get(pay.receiver_account_id), at)
        if reason:
            return self._reject(at, pay, reason)
        pay = transition_payment(transition_payment(pay, PaymentStatus.VALIDATED), PaymentStatus.QUEUED)
        self.payments[pay.payment_id] = pay
        self.queue[pay.payment_rail_id][pay.payment_id] = self.submitted
        self.submitted += 1
        self.meta[pay.payment_id]["status"] = "queued"
        self.meta[pay.payment_id]["released_at"] = at
        self._emit("PaymentReleased", pay.payment_id, "payment", at,
                   {"payment_id": pay.payment_id, "rail_id": pay.payment_rail_id, "amount_minor": pay.amount_minor})

    # -- settlement
    def _gross_pass(self, at: datetime) -> int:
        q = self.queue["rtgs"]
        if not q or not self.rail_up["rtgs"]:
            return 0
        policy = self.settings.policy
        settled_total = 0
        while True:
            if policy in ("fifo", "fifo_strict"):
                order = sorted(q, key=q.__getitem__)
            else:
                order = sorted(q, key=lambda pid: (-self.payments[pid].priority, self.payments[pid].due_at, q[pid]))
            blocked: set[str] = set()
            progressed = 0
            for pid in order:
                pay = self.payments[pid]
                if policy == "fifo_strict" and pay.sender_institution_id in blocked:
                    continue
                s = self.ledger.account(pay.sender_account_id)
                use_credit = self.settings.use_intraday_credit
                covered = s.cash_available_minor + (s.undrawn_credit_minor if use_credit else 0) >= pay.amount_minor
                if not covered:
                    blocked.add(pay.sender_institution_id)
                    continue
                pending = PaymentRail.to_settlement_pending(pay)
                res = settle_cash_transfer(pending, s, self.ledger.account(pay.receiver_account_id), settled_at=at,
                                           event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                                           simulation_id=self.simulation_id, correlation_id=self.simulation_id,
                                           allow_intraday_credit=use_credit)
                del q[pid]
                self._settled(at, res)
                progressed += 1
            settled_total += progressed
            if progressed == 0:
                return settled_total

    def _obligations(self, rail: str) -> list[Obligation]:
        return [Obligation(pid, self.payments[pid].sender_account_id, self.payments[pid].receiver_account_id,
                           self.payments[pid].amount_minor, self.payments[pid].priority, self.payments[pid].due_at, seq)
                for pid, seq in sorted(self.queue[rail].items(), key=lambda kv: kv[1])]

    def _net(self, at: datetime, rail: str, algorithm: str, engine: LiquiditySavingRail, selected_ids: list[str] | None = None) -> int:
        q = self.queue[rail]
        if not q or not self.rail_up[rail]:
            return 0
        obligations = self._obligations(rail)
        if selected_ids is not None:
            keep = set(selected_ids)
            chosen = [o for o in obligations if o.obligation_id in keep]
        else:
            available = {o: self.ledger.account(o).cash_available_minor for o in {x.payer for x in obligations} | {x.payee for x in obligations}}
            if algorithm == "bilateral":
                sel = bilateral_offsets(obligations, available)
            elif algorithm == "milp":
                sel = partial_netting_milp(obligations, available)
            else:
                sel = partial_netting_heuristic(obligations, available)
            chosen = list(sel.selected)
        if not chosen:
            return 0
        pays = [self.payments[o.obligation_id] for o in chosen]
        accounts = {a: self.ledger.account(a) for a in {p.sender_account_id for p in pays} | {p.receiver_account_id for p in pays}}
        res = engine.process_cycle(pays, accounts, at=at, simulation_id=self.simulation_id, event_id=f"{self.simulation_id}#{self.seq}",
                                   sequence_number=self.seq)
        if res.batch is None:
            return 0
        self._commit(res.batch.event)
        self.counters["netting_cycles"] += 1
        self.counters["netting_value_minor"] += res.batch.gross_value_minor
        self.counters["netting_cash_used_minor"] += res.batch.net_debit_value_minor
        for pay in res.batch.payments:
            del q[pay.payment_id]
            self.payments[pay.payment_id] = pay
            m = self.meta[pay.payment_id]
            m["status"], m["settled_at"] = "settled", at
            self._inflow(pay.receiver_institution_id, rail, pay.amount_minor, at)
        return len(res.batch.payments)

    def _on_settle(self, at: datetime, minute: int) -> None:
        s = self.settings
        self._gross_pass(at)
        if s.policy in ("bilateral", "multilateral", "multilateral_milp") and minute % s.rtgs_netting_every_min == 0:
            algo = {"bilateral": "bilateral", "multilateral": "heuristic", "multilateral_milp": "milp"}[s.policy]
            if self._net(at, "rtgs", algo, self.rtgs_netting):
                self._gross_pass(at)
        if minute % s.lsm_cycle_min == 0:
            self._net(at, "lsm", s.lsm_algorithm, self.rails["lsm"])  # type: ignore[arg-type]
        if self.queue["rtgs"] and self.rail_up["rtgs"]:
            # gridlock indicator: queue non-empty and no single queued payment is coverable gross
            coverable = any(
                self.ledger.account(self.payments[pid].sender_account_id).available_balance_minor >= self.payments[pid].amount_minor
                for pid in self.queue["rtgs"]
            )
            if not coverable:
                self.counters["gridlock_ticks"] += 1

    # -- control
    def _on_control(self, at: datetime, minute: int) -> None:
        for acct, v in self.instant_outflow_hist.items():
            v.append(self._instant_out_window.pop(acct, 0))
        view = SystemView(at, self.close_at, self.ledger.accounts, tuple(self.payments[p] for p in self.queue["rtgs"]),
                          tuple(self.payments[p] for p in self.queue["lsm"]), {i: tuple(h.values()) for i, h in self.held.items()},
                          dict(self.rail_up), self.instant_outflow_hist)
        for action in self.controller.propose(view):  # type: ignore[union-attr]
            verdict = self.safety.validate(action, view)
            entry = {"at": at.isoformat(), "kind": action.kind, "approved": verdict.approved, "reason": verdict.reason,
                     "rationale": action.rationale, "controller": getattr(self.controller, "name", "controller"),
                     "payment_count": len(action.payment_ids), "amount_minor": action.amount_minor,
                     "institution": action.institution, "from_rail": action.from_rail, "to_rail": action.to_rail}
            self.controller_log.append(entry)
            self.counters["controller_actions"] += 1
            if not verdict.approved:
                self.counters["controller_rejected"] += 1
                self._emit("ControlActionRejected", action.institution or "system", "control", at,
                           {"kind": action.kind, "reason": verdict.reason, "payment_count": len(action.payment_ids)})
                continue
            if action.kind == "settle_batch":
                self._net(at, "rtgs", "given", self.rtgs_netting, selected_ids=list(action.payment_ids))
            elif action.kind == "transfer":
                self._transfer(at, action)
            view = SystemView(at, self.close_at, self.ledger.accounts, tuple(self.payments[p] for p in self.queue["rtgs"]),
                              tuple(self.payments[p] for p in self.queue["lsm"]), view.held, dict(self.rail_up), self.instant_outflow_hist)

    def _transfer(self, at: datetime, a: Action) -> None:
        meta = lambda: dict(at=at, event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                            simulation_id=self.simulation_id, correlation_id=f"transfer:{self.seq}", causation_id=None)
        src = self.ledger.account(self._acct(a.institution, a.from_rail))
        _, ev = adjustment_event(src, -a.amount_minor, f"intra-institution transfer to {a.to_rail}", **meta())
        self._commit(ev)
        dst = self.ledger.account(self._acct(a.institution, a.to_rail))
        _, ev2 = adjustment_event(dst, a.amount_minor, f"intra-institution transfer from {a.from_rail}", **meta())
        self._commit(ev2)
        self.counters["transfers_minor"] += a.amount_minor

    # -- monitoring / close
    def _sample(self, at: datetime) -> dict:
        row: dict[str, Any] = {"t": at.isoformat(), "minute": _minute_of(self.open_at, at)}
        for rail in self.rails:
            accts = [a for a in self.ledger.accounts.values() if a.payment_rail_id == rail]
            row[f"{rail}_cash_minor"] = sum(a.ledger_balance_minor for a in accts)
            row[f"{rail}_credit_used_minor"] = sum(a.intraday_credit_used_minor for a in accts)
        for rail in LARGE_VALUE:
            row[f"{rail}_queued_value_minor"] = sum(self.meta[p]["amount"] for p in self.queue[rail])
            row[f"{rail}_queued_count"] = len(self.queue[rail])
        row["held_value_minor"] = sum(h.amount_minor for d in self.held.values() for h in d.values())
        row["settled_value_minor"] = sum(m["amount"] for m in self.meta.values() if m["status"] == "settled")
        row["settled_count"] = sum(1 for m in self.meta.values() if m["status"] == "settled")
        return row

    def _on_snapshot(self, at: datetime, minute: int) -> None:
        self.timeseries.append(self._sample(at))

    def _on_close(self, at: datetime, _: Any) -> None:
        # Final settlement attempt already ran at this timestamp (SETTLEMENT phase precedes MONITORING).
        for inst in self.institutions:
            for pid in list(self.held[inst]):
                self.held[inst].pop(pid)
                self._expire(at, pid, "held by sender at close")
        for rail in LARGE_VALUE:
            for pid in list(self.queue[rail]):
                del self.queue[rail][pid]
                self._expire(at, pid, "unsettled in central queue at close")
        meta = lambda: dict(at=at, event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                            simulation_id=self.simulation_id, correlation_id=self.simulation_id, causation_id=None)
        for inst in self.institutions:
            fac = self.facilities[inst]
            if fac.drawn_amount_minor:
                acct = self.ledger.account(self._acct(inst, "rtgs"))
                amount = min(fac.repayable_amount_minor, acct.cash_available_minor)
                for t, amt in self.facility_draw_times[inst]:
                    secs = max(1, int((at - t).total_seconds()))
                    self.counters["facility_interest_minor"] += calculate_simple_funding_cost(amt, fac.annual_rate_basis_points, secs).cost_minor
                if amount > 0:
                    op = repay_funding(fac, acct, amount, at=at, event_id=f"{self.simulation_id}#{self.seq}", sequence_number=self.seq,
                                       simulation_id=self.simulation_id, correlation_id=self.simulation_id)
                    self.facilities[inst] = op.facility
                    self._commit(op.event)
        for acct_id in sorted(self.ledger.accounts):
            acct = self.ledger.account(acct_id)
            if acct.intraday_credit_used_minor:
                rep = credit_repayment_event(acct, **meta())
                if rep:
                    self._commit(rep[1])
        self.timeseries.append(self._sample(at))
        self._emit("BusinessDayClosed", "system", "simulation", at, {"state_hash": self.ledger.state_hash()})

    def _expire(self, at: datetime, pid: str, reason: str) -> None:
        pay = self.payments[pid]
        if pay.status in (PaymentStatus.QUEUED, PaymentStatus.ELIGIBILITY_CHECKED):
            self.payments[pid] = transition_payment(pay, PaymentStatus.EXPIRED)
        elif pay.status == PaymentStatus.CREATED:
            self.payments[pid] = transition_payment(pay, PaymentStatus.CANCELLED)
        self.meta[pid]["status"] = "unsettled"
        self.meta[pid]["reason"] = reason
        self._emit("PaymentExpired", pid, "payment", at, {"payment_id": pid, "amount_minor": pay.amount_minor, "reason": reason})

    # ---------------------------------------------------------------- metrics
    def _bounds(self) -> tuple[dict[str, int], dict[str, int]]:
        """Upper bound (settle every payment on arrival) and lower bound (end-of-day net) of liquidity need per account."""
        cum: dict[str, int] = {}
        low: dict[str, int] = {}
        for p in sorted(list(self.sc.payments) + self.extra_payments, key=lambda x: (x.arrival_at, x.payment_id)):
            if p.rail not in LARGE_VALUE:
                continue
            s, r = self._acct(p.sender, p.rail), self._acct(p.receiver, p.rail)
            cum[s] = cum.get(s, 0) - p.amount_minor
            cum[r] = cum.get(r, 0) + p.amount_minor
            low[s] = min(low.get(s, 0), cum[s])
        ub = {a: -v for a, v in low.items()}
        lb = {a: max(0, -v) for a, v in cum.items()}
        return ub, lb

    def _result(self, runtime_s: float) -> SimulationResult:
        cost = self.settings.cost
        metas = self.meta
        lv = [m for m in metas.values() if m["rail"] in LARGE_VALUE and m["status"] != "delayed"]
        inst_m = [m for m in metas.values() if m["rail"] in INSTANT]

        def summarize(items: list[dict]) -> dict:
            total_v = sum(m["amount"] for m in items)
            settled = [m for m in items if m["status"] == "settled"]
            delays = sorted(int((m["settled_at"] - m["arrival"]).total_seconds()) for m in settled)
            settled_v = sum(m["amount"] for m in settled)
            vw = sum(m["amount"] * int((m["settled_at"] - m["arrival"]).total_seconds()) for m in settled)
            late = [m for m in items if (m["status"] == "settled" and m["settled_at"] > m["due"]) or m["status"] != "settled"]
            return {
                "count": len(items), "value_minor": total_v, "settled_count": len(settled), "settled_value_minor": settled_v,
                "settlement_rate_count": len(settled) / len(items) if items else 1.0,
                "settlement_rate_value": settled_v / total_v if total_v else 1.0,
                "mean_delay_s": sum(delays) / len(delays) if delays else 0.0,
                "p95_delay_s": delays[int(0.95 * (len(delays) - 1))] if delays else 0,
                "value_weighted_delay_s": vw / settled_v if settled_v else 0.0,
                "deadline_miss_count": len(late), "deadline_miss_value_minor": sum(m["amount"] for m in late),
            }

        by_rail = {r: summarize([m for m in metas.values() if m["rail"] == r and m["status"] != "delayed"]) for r in self.rails}
        ub, lb = self._bounds()
        lu = {a: max(0, -v) for a, v in self.min_cum_net.items()}
        lv_accts = [a.account_id for a in self.opening if a.payment_rail_id in LARGE_VALUE]
        sys_lu = sum(lu[a] for a in lv_accts)
        sys_ub = sum(ub.get(a, 0) for a in lv_accts)
        sys_lb = sum(lb.get(a, 0) for a in lv_accts)
        peak_credit = sum(self.peak_credit.values())

        # costs (integer minor units, rounded down)
        delay_cost = sum(m["amount"] * int((m["settled_at"] - m["arrival"]).total_seconds()) for m in lv if m["status"] == "settled") * cost.delay_bp_per_hour // (3600 * 10_000)
        late_cost = sum(m["amount"] for m in lv if m["status"] == "settled" and m["settled_at"] > m["due"]) * cost.late_penalty_bp // 10_000
        unsettled_v = sum(m["amount"] for m in lv if m["status"] != "settled")
        unsettled_cost = unsettled_v * cost.unsettled_penalty_bp // 10_000
        liq_cost = sys_lu * cost.liquidity_bp_per_day // 10_000
        credit_cost = peak_credit * cost.credit_bp_per_day // 10_000
        instant_cost = self.counters["instant_rejected_value_minor"] * cost.unsettled_penalty_bp // 10_000
        total_cost = delay_cost + late_cost + unsettled_cost + liq_cost + credit_cost + instant_cost + self.counters["facility_interest_minor"]

        metrics = {
            "large_value": summarize(lv), "instant": summarize(inst_m), "by_rail": by_rail,
            "liquidity": {
                "system_liquidity_usage_minor": sys_lu, "upper_bound_minor": sys_ub, "lower_bound_minor": sys_lb,
                # Bounds-based efficiency (Leinonen & Soramaki) is only meaningful when every payment settled.
                "liquidity_efficiency": ((sys_ub - sys_lu) / (sys_ub - sys_lb) if sys_ub > sys_lb else 1.0) if unsettled_v == 0 else None,
                "liquidity_turnover": summarize(lv)["settled_value_minor"] / (sys_lu + peak_credit) if (sys_lu + peak_credit) else 0.0,
                "peak_intraday_credit_minor": peak_credit,
                "opening_large_value_liquidity_minor": sum(a.ledger_balance_minor for a in self.opening if a.payment_rail_id in LARGE_VALUE),
            },
            "costs_minor": {"delay": delay_cost, "late_penalty": late_cost, "unsettled_penalty": unsettled_cost,
                            "liquidity": liq_cost, "intraday_credit": credit_cost, "instant_rejections": instant_cost,
                            "facility_interest": self.counters["facility_interest_minor"], "total": total_cost},
            "counters": dict(self.counters),
            "events": len(self.events), "runtime_s": runtime_s,
            "events_per_second": len(self.events) / runtime_s if runtime_s > 0 else 0.0,
            "replay_contract": {"ledger_events": self.ledger.applied_count, "final_state_hash": self.ledger.state_hash()},
        }
        per_inst = []
        for inst in self.institutions:
            items = [m for m in lv if m["sender"] == inst]
            sm = summarize(items)
            accts = [a for a in self.opening if a.institution_id == inst]
            per_inst.append({
                "institution_id": inst, "tier": next(i.tier for i in self.sc.institutions if i.institution_id == inst),
                "strategy": self.strategies[inst].name, "rails": list(self.inst_rails[inst]),
                "sent_count": sm["count"], "sent_value_minor": sm["value_minor"], "settlement_rate_value": sm["settlement_rate_value"],
                "value_weighted_delay_s": sm["value_weighted_delay_s"],
                "liquidity_usage_minor": sum(lu[a.account_id] for a in accts if a.payment_rail_id in LARGE_VALUE),
                "peak_credit_minor": sum(self.peak_credit[a.account_id] for a in accts),
                "opening_minor": {a.payment_rail_id: a.ledger_balance_minor for a in accts},
                "closing_minor": {a.payment_rail_id: self.ledger.account(a.account_id).ledger_balance_minor for a in accts},
                "received_value_minor": sum(m["amount"] for m in lv if m["receiver"] == inst and m["status"] == "settled"),
            })
        payments = [{"payment_id": pid, "rail": m["rail"], "sender": m["sender"], "receiver": m["receiver"], "amount_minor": m["amount"],
                     "priority": m["priority"], "arrival": m["arrival"].isoformat(), "due": m["due"].isoformat(), "status": m["status"],
                     "settled_at": m["settled_at"].isoformat() if m.get("settled_at") else None, "reason": m.get("reason")}
                    for pid, m in metas.items()]
        manifest = {
            "simulator_version": SIMULATOR_VERSION, "event_ordering": "atlas-event-order-v1",
            "scenario_fingerprint": self.sc.fingerprint(), "generator_version": self.sc.generator_version, "seed": self.sc.seed,
            "python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
            "controller": getattr(self.controller, "name", None), "data_origin": "synthetic",
        }
        return SimulationResult(
            self.simulation_id, self.sc.summary(), self.settings.to_dict() | {"strategy": self.settings.strategy},
            self.stress.to_dict(), metrics, per_inst, self.timeseries, payments, self.opening, tuple(self.events),
            self.ledger.state_hash(), manifest, self.controller_log,
        )


def run_day(scenario: Scenario, settings: SimulationSettings = SimulationSettings(), stress: StressScenario | None = None, **kw) -> SimulationResult:
    return DaySimulator(scenario, settings, stress, **kw).run()
