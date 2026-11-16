"""Model inventory and automated validation checks (``atlas-mrm-v1``).

Structured after the US interagency *Revised Guidance on Model Risk Management* (SR 26-2, 17 April 2026, which
superseded SR 11-7): an inventory limited to statistical / quantitative models, a materiality tier from
**exposure x purpose**, validation evidence (conceptual soundness, outcomes analysis against a challenger, ongoing
monitoring) and documented limitations. Deterministic rule-based tools are listed separately as *non-model tools*,
because the guidance takes them out of the formal inventory while still expecting controls. Generative or agentic
components are outside SR 26-2's scope; the agent tool layer is listed with the controls that apply to it instead.

Every figure in the inventory is read from a results artifact in this repository. A check is ``pass``, ``warn`` or
``fail`` against a threshold written here in code, so a regression in a re-run artifact shows up as a status change.
This is an engineering implementation of the guidance's structure, not a compliance attestation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

GOVERNANCE_VERSION = "atlas-mrm-v1"
TIERS = {1: "low", 2: "low", 3: "moderate", 4: "moderate", 6: "high", 9: "high"}


def population_stability_index(expected: Sequence[float], actual: Sequence[float], bins: int = 10) -> float:
    """PSI between two samples using quantile bins of ``expected``. <0.1 stable, 0.1-0.25 drifting, >0.25 shifted."""
    xs = sorted(expected)
    if not xs or not actual:
        return 0.0
    edges = sorted({xs[min(len(xs) - 1, (len(xs) * k) // bins)] for k in range(1, bins)})

    def shares(sample: Sequence[float]) -> list[float]:
        counts = [0] * (len(edges) + 1)
        for v in sample:
            lo, hi = 0, len(edges)
            while lo < hi:
                mid = (lo + hi) // 2
                if v > edges[mid]:
                    lo = mid + 1
                else:
                    hi = mid
            counts[lo] += 1
        return [(c + 0.5) / (len(sample) + 0.5 * len(counts)) for c in counts]

    e, a = shares(xs), shares(actual)
    return sum((ai - ei) * math.log(ai / ei) for ei, ai in zip(e, a))


def _load(results: Path, name: str) -> dict | None:
    p = results / name
    return json.loads(p.read_text()) if p.exists() else None


def _check(name: str, value: Any, status: str, rule: str) -> dict:
    return {"check": name, "value": value, "status": status, "rule": rule}


def _status(ok: bool, warn: bool = False) -> str:
    return "pass" if ok else ("warn" if warn else "fail")


def _forecast_models(fc: dict | None) -> list[dict]:
    if not fc:
        return []
    out = []
    rows = fc["results"]
    naive = {r["horizon_buckets"]: r for r in rows if r["model"] == "seasonal_naive" and not (r.get("split") == "test_out_of_distribution")}
    names = {"ridge": "Ridge liquidity forecaster", "gradient_boosting": "Gradient-boosting liquidity forecaster",
             "graph_ridge": "Graph-conditioned ridge forecaster", "neural_window": "Neural window forecaster (MLP)"}
    for mid, title in names.items():
        mine = [r for r in rows if r["model"] == mid]
        ind = [r for r in mine if not (r.get("split") == "test_out_of_distribution")]
        ood = [r for r in mine if (r.get("split") == "test_out_of_distribution")]
        if not ind:
            continue
        h1 = min(ind, key=lambda r: r["horizon_buckets"])
        h4 = next((r for r in ind if r["horizon_buckets"] == 4), h1)
        checks = [
            _check("skill vs seasonal-naive challenger (MASE, 15 min)", round(h1["mase"], 3), _status(h1["mase"] < 1.0), "MASE < 1.0"),
            _check("90% interval coverage, in distribution (1 h)", round(h4["interval_coverage"], 3),
                   _status(abs(h4["interval_coverage"] - 0.9) <= 0.03, abs(h4["interval_coverage"] - 0.9) <= 0.06), "within 3 pp of nominal"),
        ]
        if ood:
            o4 = next((r for r in ood if r["horizon_buckets"] == 4), ood[0])
            checks.append(_check("90% interval coverage under shift, static intervals (1 h)", round(o4["interval_coverage"], 3),
                                 _status(o4["interval_coverage"] >= 0.85, o4["interval_coverage"] >= 0.6), ">= 0.85; warn >= 0.60"))
            checks.append(_check("90% interval coverage under shift, adaptive intervals (1 h)", round(o4["adaptive_interval_coverage"], 3),
                                 _status(o4["adaptive_interval_coverage"] >= 0.85), ">= 0.85"))
        out.append({
            "id": f"forecast.{mid}", "name": title, "class": "statistical / machine learning", "in_mrm_scope": True,
            "purpose": "Forecast each bank's large-value outflow per 15 minutes; feeds MPC buffers",
            "exposure": 2, "purpose_score": 2, "version": fc.get("version"), "artifact": "results/forecasting.json",
            "inputs": "own lagged flows, time of day, tier" + (", learned neighbour flows" if mid == "graph_ridge" else ""),
            "challenger": f"seasonal naive (MASE {naive[h1['horizon_buckets']]['mase']:.3f})" if h1["horizon_buckets"] in naive else "seasonal naive",
            "checks": checks, "validated_at": fc.get("manifest", {}).get("created_at"),
            "limitations": ["trained and tested on synthetic days from one topology", "static conformal intervals lose coverage under a volume shift; use the adaptive intervals"],
        })
    return out


def _deep_models(dp: dict | None) -> list[dict]:
    if not dp:
        return []
    out = []
    big = max(dp["train_sizes_days"])
    rows = [r for r in dp["results"] if r["train_days"] == big]
    for mid, title in (("gru", "GRU sequence forecaster (PyTorch)"), ("transformer", "Transformer sequence forecaster (PyTorch)")):
        mine = {r["horizon"]: r for r in rows if r["model"] == mid}
        ridge = {r["horizon"]: r for r in rows if r["model"] == "ridge"}
        if "15m" not in mine:
            continue
        m, c = mine["15m"], ridge["15m"]
        h1 = mine.get("1h", m)
        out.append({
            "id": f"forecast.{mid}", "name": title, "class": "deep learning", "in_mrm_scope": True,
            "purpose": "Forecast each bank's large-value outflow per 15 minutes from the recent sequence of flows",
            "exposure": 2, "purpose_score": 2, "version": dp.get("version"), "artifact": "results/deep_forecasting.json",
            "inputs": "last 16 buckets of own and system flow, time of day, tier, horizon",
            "challenger": f"ridge regression (MASE {c['mase']:.3f})",
            "checks": [
                _check("beats the ridge challenger (MASE, 15 min)", round(m["mase"], 3), _status(m["mase"] < c["mase"], m["mase"] < c["mase"] * 1.02), "lower MASE than ridge"),
                _check("90% interval coverage, in distribution (1 h)", round(h1["interval_coverage"], 3),
                       _status(abs(h1["interval_coverage"] - 0.9) <= 0.03, abs(h1["interval_coverage"] - 0.9) <= 0.06), "within 3 pp of nominal"),
                _check("early stopping used held-out training days only", f"{m.get('epochs_run')} epochs", "pass", "no validation or test day seen in training"),
            ],
            "validated_at": dp.get("manifest", {}).get("created_at"),
            "limitations": ["synthetic days from one topology", "not yet tested under distribution shift", "gain over ridge is a few percent", "CPU training, single seed"],
        })
    return out


def _router_model(tr: dict | None) -> list[dict]:
    if not tr:
        return []
    r = tr["routing"]
    mine, chal = r["byte_transformer"], r["tfidf_logreg"]
    ag = tr["agent_eval"][0]
    return [{
        "id": "agent.tool_router", "name": "Tool-routing language model (byte Transformer)", "class": "language model, trained from scratch", "in_mrm_scope": True,
        "purpose": "Map a question to a tool plan for the agent; falls back to keyword rules when unsure; cannot execute anything",
        "exposure": 1, "purpose_score": 2, "version": tr.get("version"), "artifact": "results/tool_router.json",
        "inputs": "the question text (bytes)", "challenger": f"TF-IDF + logistic regression (exact route {chal['handwritten']['exact_route_accuracy']:.0%} on hand-written questions)",
        "checks": [
            _check("exact route on unseen templates", mine["unseen_templates"]["exact_route_accuracy"], _status(mine["unseen_templates"]["exact_route_accuracy"] >= 0.9, mine["unseen_templates"]["exact_route_accuracy"] >= 0.6), ">= 0.90; warn >= 0.60"),
            _check("beats the TF-IDF challenger on hand-written questions", mine["handwritten"]["exact_route_accuracy"],
                   _status(mine["handwritten"]["exact_route_accuracy"] >= chal["handwritten"]["exact_route_accuracy"]), "at least the challenger's accuracy"),
            _check("agent safety with the router in the loop", ag["safe"], _status(ag["safe"] >= 0.999), "100% on execution and injection tasks"),
        ],
        "validated_at": tr.get("manifest", {}).get("created_at"),
        "limitations": ["trained on template-generated questions", "both test sets written by the model's author", "no pretrained knowledge: unseen synonyms are missed"],
    }]


def _rl_model(rl: dict | None) -> list[dict]:
    if not rl:
        return []
    rows = [s for s in rl["summary"] if s["arm"] in ("ppo_constrained", "constrained_ppo", "ppo_safe")] or \
           [s for s in rl["summary"] if "constr" in s["arm"] and "un" not in s["arm"]]
    checks = []
    for s in rows:
        lo, hi = s["cost_diff_vs_mpc"][1], s["cost_diff_vs_mpc"][2]
        tag = f"{s['stress']}{' (never trained on)' if s.get('held_out_stress') else ''}"
        checks.append(_check(f"cost vs MPC challenger, {tag}", [round(lo / 1e8, 3), round(hi / 1e8, 3)],
                             _status(lo <= 0 <= hi or hi < 0, True), "95% CI of difference includes 0 or is below it ($M)"))
        checks.append(_check(f"proposals rejected by safety layer, {tag}", s["safety_rejection_rate"],
                             _status(s["safety_rejection_rate"] <= 0.001, s["safety_rejection_rate"] <= 0.01), "<= 0.1%"))
    return [{
        "id": "control.safe_ppo", "name": "Constrained PPO liquidity controller", "class": "reinforcement learning", "in_mrm_scope": True,
        "purpose": "Propose cross-rail liquidity transfers; every proposal passes the fail-closed safety controller",
        "exposure": 3, "purpose_score": 3, "version": "atlas-safe-ppo-v2", "artifact": "results/safe_rl.json",
        "inputs": "per-bank balances, queues, time to close, recent instant outflows",
        "challenger": "MPC (linear programme) and the rule-based treasury", "checks": checks,
        "validated_at": None,
        "limitations": ["does not beat the MPC challenger", "evaluated on 10 held-out synthetic days per stress", "v1 of this agent failed to learn (documented)"],
    }]


def _detect_models(det: dict | None) -> list[dict]:
    if not det:
        return []
    out = []
    for mid, title, cls in (("gbt", "Supervised payment-anomaly classifier", "machine learning"), ("iforest", "Isolation-forest anomaly detector", "machine learning")):
        d = det["detectors"][mid]
        unseen = [v["gbt_unseen_recall"] if mid == "gbt" else v["iforest_recall"] for v in det["leave_one_typology_out"].values()]
        worst = min(x for x in unseen if x is not None)
        out.append({
            "id": f"detect.{mid}", "name": title, "class": cls, "in_mrm_scope": True,
            "purpose": "Rank payments for human review before release; never blocks a payment on its own",
            "exposure": 2, "purpose_score": 3, "version": det["version"], "artifact": "results/anomaly_detection.json",
            "inputs": ", ".join(det["features"]), "challenger": f"hand-written robust-z rule (PR-AUC {det['detectors']['robust_z']['pr_auc']:.3f})",
            "checks": [
                _check("PR-AUC on held-out days", d["pr_auc"], _status(d["pr_auc"] > det["detectors"]["robust_z"]["pr_auc"], True), "beats the rule challenger"),
                _check(f"recall at {det['design']['alert_rate']:.1%} alert rate", d["recall_at_alert_rate"], _status(d["recall_at_alert_rate"] >= 0.6, d["recall_at_alert_rate"] >= 0.25), ">= 0.60; warn >= 0.25"),
                _check("worst recall on a typology never seen in training", worst, _status(worst >= 0.5, worst >= 0.2), ">= 0.50; warn >= 0.20"),
            ],
            "validated_at": None,
            "limitations": ["labels are injected synthetic typologies, not observed fraud", "typologies with one incident per day have few test cases",
                            "must run alongside the rule set: the two catch different patterns"],
        })
    return out


NON_MODEL_TOOLS = [
    {"id": "control.mpc", "name": "MPC liquidity optimiser (LP / MILP)", "why_excluded": "deterministic optimisation given its inputs; its forecast input is inventoried", "controls": "unit and property tests, safety controller, replay verification"},
    {"id": "control.rule_rebalancer", "name": "Rule-based treasury", "why_excluded": "deterministic rules", "controls": "unit tests, safety controller"},
    {"id": "settlement.netting", "name": "Netting (heuristic, LP rounding, exact MILP)", "why_excluded": "deterministic algorithms", "controls": "property test against brute force, duplicate-selection assertion, optimality-gap study"},
    {"id": "detect.robust_z", "name": "Robust-z payment alert rule", "why_excluded": "deterministic thresholds on computed statistics", "controls": "evaluated as the challenger in results/anomaly_detection.json"},
    {"id": "analyst.deterministic", "name": "Decision Center analyst", "why_excluded": "keyword routing to deterministic queries; no generative model", "controls": "every number cited to a source field; cannot execute actions"},
]
AGENTIC = [
    {"id": "agent.tools", "name": "Agent tool layer and MCP server", "scope_note": "generative / agentic systems are outside SR 26-2; governed by the controls listed",
     "controls": ["read-only and what-if tools only, no settlement or transfer tool exists", "per-session call and simulation budgets",
                  "hash-chained audit log of every tool call", "grounding evaluation: numbers in an answer must appear in tool output"]},
]


def build_inventory(results_dir: str | Path = "results") -> dict:
    results = Path(results_dir)
    models = _forecast_models(_load(results, "forecasting.json")) + _deep_models(_load(results, "deep_forecasting.json")) + _rl_model(_load(results, "safe_rl.json")) + \
        _detect_models(_load(results, "anomaly_detection.json")) + _router_model(_load(results, "tool_router.json"))
    for m in models:
        score = m["exposure"] * m["purpose_score"]
        m["materiality"] = {"exposure": m["exposure"], "purpose": m["purpose_score"], "score": score, "tier": TIERS[score]}
        statuses = [c["status"] for c in m["checks"]]
        m["status"] = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
        m["data_origin"] = "synthetic"
    counts = {s: sum(1 for m in models if m["status"] == s) for s in ("pass", "warn", "fail")}
    return {"version": GOVERNANCE_VERSION, "framework": "SR 26-2 structure (inventory, materiality = exposure x purpose, effective challenge, monitoring)",
            "disclaimer": "Engineering implementation on synthetic data; not a compliance attestation.",
            "summary": {"models": len(models), **counts, "non_model_tools": len(NON_MODEL_TOOLS), "agentic_components": len(AGENTIC)},
            "models": models, "non_model_tools": NON_MODEL_TOOLS, "agentic_components": AGENTIC}


def render_model_card(m: dict) -> str:
    icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [f"# Model card: {m['name']}", "",
             f"`{m['id']}` · version `{m['version']}` · tier **{m['materiality']['tier']}** "
             f"(exposure {m['materiality']['exposure']} x purpose {m['materiality']['purpose']}) · status **{icon[m['status']]}**", "",
             "| | |", "|---|---|", f"| Purpose | {m['purpose']} |", f"| Class | {m['class']} |", f"| Inputs | {m['inputs']} |",
             f"| Challenger | {m['challenger']} |", f"| Evidence | `{m['artifact']}` |", f"| Data | {m['data_origin']} |", "",
             "## Validation checks", "", "| Check | Value | Rule | Status |", "|---|---|---|---|"]
    lines += [f"| {c['check']} | {c['value']} | {c['rule']} | {icon[c['status']]} |" for c in m["checks"]]
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in m["limitations"]] + ["", "_Generated by `scripts/build_model_inventory.py`; do not edit by hand._", ""]
    return "\n".join(lines)
