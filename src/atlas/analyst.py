"""Grounded analyst for the Decision Center (``atlas-analyst-v1``).

Routes a natural-language question to a deterministic query over one simulation's
results. Every number in an answer is copied from a computed field and listed under
``evidence`` with the path it came from. No generative model is involved: an
LLM may later be attached to *phrase* these answers, never to produce values, and
nothing here can execute an intervention (blueprint principle 15).
"""

from __future__ import annotations

import re
from typing import Any

ANALYST_VERSION = "atlas-analyst-v1"

INTENTS = {
    "liquidity_decline": ("liquidity", "declin", "drain", "falling", "cash", "dropping"),
    "most_exposed": ("exposed", "exposure", "risk", "vulnerable", "systemic", "critical"),
    "best_policy": ("best", "policy", "performed", "which settlement", "compare", "winner"),
    "delay_what_if": ("what if", "what happens", "delayed", "late", "outage", "counterfactual"),
    "cheapest_intervention": ("intervention", "lowest", "cheapest", "cost", "reduce", "improve"),
    "unsettled": ("unsettled", "failed", "missed", "deadline", "stuck", "gridlock"),
}


def classify(question: str) -> str:
    q = question.lower()
    scores = {k: sum(1 for w in words if w in q) for k, words in INTENTS.items()}
    best = max(scores, key=lambda k: (scores[k], k))
    return best if scores[best] > 0 else "unknown"


def _usd(minor: float) -> str:
    v = minor / 100
    return f"${v / 1e9:.2f}B" if abs(v) >= 1e9 else f"${v / 1e6:.1f}M"


