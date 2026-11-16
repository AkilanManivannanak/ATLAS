"""Guarded tools an AI agent may call on the twin (``atlas-agent-v1``).

Design rules, in the order a bank's control function would ask about them:

1. **Least privilege.** Every tool is read-only or runs a *simulation*. No tool settles a payment, moves liquidity
   or changes a limit, so an agent connected here cannot act on anything real; it can only analyse and propose.
2. **Validated inputs.** Arguments are checked against each tool's JSON Schema (types, enums, ranges) before any
   code runs; unknown tools and unknown arguments are errors, never guesses.
3. **Budgets.** A session has a cap on tool calls and a smaller cap on simulations (the only expensive tool).
4. **Audit.** Every call is appended to a SHA-256 hash chain with its arguments and a digest of its result, so a
   transcript can be checked for tampering after the fact.
5. **Grounding.** Tools return plain numbers with units in the field names; ``atlas.agent.evals`` then checks that
   every number in an agent's answer can be traced to a tool result.

Standard library only (the anomaly tool imports numpy lazily).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import POLICIES, SimulationSettings, run_day
from atlas.stress import build_scenario

AGENT_VERSION = "atlas-agent-v1"
STRESSES = ("baseline", "counterparty_delay", "rtgs_outage", "liquidity_withdrawal", "funding_disruption", "haircut_shock",
            "failure_to_pay", "concentrated_outflows", "liquidity_hoarding", "messaging_failure", "combined")
CONTROLLERS = ("none", "rule_rebalancer", "mpc")
AUCTIONS = ("none", "pay_as_bid", "uniform")


class ToolError(ValueError):
    """Bad tool name or arguments. The message is safe to show to the model."""


class BudgetExceeded(ToolError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., dict]
    scope: str          # "read" | "simulate"


def _validate(schema: dict, args: dict) -> dict:
    props = schema.get("properties", {})
    unknown = set(args) - set(props)
    if unknown:
        raise ToolError(f"unknown argument(s): {sorted(unknown)}; allowed: {sorted(props)}")
    out = {}
    for name, spec in props.items():
        if name not in args:
            if name in schema.get("required", ()):
                raise ToolError(f"missing required argument {name!r}")
            if "default" in spec:
                out[name] = spec["default"]
            continue
        v = args[name]
        t = spec.get("type")
        if t == "integer" and (not isinstance(v, int) or isinstance(v, bool)):
            raise ToolError(f"{name} must be an integer")
        if t == "string" and not isinstance(v, str):
            raise ToolError(f"{name} must be a string")
        if "enum" in spec and v not in spec["enum"]:
            raise ToolError(f"{name} must be one of {spec['enum']}")
        if t == "integer" and not spec.get("minimum", v) <= v <= spec.get("maximum", v):
            raise ToolError(f"{name} must be between {spec.get('minimum')} and {spec.get('maximum')}")
        out[name] = v
    return out


def _usd(minor: int | float) -> float:
    return round(minor / 100, 2)


class ToolSession:
    """One agent conversation: its scenario, its runs, its budgets and its audit chain."""

    def __init__(self, scenario=None, *, seed: int = 11, config: NexusPayConfig | None = None, max_calls: int = 40, max_simulations: int = 6) -> None:
        self.scenario = scenario or generate_scenario(config or NexusPayConfig(), seed=seed)
        self.max_calls, self.max_simulations = max_calls, max_simulations
        self.calls = self.simulations = 0
        self.runs: dict[str, dict] = {}
        self.audit: list[dict] = []
        self._tools = {t.name: t for t in self._build()}

    # ------------------------------------------------------------------ public surface
    def list_tools(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema, "scope": t.scope} for t in self._tools.values()]

    def openai_tools(self) -> list[dict]:
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in self._tools.values()]

    def call(self, name: str, args: dict | None = None) -> dict:
        args = args or {}
        if name not in self._tools:
            raise ToolError(f"unknown tool {name!r}; available: {sorted(self._tools)}")
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"tool-call budget of {self.max_calls} reached")
        tool = self._tools[name]
        clean = _validate(tool.input_schema, args)
        if tool.scope == "simulate" and self.simulations >= self.max_simulations:
            raise BudgetExceeded(f"simulation budget of {self.max_simulations} reached; compare the runs you already have")
        self.calls += 1
        result = tool.fn(**clean)
        self._audit(name, clean, result)
        return result

    def verify_audit(self) -> bool:
        prev = "0" * 64
        for e in self.audit:
            body = {k: e[k] for k in ("seq", "tool", "args", "result_sha256", "prev_hash")}
            if e["prev_hash"] != prev or e["hash"] != hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest():
                return False
            prev = e["hash"]
        return True

    # ------------------------------------------------------------------ internals
    def _audit(self, tool: str, args: dict, result: dict) -> None:
        body = {"seq": len(self.audit) + 1, "tool": tool, "args": args,
                "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest(),
                "prev_hash": self.audit[-1]["hash"] if self.audit else "0" * 64}
        self.audit.append(body | {"hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()})

    def _run(self, run_id: str) -> dict:
        if run_id not in self.runs:
            raise ToolError(f"unknown run_id {run_id!r}; call simulate_day first. Known runs: {sorted(self.runs)}")
        return self.runs[run_id]

    @staticmethod
    def _headline(d: dict) -> dict:
        m = d["metrics"]
        lv, inst, costs = m["large_value"], m["instant"], m["costs_minor"]
        return {
            "large_value_settled_share_pct": round(lv["settlement_rate_value"] * 100, 2),
            "large_value_value_weighted_delay_min": round(lv["value_weighted_delay_s"] / 60, 1),
            "large_value_unsettled_usd": _usd(lv["value_minor"] - lv["settled_value_minor"]),
            "large_value_deadline_misses": lv["deadline_miss_count"],
            "instant_payments_rejected": inst["count"] - inst["settled_count"],
            "peak_intraday_credit_usd": _usd(m["liquidity"]["peak_intraday_credit_minor"]),
            "total_modeled_cost_usd": _usd(costs["total"]),
            "cost_components_usd": {k: _usd(v) for k, v in costs.items() if k != "total"},
        }

    def _simulate(self, policy: str, stress: str, controller: str, auction: str) -> dict:
        key = f"{policy}|{stress}|{controller}|{auction}"
        run_id = "run-" + hashlib.sha256(key.encode()).hexdigest()[:8]
        if run_id not in self.runs:
            self.simulations += 1
            ctrl = None
            if controller == "mpc":
                from atlas.control import MPCController
                ctrl = MPCController()
            elif controller == "rule_rebalancer":
                from atlas.control import RuleBasedRebalancer
                ctrl = RuleBasedRebalancer()
            res = run_day(self.scenario, SimulationSettings(policy=policy, auction=None if auction == "none" else auction),
                          build_scenario(stress), controller=ctrl)
            d = res.to_dict(include_payments=True)
            d["_replay_verified"] = res.verify_replay()
            self.runs[run_id] = d
        d = self.runs[run_id]
        return {"run_id": run_id, "policy": policy, "stress": stress, "controller": controller, "auction": auction,
                "replay_verified": d["_replay_verified"], "data_origin": d["scenario"].get("data_origin"), **self._headline(d)}

    def _metrics(self, run_id: str) -> dict:
        return {"run_id": run_id, **self._headline(self._run(run_id))}

    def _compare(self, run_a: str, run_b: str) -> dict:
        a, b = self._headline(self._run(run_a)), self._headline(self._run(run_b))
        keys = [k for k in a if k != "cost_components_usd"]
        return {"run_a": run_a, "run_b": run_b, "b_minus_a": {k: round(b[k] - a[k], 2) for k in keys},
                "cost_change_pct": round((b["total_modeled_cost_usd"] / a["total_modeled_cost_usd"] - 1) * 100, 1) if a["total_modeled_cost_usd"] else None,
                "note": "one paired day; use the benchmark for confidence intervals"}

    def _exposed(self, run_id: str, n: int) -> dict:
        rows = sorted(self._run(run_id)["per_institution"], key=lambda x: (x["settlement_rate_value"], -x["sent_value_minor"]))[:n]
        return {"run_id": run_id, "institutions": [{"institution_id": x["institution_id"], "tier": x["tier"],
                "own_value_settled_pct": round(x["settlement_rate_value"] * 100, 2), "liquidity_used_usd": _usd(x["liquidity_usage_minor"]),
                "peak_credit_usd": _usd(x["peak_credit_minor"])} for x in rows]}

    def _intraday(self, run_id: str, n: int) -> dict:
        from atlas.regulatory import intraday_liquidity_report
        rep = intraday_liquidity_report(self._run(run_id))
        rows = sorted(rep["institutions"], key=lambda r: -(r["A_i_usage_share_of_available"] or 0))[:n]
        s = rep["system"]
        return {"run_id": run_id, "standard": rep["standard"],
                "system": {"sum_max_net_negative_position_usd": _usd(s["sum_max_net_negative_minor"]),
                           "available_at_start_usd": _usd(s["sum_available_at_start_minor"]),
                           "payments_settled_per_dollar_of_liquidity_used": s["liquidity_efficiency"],
                           "time_specific_obligations_late": s["time_specific_late"], "time_specific_obligations_failed": s["time_specific_failed"]},
                "most_stretched": [{"institution_id": r["institution_id"], "max_net_negative_position_usd": _usd(r["A_i_max_net_negative_position_minor"]),
                                    "usage_of_available_pct": round((r["A_i_usage_share_of_available"] or 0) * 100, 1),
                                    "at": r["A_i_max_negative_at"]} for r in rows]}

    def _unsettled(self, run_id: str, n: int) -> dict:
        rows = [p for p in self._run(run_id)["payments"] if p["status"] != "settled"]
        by_reason: dict[str, dict] = {}
        for p in rows:
            r = by_reason.setdefault(p.get("reason") or p["status"], {"count": 0, "value_usd": 0.0})
            r["count"] += 1
            r["value_usd"] = round(r["value_usd"] + p["amount_minor"] / 100, 2)
        top = sorted(rows, key=lambda p: -p["amount_minor"])[:n]
        return {"run_id": run_id, "unsettled_count": len(rows), "by_reason": by_reason,
                "largest": [{"payment_id": p["payment_id"], "rail": p["rail"], "sender": p["sender"], "receiver": p["receiver"],
                             "amount_usd": _usd(p["amount_minor"]), "reason": p.get("reason") or p["status"]} for p in top]}

    def _alerts(self, run_id: str, n: int) -> dict:
        from atlas.detect import score_payments
        out = score_payments(self._run(run_id)["payments"], top=n)
        return {"run_id": run_id, "mode": out["mode"], "payments_scored": out.get("payments_scored", 0), "note": out.get("note"),
                "alerts": [{**{k: a[k] for k in ("payment_id", "rail", "sender", "receiver", "score", "reason")}, "amount_usd": _usd(a["amount_minor"])}
                           for a in out["alerts"]]}

    def _options(self) -> dict:
        s = self.scenario.summary()
        return {"policies": list(POLICIES), "stresses": list(STRESSES), "controllers": list(CONTROLLERS), "auctions": list(AUCTIONS),
                "scenario": {"institutions": s["institutions"], "payments": s["payments"], "data_origin": s.get("data_origin")},
                "budgets": {"tool_calls_left": self.max_calls - self.calls, "simulations_left": self.max_simulations - self.simulations},
                "cannot_do": "No tool executes payments, transfers or limit changes. Results are simulations to support a human decision."}

    def _build(self) -> list[Tool]:
        run_arg = {"run_id": {"type": "string", "description": "id returned by simulate_day"}}
        top_n = {"n": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5}}
        obj = lambda props, req=(): {"type": "object", "properties": props, "required": list(req), "additionalProperties": False}
        return [
            Tool("list_options", "List valid policies, stresses, controllers, auctions, the loaded scenario and remaining budgets.", obj({}), self._options, "read"),
            Tool("simulate_day", "Simulate the loaded business day under a settlement policy, stress scenario, liquidity controller and optional "
                 "liquidity auction. Returns a run_id and headline metrics. This is a simulation: nothing real is executed.",
                 obj({"policy": {"type": "string", "enum": list(POLICIES), "default": "priority"},
                      "stress": {"type": "string", "enum": list(STRESSES), "default": "baseline"},
                      "controller": {"type": "string", "enum": list(CONTROLLERS), "default": "none"},
                      "auction": {"type": "string", "enum": list(AUCTIONS), "default": "none"}}), self._simulate, "simulate"),
            Tool("get_metrics", "Headline metrics of an existing run.", obj(run_arg, ("run_id",)), self._metrics, "read"),
            Tool("compare_runs", "Difference in headline metrics between two existing runs (b minus a).",
                 obj({"run_a": {"type": "string"}, "run_b": {"type": "string"}}, ("run_a", "run_b")), self._compare, "read"),
            Tool("most_exposed_institutions", "Institutions with the lowest share of their own outgoing value settled.", obj(run_arg | top_n, ("run_id",)), self._exposed, "read"),
            Tool("intraday_liquidity_report", "BCBS 248 intraday liquidity monitoring figures for a run: system totals and the most stretched institutions.",
                 obj(run_arg | top_n, ("run_id",)), self._intraday, "read"),
            Tool("unsettled_payments", "Payments that did not settle in a run, grouped by reason, with the largest listed.", obj(run_arg | top_n, ("run_id",)), self._unsettled, "read"),
            Tool("anomaly_alerts", "Payments ranked as most unusual in a run, for human review. Nothing is blocked.", obj(run_arg | top_n, ("run_id",)), self._alerts, "read"),
        ]
