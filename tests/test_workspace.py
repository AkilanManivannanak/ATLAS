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
    db.execute("UPDATE events SET user='mallory' WHERE seq=2")
    db.commit()
    assert not Workspace(tmp_path / "w.db").verify()
