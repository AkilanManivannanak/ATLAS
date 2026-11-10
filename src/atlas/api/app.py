"""ATLAS-Σ REST API.

Run: ``uvicorn atlas.api.app:app --reload`` (dev) or via docker compose.
Every number served comes from a simulation, optimizer or benchmark artifact
produced by this codebase; nothing is hard-coded or fetched from real systems.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from atlas import __version__
from atlas.agents.strategies import STRATEGY_REGISTRY
from atlas.benchmark import POLICY_ARMS
from atlas.control import MPCConfig, MPCController, RuleBasedRebalancer
from atlas.iso20022 import MessageValidationError, normalize
from atlas.ledger import Ledger
from atlas.network import hourly_snapshots, network_report, residual_gridlock_components
from atlas.optimize import FundingSource, OptimizationFailure, solve_cvar_funding, solve_deterministic_funding
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.settlement import Obligation, bilateral_offsets, partial_netting_heuristic, partial_netting_milp
from atlas.sim import POLICIES, SimulationResult, SimulationSettings, run_day
from atlas.store import EventStore
from atlas.stress import SCENARIO_LIBRARY, build_scenario
from atlas.workflows import run_vertical_slice

from .security import auth_enabled, require

DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", ".atlas-data"))
RESULTS_DIR = Path(os.environ.get("ATLAS_RESULTS_DIR", Path(__file__).resolve().parents[3] / "results"))
MAX_RUNS = int(os.environ.get("ATLAS_MAX_RUNS", "40"))
DEMO = os.environ.get("ATLAS_DEMO_RUNS", "1") == "1"

@asynccontextmanager
async def _lifespan(_app):
    _demo()
    yield


app = FastAPI(
    lifespan=_lifespan,
    title="ATLAS-Σ API",
    version=__version__,
    description="Synthetic multi-rail financial-infrastructure digital twin. Research use only: no real payments, "
                "no connection to Fedwire, CHIPS, FedNow or RTP, and no real banking data.",
)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ATLAS_CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ state
class Registry:
    def __init__(self) -> None:
        self.runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.lock = threading.Lock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(DATA_DIR / "events.db")
        self.counters = {"requests_total": 0, "simulations_total": 0, "simulation_seconds_total": 0.0, "errors_total": 0}
        self.path_counts: dict[str, int] = {}

    def add(self, result: SimulationResult, request: dict) -> str:
        with self.lock:
            self.runs[result.simulation_id] = {"result": result, "request": request, "created_at": time.time()}
            while len(self.runs) > MAX_RUNS:
                self.runs.popitem(last=False)
        return result.simulation_id

    def get(self, run_id: str) -> dict[str, Any]:
        item = self.runs.get(run_id)
        if item is None:
            raise HTTPException(404, f"simulation {run_id!r} not found")
        return item


REG = Registry()


class SimulationRequest(BaseModel):
    seed: int = Field(7, ge=0, le=2**31)
    n_institutions: int = Field(16, ge=2, le=120)
    payments_per_day: int = Field(3000, ge=10, le=60000)
    instant_payments_per_day: int = Field(2000, ge=0, le=60000)
    opening_liquidity_bp: int = Field(1800, ge=50, le=20000)
    credit_limit_bp: int = Field(1000, ge=0, le=20000)
    policy: Literal["fifo", "fifo_strict", "priority", "bilateral", "multilateral", "multilateral_milp"] = "multilateral"
    strategy: str | dict[str, int] = "early"
    stress: str = "baseline"
    controller: Literal["none", "mpc", "mpc_full", "rule", "safe_rl"] = "none"
    auction: Literal["none", "pay_as_bid", "uniform"] = "none"
    label: str | None = None


def _safe_rl():
    from atlas.control.rl import RLController, load_policy
    path = RESULTS_DIR / "policies" / "safe_ppo_constrained.json"
    if not path.exists():
        raise HTTPException(409, "no trained safe-RL policy artifact; run scripts/train_safe_rl.py")
    return RLController(load_policy(path), deterministic=True)


def _controller(kind: str):
    return {"none": lambda: None, "mpc": lambda: MPCController(MPCConfig(enable_queue_milp=False)),
            "mpc_full": lambda: MPCController(MPCConfig(enable_queue_milp=True)), "rule": lambda: RuleBasedRebalancer(),
            "safe_rl": _safe_rl}[kind]()


def _run(req: SimulationRequest) -> SimulationResult:
    if req.stress not in SCENARIO_LIBRARY:
        raise HTTPException(422, f"unknown stress scenario {req.stress!r}")
    strategies = [req.strategy] if isinstance(req.strategy, str) else list(req.strategy)
    for s in strategies:
        if s not in STRATEGY_REGISTRY:
            raise HTTPException(422, f"unknown strategy {s!r}")
    cfg = NexusPayConfig(n_institutions=req.n_institutions, payments_per_day=req.payments_per_day,
                         instant_payments_per_day=req.instant_payments_per_day, opening_liquidity_bp=req.opening_liquidity_bp,
                         credit_limit_bp=req.credit_limit_bp)
    sc = generate_scenario(cfg, seed=req.seed)
    run_id = f"sim-{int(time.time() * 1000):x}-{req.seed}-{req.policy}-{req.controller}-{req.auction}-{req.stress}"
    t = time.perf_counter()
    result = run_day(sc, SimulationSettings(policy=req.policy, strategy=req.strategy, auction=None if req.auction == "none" else req.auction),
                     build_scenario(req.stress),
                     simulation_id=run_id, controller=_controller(req.controller), store=REG.store)
    REG.counters["simulations_total"] += 1
    REG.counters["simulation_seconds_total"] += time.perf_counter() - t
    REG.add(result, req.model_dump())
    return result


def _summary(run_id: str, item: dict) -> dict:
    r: SimulationResult = item["result"]
    m = r.metrics
    return {
        "id": run_id, "label": item["request"].get("label"), "request": item["request"], "created_at": item["created_at"],
        "scenario": r.scenario_summary, "stress": r.stress["name"], "policy": r.settings["policy"], "controller": r.manifest["controller"],
        "headline": {
            "total_cost_minor": m["costs_minor"]["total"], "lv_settlement_rate_value": m["large_value"]["settlement_rate_value"],
            "lv_value_weighted_delay_s": m["large_value"]["value_weighted_delay_s"], "instant_rejected": m["counters"]["instant_rejected"],
            "liquidity_usage_minor": m["liquidity"]["system_liquidity_usage_minor"], "events": m["events"], "runtime_s": m["runtime_s"],
        },
        "final_state_hash": r.final_state_hash,
    }


@app.middleware("http")
async def _count(request: Request, call_next):
    REG.counters["requests_total"] += 1
    route = request.url.path.split("/sim-")[0][:80]
    REG.path_counts[route] = REG.path_counts.get(route, 0) + 1
    try:
        return await call_next(request)
    except Exception:
        REG.counters["errors_total"] += 1
        raise


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.status_code, "message": exc.detail}})


def _demo() -> None:
    if DEMO and not REG.runs:
        for req in (SimulationRequest(policy="priority", label="Baseline · priority queue"),
                    SimulationRequest(controller="mpc", label="Adaptive · MPC rebalancing"),
                    SimulationRequest(controller="mpc", auction="uniform", label="Adaptive · MPC + liquidity auction"),
                    SimulationRequest(policy="priority", stress="combined", label="Stress · combined shock"),
                    SimulationRequest(stress="combined", controller="mpc", auction="uniform", label="Stress · combined + MPC + auction")):
            _run(req)


# ------------------------------------------------------------------ meta
@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "auth": "enabled" if auth_enabled() else "disabled (development mode)",
            "runs_in_memory": len(REG.runs), "event_store": str(REG.store.path), "synthetic_only": True}


@app.get("/api/v1/meta")
def meta(_=Depends(require("read"))) -> dict:
    return {"policies": list(POLICIES), "strategies": sorted(STRATEGY_REGISTRY), "controllers": ["none", "rule", "mpc", "mpc_full", "safe_rl"],
            "auctions": ["none", "pay_as_bid", "uniform"],
            "stress_scenarios": {k: v().to_dict() for k, v in SCENARIO_LIBRARY.items()}, "benchmark_arms": {k: list(v) for k, v in POLICY_ARMS.items()},
            "disclaimer": "Synthetic research simulator. Rail models are archetypes, not replicas of Fedwire, CHIPS, FedNow or RTP."}


@app.get("/api/v1/scenarios")
def scenarios(_=Depends(require("read"))) -> list[dict]:
    return [v().to_dict() for v in SCENARIO_LIBRARY.values()]


@app.get("/api/v1/vertical-slice")
def vertical_slice(_=Depends(require("read"))) -> dict:
    return run_vertical_slice().to_dict()


# ------------------------------------------------------------------ simulations
@app.post("/api/v1/simulations", status_code=201)
def create_simulation(req: SimulationRequest, _=Depends(require("simulate"))) -> dict:
    r = _run(req)
    return _summary(r.simulation_id, REG.get(r.simulation_id))


@app.get("/api/v1/simulations")
def list_simulations(_=Depends(require("read"))) -> list[dict]:
    return [_summary(k, v) for k, v in reversed(REG.runs.items())]


@app.get("/api/v1/simulations/{run_id}")
def get_simulation(run_id: str, _=Depends(require("read"))) -> dict:
    item = REG.get(run_id)
    return {**_summary(run_id, item), **item["result"].to_dict()}


@app.get("/api/v1/simulations/{run_id}/payments")
def payments(run_id: str, status: str | None = None, rail: str | None = None, institution: str | None = None,
             offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=5000), _=Depends(require("read"))) -> dict:
    rows = REG.get(run_id)["result"].payments
    rows = [p for p in rows if (status is None or p["status"] == status) and (rail is None or p["rail"] == rail)
            and (institution is None or institution in (p["sender"], p["receiver"]))]
    return {"total": len(rows), "offset": offset, "items": rows[offset:offset + limit]}


@app.get("/api/v1/simulations/{run_id}/events")
def events(run_id: str, event_type: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000),
           _=Depends(require("read"))) -> dict:
    REG.get(run_id)
    total = REG.store.count(run_id, event_type)
    items = [{"seq": s.event.sequence_number, "type": s.event.event_type, "at": s.event.event_at.isoformat(), "aggregate_id": s.event.aggregate_id,
              "aggregate_type": s.event.aggregate_type, "payload": json.loads(s.event.payload_json), "record_hash": s.record_hash, "prev_hash": s.prev_hash}
             for s in REG.store.iter_events(run_id, event_type=event_type, offset=offset, limit=limit)]
    return {"total": total, "offset": offset, "items": items}


@app.post("/api/v1/simulations/{run_id}/replay")
def replay(run_id: str, _=Depends(require("read"))) -> dict:
    r: SimulationResult = REG.get(run_id)["result"]
    t = time.perf_counter()
    chain = REG.store.verify_chain(run_id)
    replayed = Ledger.replay(r.opening_accounts, REG.store.events(run_id))
    return {"chain_valid": chain.valid, "chain_events": chain.event_count, "chain_head": chain.head_hash, "first_invalid_sequence": chain.first_invalid_sequence,
            "replayed_state_hash": replayed.state_hash(), "live_state_hash": r.final_state_hash,
            "replay_matches": replayed.state_hash() == r.final_state_hash, "ledger_events_applied": replayed.applied_count,
            "conservation": {"opening_total_minor": replayed.opening_total_minor, "external_net_flow_minor": replayed.external_net_flow_minor,
                             "closing_total_minor": replayed.total_ledger_minor()},
            "runtime_ms": (time.perf_counter() - t) * 1000}


@app.get("/api/v1/simulations/{run_id}/institutions")
def institutions(run_id: str, _=Depends(require("read"))) -> list[dict]:
    return REG.get(run_id)["result"].per_institution


@app.get("/api/v1/simulations/{run_id}/institutions/{inst}")
def institution(run_id: str, inst: str, _=Depends(require("read"))) -> dict:
    r: SimulationResult = REG.get(run_id)["result"]
    stats = next((x for x in r.per_institution if x["institution_id"] == inst), None)
    if stats is None:
        raise HTTPException(404, f"institution {inst!r} not in simulation")
    mine = [p for p in r.payments if inst in (p["sender"], p["receiver"])]
    exposures: dict[str, dict[str, int]] = {}
    for p in mine:
        cp = p["receiver"] if p["sender"] == inst else p["sender"]
        e = exposures.setdefault(cp, {"sent_minor": 0, "received_minor": 0, "unsettled_minor": 0})
        if p["sender"] == inst:
            e["sent_minor"] += p["amount_minor"]
        else:
            e["received_minor"] += p["amount_minor"]
        if p["status"] != "settled":
            e["unsettled_minor"] += p["amount_minor"]
    return {**stats, "exposures": exposures, "payment_count": len(mine)}


@app.get("/api/v1/simulations/{run_id}/network")
def network(run_id: str, rail: str | None = None, _=Depends(require("read"))) -> dict:
    r: SimulationResult = REG.get(run_id)["result"]
    rails = (rail,) if rail else ("rtgs", "lsm")
    rep = network_report(r.payments, r.per_institution, rails=rails)
    from datetime import datetime
    open_at = datetime.fromisoformat(r.timeseries[0]["t"])
    close_at = datetime.fromisoformat(r.timeseries[-1]["t"])
    rep["hourly"] = hourly_snapshots([p for p in r.payments if p["rail"] in rails], open_at, close_at)
    rep["residual_gridlock"] = residual_gridlock_components(r.payments)
    return rep


@app.get("/api/v1/simulations/{run_id}/rails/{rail}")
def rail_metrics(run_id: str, rail: str, _=Depends(require("read"))) -> dict:
    r: SimulationResult = REG.get(run_id)["result"]
    if rail not in r.metrics["by_rail"]:
        raise HTTPException(404, f"rail {rail!r} not modeled")
    ts = [{k: v for k, v in row.items() if k in ("t", "minute") or k.startswith(rail + "_")} for row in r.timeseries]
    return {"rail": rail, "metrics": r.metrics["by_rail"][rail], "timeseries": ts}


class CounterfactualRequest(BaseModel):
    policy: str | None = None
    strategy: str | dict[str, int] | None = None
    stress: str | None = None
    controller: Literal["none", "mpc", "mpc_full", "rule", "safe_rl"] | None = None
    auction: Literal["none", "pay_as_bid", "uniform"] | None = None
    opening_liquidity_bp: int | None = Field(None, ge=50, le=20000)
    credit_limit_bp: int | None = Field(None, ge=0, le=20000)


@app.post("/api/v1/simulations/{run_id}/counterfactual", status_code=201)
def counterfactual(run_id: str, change: CounterfactualRequest, _=Depends(require("simulate"))) -> dict:
    base_item = REG.get(run_id)
    base_req = SimulationRequest(**base_item["request"])
    changes = {k: v for k, v in change.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(422, "counterfactual requires at least one explicit change")
    new_req = base_req.model_copy(update={**changes, "label": f"Counterfactual of {run_id}: {changes}"})
    new = _run(new_req)
    b, n = base_item["result"].metrics, new.metrics
    keys = {"total_cost_minor": lambda m: m["costs_minor"]["total"], "lv_settlement_rate_value": lambda m: m["large_value"]["settlement_rate_value"],
            "lv_value_weighted_delay_s": lambda m: m["large_value"]["value_weighted_delay_s"], "instant_rejected": lambda m: m["counters"]["instant_rejected"],
            "liquidity_usage_minor": lambda m: m["liquidity"]["system_liquidity_usage_minor"],
            "peak_credit_minor": lambda m: m["liquidity"]["peak_intraday_credit_minor"]}
    return {"base_id": run_id, "counterfactual_id": new.simulation_id, "changed_assumptions": changes, "paired_seed": base_req.seed,
            "same_scenario_fingerprint": new.scenario_summary["fingerprint"] == base_item["result"].scenario_summary["fingerprint"],
            "diff": {k: {"base": f(b), "counterfactual": f(n), "delta": f(n) - f(b)} for k, f in keys.items()}}


class Question(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


@app.post("/api/v1/simulations/{run_id}/ask")
def ask(run_id: str, q: Question, _=Depends(require("read"))) -> dict:
    """Grounded analyst: deterministic retrieval over this run; every number is cited; cannot execute anything."""
    from atlas.analyst import answer
    r: SimulationResult = REG.get(run_id)["result"]
    bench_path = RESULTS_DIR / "benchmarks" / "standard.json"
    bench = json.loads(bench_path.read_text()) if bench_path.exists() else None
    return answer(q.question, r.to_dict(include_payments=True) | {"simulation_id": run_id}, bench)


@app.get("/api/v1/simulations/{run_id}/statements/{account_id}")
def statement(run_id: str, account_id: str, _=Depends(require("read"))) -> dict:
    """ISO 20022 camt.053 end-of-day statement for one account, built from the hash-chained events, with reconciliation."""
    from atlas.iso20022 import build_camt053, reconcile_statement
    r: SimulationResult = REG.get(run_id)["result"]
    acct = next((a for a in r.opening_accounts if a.account_id == account_id), None)
    if acct is None:
        raise HTTPException(404, f"account {account_id!r} not in simulation")
    events = REG.store.events(run_id)
    xml = build_camt053(acct, acct.ledger_balance_minor, events, statement_id=f"STMT-{account_id}", created_at=events[-1].event_at)
    closing = Ledger.replay(r.opening_accounts, events).account(account_id).ledger_balance_minor
    rec = reconcile_statement(xml, closing)
    return {"account_id": account_id, "message_definition": "camt.053.001.08", "reconciliation": rec.__dict__, "xml": xml}


@app.delete("/api/v1/simulations/{run_id}")
def delete_run(run_id: str, _=Depends(require("admin"))) -> dict:
    REG.get(run_id)
    with REG.lock:
        REG.runs.pop(run_id, None)
    return {"deleted": run_id, "note": "removed from memory; immutable events remain in the event store"}


# ------------------------------------------------------------------ optimization / iso / research
class FundingRequest(BaseModel):
    sources: list[dict] = Field(..., description="[{name, capacity_minor, cost_bp, collateral_bp}]")
    scenarios: list[int]
    shortfall_cost_bp: int = 500
    alpha: float = Field(0.95, gt=0, lt=1)
    risk_weight: float = Field(0.5, ge=0, le=1)
    collateral_budget_minor: int | None = None


@app.post("/api/v1/optimization/funding")
def optimize_funding(req: FundingRequest, _=Depends(require("simulate"))) -> dict:
    try:
        sources = [FundingSource(**s) for s in req.sources]
        cvar = solve_cvar_funding(sources, req.scenarios, shortfall_cost_bp=req.shortfall_cost_bp, alpha=req.alpha, risk_weight=req.risk_weight,
                                  collateral_budget_minor=req.collateral_budget_minor)
        ev = solve_deterministic_funding(sources, req.scenarios, shortfall_cost_bp=req.shortfall_cost_bp, collateral_budget_minor=req.collateral_budget_minor)
    except OptimizationFailure as exc:
        raise HTTPException(409, {"status": exc.status, "message": exc.message}) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"cvar": cvar.to_dict(), "expected_value": ev.to_dict()}


class NettingRequest(BaseModel):
    obligations: list[dict] = Field(..., description="[{obligation_id, payer, payee, amount_minor, priority}]")
    available: dict[str, int]
    algorithm: Literal["heuristic", "milp", "bilateral"] = "heuristic"


@app.post("/api/v1/optimization/netting")
def optimize_netting(req: NettingRequest, _=Depends(require("simulate"))) -> dict:
    try:
        obs = [Obligation(o["obligation_id"], o["payer"], o["payee"], int(o["amount_minor"]), int(o.get("priority", 1))) for o in req.obligations]
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"invalid obligation: {exc}") from exc
    algo = {"heuristic": partial_netting_heuristic, "milp": partial_netting_milp, "bilateral": bilateral_offsets}[req.algorithm]
    sel = algo(obs, req.available)
    return {"algorithm": sel.algorithm, "status": sel.status, "selected": [o.obligation_id for o in sel.selected], "gross_value_minor": sel.gross_value_minor,
            "net_liquidity_used_minor": sel.net_liquidity_used_minor, "liquidity_saving_ratio": sel.liquidity_saving_ratio, "runtime_ms": sel.runtime_ms}


@app.post("/api/v1/iso20022/normalize")
def iso_normalize(xml: str = Body(..., media_type="application/xml"), _=Depends(require("read"))) -> dict:
    try:
        m = normalize(xml)
    except MessageValidationError as exc:
        raise HTTPException(422, {"errors": list(exc.errors)}) from exc
    return {"message_definition": m.message_definition, "message_id": m.message_id, "created_at": m.created_at.isoformat(),
            "original_sha256": m.original_sha256, "canonical_schema_version": m.canonical_schema_version, "transformation_version": m.transformation_version,
            "transactions": [{"end_to_end_id": t.end_to_end_id, "instruction_id": t.instruction_id, "uetr": t.uetr, "amount_minor": t.amount.amount_minor,
                              "currency": t.amount.currency, "settlement_date": t.settlement_date.isoformat(), "debtor_agent": t.debtor_agent_bic,
                              "creditor_agent": t.creditor_agent_bic, "return_reason": t.return_reason_code} for t in m.transactions]}


def _artifact(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(404, f"artifact {path.name} has not been generated yet")
    return json.loads(path.read_text())


@app.get("/api/v1/benchmarks")
def list_benchmarks(_=Depends(require("read"))) -> list[dict]:
    out = []
    for p in sorted((RESULTS_DIR / "benchmarks").glob("*.json")):
        d = json.loads(p.read_text())
        out.append({"name": d["name"], "version": d["benchmark_version"], "runs": d["manifest"]["runs"], "created_at": d["manifest"]["created_at"],
                    "all_replays_verified": d["manifest"]["all_replays_verified"]})
    return out


@app.get("/api/v1/benchmarks/{name}")
def get_benchmark(name: str, _=Depends(require("read"))) -> dict:
    if not name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(422, "invalid benchmark name")
    return _artifact(RESULTS_DIR / "benchmarks" / f"{name}.json")


@app.get("/api/v1/research/{artifact}")
def research_artifact(artifact: Literal["forecasting", "game", "netting_optimality", "auction", "safe_rl", "scaling"],
                      _=Depends(require("read"))) -> dict:
    return _artifact(RESULTS_DIR / f"{artifact}.json")


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus() -> str:
    lines = ["# HELP atlas_requests_total HTTP requests served", "# TYPE atlas_requests_total counter",
             f"atlas_requests_total {REG.counters['requests_total']}",
             "# HELP atlas_simulations_total Simulations executed", "# TYPE atlas_simulations_total counter",
             f"atlas_simulations_total {REG.counters['simulations_total']}",
             "# HELP atlas_simulation_seconds_total Wall time spent simulating", "# TYPE atlas_simulation_seconds_total counter",
             f"atlas_simulation_seconds_total {REG.counters['simulation_seconds_total']:.6f}",
             "# HELP atlas_runs_in_memory Simulation results held in memory", "# TYPE atlas_runs_in_memory gauge",
             f"atlas_runs_in_memory {len(REG.runs)}"]
    for run_id, item in list(REG.runs.items())[-10:]:
        m = item["result"].metrics
        lab = f'run="{run_id}"'
        lines += [f"atlas_run_settlement_rate_value{{{lab}}} {m['large_value']['settlement_rate_value']:.6f}",
                  f"atlas_run_total_cost_minor{{{lab}}} {m['costs_minor']['total']}",
                  f"atlas_run_events_per_second{{{lab}}} {m['events_per_second']:.1f}"]
    return "\n".join(lines) + "\n"
