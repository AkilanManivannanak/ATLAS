"""Deterministic synthetic multi-rail workload generator (``nexus-pay-gen-v1``).

Modeling choices (all synthetic and documented in docs/18_benchmark_specification.md):

* **Topology.** Institutions are split into a small *core* tier and a *periphery*
  tier. Counterparty choice uses size-proportional weights, which yields the
  heavy-tailed, core-periphery structure commonly reported for interbank payment
  networks (e.g. Soramäki et al., 2007, "The topology of interbank payment flows",
  Physica A 379). We reproduce the *shape*, not any real network's statistics.
* **Arrivals.** Each bank has an independent named random stream. Intraday
  arrival intensity follows a configurable piecewise profile with a morning ramp
  and an afternoon peak.
* **Amounts.** Log-normal draws (Box–Muller from two uint64-derived uniforms),
  rounded to integer minor units. Floating point is used only *inside sampling*;
  every amount that enters the ledger is an integer.
* **Liquidity.** Opening balances are a configurable fraction of each account's
  expected gross daily outflow, so liquidity stress is controlled, not accidental.

Same config + seed => byte-identical scenario (verified by ``Scenario.fingerprint``).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from atlas.simulation.rng import DeterministicRandomStream, derive_stream_seed

GENERATOR_VERSION = "nexus-pay-gen-v1"
RAIL_KINDS = ("rtgs", "lsm", "fednow", "rtp")
_TZ = "America/New_York"


@dataclass(frozen=True, slots=True)
class NexusPayConfig:
    n_institutions: int = 16
    core_fraction_bp: int = 2_500                 # share of institutions in the core tier (basis points)
    core_size_multiplier: int = 6                 # relative activity of a core bank vs periphery
    payments_per_day: int = 3_000                 # large-value (rtgs+lsm) payments
    instant_payments_per_day: int = 2_000         # fednow+rtp payments
    lsm_share_bp: int = 3_500                     # share of large-value payments routed to the LSM rail
    rtp_share_bp: int = 4_500                     # share of instant payments routed to RTP
    rtp_participation_bp: int = 7_500             # share of institutions on the RTP rail
    business_date: date = date(2026, 3, 10)       # a Tuesday
    day_open: time = time(8, 0)
    day_close: time = time(18, 30)
    large_value_median_minor: int = 2_500_000_00  # $2.5m
    large_value_sigma_milli: int = 1_100          # log-normal sigma * 1000
    instant_median_minor: int = 15_000_00         # $15k
    instant_sigma_milli: int = 1_000
    opening_liquidity_bp: int = 1_800             # opening balance as share of expected gross outflow
    instant_prefunding_bp: int = 2_500
    credit_limit_bp: int = 1_000                  # RTGS intraday credit line as share of expected outflow
    urgent_share_bp: int = 1_200
    fednow_limit_minor: int = 1_000_000_00        # simulator assumption, configurable
    rtp_limit_minor: int = 10_000_000_00          # simulator assumption, configurable

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.n_institutions < 2:
            raise ValueError("at least two institutions are required")
        if self.day_open >= self.day_close:
            raise ValueError("day_open must precede day_close")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["business_date"] = self.business_date.isoformat()
        d["day_open"] = self.day_open.isoformat()
        d["day_close"] = self.day_close.isoformat()
        return d


@dataclass(frozen=True, slots=True)
class InstitutionSpec:
    institution_id: str
    name: str
    tier: str
    size_weight: int
    rails: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccountSpec:
    account_id: str
    institution_id: str
    rail: str
    opening_balance_minor: int
    credit_limit_minor: int


@dataclass(frozen=True, slots=True)
class ScenarioPayment:
    payment_id: str
    rail: str
    sender: str
    receiver: str
    amount_minor: int
    arrival_at: datetime
    due_at: datetime
    priority: int


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    seed: int
    config: NexusPayConfig
    institutions: tuple[InstitutionSpec, ...]
    accounts: tuple[AccountSpec, ...]
    payments: tuple[ScenarioPayment, ...]
    open_at: datetime
    close_at: datetime
    generator_version: str = GENERATOR_VERSION
    labels: dict = field(default_factory=lambda: {"data_origin": "synthetic", "observed_financial_data": False})

    def account_id(self, institution_id: str, rail: str) -> str:
        return f"{institution_id}:{rail}"

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(json.dumps(self.config.to_dict(), sort_keys=True).encode())
        h.update(str(self.seed).encode())
        for a in self.accounts:
            h.update(f"{a.account_id}|{a.opening_balance_minor}|{a.credit_limit_minor}".encode())
        for p in self.payments:
            h.update(f"{p.payment_id}|{p.rail}|{p.sender}|{p.receiver}|{p.amount_minor}|{p.arrival_at.isoformat()}|{p.due_at.isoformat()}|{p.priority}".encode())
        return h.hexdigest()

    def summary(self) -> dict:
        by_rail: dict[str, dict[str, int]] = {}
        for p in self.payments:
            r = by_rail.setdefault(p.rail, {"count": 0, "value_minor": 0})
            r["count"] += 1
            r["value_minor"] += p.amount_minor
        return {
            "scenario_id": self.scenario_id, "seed": self.seed, "generator_version": self.generator_version,
            "institutions": len(self.institutions), "accounts": len(self.accounts), "payments": len(self.payments),
            "by_rail": by_rail, "fingerprint": self.fingerprint(), **self.labels,
        }


class _Sampler:
    """Float sampling helpers on top of the integer SplitMix64 stream (sampling only)."""

    def __init__(self, stream: DeterministicRandomStream) -> None:
        self.s = stream

    def uniform(self) -> float:
        return (self.s.next_uint64() >> 11) * (1.0 / (1 << 53))

    def normal(self) -> float:
        u1 = max(self.uniform(), 1e-300)
        u2 = self.uniform()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def lognormal_minor(self, median_minor: int, sigma_milli: int) -> int:
        value = median_minor * math.exp(self.normal() * sigma_milli / 1000.0)
        return max(100, int(round(value)))  # at least 1.00 major unit

    def choice_weighted(self, items: list, weights: list[int]):
        total = sum(weights)
        pick = self.s.randbelow(total)
        acc = 0
        for item, w in zip(items, weights):
            acc += w
            if pick < acc:
                return item
        return items[-1]

    def bp(self, basis_points: int) -> bool:
        return self.s.randbelow(10_000) < basis_points


# Relative intraday intensity per hour from 08:00 (shape assumption, not observed data).
_INTRADAY_PROFILE = (6, 10, 12, 11, 9, 8, 9, 12, 14, 9, 4)


def _arrival_offset_seconds(sampler: _Sampler, day_seconds: int) -> int:
    weights = list(_INTRADAY_PROFILE)
    bucket = sampler.choice_weighted(list(range(len(weights))), weights)
    bucket_len = day_seconds / len(weights)
    return min(day_seconds - 1, int(bucket * bucket_len + sampler.uniform() * bucket_len))


def generate_scenario(config: NexusPayConfig = NexusPayConfig(), seed: int = 7, scenario_id: str | None = None,
                      topology_seed: int | None = None) -> Scenario:
    """``topology_seed`` fixes institutions/rails across days while ``seed`` drives that day's arrivals (multi-day panels)."""
    tz = ZoneInfo(_TZ)
    open_at = datetime.combine(config.business_date, config.day_open, tz).astimezone(UTC)
    close_at = datetime.combine(config.business_date, config.day_close, tz).astimezone(UTC)
    day_seconds = int((close_at - open_at).total_seconds())
    root = _Sampler(DeterministicRandomStream(derive_stream_seed(seed if topology_seed is None else topology_seed, "nexus:topology")))

    n_core = max(1, config.n_institutions * config.core_fraction_bp // 10_000)
    institutions: list[InstitutionSpec] = []
    for i in range(config.n_institutions):
        core = i < n_core
        rails = ["rtgs", "lsm", "fednow"]
        if core or root.bp(config.rtp_participation_bp):
            rails.append("rtp")
        size = config.core_size_multiplier * 10 + root.s.randbelow(10) if core else 10 + root.s.randbelow(10)
        institutions.append(
            InstitutionSpec(f"bank-{i:03d}", f"Synthetic {'Core' if core else 'Regional'} Bank {i:03d}",
                            "core" if core else "periphery", size, tuple(rails))
        )
    inst_ids = [x.institution_id for x in institutions]
    weights = [x.size_weight for x in institutions]
    total_w = sum(weights)
    rails_of = {x.institution_id: x.rails for x in institutions}

    payments: list[ScenarioPayment] = []
    for inst in institutions:
        sampler = _Sampler(DeterministicRandomStream(derive_stream_seed(seed, f"nexus:arrivals:{inst.institution_id}")))
        n_large = round(config.payments_per_day * inst.size_weight / total_w)
        n_instant = round(config.instant_payments_per_day * inst.size_weight / total_w)
        for k in range(n_large + n_instant):
            large = k < n_large
            others = [j for j in inst_ids if j != inst.institution_id]
            ow = [weights[inst_ids.index(j)] for j in others]
            if large:
                rail = "lsm" if sampler.bp(config.lsm_share_bp) else "rtgs"
            else:
                rail = "rtp" if ("rtp" in inst.rails and sampler.bp(config.rtp_share_bp)) else "fednow"
            if rail == "rtp":
                pairs = [(j, w) for j, w in zip(others, ow) if "rtp" in rails_of[j]]
                if not pairs:
                    rail = "fednow"
                else:
                    others, ow = [p[0] for p in pairs], [p[1] for p in pairs]
            receiver = sampler.choice_weighted(others, ow)
            if large:
                amount = sampler.lognormal_minor(config.large_value_median_minor, config.large_value_sigma_milli)
            else:
                limit = config.rtp_limit_minor if rail == "rtp" else config.fednow_limit_minor
                amount = min(limit, sampler.lognormal_minor(config.instant_median_minor, config.instant_sigma_milli))
            offset = _arrival_offset_seconds(sampler, day_seconds)
            arrival = open_at + timedelta(seconds=offset)
            urgent = large and sampler.bp(config.urgent_share_bp)
            if large:
                window = timedelta(minutes=30) if urgent else timedelta(minutes=90 + sampler.s.randbelow(150))
                due = min(close_at, arrival + window)
                priority = 2 if urgent else 1
            else:
                due, priority = arrival, 3
            payments.append(ScenarioPayment(f"{inst.institution_id}-{rail}-{k:05d}", rail, inst.institution_id, receiver,
                                            amount, arrival, due, priority))
    payments.sort(key=lambda p: (p.arrival_at, p.payment_id))

    # Opening liquidity sized from expected gross outflow per account.
    outflow: dict[tuple[str, str], int] = {}
    for p in payments:
        outflow[(p.sender, p.rail)] = outflow.get((p.sender, p.rail), 0) + p.amount_minor
    accounts: list[AccountSpec] = []
    for inst in institutions:
        for rail in inst.rails:
            gross = outflow.get((inst.institution_id, rail), 0)
            share = config.instant_prefunding_bp if rail in ("fednow", "rtp") else config.opening_liquidity_bp
            credit = gross * config.credit_limit_bp // 10_000 if rail == "rtgs" else 0
            accounts.append(AccountSpec(f"{inst.institution_id}:{rail}", inst.institution_id, rail,
                                        max(1_000_000_00 if rail in ("rtgs", "lsm") else 100_000_00, gross * share // 10_000), credit))
    return Scenario(
        scenario_id=scenario_id or f"nexus-{seed}", seed=seed, config=config, institutions=tuple(institutions),
        accounts=tuple(accounts), payments=tuple(payments), open_at=open_at, close_at=close_at,
    )
