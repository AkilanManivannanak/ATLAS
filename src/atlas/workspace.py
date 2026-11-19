"""Shared team workspace for the app: who used it, what they ran, case decisions, and reviews.

Two backends, same behaviour:

* **SQLite** (default, standard library). One file per deployment; ``ATLAS_DB`` overrides the path. On Streamlit
  Community Cloud this file is lost whenever the app is redeployed.
* **Postgres** when ``ATLAS_DB_URL`` (or the ``url`` argument) is set, for example a free Supabase project. History
  then survives redeploys, so returning users are remembered. Needs ``psycopg``.

Every activity row is chained by SHA-256 like the settlement ledger, so the log is tamper-evident: ``verify()``
recomputes the chain. Names are whatever people type; there are no passwords, and nothing secret is stored.
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
_SCHEMA = """
CREATE TABLE IF NOT EXISTS atlas_events(seq {pk}, at TEXT, usr TEXT, kind TEXT, detail TEXT, prev TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS atlas_cases(payment_id TEXT, run TEXT, usr TEXT, decision TEXT, note TEXT, at TEXT, PRIMARY KEY(payment_id, run));
CREATE TABLE IF NOT EXISTS atlas_reviews(id {pk}, at TEXT, usr TEXT, role TEXT, stars INTEGER, worked TEXT, broke TEXT);
"""


def default_path() -> Path:
    return Path(os.environ.get("ATLAS_DB") or Path(__file__).resolve().parents[2] / ".atlas" / "workspace.db")


def _out(row) -> dict:
    d = dict(row)
    if "usr" in d:
        d["user"] = d.pop("usr")
    return d


class Workspace:
    def __init__(self, path: Path | str | None = None, url: str | None = None):
        self.url = url if url is not None else os.environ.get("ATLAS_DB_URL") or None
        self.backend = "postgres" if self.url else "sqlite"
        if self.url:
            self._connect_pg()
            for stmt in _SCHEMA.format(pk="BIGSERIAL PRIMARY KEY").strip().split(";\n"):
                self._x(stmt)
        else:
            self.path = Path(path) if path else default_path()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.path), check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            with _LOCK, self._db:
                self._db.executescript(_SCHEMA.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT"))

    # ---------------------------------------------------------- one execute path for both backends
    def _connect_pg(self) -> None:
        import psycopg
        from psycopg.rows import dict_row
        self._db = psycopg.connect(self.url, autocommit=True, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)

    def _x(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.backend == "sqlite":
            with _LOCK, self._db:
                return [_out(r) for r in self._db.execute(sql, params).fetchall()]
        sql = sql.replace("?", "%s")
        for attempt in (0, 1):
            try:
                with _LOCK:
                    cur = self._db.execute(sql, params)
                    return [_out(r) for r in cur.fetchall()] if cur.description else []
            except Exception as exc:  # noqa: BLE001 - one reconnect for a dropped pooled connection
                if attempt or "closed" not in str(exc).lower() and "connection" not in str(exc).lower():
                    raise
                self._connect_pg()
        return []

    # ---------------------------------------------------------- activity (hash chained)
    def log(self, user: str, kind: str, detail: dict | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind}")
        user = (user or "guest").strip()[:40] or "guest"
        at = datetime.now(UTC).isoformat(timespec="seconds")
        body = json.dumps(detail or {}, sort_keys=True, default=str)[:4000]
        if self.backend == "sqlite":
            with _LOCK, self._db:
                row = self._db.execute("SELECT hash FROM atlas_events ORDER BY seq DESC LIMIT 1").fetchone()
                prev = row["hash"] if row else "0" * 64
                h = hashlib.sha256(f"{prev}|{at}|{user}|{kind}|{body}".encode()).hexdigest()
                seq = self._db.execute("INSERT INTO atlas_events(at,usr,kind,detail,prev,hash) VALUES(?,?,?,?,?,?)", (at, user, kind, body, prev, h)).lastrowid
        else:  # serialise appends across every app instance with a transaction-scoped advisory lock
            with _LOCK, self._db.transaction():
                self._db.execute("SELECT pg_advisory_xact_lock(424242)")
                row = self._db.execute("SELECT hash FROM atlas_events ORDER BY seq DESC LIMIT 1").fetchone()
                prev = row["hash"] if row else "0" * 64
                h = hashlib.sha256(f"{prev}|{at}|{user}|{kind}|{body}".encode()).hexdigest()
                seq = self._db.execute("INSERT INTO atlas_events(at,usr,kind,detail,prev,hash) VALUES(%s,%s,%s,%s,%s,%s) RETURNING seq",
                                       (at, user, kind, body, prev, h)).fetchone()["seq"]
        return {"seq": seq, "at": at, "user": user, "kind": kind, "hash": h}

    def events(self, limit: int = 200) -> list[dict]:
        return [r | {"detail": json.loads(r["detail"])} for r in self._x("SELECT * FROM atlas_events ORDER BY seq DESC LIMIT ?", (limit,))]

    def verify(self) -> bool:
        prev = "0" * 64
        for r in self._x("SELECT * FROM atlas_events ORDER BY seq"):
            if r["prev"] != prev or hashlib.sha256(f"{prev}|{r['at']}|{r['user']}|{r['kind']}|{r['detail']}".encode()).hexdigest() != r["hash"]:
                return False
            prev = r["hash"]
        return True

    def people(self) -> list[dict]:
        return self._x("SELECT usr, COUNT(*) AS n, MIN(at) AS first, MAX(at) AS last, COUNT(DISTINCT kind) AS kinds FROM atlas_events GROUP BY usr ORDER BY n DESC")

    # ---------------------------------------------------------- alert cases
    def decide(self, user: str, payment_id: str, run: str, decision: str, note: str = "") -> None:
        if decision not in DECISIONS:
            raise ValueError(decision)
        at = datetime.now(UTC).isoformat(timespec="seconds")
        self._x("INSERT INTO atlas_cases VALUES(?,?,?,?,?,?) ON CONFLICT(payment_id, run) DO UPDATE SET usr=excluded.usr, decision=excluded.decision, "
                "note=excluded.note, at=excluded.at", (payment_id, run, user, decision, note[:1000], at))
        self.log(user, "case_decision", {"payment": payment_id, "run": run[:12], "decision": decision})

    def decisions(self, run: str | None = None) -> dict[str, dict]:
        rows = self._x("SELECT * FROM atlas_cases" + (" WHERE run=?" if run else ""), (run,) if run else ())
        return {r["payment_id"]: r for r in rows}

    # ---------------------------------------------------------- reviews
    def review(self, user: str, role: str, stars: int, worked: str, broke: str) -> None:
        stars = max(1, min(5, int(stars)))
        at = datetime.now(UTC).isoformat(timespec="seconds")
        self._x("INSERT INTO atlas_reviews(at,usr,role,stars,worked,broke) VALUES(?,?,?,?,?,?)", (at, user, role[:80], stars, worked[:2000], broke[:2000]))
        self.log(user, "review", {"stars": stars})

    def reviews(self) -> list[dict]:
        return self._x("SELECT * FROM atlas_reviews ORDER BY id DESC")

    def export(self) -> dict:
        return {"exported_at": datetime.now(UTC).isoformat(timespec="seconds"), "backend": self.backend, "chain_intact": self.verify(),
                "events": self.events(10_000), "cases": list(self.decisions().values()), "reviews": self.reviews()}
