import os

import pytest

os.environ["ATLAS_DEMO_RUNS"] = "0"

from datetime import UTC

from fastapi.testclient import TestClient  # noqa: E402

from atlas.api import app as app_module  # noqa: E402
from atlas.iso20022 import build_pacs008  # noqa: E402

SMALL = {"n_institutions": 6, "payments_per_day": 300, "instant_payments_per_day": 150, "seed": 3}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return TestClient(app_module.app)


def test_health_and_meta(client):
    h = client.get("/api/v1/health").json()
    assert h["status"] == "ok" and h["synthetic_only"] is True
    meta = client.get("/api/v1/meta").json()
    assert "multilateral" in meta["policies"] and "combined" in meta["stress_scenarios"]


def test_simulation_lifecycle_replay_and_counterfactual(client):
    created = client.post("/api/v1/simulations", json={**SMALL, "policy": "priority"})
    assert created.status_code == 201
    run_id = created.json()["id"]
    detail = client.get(f"/api/v1/simulations/{run_id}").json()
    assert detail["metrics"]["large_value"]["count"] > 0 and detail["timeseries"]
    ev = client.get(f"/api/v1/simulations/{run_id}/events", params={"limit": 5}).json()
    assert ev["total"] > 0 and len(ev["items"]) == 5 and len(ev["items"][0]["record_hash"]) == 64
    rp = client.post(f"/api/v1/simulations/{run_id}/replay").json()
    assert rp["chain_valid"] and rp["replay_matches"]
    pays = client.get(f"/api/v1/simulations/{run_id}/payments", params={"status": "settled", "limit": 3}).json()
    assert pays["total"] > 0 and all(p["status"] == "settled" for p in pays["items"])
    inst = client.get(f"/api/v1/simulations/{run_id}/institutions").json()[0]["institution_id"]
    assert "exposures" in client.get(f"/api/v1/simulations/{run_id}/institutions/{inst}").json()
    net = client.get(f"/api/v1/simulations/{run_id}/network").json()
    assert net["n_nodes"] == 6 and net["hourly"]
    assert client.get(f"/api/v1/simulations/{run_id}/rails/fednow").json()["rail"] == "fednow"
    cf = client.post(f"/api/v1/simulations/{run_id}/counterfactual", json={"controller": "mpc"}).json()
    assert cf["same_scenario_fingerprint"] and cf["changed_assumptions"] == {"controller": "mpc"}
    assert client.post(f"/api/v1/simulations/{run_id}/counterfactual", json={}).status_code == 422


def test_validation_errors_are_structured(client):
    r = client.post("/api/v1/simulations", json={**SMALL, "stress": "alien_invasion"})
    assert r.status_code == 422 and "error" in r.json()
    assert client.get("/api/v1/simulations/nope").status_code == 404
    assert client.get("/api/v1/benchmarks/..%2Fetc").status_code in (404, 422)


def test_optimization_and_iso_endpoints(client):
    f = client.post("/api/v1/optimization/funding", json={"sources": [{"name": "res", "capacity_minor": 500, "cost_bp": 5}],
                                                         "scenarios": [100, 200, 900]}).json()
    assert f["cvar"]["status"] == "optimal"
    n = client.post("/api/v1/optimization/netting", json={"obligations": [{"obligation_id": "a", "payer": "X", "payee": "Y", "amount_minor": 5},
                                                                           {"obligation_id": "b", "payer": "Y", "payee": "X", "amount_minor": 5}],
                                                          "available": {"X": 0, "Y": 0}, "algorithm": "milp"}).json()
    assert sorted(n["selected"]) == ["a", "b"]
    from datetime import date, datetime

    from atlas.domain import CurrencySpec, Money
    xml = build_pacs008("M1", datetime(2026, 1, 6, tzinfo=UTC), [{"end_to_end_id": "E", "amount": Money.from_major_units("1.00", CurrencySpec("USD", 2)),
                                                                           "settlement_date": date(2026, 1, 6), "debtor_bic": "AAAAUS33", "creditor_bic": "BBBBUS33"}])
    ok = client.post("/api/v1/iso20022/normalize", content=xml, headers={"content-type": "application/xml"})
    assert ok.status_code == 200 and ok.json()["transactions"][0]["amount_minor"] == 100
    bad = client.post("/api/v1/iso20022/normalize", content="<x/>", headers={"content-type": "application/xml"})
    assert bad.status_code == 422


def test_rbac(client, monkeypatch):
    monkeypatch.setenv("ATLAS_API_KEYS", "k-admin:admin,k-audit:auditor")
    assert client.get("/api/v1/meta").status_code == 401
    assert client.get("/api/v1/meta", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/meta", headers={"X-API-Key": "k-audit"}).status_code == 200
    assert client.post("/api/v1/simulations", json=SMALL, headers={"X-API-Key": "k-audit"}).status_code == 403


def test_metrics_endpoint(client):
    body = client.get("/metrics").text
    assert "atlas_requests_total" in body and "atlas_simulations_total" in body


def test_vertical_slice_endpoint(client):
    vs = client.get("/api/v1/vertical-slice").json()
    assert vs["replay_matches"] and vs["payment"]["status"] == "settled"


def test_analyst_statements_and_auction(client):
    run_id = client.post("/api/v1/simulations", json={**SMALL, "auction": "uniform"}).json()["id"]
    a = client.post(f"/api/v1/simulations/{run_id}/ask", json={"question": "Which institutions are most exposed?"}).json()
    assert a["intent"] == "most_exposed" and a["evidence"] and a["can_execute"] is False
    assert client.post(f"/api/v1/simulations/{run_id}/ask", json={"question": "why is liquidity declining"}).json()["intent"] == "liquidity_decline"
    inst = client.get(f"/api/v1/simulations/{run_id}/institutions").json()[0]["institution_id"]
    st = client.get(f"/api/v1/simulations/{run_id}/statements/{inst}:rtgs").json()
    assert st["reconciliation"]["balanced"] and st["reconciliation"]["matches_ledger"] and st["xml"].startswith("<?xml")
    detail = client.get(f"/api/v1/simulations/{run_id}").json()
    assert detail["metrics"]["auction"]["mechanism"] == "uniform"
