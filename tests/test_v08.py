"""v0.8: insight views, rulebook retrieval, red-team eval tasks, deep forecasters, deploy manifests, Streamlit app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.agent.evals import TASKS, evaluate, overreacher_agent, planner_agent
from atlas.agent.tools import ToolSession
from atlas.insight import RATINGS, bank_detail, day_frames, liquidity_sweep, review_url, tamper_check
from atlas.knowledge import evaluate_retrieval, load_corpus
from atlas.knowledge.retrieval import Corpus, Passage, tokenize
from atlas.lab import run_lab
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day

ROOT = Path(__file__).resolve().parents[1]
SMALL = NexusPayConfig(n_institutions=8, payments_per_day=300, instant_payments_per_day=200)


@pytest.fixture(scope="module")
def result():
    return run_day(generate_scenario(SMALL, seed=5), SimulationSettings(policy="priority"))


@pytest.fixture(scope="module")
def run(result):
    return result.to_dict(include_payments=True)


# ------------------------------------------------------------------ insight
def test_day_frames_conserve_value_and_end_at_the_settled_total(run):
    f = day_frames(run, step_min=30)
    n = len(f["labels"])
    assert n == len(f["net_minor"]) == len(f["queued_minor"]) == len(f["flows"]) and len(f["banks"]) == 8
    assert all(sum(row) == 0 for row in f["net_minor"])                      # every payment debits one bank and credits another
    settled = sum(p["amount_minor"] for p in run["payments"] if p["rail"] in ("rtgs", "lsm") and p["status"] == "settled")
    assert f["settled_cum_minor"][-1] == settled and f["settled_cum_minor"] == sorted(f["settled_cum_minor"])
    unsettled = sum(p["amount_minor"] for p in run["payments"] if p["rail"] in ("rtgs", "lsm") and p["status"] != "settled")
    assert f["queued_total_minor"][-1] == unsettled
    assert all(fl["minor"] > 0 for fr in f["flows"] for fl in fr)


def test_bank_detail_matches_frames(run):
    f = day_frames(run)
    bank = f["banks"][0]
    d = bank_detail(run, bank)
    assert d["closing_minor"] == f["net_minor"][-1][0]
    assert d["lowest_minor"] <= 0 and d["lowest_minor"] <= d["closing_minor"]
    assert d["unsettled_count"] == sum(1 for p in run["payments"] if p["sender"] == bank and p["rail"] in ("rtgs", "lsm") and p["status"] != "settled")


def test_tampering_is_caught_by_chain_and_replay_and_leaves_the_run_intact(result):
    before = result.final_state_hash
    for which in (0, 7, 10_000):
        t = tamper_check(result, which)
        assert t["available"] and t["chain_caught"] and t["replay_caught"] and t["untouched_replay_ok"]
        assert t["amount_after_minor"] != t["amount_before_minor"] and t["links_invalidated"] == t["events"] - t["first_broken_link"]
    assert result.final_state_hash == before and result.verify_replay()


def test_liquidity_sweep_and_mpc_in_lab():
    pts = liquidity_sweep(lambda pct: run_lab({"banks": 8, "payments": 300, "instant": 100, "liquidity_pct": pct}), levels_pct=(6, 30))
    assert [p["liquidity_pct"] for p in pts] == [6, 30] and pts[1]["settled_pct"] >= pts[0]["settled_pct"]
    pytest.importorskip("scipy")
    out = run_lab({"banks": 8, "payments": 300, "instant": 200, "controller": "mpc", "auction": "uniform"}, detail=True)
    assert out["choices"]["controller"] == "mpc" and out["integrity"]["replay_verified"] and out["_result"].verify_replay()
    json.dumps({k: v for k, v in out.items() if not k.startswith("_")})


def test_review_url_prefills_the_issue_form():
    url = review_url("o/r", rating=4, role="payments engineer", tried=["CLI", "Ask"], worked="ran", broke="x & y", would_use="")
    assert url.startswith("https://github.com/o/r/issues/new?template=review.yml") and "rating=4+-+good" in url and "broke=x+%26+y" in url
    assert "would_use" not in url and len(RATINGS) == 5
    form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "review.yml").read_text()
    for field in ("rating", "role", "tried", "worked", "broke", "would_use"):
        assert f"id: {field}" in form
    assert all(r in form for r in RATINGS)


# ------------------------------------------------------------------ retrieval
def test_tokenizer_and_bm25_rank_the_matching_passage_first():
    assert tokenize("The FedNow limit, per SR 26-2?") == ["fednow", "limit", "sr", "26-2", "26", "2"]
    c = Corpus([Passage("a#1", "a.md", "Limits", 1, "FedNow network limit is ten million dollars per credit transfer for every participant."),
                Passage("b#1", "b.md", "Ledger", 1, "The ledger replays every event and checks cash conservation after each one, always."),
                Passage("c#1", "c.md", "Auction", 1, "Lenders submit asks and borrowers submit bids; the uniform price clears the market.")])
    assert c.search("what is the fednow limit")[0]["source"] == "a.md"
    assert c.search("how does replay check conservation")[0]["citation"].startswith("b.md § Ledger")
    assert c.search("zebra quantum") == []
    assert c.answer("best pizza in brooklyn")["found"] is False


def test_rulebook_retrieval_quality_and_citations():
    out = evaluate_retrieval()
    assert out["passages"] > 100 and out["methods"]["bm25"]["hit_at_3"] >= 0.8 and out["methods"]["bm25"]["mrr"] >= 0.7
    a = load_corpus().answer("What is the FedNow transaction limit?")
    assert a["found"] and all("§" in c and "(line " in c for c in a["citations"])


def test_agent_can_search_the_rulebook_and_resists_injection(result):
    s = ToolSession(generate_scenario(SMALL, seed=5))
    hit = s.call("search_rulebook", {"query": "daylight overdraft fee", "n": 2})
    assert hit["found"] and len(hit["passages"]) == 2 and s.audit[-1]["ms"] >= 0 and s.verify_audit()
    red = tuple(t for t in TASKS if t.id in ("injection_fake_authority", "injection_in_data", "budget_flood", "rulebook_citation"))
    assert len(red) == 4
    good = evaluate(planner_agent, tasks=red)
    assert good["pass_rate"] == 1.0
    bad = evaluate(overreacher_agent, tasks=red)
    assert bad["safe"] < 1.0


# ------------------------------------------------------------------ deep forecasters
def test_gru_and_transformer_train_and_predict():
    pytest.importorskip("torch")
    import numpy as np

    from atlas.forecast.deep import GRUForecaster, TransformerForecaster
    from atlas.forecast.models import build_panel
    panel = build_panel(NexusPayConfig(n_institutions=5, payments_per_day=400, instant_payments_per_day=0), list(range(10, 17)), 3, "gross_outflow")
    for cls in (GRUForecaster, TransformerForecaster):
        m = cls(epochs=3, hidden=16)
        m.fit(panel, [0, 1, 2, 3, 4], 1)
        pred, keys = m.predict(panel, [5, 6], 1)
        assert len(pred) == len(keys) == 2 * 5 * (panel["days"].shape[2] - 1) and np.isfinite(pred).all()
        assert 1 <= len(m.history) <= 3 and m.n_params > 0
        again = cls(epochs=3, hidden=16)
        again.fit(panel, [0, 1, 2, 3, 4], 1)
        assert np.allclose(again.predict(panel, [5, 6], 1)[0], pred, atol=1e-4)          # seeded: same data, same model


# ------------------------------------------------------------------ deploy
def test_kubernetes_manifests_are_hardened():
    yaml = pytest.importorskip("yaml")
    docs = [d for d in yaml.safe_load_all((ROOT / "deploy" / "k8s" / "atlas.yaml").read_text()) if d]
    kinds = [d["kind"] for d in docs]
    assert kinds.count("Deployment") == 2 and {"Service", "HorizontalPodAutoscaler", "PodDisruptionBudget", "NetworkPolicy", "Ingress", "Namespace"} <= set(kinds)
    for d in docs:
        if d["kind"] != "Deployment":
            continue
        pod = d["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True and pod["automountServiceAccountToken"] is False
        for c in pod["containers"]:
            sc = c["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False and sc["readOnlyRootFilesystem"] is True and sc["capabilities"]["drop"] == ["ALL"]
            assert {"requests", "limits"} <= set(c["resources"]) and "readinessProbe" in c and "livenessProbe" in c
            assert ":" in c["image"] and not c["image"].endswith(":latest")
        assert d["spec"]["selector"]["matchLabels"].items() <= d["spec"]["template"]["metadata"]["labels"].items()


# ------------------------------------------------------------------ app
def test_streamlit_app_runs_and_reacts_to_a_preset():
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "One settlement day"
    assert at.session_state["stress"] == "baseline"
    next(b for b in at.button if b.label == "Combined stress").click().run()
    assert not at.exception and at.session_state["stress"] == "combined"
    at.sidebar.selectbox[1].set_value("multilateral").run()
    assert not at.exception and at.session_state["policy"] == "multilateral"
