"""One-call entry point for the browser lab and other thin front ends (``atlas-lab-v1``). Standard library only.

``run_lab`` takes a small dict of choices (or a user's CSV), runs one business day and returns everything a
dashboard needs as plain JSON-serialisable data. The same function runs natively and under Pyodide in the browser,
where the user's file never leaves their machine.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from atlas.regulatory import intraday_liquidity_report
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day
from atlas.stress import build_scenario

LAB_VERSION = "atlas-lab-v1"
LAB_POLICIES = ("fifo", "priority", "bilateral", "multilateral")
LAB_CONTROLLERS = ("none", "rule", "mpc")      # "mpc" needs numpy and scipy (not offered in the browser lab)
_NY = "America/New_York"


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def run_lab(params: dict | None = None, csv_text: str | None = None, balances_csv: str | None = None, *, detail: bool = False) -> dict:
    """``detail=True`` also returns the raw run (``_run``), the result object (``_result``) and the scenario
    (``_scenario``) for front ends that drill further; those three are not JSON-serialisable."""
    p = params or {}
    policy = p.get("policy", "priority") if p.get("policy") in LAB_POLICIES else "priority"
    controller = p.get("controller", "none") if p.get("controller") in LAB_CONTROLLERS else "none"
    auction = p.get("auction") if p.get("auction") in ("pay_as_bid", "uniform") else None
    stress = str(p.get("stress", "baseline"))
    liquidity_bp = _clamp(p.get("liquidity_pct", 18), 2, 100, 18) * 100
    t0 = time.perf_counter()
    ingest = None
    if csv_text:
        from atlas.ingest import load_payments_csv
        scenario, report = load_payments_csv(csv_text, balances_csv=balances_csv, opening_liquidity_bp=liquidity_bp)
        ingest = report.to_dict()
    else:
        cfg = replace(NexusPayConfig(), n_institutions=_clamp(p.get("banks", 12), 4, 40, 12), payments_per_day=_clamp(p.get("payments", 1500), 100, 20000, 1500),
                      instant_payments_per_day=_clamp(p.get("instant", 1000), 0, 20000, 1000), opening_liquidity_bp=liquidity_bp)
        scenario = generate_scenario(cfg, seed=_clamp(p.get("seed", 11), 0, 2**31 - 1, 11))
    ctrl = None
    if controller == "rule":
        from atlas.control.mpc import RuleBasedRebalancer
        ctrl = RuleBasedRebalancer()
    elif controller == "mpc":
        from atlas.control.mpc import MPCController
        ctrl = MPCController()
    settings = SimulationSettings(policy=policy, auction=auction, fednow_shared_master=bool(p.get("shared_master", False)))
    result = run_day(scenario, settings, build_scenario(stress), controller=ctrl)
    d = result.to_dict(include_payments=True)
    replay = result.verify_replay()
    bcbs = intraday_liquidity_report(d)
    m = d["metrics"]
    lv, inst, costs = m["large_value"], m["instant"], m["costs_minor"]
    tz = ZoneInfo(_NY)
    ts = d["timeseries"]
    usd = lambda v: round(v / 100, 2)
    hours = len(bcbs["hour_labels"])
    sys_out = [0.0] * hours
    total_out = sum(r["A_iii_submitted_minor"] for r in bcbs["institutions"]) or 1
    for r in bcbs["institutions"]:
        for h, share in enumerate(r["C_i_throughput_by_hour"]):
            sys_out[h] += (share or 0.0) * r["A_iii_submitted_minor"]
    own = {x["institution_id"]: x for x in d["per_institution"]}
    unsettled = sorted((x for x in d["payments"] if x["status"] != "settled"), key=lambda x: -x["amount_minor"])
    extra = {"_run": d, "_result": result, "_scenario": scenario, "_bcbs": bcbs} if detail else {}
    return extra | {
        "version": LAB_VERSION, "data_origin": d["scenario"].get("data_origin"), "ingest": ingest,
        "choices": {"policy": policy, "stress": stress, "controller": controller, "auction": auction or "none",
                    "liquidity_pct": liquidity_bp // 100, "shared_master": bool(p.get("shared_master", False))},
        "scenario": {"institutions": d["scenario"]["institutions"], "payments": d["scenario"]["payments"],
                     "value_usd": usd(lv["value_minor"] + inst["value_minor"]), "fingerprint": d["scenario"]["fingerprint"][:16]},
        "kpis": {
            "settled_pct": round(lv["settlement_rate_value"] * 100, 2), "delay_min": round(lv["value_weighted_delay_s"] / 60, 1),
            "instant_rejected": inst["count"] - inst["settled_count"], "instant_total": inst["count"],
            "unsettled_usd": usd(lv["value_minor"] - lv["settled_value_minor"]), "deadline_misses": lv["deadline_miss_count"],
            "peak_credit_usd": usd(m["liquidity"]["peak_intraday_credit_minor"]), "cost_usd": usd(costs["total"]),
            "cost_components_usd": {k: usd(v) for k, v in costs.items() if k != "total" and v},
            "max_net_debit_usd": usd(bcbs["system"]["sum_max_net_negative_minor"]), "available_usd": usd(bcbs["system"]["sum_available_at_start_minor"]),
            "late_timed": bcbs["system"]["time_specific_late"], "failed_timed": bcbs["system"]["time_specific_failed"],
        },
        "integrity": {"replay_verified": replay, "state_hash": result.final_state_hash, "events": len(result.events),
                      "runtime_s": round(time.perf_counter() - t0, 2)},
        "series": {
            "t": [datetime.fromisoformat(r["t"]).astimezone(tz).strftime("%H:%M") for r in ts],
            "queued_usd": [usd(r.get("rtgs_queued_value_minor", 0) + r.get("lsm_queued_value_minor", 0) + r.get("held_value_minor", 0)) for r in ts],
            "settled_usd": [usd(r.get("settled_value_minor", 0)) for r in ts],
            "credit_usd": [usd(r.get("rtgs_credit_used_minor", 0)) for r in ts],
            "cash_usd": {rail: [usd(r.get(f"{rail}_cash_minor", 0)) for r in ts] for rail in ("rtgs", "lsm", "fednow", "rtp")},
        },
        "throughput": {"hours": [(datetime.fromisoformat(bcbs["open_at"]).astimezone(tz) + timedelta(hours=h + 1)).strftime("%H:%M") for h in range(hours)],
                       "share": [round(v / total_out, 4) for v in sys_out]},
        "banks": [{"id": r["institution_id"], "tier": r["tier"], "max_net_debit_usd": usd(r["A_i_max_net_negative_position_minor"]),
                   "available_usd": usd(r["A_ii_available_at_start_minor"]), "usage_pct": round((r["A_i_usage_share_of_available"] or 0) * 100, 1),
                   "own_settled_pct": round(own[r["institution_id"]]["settlement_rate_value"] * 100, 2),
                   "sent_usd": usd(r["A_iii_submitted_minor"])} for r in bcbs["institutions"]],
        "unsettled": [{"id": x["payment_id"], "rail": x["rail"], "from": x["sender"], "to": x["receiver"], "usd": usd(x["amount_minor"]),
                       "why": x.get("reason") or x["status"]} for x in unsettled[:12]],
        "unsettled_count": len(unsettled),
    }
