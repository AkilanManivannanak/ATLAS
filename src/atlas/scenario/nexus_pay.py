"""Deterministic synthetic multi-rail workload generator (``nexus-pay-gen-v2``; v1 retained).

v2 realism upgrades (docs/18_benchmark_specification.md, "Generator v2"):

* persistent, heavy-tailed bilateral relationships fixed by the topology seed;
* a market-wide and a bank-specific AR(1) intraday activity factor on 15-minute
  buckets plus a day-level volume shock, so arrivals are autocorrelated in time
  and correlated across banks (forecastable, unlike v1's independent arrivals);
* payment types: customer transfers (earlier cutoff), interbank transfers, and
  timed obligations with hard settlement deadlines (ancillary-system style);
* round-number amount clustering;
* opening liquidity and credit sized from the *expected* outflow implied by the
  topology, never from the realised day (v1 leaked the day's own volume);
* rail limits from public sources: FedNow network limit $10M since 2025-11-12,
  RTP $10M; participant-chosen lower FedNow limits are a simulator assumption.

v1 description:

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

import bisect
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from atlas.simulation.rng import DeterministicRandomStream, derive_stream_seed

GENERATOR_VERSION = "nexus-pay-gen-v2"
GENERATOR_VERSIONS = {"v1": "nexus-pay-gen-v1", "v2": "nexus-pay-gen-v2"}
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
    fednow_limit_minor: int = 10_000_000_00       # FedNow network limit since 2025-11-12 (frbservices.org)
    rtp_limit_minor: int = 10_000_000_00          # RTP network limit (The Clearing House, 2025)
    generator: str = "v2"                         # "v1" reproduces the original generator exactly
    # ---- v2 parameters (all simulator assumptions unless noted)
    day_volume_sigma_milli: int = 150             # day-level lognormal volume shock
    intraday_phi_milli: int = 800                 # AR(1) persistence of 15-min log-activity
    market_sigma_milli: int = 300                 # market-wide innovation sd
    bank_sigma_milli: int = 200                   # bank-specific innovation sd
    relationship_sigma_milli: int = 1_000         # dispersion of persistent bilateral relationship strengths
    customer_share_bp: int = 5_500                # large-value payments that are customer transfers
    customer_cutoff: time = time(18, 0)           # customer transfers must settle before this
    timed_share_bp: int = 800                     # large-value payments that are timed obligations
    round_amount_share_bp: int = 1_500            # amounts rounded to $100k (LV) or $1k (instant)
    collateralized_credit_bp: int = 6_000         # share of the RTGS credit line backed by pledged collateral
    flow_imbalance_milli: int = 100               # lognormal sd of each bank's expected net position (0 = perfectly balanced)

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.n_institutions < 2:
            raise ValueError("at least two institutions are required")
        if self.day_open >= self.day_close:
            raise ValueError("day_open must precede day_close")
        if self.generator not in GENERATOR_VERSIONS:
            raise ValueError(f"generator must be one of {sorted(GENERATOR_VERSIONS)}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["business_date"] = self.business_date.isoformat()
        d["day_open"] = self.day_open.isoformat()
        d["day_close"] = self.day_close.isoformat()
        d["customer_cutoff"] = self.customer_cutoff.isoformat()
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
    collateralized_credit_minor: int = 0
    participant_limit_minor: int | None = None


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
    kind: str = "interbank"     # interbank | customer | timed | instant


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
            if self.generator_version != GENERATOR_VERSIONS["v1"]:
                h.update(p.kind.encode())
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

    def choice_cum(self, items: list, cum: list[int]):
        """Weighted choice with precomputed cumulative integer weights (O(log n))."""
        return items[bisect.bisect_right(cum, self.s.randbelow(cum[-1]))]

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
    if config.generator == "v1":
        return _generate_v1(config, seed, scenario_id, topology_seed)
    return _generate_v2(config, seed, scenario_id, topology_seed)


def _generate_v1(config: NexusPayConfig, seed: int, scenario_id: str | None, topology_seed: int | None) -> Scenario:
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
        generator_version=GENERATOR_VERSIONS["v1"],
    )


BUCKET_MIN = 15
_TIMED_WINDOWS = (time(10, 0), time(13, 0), time(15, 30))
_FEDNOW_PARTICIPANT_LIMITS = (500_000_00, 1_000_000_00, 5_000_000_00, 10_000_000_00)   # assumption: menu of chosen limits


def _profile_weight(bucket: int, n_buckets: int) -> float:
    """Smooth intraday shape: morning ramp, midday plateau, afternoon peak, pre-close taper (assumption)."""
    x = (bucket + 0.5) / n_buckets
    return 0.35 + 1.2 * math.exp(-((x - 0.22) / 0.13) ** 2) + 1.5 * math.exp(-((x - 0.78) / 0.12) ** 2) + 0.6 * x


def _ar_path(sampler: _Sampler, n: int, phi: float, sigma: float) -> list[float]:
    """Stationary AR(1) path with unconditional variance sigma^2/(1-phi^2)."""
    out = [sampler.normal() * sigma / math.sqrt(max(1e-9, 1 - phi * phi))]
    for _ in range(n - 1):
        out.append(phi * out[-1] + sigma * sampler.normal())
    return out


def _generate_v2(config: NexusPayConfig, seed: int, scenario_id: str | None, topology_seed: int | None) -> Scenario:
    tz = ZoneInfo(_TZ)
    open_at = datetime.combine(config.business_date, config.day_open, tz).astimezone(UTC)
    close_at = datetime.combine(config.business_date, config.day_close, tz).astimezone(UTC)
    cust_cut = datetime.combine(config.business_date, config.customer_cutoff, tz).astimezone(UTC)
    day_seconds = int((close_at - open_at).total_seconds())
    n_buckets = max(1, day_seconds // (BUCKET_MIN * 60))
    topo = _Sampler(DeterministicRandomStream(derive_stream_seed(seed if topology_seed is None else topology_seed, "nexus:v2:topology")))

    # ---- topology (fixed by topology seed)
    n = config.n_institutions
    n_core = max(1, n * config.core_fraction_bp // 10_000)
    institutions: list[InstitutionSpec] = []
    for i in range(n):
        core = i < n_core
        rails = ["rtgs", "lsm", "fednow"]
        if core or topo.bp(config.rtp_participation_bp):
            rails.append("rtp")
        size = config.core_size_multiplier * 10 + topo.s.randbelow(10) if core else 10 + topo.s.randbelow(10)
        institutions.append(InstitutionSpec(f"bank-{i:03d}", f"Synthetic {'Core' if core else 'Regional'} Bank {i:03d}",
                                            "core" if core else "periphery", size, tuple(rails)))
    ids = [x.institution_id for x in institutions]
    size = {x.institution_id: x.size_weight for x in institutions}
    rails_of = {x.institution_id: x.rails for x in institutions}
    total_w = sum(size.values())
    rel_sigma = config.relationship_sigma_milli / 1000.0
    # persistent bilateral relationship weights (integer, for exact cumulative sampling)
    raw = {a: {b: size[b] * math.exp(rel_sigma * topo.normal() - rel_sigma ** 2 / 2) for b in ids if b != a} for a in ids}
    # Balance expected gross flows (Sinkhorn-Knopp): each bank's expected outflow ~= its expected inflow, up to a
    # small configurable imbalance. Real banks' daily gross flows roughly offset; RTGS liquidity needs come from timing.
    imb = config.flow_imbalance_milli / 1000.0
    out_target = {a: size[a] for a in ids}
    in_target = {a: size[a] * math.exp(imb * topo.normal() - imb * imb / 2) for a in ids}
    scale_in = sum(out_target.values()) / sum(in_target.values())
    in_target = {a: v * scale_in for a, v in in_target.items()}
    W = {a: dict(raw[a]) for a in ids}
    for _ in range(200):
        for a in ids:
            row = sum(W[a].values())
            f = out_target[a] / row
            for b in W[a]:
                W[a][b] *= f
        col = {b: 0.0 for b in ids}
        for a in ids:
            for b, v in W[a].items():
                col[b] += v
        for a in ids:
            for b in W[a]:
                W[a][b] *= in_target[b] / col[b]
    rel: dict[str, dict[str, int]] = {a: {b: max(1, int(1e9 * W[a][b] / sum(W[a].values()))) for b in W[a]} for a in ids}
    fednow_limit = {a: min(config.fednow_limit_minor, _FEDNOW_PARTICIPANT_LIMITS[topo.s.randbelow(len(_FEDNOW_PARTICIPANT_LIMITS))]) for a in ids}

    def cum_for(a: str, rtp_only: bool) -> tuple[list[str], list[int]]:
        items = [b for b in rel[a] if not rtp_only or "rtp" in rails_of[b]]
        cum, acc = [], 0
        for b in items:
            acc += rel[a][b]
            cum.append(acc)
        return items, cum
    cp_all = {a: cum_for(a, False) for a in ids}
    cp_rtp = {a: cum_for(a, True) for a in ids if "rtp" in rails_of[a]}

    # ---- day-level and intraday activity (drawn from the day seed)
    day = _Sampler(DeterministicRandomStream(derive_stream_seed(seed, "nexus:v2:day")))
    day_factor = math.exp(config.day_volume_sigma_milli / 1000.0 * day.normal() - (config.day_volume_sigma_milli / 1000.0) ** 2 / 2)
    phi = config.intraday_phi_milli / 1000.0
    market = _ar_path(day, n_buckets, phi, config.market_sigma_milli / 1000.0)
    base = [_profile_weight(b, n_buckets) for b in range(n_buckets)]
    lv_mean = config.large_value_median_minor * math.exp((config.large_value_sigma_milli / 1000.0) ** 2 / 2)
    in_mean = config.instant_median_minor * math.exp((config.instant_sigma_milli / 1000.0) ** 2 / 2)
    timed_dt = [datetime.combine(config.business_date, t, tz).astimezone(UTC) for t in _TIMED_WINDOWS]
    timed_dt = [t for t in timed_dt if open_at + timedelta(minutes=90) <= t <= close_at]

    payments: list[ScenarioPayment] = []
    expected_out: dict[tuple[str, str], float] = {}
    for inst in institutions:
        a = inst.institution_id
        smp = _Sampler(DeterministicRandomStream(derive_stream_seed(seed, f"nexus:v2:arrivals:{a}")))
        bank_path = _ar_path(smp, n_buckets, phi, config.bank_sigma_milli / 1000.0)
        wts = [max(1, int(1000 * base[b] * math.exp(market[b] + bank_path[b]))) for b in range(n_buckets)]
        cum_b, acc = [], 0
        for w in wts:
            acc += w
            cum_b.append(acc)
        buckets = list(range(n_buckets))
        share = inst.size_weight / total_w
        exp_large = config.payments_per_day * share
        exp_instant = config.instant_payments_per_day * share
        bank_factor = math.exp(0.1 * smp.normal() - 0.005)
        n_large = max(0, round(exp_large * day_factor * bank_factor))
        n_instant = max(0, round(exp_instant * day_factor * bank_factor))
        lsm_frac = config.lsm_share_bp / 10_000
        expected_out[(a, "lsm")] = exp_large * lsm_frac * lv_mean
        expected_out[(a, "rtgs")] = exp_large * (1 - lsm_frac) * lv_mean
        rtp_frac = config.rtp_share_bp / 10_000 if "rtp" in inst.rails else 0.0
        expected_out[(a, "rtp")] = exp_instant * rtp_frac * in_mean
        expected_out[(a, "fednow")] = exp_instant * (1 - rtp_frac) * in_mean
        for k in range(n_large + n_instant):
            large = k < n_large
            if large:
                rail = "lsm" if smp.bp(config.lsm_share_bp) else "rtgs"
            else:
                rail = "rtp" if ("rtp" in inst.rails and smp.bp(config.rtp_share_bp)) else "fednow"
            pool = cp_rtp.get(a) if rail == "rtp" else cp_all[a]
            if rail == "rtp" and (pool is None or not pool[0]):
                rail, pool = "fednow", cp_all[a]
            receiver = smp.choice_cum(*pool)
            if large:
                amount = smp.lognormal_minor(config.large_value_median_minor, config.large_value_sigma_milli)
                if smp.bp(config.round_amount_share_bp):
                    amount = max(100_000_00, (amount + 50_000_00) // 100_000_00 * 100_000_00)
            else:
                amount = smp.lognormal_minor(config.instant_median_minor, config.instant_sigma_milli)
                if smp.bp(config.round_amount_share_bp):
                    amount = max(1_000_00, (amount + 500_00) // 1_000_00 * 1_000_00)
                limit = config.rtp_limit_minor if rail == "rtp" else fednow_limit[a]
                amount = min(limit, amount)
            b = smp.choice_cum(buckets, cum_b)
            arrival = open_at + timedelta(seconds=min(day_seconds - 1, b * BUCKET_MIN * 60 + smp.s.randbelow(BUCKET_MIN * 60)))
            if not large:
                kind, due, priority = "instant", arrival, 3
            elif timed_dt and smp.bp(config.timed_share_bp):
                window = timed_dt[smp.s.randbelow(len(timed_dt))]
                arrival = window - timedelta(minutes=20 + smp.s.randbelow(70))
                kind, due, priority = "timed", window, 2
            elif smp.bp(config.customer_share_bp):
                if arrival >= cust_cut:
                    arrival = cust_cut - timedelta(minutes=1 + smp.s.randbelow(60))
                urgent = smp.bp(config.urgent_share_bp)
                due = min(cust_cut, arrival + (timedelta(minutes=30) if urgent else timedelta(minutes=60 + smp.s.randbelow(120))))
                kind, priority = "customer", 2 if urgent else 1
            else:
                urgent = smp.bp(config.urgent_share_bp)
                due = min(close_at, arrival + (timedelta(minutes=30) if urgent else timedelta(minutes=90 + smp.s.randbelow(150))))
                kind, priority = "interbank", 2 if urgent else 1
            payments.append(ScenarioPayment(f"{a}-{rail}-{k:05d}", rail, a, receiver, amount, arrival, max(due, arrival), priority, kind))
    payments.sort(key=lambda p: (p.arrival_at, p.payment_id))

    accounts: list[AccountSpec] = []
    for inst in institutions:
        for rail in inst.rails:
            gross = int(expected_out.get((inst.institution_id, rail), 0))
            share_bp = config.instant_prefunding_bp if rail in ("fednow", "rtp") else config.opening_liquidity_bp
            credit = gross * config.credit_limit_bp // 10_000 if rail == "rtgs" else 0
            floor = 1_000_000_00 if rail in ("rtgs", "lsm") else 100_000_00
            accounts.append(AccountSpec(
                f"{inst.institution_id}:{rail}", inst.institution_id, rail, max(floor, gross * share_bp // 10_000), credit,
                collateralized_credit_minor=credit * config.collateralized_credit_bp // 10_000,
                participant_limit_minor=fednow_limit[inst.institution_id] if rail == "fednow" else (config.rtp_limit_minor if rail == "rtp" else None),
            ))
    return Scenario(
        scenario_id=scenario_id or f"nexus-{seed}", seed=seed, config=config, institutions=tuple(institutions),
        accounts=tuple(accounts), payments=tuple(payments), open_at=open_at, close_at=close_at,
        generator_version=GENERATOR_VERSIONS["v2"],
    )
