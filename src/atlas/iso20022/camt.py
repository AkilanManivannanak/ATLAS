"""camt.053.001.08 end-of-day account statements built from the event-sourced ledger.

Each ledger-affecting event that moves cash on an account becomes one statement entry
(``CRDT``/``DBIT``, booked, with the event id as the entry reference so every line is
traceable to the hash-chained store). Balances: ``OPBD`` (opening booked) and ``CLBD``
(closing booked). ``reconcile_statement`` parses a statement back and checks

    OPBD + sum(credits) - sum(debits) == CLBD == ledger closing balance

Structural only: no official XSD validation, no bank-specific usage guideline.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape

from atlas.domain import FinancialEvent, SettlementAccount

CAMT053 = "camt.053.001.08"
_NS = f"urn:iso:std:iso:20022:tech:xsd:{CAMT053}"


def _fmt(minor: int) -> str:
    return f"{abs(minor) // 100}.{abs(minor) % 100:02d}"


def account_movements(account_id: str, events: Iterable[FinancialEvent]) -> list[tuple[FinancialEvent, int, str]]:
    """(event, signed amount, description) for every cash movement on the account, in event order."""
    out = []
    for ev in events:
        p = json.loads(ev.payload_json)
        t = ev.event_type
        delta = 0
        desc = t
        if t == "PaymentSettled":
            if p["sender_account_id"] == account_id:
                delta, desc = -p["amount_minor"], f"payment {p['payment_id']}"
                if p["credit_draw_minor"]:
                    out.append((ev, p["credit_draw_minor"], "intraday credit draw"))
            elif p["receiver_account_id"] == account_id:
                delta, desc = p["amount_minor"], f"payment {p['payment_id']}"
        elif t == "LiquiditySavingCycleSettled":
            delta, desc = p["account_deltas_minor"].get(account_id, 0), f"net settlement cycle ({len(p['payment_ids'])} payments)"
        elif t in ("FundingDrawn", "FundingRepaid", "LiquidityAdjusted", "IntradayCreditRepaid") and p.get("account_id") == account_id:
            delta, desc = p["account_ledger_after_minor"] - p["account_ledger_before_minor"], p.get("reason", t)
        elif t == "InterbankLoanTransfer":
            if p["from_account_id"] == account_id:
                delta, desc = -p["amount_minor"], p["purpose"]
            elif p["to_account_id"] == account_id:
                delta, desc = p["amount_minor"], p["purpose"]
        if delta:
            out.append((ev, delta, desc))
    return out


def build_camt053(account: SettlementAccount, opening_balance_minor: int, events: Iterable[FinancialEvent], *,
                  statement_id: str, created_at: datetime) -> str:
    moves = account_movements(account.account_id, events)
    closing = opening_balance_minor + sum(d for _, d, _ in moves)

    def bal(code: str, amount: int, at: datetime) -> str:
        return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy=\"{account.currency}\">{_fmt(amount)}</Amt>"
                f"<CdtDbtInd>{'CRDT' if amount >= 0 else 'DBIT'}</CdtDbtInd><Dt><DtTm>{at.isoformat()}</DtTm></Dt></Bal>")

    start = moves[0][0].event_at if moves else created_at
    parts = [f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{_NS}"><BkToCstmrStmt>',
             f"<GrpHdr><MsgId>{escape(statement_id)}</MsgId><CreDtTm>{created_at.isoformat()}</CreDtTm></GrpHdr>",
             f"<Stmt><Id>{escape(statement_id)}</Id><CreDtTm>{created_at.isoformat()}</CreDtTm>",
             f"<Acct><Id><Othr><Id>{escape(account.account_id)}</Id></Othr></Id><Ccy>{account.currency}</Ccy></Acct>",
             bal("OPBD", opening_balance_minor, start), bal("CLBD", closing, created_at),
             f"<TxsSummry><TtlNtries><NbOfNtries>{len(moves)}</NbOfNtries></TtlNtries></TxsSummry>"]
    for ev, delta, desc in moves:
        parts.append(f"<Ntry><NtryRef>{escape(ev.event_id)}</NtryRef><Amt Ccy=\"{account.currency}\">{_fmt(delta)}</Amt>"
                     f"<CdtDbtInd>{'CRDT' if delta > 0 else 'DBIT'}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>"
                     f"<BookgDt><DtTm>{ev.event_at.isoformat()}</DtTm></BookgDt><AddtlNtryInf>{escape(desc)}</AddtlNtryInf></Ntry>")
    parts.append("</Stmt></BkToCstmrStmt></Document>")
    return "".join(parts)


@dataclass(frozen=True)
class StatementReconciliation:
    account_id: str
    entries: int
    opening_minor: int
    credits_minor: int
    debits_minor: int
    closing_minor: int
    balanced: bool
    matches_ledger: bool | None


def _minor(el: ET.Element, ns: str) -> int:
    amt = el.find(f"{{{ns}}}Amt").text
    whole, frac = amt.split(".")
    v = int(whole) * 100 + int(frac)
    return v if el.find(f"{{{ns}}}CdtDbtInd").text == "CRDT" else -v


def reconcile_statement(xml: str, ledger_closing_minor: int | None = None) -> StatementReconciliation:
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("DOCTYPE/ENTITY declarations are not permitted")
    root = ET.fromstring(xml)
    ns = root.tag[1:].split("}")[0]
    if not ns.endswith(CAMT053):
        raise ValueError(f"not a {CAMT053} document")
    stmt = root.find(f"{{{ns}}}BkToCstmrStmt/{{{ns}}}Stmt")
    bals = {b.find(f"{{{ns}}}Tp/{{{ns}}}CdOrPrtry/{{{ns}}}Cd").text: _minor(b, ns) for b in stmt.findall(f"{{{ns}}}Bal")}
    entries = [_minor(e, ns) for e in stmt.findall(f"{{{ns}}}Ntry")]
    declared = int(stmt.find(f"{{{ns}}}TxsSummry/{{{ns}}}TtlNtries/{{{ns}}}NbOfNtries").text)
    credits = sum(e for e in entries if e > 0)
    debits = -sum(e for e in entries if e < 0)
    balanced = declared == len(entries) and bals["OPBD"] + credits - debits == bals["CLBD"]
    acct = stmt.find(f"{{{ns}}}Acct/{{{ns}}}Id/{{{ns}}}Othr/{{{ns}}}Id").text
    return StatementReconciliation(acct, len(entries), bals["OPBD"], credits, debits, bals["CLBD"], balanced,
                                   None if ledger_closing_minor is None else bals["CLBD"] == ledger_closing_minor)
