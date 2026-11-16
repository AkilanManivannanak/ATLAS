"""Derived views for interactive front ends (``atlas-insight-v1``). Standard library only.

* ``day_frames``     per-bank positions, queues and interbank flows in fixed time steps, for animating a day
* ``bank_detail``    one bank's intraday position curve, counterparties and unsettled payments
* ``tamper_check``   change one settled amount in a copy of the event log and show that both the hash chain and
                     the strict replay notice
* ``liquidity_sweep`` the settle-versus-liquidity frontier for a set of configurations
* ``review_url``     a pre-filled GitHub issue link so a reviewer's feedback lands in the public tracker
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

INSIGHT_VERSION = "atlas-insight-v1"
_NY = ZoneInfo("America/New_York")
_LV = ("rtgs", "lsm")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def day_frames(run: Mapping[str, Any], step_min: int = 30, top_flows: int = 14, rails: Sequence[str] = _LV) -> dict:
    """Split the day into ``step_min`` windows. For each window and bank: net position at the end of the window,
    value it has submitted but not yet settled, and the largest bilateral flows settled inside the window."""
    ts = run["timeseries"]
    open_at, close_at = _ts(ts[0]["t"]), _ts(ts[-1]["t"])
    n = max(1, int((close_at - open_at).total_seconds() // (step_min * 60)) + 1)
    banks = [x["institution_id"] for x in run["per_institution"]]
    idx = {b: i for i, b in enumerate(banks)}
    net = [[0] * len(banks) for _ in range(n)]
    queued = [[0] * len(banks) for _ in range(n)]
    flows: list[dict[tuple[str, str], int]] = [{} for _ in range(n)]
    settled_value = [0] * n
    frame_of = lambda at: min(n - 1, max(0, int((at - open_at).total_seconds() // (step_min * 60))))
    for p in run["payments"]:
        if p["rail"] not in rails or p["sender"] not in idx or p["receiver"] not in idx:
            continue
        a = frame_of(_ts(p["arrival"]))
        s = frame_of(_ts(p["settled_at"])) if p["status"] == "settled" and p.get("settled_at") else None
        amt = p["amount_minor"]
        for f in range(a, n if s is None else s):
            queued[f][idx[p["sender"]]] += amt
        if s is not None:
            for f in range(s, n):
                net[f][idx[p["sender"]]] -= amt
                net[f][idx[p["receiver"]]] += amt
            key = (p["sender"], p["receiver"])
            flows[s][key] = flows[s].get(key, 0) + amt
            settled_value[s] += amt
    cum, total = [], 0
    for v in settled_value:
        total += v
        cum.append(total)
    return {
        "version": INSIGHT_VERSION, "step_min": step_min, "banks": banks,
        "tiers": [x["tier"] for x in run["per_institution"]],
        "sent_minor": [x["sent_value_minor"] for x in run["per_institution"]],
        "available_minor": [sum(v for r, v in x["opening_minor"].items() if r in rails) + int(x.get("credit_limit_minor", 0)) for x in run["per_institution"]],
        "labels": [(open_at + timedelta(minutes=step_min * (i + 1))).astimezone(_NY).strftime("%H:%M") for i in range(n)],
        "net_minor": net, "queued_minor": queued, "settled_cum_minor": cum,
        "queued_total_minor": [sum(q) for q in queued],
        "flows": [[{"from": k[0], "to": k[1], "minor": v} for k, v in sorted(f.items(), key=lambda kv: -kv[1])[:top_flows]] for f in flows],
    }


def bank_detail(run: Mapping[str, Any], bank: str, rails: Sequence[str] = _LV) -> dict:
    events, out_to, in_from, unsettled = [], {}, {}, []
    for p in run["payments"]:
        if p["rail"] not in rails or bank not in (p["sender"], p["receiver"]):
            continue
        settled = p["status"] == "settled" and p.get("settled_at")
        if p["sender"] == bank:
            if settled:
                events.append((_ts(p["settled_at"]), -p["amount_minor"]))
                out_to[p["receiver"]] = out_to.get(p["receiver"], 0) + p["amount_minor"]
            else:
                unsettled.append(p)
        elif settled:
            events.append((_ts(p["settled_at"]), p["amount_minor"]))
            in_from[p["sender"]] = in_from.get(p["sender"], 0) + p["amount_minor"]
    events.sort()
    pos, curve = 0, []
    for at, d in events:
        pos += d
        curve.append((at.astimezone(_NY).strftime("%H:%M:%S"), pos))
    meta = next(x for x in run["per_institution"] if x["institution_id"] == bank)
    top = lambda d: [{"bank": k, "minor": v} for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:6]]
    return {"bank": bank, "tier": meta["tier"], "strategy": meta.get("strategy"), "curve": curve,
            "lowest_minor": min([c[1] for c in curve] + [0]), "closing_minor": pos,
            "available_minor": sum(v for r, v in meta["opening_minor"].items() if r in rails) + int(meta.get("credit_limit_minor", 0)),
            "own_settled_share": meta["settlement_rate_value"], "pays_most_to": top(out_to), "receives_most_from": top(in_from),
            "unsettled": sorted(({"payment_id": p["payment_id"], "to": p["receiver"], "minor": p["amount_minor"],
                                  "why": p.get("reason") or p["status"]} for p in unsettled), key=lambda x: -x["minor"])[:8],
            "unsettled_count": len(unsettled)}


def tamper_check(result, which: int = 0, factor: float = 1.01) -> dict:
    """Alter the amount of the ``which``-th settled payment in a *copy* of the event log, then run both integrity
    checks. Nothing in ``result`` is modified."""
    from atlas.ledger.book import Ledger
    from atlas.store.event_store import chain_hash

    events = list(result.events)
    settled = [i for i, e in enumerate(events) if e.event_type == "PaymentSettled"]
    if not settled:
        return {"available": False}
    i = settled[which % len(settled)]
    payload = json.loads(events[i].payload_json)
    key = next((k for k in ("amount_minor", "amount") if isinstance(payload.get(k), int)), None)
    if key is None:
        return {"available": False}
    before = payload[key]
    payload[key] = max(1, int(before * factor)) if int(before * factor) != before else before + 1
    forged = replace(events[i], payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def head(evs) -> list[str]:
        h, out = "0" * 64, []
        for e in evs:
            h = chain_hash(h, e)
            out.append(h)
        return out

    original, changed = head(events), head(events[:i] + [forged] + events[i + 1:])
    first_diff = next(k for k, (a, b) in enumerate(zip(original, changed)) if a != b)
    try:
        replay_hash = Ledger.replay(result.opening_accounts, events[:i] + [forged] + events[i + 1:]).state_hash()
        replay_error = None if replay_hash != result.final_state_hash else "undetected"
        replay_caught = replay_hash != result.final_state_hash
        if replay_caught:
            replay_error = "replayed ledger ends in a different state hash"
    except Exception as exc:  # noqa: BLE001 - any rejection by the strict ledger counts as detection
        replay_caught, replay_error = True, f"{type(exc).__name__}: {exc}"[:240]
    return {
        "available": True, "event_sequence": events[i].sequence_number, "event_index": i, "events": len(events),
        "payment": payload.get("payment_id"), "amount_before_minor": before, "amount_after_minor": payload[key],
        "chain_head_original": original[-1], "chain_head_tampered": changed[-1], "chain_caught": original[-1] != changed[-1],
        "first_broken_link": first_diff, "links_invalidated": len(events) - first_diff,
        "replay_caught": replay_caught, "replay_message": replay_error,
        "untouched_replay_ok": result.verify_replay(),
    }


def liquidity_sweep(run_fn: Callable[[int], Mapping[str, Any]], levels_pct: Sequence[int] = (6, 10, 14, 18, 24, 30)) -> list[dict]:
    """``run_fn(liquidity_pct)`` returns ``run_lab``-style output; collect the frontier points."""
    out = []
    for pct in levels_pct:
        k = run_fn(pct)["kpis"]
        out.append({"liquidity_pct": pct, "settled_pct": k["settled_pct"], "cost_usd": k["cost_usd"], "delay_min": k["delay_min"],
                    "unsettled_usd": k["unsettled_usd"], "peak_credit_usd": k["peak_credit_usd"]})
    return out


RATINGS = ("5 - excellent", "4 - good", "3 - mixed", "2 - weak", "1 - poor")


def review_url(repo: str, *, rating: int | None, role: str, tried: Sequence[str], worked: str, broke: str, would_use: str) -> str:
    """Link to the repository's *Review* issue form with the reviewer's answers pre-filled (they still press Submit,
    under their own GitHub account, so every published review is attributable to a real person)."""
    params = {"template": "review.yml", "title": f"Review: {rating}/5" + (f" from a {role}" if role else "") if rating else "Review",
              "role": role, "tried": ", ".join(tried), "worked": worked, "broke": broke, "would_use": would_use}
    if rating:
        params["rating"] = RATINGS[5 - rating]
    return f"https://github.com/{repo}/issues/new?" + urlencode({k: v for k, v in params.items() if v})