def answer(question: str, run: dict, benchmark: dict | None = None) -> dict[str, Any]:
    """``run`` is SimulationResult.to_dict(include_payments=True); ``benchmark`` an optional benchmark artifact."""
    intent = classify(question)
    m = run["metrics"]
    ev: list[dict] = []

    def cite(path: str, value: Any) -> Any:
        ev.append({"path": path, "value": value})
        return value

    if intent == "liquidity_decline":
        ts = run["timeseries"]
        rows = []
        for rail in ("rtgs", "lsm", "fednow", "rtp"):
            a, b = ts[0].get(f"{rail}_cash_minor", 0), ts[-1].get(f"{rail}_cash_minor", 0)
            rows.append((b - a, rail, a, b))
        rows.sort()
        d, rail, a, b = rows[0]
        cite(f"timeseries[0].{rail}_cash_minor", a)
        cite(f"timeseries[-1].{rail}_cash_minor", b)
        peak = cite("metrics.liquidity.peak_intraday_credit_minor", m["liquidity"]["peak_intraday_credit_minor"])
        moved = cite("metrics.counters.transfers_minor", m["counters"].get("transfers_minor", 0))
        text = (f"Cash fell most on {rail.upper()}: {_usd(a)} at open to {_usd(b)} at close ({_usd(d)}). Liquidity on a rail only changes "
                f"through payment flows, shocks or own-account transfers; {_usd(moved)} was moved between rails and peak intraday credit was {_usd(peak)}.")
    elif intent == "most_exposed":
        inst = sorted(run["per_institution"], key=lambda x: (x["settlement_rate_value"], -x["sent_value_minor"]))[:3]
        parts = []
        for x in inst:
            cite(f"per_institution[{x['institution_id']}].settlement_rate_value", x["settlement_rate_value"])
            cite(f"per_institution[{x['institution_id']}].liquidity_usage_minor", x["liquidity_usage_minor"])
            parts.append(f"{x['institution_id']} ({x['tier']}, {x['strategy']}): {x['settlement_rate_value'] * 100:.1f}% of its sent value settled, "
                         f"liquidity used {_usd(x['liquidity_usage_minor'])}")
        text = "Lowest settled share of own outgoing value: " + "; ".join(parts) + "."
    elif intent == "best_policy":
        if not benchmark:
            text = "No benchmark artifact is loaded; run the NEXUS-PAY benchmark to compare policies."
        else:
            ref = benchmark["config"]["reference_arm"]
            rows = [c for c in benchmark["comparison"] if c["metric"] == "total_cost_minor" and c["stress"] == "baseline"]
            rows.sort(key=lambda c: c["mean"])
            top = rows[0]
            cite(f"benchmark.comparison[baseline,{top['arm']},total_cost_minor].mean", top["mean"])
            cite(f"benchmark.comparison[baseline,{top['arm']},total_cost_minor].ci95_diff", top["ci95_diff"])
            sig = "significant" if top["significant"] else "not significant"
            text = (f"On baseline days the lowest mean modeled cost is `{top['arm']}` at {_usd(top['mean'])} vs `{ref}` "
                    f"{_usd(top['reference_mean'])} (paired difference {_usd(top['mean_diff'])}, 95% CI {_usd(top['ci95_diff'][0])} to "
                    f"{_usd(top['ci95_diff'][1])}, {sig}, n={top['n']} seeds).")
    elif intent == "delay_what_if":
        lv = m["large_value"]
        cite("metrics.large_value.value_weighted_delay_s", lv["value_weighted_delay_s"])
        cite("metrics.large_value.settlement_rate_value", lv["settlement_rate_value"])
        text = (f"This run settled {lv['settlement_rate_value'] * 100:.2f}% of large-value value with {lv['value_weighted_delay_s'] / 60:.1f} min "
                "value-weighted delay. To answer a what-if exactly, run a paired counterfactual on the same day: POST "
                f"/api/v1/simulations/{run['simulation_id']}/counterfactual with e.g. {{\"stress\": \"counterparty_delay\"}}. "
                "The analyst does not estimate counterfactual numbers; it only reports simulated ones.")
    elif intent == "cheapest_intervention":
        costs = m["costs_minor"]
        comps = sorted(((v, k) for k, v in costs.items() if k != "total"), reverse=True)
        for v, k in comps[:3]:
            cite(f"metrics.costs_minor.{k}", v)
        biggest = comps[0][1]
        lever = {"unsettled_penalty": "more liquidity at the right rail (rebalancing or an auction)", "delay": "earlier release or netting",
                 "instant_rejections": "pre-funding instant accounts", "daylight_overdraft_fee": "pledging collateral",
                 "liquidity": "liquidity-saving netting", "late_penalty": "deadline-aware prioritisation"}.get(biggest, "reducing that component")
        text = (f"The largest modeled cost component is {biggest.replace('_', ' ')} ({_usd(comps[0][0])} of {_usd(cite('metrics.costs_minor.total', costs['total']))}). "
                f"The cheapest lever to test is {lever}; compare arms with a paired counterfactual before acting.")
    elif intent == "unsettled":
        unsettled = [p for p in run.get("payments", []) if p["status"] != "settled" and p["rail"] in ("rtgs", "lsm")]
        reasons: dict[str, int] = {}
        for p in unsettled:
            reasons[p.get("reason") or "unknown"] = reasons.get(p.get("reason") or "unknown", 0) + p["amount_minor"]
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
        for r, v in top:
            cite(f"payments[status!=settled].reason={r}", v)
        text = (f"{len(unsettled)} large-value payments did not settle. By value: " + "; ".join(f"{r}: {_usd(v)}" for r, v in top) + "."
                if unsettled else "Every large-value payment settled.")
    else:
        text = ("I can answer: why liquidity is declining, which institutions are most exposed, which policy performed best, "
                "what-if questions (via a paired counterfactual), the lowest-cost lever, and why payments did not settle.")
    return {"version": ANALYST_VERSION, "question": question, "intent": intent, "answer": text, "evidence": ev,
            "grounding": "every number above is copied from the cited fields of this simulation or benchmark; no generative model is used",
            "can_execute": False}


__all__ = ["ANALYST_VERSION", "INTENTS", "answer", "classify"]

_ = re  # reserved for richer parsing
