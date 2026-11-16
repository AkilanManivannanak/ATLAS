"""BCBS 248 intraday liquidity monitoring tools, computed per institution (``atlas-bcbs248-v1``).

Reference: Basel Committee on Banking Supervision, *Monitoring tools for intraday liquidity management* (April 2013).
Implemented tools, for a direct participant, from the settled payment record of one business day:

* A(i)   daily maximum intraday liquidity usage: the largest net cumulative negative position, and the largest positive one
* A(ii)  available intraday liquidity at the start of the business day (opening balances + credit lines, by source)
* A(iii) total payments: gross payments sent and received
* A(iv)  time-specific obligations: count / value, and how many settled after their deadline or not at all
* C(i)   intraday throughput: cumulative share of the day's outgoing value settled by each hour

Not implemented: B(i)/(ii) (correspondent-bank tools: the twin has no customer banks) and the stress-scenario
columns, which callers obtain by running the same report on a stressed run. Positions follow payment flows only;
own-account transfers between rails do not change a bank's net position and are excluded, as the standard intends.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

BCBS248_VERSION = "atlas-bcbs248-v1"
_LV = ("rtgs", "lsm")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def intraday_liquidity_report(run: Mapping[str, Any], *, rails: tuple[str, ...] = _LV, timed_kinds: tuple[str, ...] = ("timed",),
                              scenario_payments: Mapping[str, Mapping] | None = None) -> dict:
    """``run`` is ``SimulationResult.to_dict(include_payments=True)``.

    ``scenario_payments`` optionally maps payment_id -> {"kind": ...} when the run's payment rows carry no kind.
    """
    payments = [p for p in run["payments"] if p["rail"] in rails]
    ts = run["timeseries"]
    open_at, close_at = _ts(ts[0]["t"]), _ts(ts[-1]["t"])
    hours = max(1, int((close_at - open_at).total_seconds() // 3600))
    insts = {x["institution_id"]: x for x in run["per_institution"]}

    flows: dict[str, list[tuple[datetime, int]]] = {i: [] for i in insts}
    sent: dict[str, dict] = {i: {"count": 0, "value": 0, "settled_value": 0, "by_hour": [0] * (hours + 1)} for i in insts}
    recv: dict[str, dict] = {i: {"count": 0, "value": 0} for i in insts}
    timed: dict[str, dict] = {i: {"count": 0, "value": 0, "late": 0, "late_value": 0, "failed": 0, "failed_value": 0} for i in insts}

    for p in payments:
        s, r, amt = p["sender"], p["receiver"], p["amount_minor"]
        if s not in insts or r not in insts:
            continue
        kind = p.get("kind") or (scenario_payments or {}).get(p["payment_id"], {}).get("kind")
        sent[s]["count"] += 1
        sent[s]["value"] += amt
        settled = p["status"] == "settled" and p.get("settled_at")
        if settled:
            at = _ts(p["settled_at"])
            flows[s].append((at, -amt))
            flows[r].append((at, amt))
            recv[r]["count"] += 1
            recv[r]["value"] += amt
            sent[s]["settled_value"] += amt
            h = min(hours, max(0, int((at - open_at).total_seconds() // 3600)))
            sent[s]["by_hour"][h] += amt
        if kind in timed_kinds:
            t = timed[s]
            t["count"] += 1
            t["value"] += amt
            if not settled:
                t["failed"] += 1
                t["failed_value"] += amt
            elif _ts(p["settled_at"]) > _ts(p["due"]):
                t["late"] += 1
                t["late_value"] += amt

    rows = []
    for i, meta in sorted(insts.items()):
        pos = lo = hi = 0
        lo_at = hi_at = open_at
        for at, d in sorted(flows[i]):
            pos += d
            if pos < lo:
                lo, lo_at = pos, at
            if pos > hi:
                hi, hi_at = pos, at
        opening = sum(v for r, v in meta["opening_minor"].items() if r in rails)
        credit = int(meta.get("credit_limit_minor", 0))
        available = opening + credit
        cum, throughput = 0, []
        total_out = sent[i]["value"]
        for h in range(hours + 1):
            cum += sent[i]["by_hour"][h]
            throughput.append(round(cum / total_out, 6) if total_out else None)
        rows.append({
            "institution_id": i, "tier": meta.get("tier"),
            "A_i_max_net_negative_position_minor": -lo, "A_i_max_negative_at": lo_at.isoformat() if lo else None,
            "A_i_max_net_positive_position_minor": hi, "A_i_max_positive_at": hi_at.isoformat() if hi else None,
            "A_i_usage_share_of_available": round(-lo / available, 6) if available else None,
            "A_ii_available_at_start_minor": available,
            "A_ii_sources": {"reserve_and_settlement_balances_minor": opening, "committed_intraday_credit_minor": credit},
            "A_iii_gross_sent_minor": sent[i]["settled_value"], "A_iii_gross_received_minor": recv[i]["value"],
            "A_iii_submitted_minor": total_out, "A_iii_sent_count": sent[i]["count"],
            "A_iv_time_specific": dict(timed[i]),
            "C_i_throughput_by_hour": throughput,
            "end_of_day_net_position_minor": pos,
        })
    worst = max(rows, key=lambda r: (r["A_i_usage_share_of_available"] or 0, r["institution_id"])) if rows else None
    return {
        "version": BCBS248_VERSION, "standard": "BCBS 248 (April 2013) monitoring tools A(i)-A(iv), C(i)", "rails": list(rails),
        "open_at": open_at.isoformat(), "close_at": close_at.isoformat(),
        "hour_labels": [f"+{h + 1}h" for h in range(hours + 1)],
        "system": {
            "sum_max_net_negative_minor": sum(r["A_i_max_net_negative_position_minor"] for r in rows),
            "sum_available_at_start_minor": sum(r["A_ii_available_at_start_minor"] for r in rows),
            "gross_settled_minor": sum(r["A_iii_gross_sent_minor"] for r in rows),
            "liquidity_efficiency": (round(sum(r["A_iii_gross_sent_minor"] for r in rows) / max(1, sum(r["A_i_max_net_negative_position_minor"] for r in rows)), 4)),
            "most_stretched_institution": worst["institution_id"] if worst else None,
            "time_specific_failed": sum(r["A_iv_time_specific"]["failed"] for r in rows),
            "time_specific_late": sum(r["A_iv_time_specific"]["late"] for r in rows),
        },
        "institutions": rows,
        "not_implemented": ["B(i) value of payments made on behalf of correspondent banking customers",
                            "B(ii) intraday credit lines extended to customers"],
        "data_origin": run.get("scenario", {}).get("data_origin"),
    }
