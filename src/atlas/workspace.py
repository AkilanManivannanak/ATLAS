"""Shared team workspace for the app: who used it, what they ran, case decisions, and reviews. Standard library only.

One SQLite file shared by everyone using the same deployment (``ATLAS_DB`` overrides the path). Every row is also
chained by SHA-256 like the settlement ledger, so the activity log is tamper-evident: ``verify()`` recomputes the
chain. Names are whatever people type; there are no passwords, and nothing secret should be stored here.

On Streamlit Community Cloud the file lives as long as the app container does (restarts and redeploys reset it);
``export()`` returns everything as JSON so a team can keep a copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_LOCK = threading.Lock()
KINDS = ("joined", "ran_day", "ran_live_market", "compared", "uploaded", "asked", "case_decision", "review", "pinned", "exported")
DECISIONS = ("clear", "escalate", "file_report")


def default_path() -> Path:
    return Path(os.environ.get("ATLAS_DB") or Path(__file__).resolve().parents[2] / ".atlas" / "workspace.db")


class Workspace:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with _LOCK, self._db:
            self._db.executescript("""
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user TEXT, kind TEXT, detail TEXT, prev TEXT, hash TEXT);
            CREATE TABLE IF NOT EXISTS cases(payment_id TEXT, run TEXT, user TEXT, decision TEXT, note TEXT, at TEXT, PRIMARY KEY(payment_id, run));
            CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user TEXT, role TEXT, stars INTEGER, worked TEXT, broke TEXT);
            """)

    # ---------------------------------------------------------- activity (hash chained)
    def log(self, user: str, kind: str, detail: dict | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind}")
        user = (user or "guest").strip()[:40] or "guest"
        at = datetime.now(UTC).isoformat(timespec="seconds")
        body = json.dumps(detail or {}, sort_keys=True, default=str)[:4000]
        with _LOCK, self._db:
            row = self._db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else "0" * 64
            h = hashlib.sha256(f"{prev}|{at}|{user}|{kind}|{body}".encode()).hexdigest()
            cur = self._db.execute("INSERT INTO events(at,user,kind,detail,prev,hash) VALUES(?,?,?,?,?,?)", (at, user, kind, body, prev, h))
        return {"seq": cur.lastrowid, "at": at, "user": user, "kind": kind, "hash": h}

    def events(self, limit: int = 200) -> list[dict]:
        rows = self._db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]

    def verify(self) -> bool:
        prev = "0" * 64
        for r in self._db.execute("SELECT * FROM events ORDER BY seq"):
            if r["prev"] != prev or hashlib.sha256(f"{prev}|{r['at']}|{r['user']}|{r['kind']}|{r['detail']}".encode()).hexdigest() != r["hash"]:
                return False
            prev = r["hash"]
        return True

    def people(self) -> list[dict]:
        rows = self._db.execute("SELECT user, COUNT(*) n, MIN(at) first, MAX(at) last, COUNT(DISTINCT kind) kinds FROM events GROUP BY user ORDER BY n DESC").fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- alert cases
    def decide(self, user: str, payment_id: str, run: str, decision: str, note: str = "") -> None:
        if decision not in DECISIONS:
            raise ValueError(decision)
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with _LOCK, self._db:
            self._db.execute("INSERT OR REPLACE INTO cases VALUES(?,?,?,?,?,?)", (payment_id, run, user, decision, note[:1000], at))
        self.log(user, "case_decision", {"payment": payment_id, "run": run[:12], "decision": decision})

    def decisions(self, run: str | None = None) -> dict[str, dict]:
        q = "SELECT * FROM cases" + (" WHERE run=?" if run else "")
        return {r["payment_id"]: dict(r) for r in self._db.execute(q, (run,) if run else ())}

    # ---------------------------------------------------------- reviews
    def review(self, user: str, role: str, stars: int, worked: str, broke: str) -> None:
        stars = max(1, min(5, int(stars)))
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with _LOCK, self._db:
            self._db.execute("INSERT INTO reviews(at,user,role,stars,worked,broke) VALUES(?,?,?,?,?,?)", (at, user, role[:80], stars, worked[:2000], broke[:2000]))
        self.log(user, "review", {"stars": stars})

    def reviews(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM reviews ORDER BY id DESC")]

    def export(self) -> dict:
        return {"exported_at": datetime.now(UTC).isoformat(timespec="seconds"), "chain_intact": self.verify(),
                "events": self.events(10_000), "cases": list(self.decisions().values()), "reviews": self.reviews()}
