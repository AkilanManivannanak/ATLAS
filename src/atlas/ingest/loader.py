"""Load a user's own payment file into a :class:`~atlas.scenario.Scenario` (``atlas-ingest-v1``).

Two inputs are accepted:

* a CSV with one payment per row (``template_csv()`` prints the expected header), and
* ISO 20022 ``pacs.008`` / ``pacs.009`` XML, the formats Fedwire Funds (since 14 July 2025), CHIPS, FedNow and RTP use.

Nothing is silently dropped or repaired: every rejected row is listed with its reason, and every value the
loader had to *assume* (opening balances, credit lines, the business day window) is listed under ``assumptions``.
Standard library only, so the same code runs in the browser lab.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from atlas.scenario.nexus_pay import AccountSpec, InstitutionSpec, NexusPayConfig, Scenario, ScenarioPayment

INGEST_VERSION = "atlas-ingest-v1"
MAX_ROWS = 2_000_000
_ID = re.compile(r"[^A-Za-z0-9_.\-]")

RAIL_ALIASES = {
    "rtgs": "rtgs", "fedwire": "rtgs", "wire": "rtgs", "fedwire funds": "rtgs",
    "lsm": "lsm", "chips": "lsm",
    "fednow": "fednow", "instant": "fednow",
    "rtp": "rtp",
}
COLUMN_ALIASES = {
    "payment_id": ("payment_id", "id", "reference", "end_to_end_id", "uetr", "instruction_id"),
    "rail": ("rail", "network", "system", "channel"),
    "sender": ("sender", "debtor", "debtor_agent", "from", "originator", "payer", "sender_bic"),
    "receiver": ("receiver", "creditor", "creditor_agent", "to", "beneficiary", "payee", "receiver_bic"),
    "amount": ("amount", "amount_usd", "value", "amt"),
    "amount_minor": ("amount_minor", "amount_cents"),
    "currency": ("currency", "ccy"),
    "time": ("time", "arrival", "arrival_at", "timestamp", "created_at", "submitted_at", "datetime"),
    "due": ("due", "due_at", "deadline", "latest_settlement"),
    "priority": ("priority", "urgency"),
    "kind": ("kind", "type", "category"),
}
PRIORITY_ALIASES = {"low": 1, "normal": 1, "standard": 1, "high": 2, "urgent": 2, "critical": 3, "timed": 3}
KINDS = ("interbank", "customer", "timed", "instant")


class IngestError(ValueError):
    """The file as a whole cannot be used (no usable rows, missing mandatory column, ...)."""


@dataclass
class IngestReport:
    source: str
    rows_read: int = 0
    accepted: int = 0
    rejected: list[dict] = field(default_factory=list)       # {"row": n, "reason": str}
    assumptions: list[str] = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    version: str = INGEST_VERSION

    def to_dict(self) -> dict:
        return {"version": self.version, "source": self.source, "rows_read": self.rows_read, "accepted": self.accepted,
                "rejected_count": len(self.rejected), "rejected": self.rejected[:200], "assumptions": self.assumptions,
                "totals": self.totals}


def template_csv() -> str:
    return ("payment_id,rail,sender,receiver,amount,time,due,priority,kind\n"
            "P-0001,fedwire,BANKAUS33,BANKBUS33,2500000.00,2026-03-10T09:15:00-04:00,2026-03-10T11:15:00-04:00,normal,customer\n"
            "P-0002,chips,BANKBUS33,BANKAUS33,1800000.00,09:20,,urgent,interbank\n"
            "P-0003,fednow,BANKAUS33,BANKCUS33,12500.00,09:21:30,,,instant\n")


def _clean_id(raw: str) -> str:
    return _ID.sub("-", raw.strip())[:64]


def _parse_time(raw: str, business_date: date | None, tz: ZoneInfo) -> datetime:
    s = raw.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s):
        if business_date is None:
            raise ValueError("time of day given without a business date")
        parts = [int(x) for x in s.split(":")] + [0]
        return datetime.combine(business_date, time(parts[0], parts[1], parts[2]), tz).astimezone(UTC)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(UTC)


def _amount_minor(row: dict) -> int:
    if row.get("amount_minor"):
        v = int(row["amount_minor"].strip())
    else:
        raw = (row.get("amount") or "").replace(",", "").replace("$", "").strip()
        if not raw:
            raise ValueError("amount is empty")
        d = Decimal(raw)
        if d != d.quantize(Decimal("0.01")):
            raise ValueError(f"amount {raw} has more than 2 decimal places")
        v = int(d * 100)
    if v <= 0:
        raise ValueError("amount must be positive")
    return v


def _build(rows: Iterable[tuple[int, dict]], report: IngestReport, *, business_date: date | None, timezone: str,
           opening_balances: dict[tuple[str, str], dict] | None, opening_liquidity_bp: int, instant_prefunding_bp: int,
           credit_limit_bp: int, collateralized_credit_bp: int, scenario_id: str, day_open: time, day_close: time) -> Scenario:
    tz = ZoneInfo(timezone)
    seen: set[str] = set()
    raw_payments: list[tuple] = []
    for n, row in rows:
        report.rows_read += 1
        if report.rows_read > MAX_ROWS:
            raise IngestError(f"more than {MAX_ROWS:,} rows; split the file by business day")
        try:
            ccy = (row.get("currency") or "USD").strip().upper()
            if ccy != "USD":
                raise ValueError(f"currency {ccy} not supported (USD only)")
            sender, receiver = _clean_id(row.get("sender") or ""), _clean_id(row.get("receiver") or "")
            if not sender or not receiver:
                raise ValueError("sender and receiver are required")
            if sender == receiver:
                raise ValueError("sender and receiver are the same institution")
            amount = _amount_minor(row)
            rail_raw = (row.get("rail") or "rtgs").strip().lower()
            if rail_raw not in RAIL_ALIASES:
                raise ValueError(f"unknown rail {rail_raw!r}; use one of {sorted(set(RAIL_ALIASES))}")
            rail = RAIL_ALIASES[rail_raw]
            if not (row.get("time") or "").strip():
                raise ValueError("time is required")
            arrival = _parse_time(row["time"], business_date, tz)
            due = _parse_time(row["due"], business_date or arrival.astimezone(tz).date(), tz) if (row.get("due") or "").strip() else None
            pr_raw = (row.get("priority") or "").strip().lower()
            priority = PRIORITY_ALIASES[pr_raw] if pr_raw in PRIORITY_ALIASES else (int(pr_raw) if pr_raw else 1)
            if not 1 <= priority <= 3:
                raise ValueError("priority must be 1-3 or low/normal/high/urgent/critical")
            kind = (row.get("kind") or "").strip().lower() or ("instant" if rail in ("fednow", "rtp") else "interbank")
            if kind not in KINDS:
                raise ValueError(f"kind must be one of {KINDS}")
            pid = _clean_id(row.get("payment_id") or "") or f"row-{n:07d}"
            if pid in seen:
                raise ValueError(f"duplicate payment_id {pid}")
            seen.add(pid)
            raw_payments.append((pid, rail, sender, receiver, amount, arrival, due, priority, kind))
        except (ValueError, InvalidOperation, KeyError) as exc:
            report.rejected.append({"row": n, "reason": str(exc)})
    if not raw_payments:
        raise IngestError("no usable payments in the file" + (f" (first problem: {report.rejected[0]['reason']})" if report.rejected else ""))

    first = min(p[5] for p in raw_payments).astimezone(tz)
    bdate = business_date or first.date()
    days = {p[5].astimezone(tz).date() for p in raw_payments}
    if len(days) > 1:
        keep = [p for p in raw_payments if p[5].astimezone(tz).date() == bdate]
        report.assumptions.append(f"file spans {len(days)} dates; only {bdate.isoformat()} is simulated ({len(raw_payments) - len(keep)} rows on other dates left out)")
        for _ in range(len(raw_payments) - len(keep)):
            report.rejected.append({"row": None, "reason": "outside the simulated business date"})
        raw_payments = keep
        if not raw_payments:
            raise IngestError(f"no payments on business date {bdate.isoformat()}")
    earliest = min(p[5] for p in raw_payments).astimezone(tz)
    latest = max(p[5] for p in raw_payments).astimezone(tz)
    open_local = datetime.combine(bdate, day_open, tz)
    close_local = datetime.combine(bdate, day_close, tz)
    if earliest < open_local:
        open_local = earliest.replace(minute=0, second=0, microsecond=0)
        report.assumptions.append(f"day opens at {open_local.strftime('%H:%M')} {timezone} (earliest payment is before the default open)")
    if latest >= close_local:
        close_local = (latest + timedelta(minutes=59)).replace(minute=0, second=0, microsecond=0) + timedelta(minutes=30)
        report.assumptions.append(f"day closes at {close_local.strftime('%H:%M')} {timezone} (latest payment is after the default close)")
    open_at, close_at = open_local.astimezone(UTC), close_local.astimezone(UTC)

    payments: list[ScenarioPayment] = []
    defaulted_due = 0
    for pid, rail, sender, receiver, amount, arrival, due, priority, kind in raw_payments:
        if due is None:
            defaulted_due += 1
            due = arrival if rail in ("fednow", "rtp") else close_at
        payments.append(ScenarioPayment(pid, rail, sender, receiver, amount, arrival, max(due, arrival), priority, kind))
    if defaulted_due:
        report.assumptions.append(f"{defaulted_due} payments had no deadline: large-value ones are due at close, instant ones immediately")
    payments.sort(key=lambda p: (p.arrival_at, p.payment_id))

    out: dict[tuple[str, str], int] = {}
    volume: dict[str, int] = {}
    rails_of: dict[str, set[str]] = {}
    for p in payments:
        out[(p.sender, p.rail)] = out.get((p.sender, p.rail), 0) + p.amount_minor
        volume[p.sender] = volume.get(p.sender, 0) + p.amount_minor
        volume[p.receiver] = volume.get(p.receiver, 0) + p.amount_minor
        rails_of.setdefault(p.sender, set()).add(p.rail)
        rails_of.setdefault(p.receiver, set()).add(p.rail)
    ids = sorted(rails_of)
    if len(ids) < 2:
        raise IngestError("need at least two institutions")
    ranked = sorted(ids, key=lambda i: (-volume[i], i))
    core = set(ranked[: max(1, len(ids) // 4)])
    top = max(volume.values())
    order = ("rtgs", "lsm", "fednow", "rtp")
    institutions = tuple(InstitutionSpec(i, i, "core" if i in core else "periphery", max(1, round(6 * volume[i] / top)),
                                         tuple(r for r in order if r in rails_of[i])) for i in ids)

    accounts: list[AccountSpec] = []
    assumed = 0
    given = opening_balances or {}
    for inst in institutions:
        for rail in inst.rails:
            gross = out.get((inst.institution_id, rail), 0)
            g = given.get((inst.institution_id, rail))
            if g is not None:
                opening, credit = g["opening_balance_minor"], g.get("credit_limit_minor", 0)
                coll = g.get("collateralized_credit_minor", credit * collateralized_credit_bp // 10_000)
            else:
                assumed += 1
                share = instant_prefunding_bp if rail in ("fednow", "rtp") else opening_liquidity_bp
                floor = 1_000_000_00 if rail in ("rtgs", "lsm") else 100_000_00
                opening = max(floor, gross * share // 10_000)
                credit = gross * credit_limit_bp // 10_000 if rail == "rtgs" else 0
                coll = credit * collateralized_credit_bp // 10_000
            accounts.append(AccountSpec(f"{inst.institution_id}:{rail}", inst.institution_id, rail, opening, credit,
                                        collateralized_credit_minor=min(coll, credit)))
    if assumed:
        report.assumptions.append(
            f"{assumed} of {len(accounts)} opening balances were not supplied: set to {opening_liquidity_bp / 100:.0f}% of each bank's gross outflow "
            f"on large-value rails ({instant_prefunding_bp / 100:.0f}% on instant rails), RTGS credit line {credit_limit_bp / 100:.0f}% of outflow")

    config = NexusPayConfig(n_institutions=len(ids), business_date=bdate, day_open=open_local.timetz().replace(tzinfo=None),
                            day_close=close_local.timetz().replace(tzinfo=None),
                            payments_per_day=sum(1 for p in payments if p.rail in ("rtgs", "lsm")) or 1,
                            instant_payments_per_day=sum(1 for p in payments if p.rail in ("fednow", "rtp")) or 1,
                            opening_liquidity_bp=opening_liquidity_bp, instant_prefunding_bp=instant_prefunding_bp,
                            credit_limit_bp=credit_limit_bp, collateralized_credit_bp=collateralized_credit_bp)
    report.accepted = len(payments)
    report.totals = {"institutions": len(ids), "accounts": len(accounts), "payments": len(payments),
                     "value_minor": sum(p.amount_minor for p in payments),
                     "open_at": open_at.isoformat(), "close_at": close_at.isoformat(), "business_date": bdate.isoformat()}
    return Scenario(scenario_id=scenario_id, seed=0, config=config, institutions=institutions, accounts=tuple(accounts),
                    payments=tuple(payments), open_at=open_at, close_at=close_at, generator_version=INGEST_VERSION,
                    labels={"data_origin": "user_supplied", "observed_financial_data": None})


def _normalise_header(fieldnames: list[str]) -> dict[str, str]:
    lower = {f.strip().lower().replace(" ", "_"): f for f in fieldnames if f}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in lower:
                mapping[canonical] = lower[a]
                break
    return mapping


def parse_balances_csv(text: str) -> dict[tuple[str, str], dict]:
    """Optional second file: ``institution,rail,opening_balance,credit_limit[,collateralized_credit]`` (USD)."""
    out: dict[tuple[str, str], dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        rail = RAIL_ALIASES.get(r.get("rail", "").lower())
        if not r.get("institution") or rail is None:
            raise IngestError("balances file needs institution and a known rail on every row")
        to_minor = lambda s: int(Decimal(s.replace(",", "").replace("$", "") or "0") * 100)
        entry = {"opening_balance_minor": to_minor(r.get("opening_balance", "0")), "credit_limit_minor": to_minor(r.get("credit_limit", "0"))}
        if r.get("collateralized_credit"):
            entry["collateralized_credit_minor"] = to_minor(r["collateralized_credit"])
        if entry["opening_balance_minor"] < 0 or entry["credit_limit_minor"] < 0:
            raise IngestError("balances and credit limits cannot be negative")
        out[(_clean_id(r["institution"]), rail)] = entry
    return out


def load_payments_csv(text: str, *, balances_csv: str | None = None, business_date: date | None = None,
                      timezone: str = "America/New_York", opening_liquidity_bp: int = 1_800, instant_prefunding_bp: int = 2_500,
                      credit_limit_bp: int = 1_000, collateralized_credit_bp: int = 6_000, scenario_id: str = "user-data",
                      day_open: time = time(8, 0), day_close: time = time(18, 30)) -> tuple[Scenario, IngestReport]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise IngestError("the file is empty")
    mapping = _normalise_header(list(reader.fieldnames))
    missing = [c for c in ("sender", "receiver", "time") if c not in mapping]
    if "amount" not in mapping and "amount_minor" not in mapping:
        missing.append("amount")
    if missing:
        raise IngestError(f"missing column(s): {', '.join(missing)}. Expected header like: {template_csv().splitlines()[0]}")
    report = IngestReport(source="csv")
    rows = ((n, {c: (raw.get(src) or "") for c, src in mapping.items()}) for n, raw in enumerate(reader, start=2))
    scenario = _build(rows, report, business_date=business_date, timezone=timezone,
                      opening_balances=parse_balances_csv(balances_csv) if balances_csv else None,
                      opening_liquidity_bp=opening_liquidity_bp, instant_prefunding_bp=instant_prefunding_bp,
                      credit_limit_bp=credit_limit_bp, collateralized_credit_bp=collateralized_credit_bp,
                      scenario_id=scenario_id, day_open=day_open, day_close=day_close)
    return scenario, report


def load_payments_iso20022(messages: Iterable[bytes | str], *, rail: str = "rtgs", **kw) -> tuple[Scenario, IngestReport]:
    """Each item is one pacs.008 / pacs.009 document. BICs become institution ids; ``CreDtTm`` is the arrival time."""
    from atlas.iso20022.messages import MessageValidationError, normalize

    if rail not in ("rtgs", "lsm", "fednow", "rtp"):
        raise IngestError("rail must be rtgs, lsm, fednow or rtp")
    report = IngestReport(source="iso20022")
    rows: list[tuple[int, dict]] = []
    for n, payload in enumerate(messages, start=1):
        try:
            msg = normalize(payload)
        except MessageValidationError as exc:
            report.rows_read += 1
            report.rejected.append({"row": n, "reason": f"message {n}: {exc}"})
            continue
        for tx in msg.transactions:
            rows.append((n, {"payment_id": tx.end_to_end_id or tx.instruction_id, "rail": rail, "sender": tx.debtor_agent_bic,
                             "receiver": tx.creditor_agent_bic, "amount_minor": str(tx.amount.amount_minor),
                             "currency": tx.amount.currency, "time": msg.created_at.isoformat(), "due": "", "priority": "",
                             "kind": "customer" if msg.message_definition.startswith("pacs.008") else "interbank"}))
    kw.setdefault("scenario_id", "user-iso20022")
    balances = kw.pop("balances_csv", None)
    scenario = _build(iter(rows), report, business_date=kw.pop("business_date", None), timezone=kw.pop("timezone", "America/New_York"),
                      opening_balances=parse_balances_csv(balances) if balances else None,
                      opening_liquidity_bp=kw.pop("opening_liquidity_bp", 1_800), instant_prefunding_bp=kw.pop("instant_prefunding_bp", 2_500),
                      credit_limit_bp=kw.pop("credit_limit_bp", 1_000), collateralized_credit_bp=kw.pop("collateralized_credit_bp", 6_000),
                      scenario_id=kw.pop("scenario_id"), day_open=kw.pop("day_open", time(8, 0)), day_close=kw.pop("day_close", time(18, 30)))
    return scenario, report


def export_scenario_csv(scenario: Scenario, timezone: str = "America/New_York") -> str:
    """Write any scenario in the ingest format (used for the downloadable sample file and round-trip tests)."""
    tz = ZoneInfo(timezone)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["payment_id", "rail", "sender", "receiver", "amount", "time", "due", "priority", "kind"])
    for p in scenario.payments:
        w.writerow([p.payment_id, p.rail, p.sender, p.receiver, f"{p.amount_minor // 100}.{p.amount_minor % 100:02d}",
                    p.arrival_at.astimezone(tz).isoformat(), p.due_at.astimezone(tz).isoformat(), p.priority, p.kind])
    return buf.getvalue()
