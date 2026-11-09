"""SQLite-backed append-only event store with a per-simulation SHA-256 hash chain.

Design contract (``atlas-event-store-v1``):

* Events are immutable once appended. There is no update or delete API.
* Each simulation stream has its own gap-free sequence, starting at 0. An event's
  ``sequence_number`` must equal the next expected stream position.
* Each record stores ``prev_hash`` and ``record_hash`` where
  ``record_hash = sha256(prev_hash || canonical_record_json)``. Any edit to a stored
  row (or a deleted/reordered row) is detected by :meth:`EventStore.verify_chain`.
* Appending an event whose ``event_id`` is already stored with identical content is
  an idempotent no-op (safe retry). Same id with different content is rejected.

SQLite is used because it is in the standard library, transactional and portable.
PostgreSQL can implement the same contract later; the chain hash is storage
independent because it is computed from canonical JSON, not database bytes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from atlas.domain import FinancialEvent

STORE_CONTRACT_VERSION = "atlas-event-store-v1"
GENESIS_HASH = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS financial_events (
    simulation_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    event_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    schema_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    PRIMARY KEY (simulation_id, sequence_number)
);
CREATE INDEX IF NOT EXISTS idx_events_aggregate ON financial_events (simulation_id, aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON financial_events (simulation_id, event_type);
"""


class EventStoreError(RuntimeError):
    """Raised when an append would violate the store contract."""


@dataclass(frozen=True, slots=True)
class StoredEvent:
    event: FinancialEvent
    prev_hash: str
    record_hash: str


@dataclass(frozen=True, slots=True)
class ChainVerification:
    simulation_id: str
    valid: bool
    event_count: int
    head_hash: str
    first_invalid_sequence: int | None = None
    reason: str = ""


def canonical_record(event: FinancialEvent) -> str:
    """Storage-independent canonical encoding used for hashing."""
    record = {
        "aggregate_id": event.aggregate_id,
        "aggregate_type": event.aggregate_type,
        "causation_id": event.causation_id,
        "correlation_id": event.correlation_id,
        "event_at": event.event_at.isoformat(),
        "event_id": event.event_id,
        "event_type": event.event_type,
        "ingested_at": event.ingested_at.isoformat(),
        "payload_json": event.payload_json,
        "schema_version": event.schema_version,
        "sequence_number": event.sequence_number,
        "simulation_id": event.simulation_id,
    }
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def chain_hash(prev_hash: str, event: FinancialEvent) -> str:
    return hashlib.sha256((prev_hash + canonical_record(event)).encode("utf-8")).hexdigest()


