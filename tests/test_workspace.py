import sqlite3

import pytest

from atlas.workspace import Workspace


def test_log_chain_cases_reviews(tmp_path):
    ws = Workspace(tmp_path / "w.db")
    ws.log("ana", "joined")
    ws.log("ben", "ran_day", {"stress": "combined"})
    ws.decide("ana", "P-1", "run1", "escalate", "fan-in from new corridor")
    ws.review("ben", "treasury analyst", 4, "the live market page", "upload errors")
    assert ws.verify()
    assert ws.decisions("run1")["P-1"]["decision"] == "escalate"
    assert {p["user"] for p in ws.people()} == {"ana", "ben"}
    assert ws.reviews()[0]["stars"] == 4 and ws.export()["chain_intact"]
    with pytest.raises(ValueError):
        ws.log("x", "transfer_money")


def test_tamper_detected(tmp_path):
    ws = Workspace(tmp_path / "w.db")
    for i in range(3):
        ws.log("ana", "ran_day", {"i": i})
    db = sqlite3.connect(tmp_path / "w.db")
    db.execute("UPDATE atlas_events SET usr='mallory' WHERE seq=2")
    db.commit()
    assert not Workspace(tmp_path / "w.db").verify()


@pytest.mark.skipif(not __import__("os").environ.get("ATLAS_TEST_PG_URL"), reason="set ATLAS_TEST_PG_URL to test the Postgres backend")
def test_postgres_backend_same_behaviour():
    import os
    url = os.environ["ATLAS_TEST_PG_URL"]
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        for t in ("atlas_events", "atlas_cases", "atlas_reviews"):
            c.execute(f"DROP TABLE IF EXISTS {t}")
    ws = Workspace(url=url)
    assert ws.backend == "postgres"
    ws.log("ana", "joined")
    ws.decide("ana", "P-1", "run1", "clear")
    ws.decide("ana", "P-1", "run1", "escalate", "changed my mind")
    ws.review("ben", "analyst", 5, "fast", "")
    again = Workspace(url=url)  # a redeploy: new process, same database
    assert again.decisions("run1")["P-1"]["decision"] == "escalate"
    assert [e["user"] for e in again.events()][-1] == "ana" and again.verify()
    assert {p["user"] for p in again.people()} == {"ana", "ben"}
