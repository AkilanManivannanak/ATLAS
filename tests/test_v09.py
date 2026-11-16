"""v0.9: real fraud data path, learned tool router, hosted-inference contract, GPU device selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.agent.evals import INTENTS, TASKS, evaluate, execute_route, planner_agent, route_by_keywords
from atlas.agent.tools import STRESSES, ToolSession
from atlas.scenario import NexusPayConfig, generate_scenario

ROOT = Path(__file__).resolve().parents[1]
SMALL = NexusPayConfig(n_institutions=8, payments_per_day=300, instant_payments_per_day=200)


# ------------------------------------------------------------------ routing
def test_keyword_router_and_execute_route_are_the_planner():
    r = route_by_keywords("Under combined stress, does adding MPC and an auction lower cost?")
    assert r == {"stress": "combined", "mpc": True, "auction": True, "intent": "compare"}
    assert route_by_keywords("Move $5 million now")["intent"] == "execute"
    assert route_by_keywords("what is the weather")["intent"] == "out_of_scope"
    s1, s2 = ToolSession(generate_scenario(SMALL, seed=5)), ToolSession(generate_scenario(SMALL, seed=5))
    q = "How many payments did not settle under rtgs_outage?"
    assert planner_agent(q, s1)["answer"] == execute_route(route_by_keywords(q), q, s2)["answer"]


def test_router_dataset_is_reproducible_and_held_out():
    pytest.importorskip("sklearn")
    from atlas.agent.router import HANDWRITTEN, TEMPLATES, TfidfRouter, make_dataset, score_routes
    assert set(TEMPLATES) == set(INTENTS) and all(len(v) >= 8 for v in TEMPLATES.values())
    train, test_a, hand = make_dataset(n_train=600, n_test=200, seed=1)
    assert make_dataset(n_train=600, n_test=200, seed=1)[0] == train and len(hand) == len(HANDWRITTEN)
    assert {r["intent"] for r in train} == set(INTENTS) and {r["stress"] for r in train} <= set(STRESSES)
    perfect = score_routes(lambda t: next(r for r in hand if r["text"] == t), hand)
    assert perfect["intent_accuracy"] == perfect["exact_route_accuracy"] == 1.0
    keyword = score_routes(route_by_keywords, hand)
    assert 0.5 < keyword["intent_accuracy"] <= 1.0
    model = TfidfRouter().fit(train)
    assert score_routes(model.route, test_a)["intent_accuracy"] > 0.8        # templates it never saw


def test_router_agent_falls_back_when_unsure_and_cannot_execute_anything():
    from atlas.agent.router import RouterAgent

    class Unsure:
        name = "stub"

        def route(self, text):
            return {"intent": "settled", "stress": "baseline", "mpc": False, "auction": False, "confidence": 0.2}

    class WrongButSure(Unsure):
        def route(self, text):
            return {"intent": "settled", "stress": "combined", "mpc": False, "auction": False, "confidence": 0.99}

    s = ToolSession(generate_scenario(SMALL, seed=5))
    out = RouterAgent(Unsure(), min_confidence=0.6)("Move $50 million from RTGS to FedNow for bank-003 right now.", s)
    assert out["route"]["decided_by"].startswith("keyword fallback") and "cannot execute" in out["answer"]
    # a confidently wrong router misreads an execution request, yet nothing is executed: it can only simulate
    s2 = ToolSession(generate_scenario(SMALL, seed=5))
    out2 = RouterAgent(WrongButSure())("Move $50 million from RTGS to FedNow for bank-003 right now.", s2)
    assert out2["route"]["decided_by"] == "model" and [t["tool"] for t in out2["trace"]] == ["simulate_day"]
    quick = tuple(t for t in TASKS if t.kind == "execute")
    assert evaluate(RouterAgent(WrongButSure()), tasks=quick)["safe"] == 0.0             # and the harness scores that as unsafe


def test_neural_router_trains_saves_and_loads(tmp_path):
    torch = pytest.importorskip("torch")
    from atlas.agent.router import NeuralRouter, make_dataset
    train, _, _ = make_dataset(n_train=300, n_test=10, seed=2)
    m = NeuralRouter(d_model=32, layers=1).fit(train, epochs=2)
    assert len(m.history) == 2 and m.history[1]["train_loss"] < m.history[0]["train_loss"] and m.n_params > 10_000
    r = m.route("How many instant payments are rejected under combined stress?")
    assert r["intent"] in INTENTS and r["stress"] in STRESSES and 0 <= r["confidence"] <= 1
    full = NeuralRouter().fit(train[:64], epochs=1)
    full.save(tmp_path / "r.pt")
    again = NeuralRouter.load(tmp_path / "r.pt")
    q = "Which institution is most stretched under rtgs_outage?"
    assert again.route(q) == full.route(q)
    assert torch.load(tmp_path / "r.pt", weights_only=True)["version"] == "atlas-router-v1"


# ------------------------------------------------------------------ real fraud data path
def test_real_data_loader_rejects_anything_but_the_expected_file(tmp_path):
    np = pytest.importorskip("numpy")
    from atlas.detect.realdata import EXPECTED, alert_metrics, load_creditcard
    bad = tmp_path / "x.csv"
    bad.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="unexpected columns"):
        load_creditcard(bad)
    cols = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount", "Class"]
    small = tmp_path / "y.csv"
    small.write_text(",".join(cols) + "\n" + "\n".join(",".join(["1.0"] * 30 + ["0"]) for _ in range(5)) + "\n")
    with pytest.raises(ValueError, match="unexpected size"):
        load_creditcard(small)
    assert EXPECTED == {"rows": 284_807, "frauds": 492, "columns": 31}
    y = np.array([0, 0, 1, 0, 1, 0, 0, 0, 0, 0])
    m = alert_metrics(y, np.array([.1, .2, .9, .3, .05, .1, .1, .1, .1, .8]), alert_rate=0.2)
    assert m["alerts"] == 2 and m["frauds_caught"] == 1 and m["recall_at_alert_rate"] == 0.5 and m["alerts_per_fraud_caught"] == 2.0


def test_real_fraud_artifact_is_consistent():
    import json
    p = ROOT / "results" / "real_fraud.json"
    if not p.exists():
        pytest.skip("real-data study not run")
    d = json.loads(p.read_text())
    assert d["dataset"]["rows"] == 284_807 and d["dataset"]["frauds"] == 492 and d["data_origin"].startswith("observed")
    for m in d["models"].values():
        assert m["frauds_total"] == d["design"]["test_frauds"] and 0 <= m["frauds_caught"] <= m["alerts"]
    assert d["models"]["gradient_boosting"]["pr_auc"] > d["models"]["isolation_forest"]["pr_auc"]


# ------------------------------------------------------------------ hosted contract and devices
def test_hosted_inference_contract():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from atlas.api.app import app
    from atlas.sim import run_day
    with TestClient(app) as c:
        assert c.get("/ping").json() == {"status": "ok"}
        pays = run_day(generate_scenario(SMALL, seed=5)).payments
        dup = dict(pays[3], payment_id="dup")
        out = c.post("/invocations", json={"payments": pays + [dup], "top": 5})
        assert out.status_code == 200 and out.json()["contract"] == "ping/invocations" and out.json()["payments_scored"] == len(pays) + 1
        assert any(a["reason"] == "repeat within 60s" for a in out.json()["alerts"])
        assert c.post("/invocations", json={"payments": [{"payment_id": "x"}]}).status_code == 422
        assert c.post("/invocations", json={"payments": []}).status_code == 422


def test_device_selection_defaults_to_cpu_and_honours_explicit_choice():
    torch = pytest.importorskip("torch")
    from atlas.forecast.deep import pick_device
    assert pick_device("cpu") == "cpu"
    expect = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    assert pick_device("auto") == expect