class EventStore:
    """Append-only event store. Use ``EventStore()`` for an in-memory store."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute("SELECT value FROM store_meta WHERE key='contract'").fetchone()
        if row is None:
            self._conn.execute("INSERT INTO store_meta(key, value) VALUES ('contract', ?)", (STORE_CONTRACT_VERSION,))
        elif row[0] != STORE_CONTRACT_VERSION:
            raise EventStoreError(f"unsupported store contract {row[0]!r}; expected {STORE_CONTRACT_VERSION!r}")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ writes
    def head(self, simulation_id: str) -> tuple[int, str]:
        """Return (next_sequence_number, head_hash) for a stream."""
        row = self._conn.execute(
            "SELECT sequence_number, record_hash FROM financial_events WHERE simulation_id=? "
            "ORDER BY sequence_number DESC LIMIT 1",
            (simulation_id,),
        ).fetchone()
        if row is None:
            return 0, GENESIS_HASH
        return row[0] + 1, row[1]

    def append(self, event: FinancialEvent) -> StoredEvent:
        return self.append_many((event,))[0]

    def append_many(self, events: Iterable[FinancialEvent]) -> tuple[StoredEvent, ...]:
        """Atomically append events in order; all succeed or none are written."""
        items = tuple(events)
        if any(not isinstance(item, FinancialEvent) for item in items):
            raise TypeError("only FinancialEvent records can be appended")
        stored: list[StoredEvent] = []
        cursor = self._conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            heads: dict[str, tuple[int, str]] = {}
            for event in items:
                existing = cursor.execute(
                    "SELECT simulation_id, sequence_number, prev_hash, record_hash FROM financial_events WHERE event_id=?",
                    (event.event_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] == event.simulation_id and existing[1] == event.sequence_number and existing[3] == chain_hash(existing[2], event):
                        stored.append(StoredEvent(event, existing[2], existing[3]))
                        continue
                    raise EventStoreError(f"event id {event.event_id!r} already stored with different content")
                if event.simulation_id not in heads:
                    heads[event.simulation_id] = self.head(event.simulation_id)
                expected, prev = heads[event.simulation_id]
                if event.sequence_number != expected:
                    raise EventStoreError(
                        f"sequence gap for {event.simulation_id!r}: expected {expected}, got {event.sequence_number}"
                    )
                record_hash = chain_hash(prev, event)
                cursor.execute(
                    "INSERT INTO financial_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event.simulation_id, event.sequence_number, event.event_id, event.event_type,
                        event.aggregate_id, event.aggregate_type, event.event_at.isoformat(),
                        event.ingested_at.isoformat(), event.correlation_id, event.causation_id,
                        event.schema_version, event.payload_json, prev, record_hash,
                    ),
                )
                heads[event.simulation_id] = (expected + 1, record_hash)
                stored.append(StoredEvent(event, prev, record_hash))
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
        return tuple(stored)

    # ------------------------------------------------------------------- reads
    @staticmethod
    def _row_to_event(row: tuple) -> StoredEvent:
        event = FinancialEvent(
            simulation_id=row[0], sequence_number=row[1], event_id=row[2], event_type=row[3],
            aggregate_id=row[4], aggregate_type=row[5], event_at=datetime.fromisoformat(row[6]),
            ingested_at=datetime.fromisoformat(row[7]), correlation_id=row[8], causation_id=row[9],
            schema_version=row[10], payload_json=row[11],
        )
        return StoredEvent(event, row[12], row[13])

    def iter_events(
        self,
        simulation_id: str,
        *,
        event_type: str | None = None,
        aggregate_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Iterator[StoredEvent]:
        sql = "SELECT * FROM financial_events WHERE simulation_id=?"
        params: list[object] = [simulation_id]
        if event_type is not None:
            sql += " AND event_type=?"
            params.append(event_type)
        if aggregate_id is not None:
            sql += " AND aggregate_id=?"
            params.append(aggregate_id)
        sql += " ORDER BY sequence_number LIMIT ? OFFSET ?"
        params.extend([-1 if limit is None else limit, offset])
        for row in self._conn.execute(sql, params):
            yield self._row_to_event(row)

    def events(self, simulation_id: str) -> tuple[FinancialEvent, ...]:
        return tuple(item.event for item in self.iter_events(simulation_id))

    def count(self, simulation_id: str, event_type: str | None = None) -> int:
        if event_type is None:
            return self._conn.execute("SELECT COUNT(*) FROM financial_events WHERE simulation_id=?", (simulation_id,)).fetchone()[0]
        return self._conn.execute(
            "SELECT COUNT(*) FROM financial_events WHERE simulation_id=? AND event_type=?", (simulation_id, event_type)
        ).fetchone()[0]

    def simulations(self) -> tuple[str, ...]:
        return tuple(row[0] for row in self._conn.execute("SELECT DISTINCT simulation_id FROM financial_events ORDER BY simulation_id"))

    def verify_chain(self, simulation_id: str) -> ChainVerification:
        prev = GENESIS_HASH
        count = 0
        for expected_seq, row in enumerate(
            self._conn.execute("SELECT * FROM financial_events WHERE simulation_id=? ORDER BY sequence_number", (simulation_id,))
        ):
            try:
                stored = self._row_to_event(row)
            except (ValueError, TypeError) as exc:
                return ChainVerification(simulation_id, False, count, prev, row[1], f"invalid stored record: {exc}")
            if stored.event.sequence_number != expected_seq:
                return ChainVerification(simulation_id, False, count, prev, expected_seq, "sequence gap")
            if stored.prev_hash != prev:
                return ChainVerification(simulation_id, False, count, prev, expected_seq, "previous-hash link broken")
            if chain_hash(prev, stored.event) != stored.record_hash:
                return ChainVerification(simulation_id, False, count, prev, expected_seq, "record hash mismatch")
            prev = stored.record_hash
            count += 1
        return ChainVerification(simulation_id, True, count, prev)


__all__ = [
    "GENESIS_HASH",
    "STORE_CONTRACT_VERSION",
    "ChainVerification",
    "EventStore",
    "EventStoreError",
    "StoredEvent",
    "canonical_record",
    "chain_hash",
]
