"""Deterministic discrete-event engine with replay and checkpoint support."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from .events import EVENT_ORDERING_VERSION, EventPhase, SimulationEvent, canonical_json_object, encode_json_object
from .rng import DeterministicRandomStream, derive_stream_seed


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    simulation_id: str
    start_at: datetime
    seed: int
    ordering_version: str = EVENT_ORDERING_VERSION
    handler_version: str = "atlas-handlers-v1"

    def __post_init__(self) -> None:
        if any(not isinstance(item, str) or not item.strip() for item in (self.simulation_id, self.handler_version, self.ordering_version)):
            raise ValueError("simulation id and version identifiers are required")
        if not isinstance(self.start_at, datetime) or self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("simulation start time must be timezone-aware")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TypeError("simulation seed must be an integer")
        if self.ordering_version != EVENT_ORDERING_VERSION:
            raise ValueError(f"unsupported event ordering version: {self.ordering_version}")


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    config: SimulationConfig
    current_time: datetime
    initial_state_json: str
    state_json: str
    state_sha256: str
    pending_events: tuple[SimulationEvent, ...]
    canceled_events: tuple[SimulationEvent, ...]
    applied_events: tuple[SimulationEvent, ...]
    known_event_ids: tuple[str, ...]
    next_insertion_order: int
    random_streams_json: str

    def __post_init__(self) -> None:
        for name, events in (
            ("pending_events", self.pending_events),
            ("canceled_events", self.canceled_events),
            ("applied_events", self.applied_events),
        ):
            if not isinstance(events, tuple):
                raise TypeError(f"{name} must be an immutable tuple")
        if not isinstance(self.known_event_ids, tuple):
            raise TypeError("known_event_ids must be an immutable tuple")
        if not isinstance(self.current_time, datetime) or self.current_time.tzinfo is None or self.current_time.utcoffset() is None:
            raise ValueError("snapshot time must be timezone-aware")
        canonical_json_object(self.initial_state_json)
        canonical_json_object(self.state_json)
        canonical_json_object(self.random_streams_json)
        digest = hashlib.sha256(self.state_json.encode("utf-8")).hexdigest()
        if digest != self.state_sha256:
            raise ValueError("snapshot state hash does not match its state payload")

    def to_json(self) -> str:
        def event_data(event: SimulationEvent) -> dict[str, Any]:
            return {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "scheduled_at": event.scheduled_at.isoformat(),
                "phase": int(event.phase),
                "payload_json": event.payload_json,
                "insertion_order": event.insertion_order,
                "correlation_id": event.correlation_id,
                "causation_id": event.causation_id,
            }

        data = {
            "config": {
                "simulation_id": self.config.simulation_id,
                "start_at": self.config.start_at.isoformat(),
                "seed": self.config.seed,
                "ordering_version": self.config.ordering_version,
                "handler_version": self.config.handler_version,
            },
            "current_time": self.current_time.isoformat(),
            "initial_state_json": self.initial_state_json,
            "state_json": self.state_json,
            "state_sha256": self.state_sha256,
            "pending_events": [event_data(item) for item in self.pending_events],
            "canceled_events": [event_data(item) for item in self.canceled_events],
            "applied_events": [event_data(item) for item in self.applied_events],
            "known_event_ids": list(self.known_event_ids),
            "next_insertion_order": self.next_insertion_order,
            "random_streams_json": self.random_streams_json,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, value: str) -> SimulationSnapshot:
        def event_from_data(data: Mapping[str, Any]) -> SimulationEvent:
            try:
                return SimulationEvent(
                    event_id=data["event_id"],
                    event_type=data["event_type"],
                    scheduled_at=datetime.fromisoformat(data["scheduled_at"]),
                    phase=EventPhase(data["phase"]),
                    payload_json=data["payload_json"],
                    insertion_order=data["insertion_order"],
                    correlation_id=data.get("correlation_id"),
                    causation_id=data.get("causation_id"),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("snapshot contains an invalid event record") from exc

        canonical_json_object(value)
        try:
            data = json.loads(value)
            if json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) != value:
                raise ValueError("snapshot JSON must use canonical encoding")
            config_data = data["config"]
            config = SimulationConfig(
                simulation_id=config_data["simulation_id"],
                start_at=datetime.fromisoformat(config_data["start_at"]),
                seed=config_data["seed"],
                ordering_version=config_data["ordering_version"],
                handler_version=config_data["handler_version"],
            )
            return cls(
                config=config,
                current_time=datetime.fromisoformat(data["current_time"]),
                initial_state_json=data["initial_state_json"],
                state_json=data["state_json"],
                state_sha256=data["state_sha256"],
                pending_events=tuple(event_from_data(item) for item in data["pending_events"]),
                canceled_events=tuple(event_from_data(item) for item in data["canceled_events"]),
                applied_events=tuple(event_from_data(item) for item in data["applied_events"]),
                known_event_ids=tuple(data["known_event_ids"]),
                next_insertion_order=data["next_insertion_order"],
                random_streams_json=data["random_streams_json"],
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("snapshot JSON is missing required fields or has invalid types") from exc


class SimulationExecutionError(RuntimeError):
    def __init__(self, event: SimulationEvent, cause: Exception) -> None:
        super().__init__(f"simulation handler failed for event {event.event_id!r} ({event.event_type}): {cause}")
        self.event = event
        self.__cause__ = cause


class EventContext:
    """Transactional event context; staged schedules and random draws commit on success."""

    def __init__(self, engine: SimulationEngine, event: SimulationEvent) -> None:
        self._engine = engine
        self._event = event
        self._staged_events: list[SimulationEvent] = []
        self._staged_streams: dict[str, DeterministicRandomStream] = {}

    def schedule_event(self, event: SimulationEvent) -> None:
        related = replace(
            event,
            correlation_id=event.correlation_id or self._event.correlation_id or self._event.event_id,
            causation_id=event.causation_id or self._event.event_id,
        )
        self._engine._validate_new_event(related, current_event=self._event, staged=self._staged_events)
        self._staged_events.append(related)

    def random_stream(self, name: str) -> DeterministicRandomStream:
        if name not in self._staged_streams:
            current = self._engine._random_streams.get(name)
            if current is None:
                current = DeterministicRandomStream(derive_stream_seed(self._engine.config.seed, name))
            self._staged_streams[name] = current.copy()
        return self._staged_streams[name]


Handler = Callable[[dict[str, Any], SimulationEvent, EventContext], Mapping[str, Any]]


def _utc_instant(value: datetime) -> datetime:
    return value.astimezone(UTC)


class SimulationEngine:
    """Event ordering is timestamp, phase priority, then schedule insertion order.

    Handlers must be deterministic functions of the supplied state, event, and
    context. They must not perform I/O or use external randomness. Handler state
    updates, newly scheduled events, and random draws commit atomically only if
    the handler returns a JSON-compatible state successfully.
    """

    def __init__(
        self,
        config: SimulationConfig,
        initial_state: Mapping[str, Any],
        handlers: Mapping[str, Handler],
    ) -> None:
        if not isinstance(initial_state, Mapping):
            raise TypeError("initial state must be a mapping")
        self.config = config
        self.current_time = config.start_at
        self._initial_state_json = encode_json_object(dict(initial_state))
        self._state_json = self._initial_state_json
        self._handlers = dict(handlers)
        if any(not isinstance(key, str) or not key.strip() or not callable(handler) for key, handler in self._handlers.items()):
            raise ValueError("handlers require non-empty event type keys and callable values")
        self._queue: list[tuple[datetime, int, int, str, SimulationEvent]] = []
        self._events: dict[str, SimulationEvent] = {}
        self._pending_ids: set[str] = set()
        self._canceled_ids: set[str] = set()
        self._applied_events: list[SimulationEvent] = []
        self._known_ids: set[str] = set()
        self._next_insertion_order = 0
        self._random_streams: dict[str, DeterministicRandomStream] = {}
        self._failed_event: SimulationEvent | None = None
        self._active_event: SimulationEvent | None = None

    def get_state(self) -> dict[str, Any]:
        return json.loads(self._state_json)

    @property
    def state_sha256(self) -> str:
        return hashlib.sha256(self._state_json.encode("utf-8")).hexdigest()

    @property
    def event_log(self) -> tuple[SimulationEvent, ...]:
        return tuple(self._applied_events)

    @property
    def failed_event(self) -> SimulationEvent | None:
        return self._failed_event

    def random_stream(self, name: str) -> DeterministicRandomStream:
        self._ensure_healthy()
        if self._active_event is not None:
            raise RuntimeError("handlers must obtain random streams from their event context")
        if name not in self._random_streams:
            self._random_streams[name] = DeterministicRandomStream(derive_stream_seed(self.config.seed, name))
        return self._random_streams[name]

    def random_stream_state(self, name: str) -> int:
        """Read a stream checkpoint without advancing it, including after a fault."""
        stream = self._random_streams.get(name)
        return stream.state if stream is not None else derive_stream_seed(self.config.seed, name)

    def schedule_event(self, event: SimulationEvent) -> SimulationEvent:
        self._ensure_healthy()
        self._validate_new_event(event)
        return self._insert_event(event)

    def _validate_new_event(
        self,
        event: SimulationEvent,
        *,
        current_event: SimulationEvent | None = None,
        staged: list[SimulationEvent] | None = None,
    ) -> None:
        if not isinstance(event, SimulationEvent):
            raise TypeError("event must be a SimulationEvent")
        if event.insertion_order != -1:
            raise ValueError("new events must not carry an insertion order")
        if event.event_id in self._known_ids or any(item.event_id == event.event_id for item in (staged or ())):
            raise ValueError(f"duplicate event id: {event.event_id}")
        boundary_time = current_event.scheduled_at if current_event is not None else self.current_time
        if _utc_instant(event.scheduled_at) < _utc_instant(boundary_time):
            raise ValueError("cannot schedule an event in the simulation past")
        same_instant = current_event is not None and _utc_instant(event.scheduled_at) == _utc_instant(current_event.scheduled_at)
        if same_instant and event.phase < current_event.phase:
            raise ValueError("same-time event cannot be scheduled into an earlier phase")

    def _insert_event(self, event: SimulationEvent, insertion_order: int | None = None) -> SimulationEvent:
        order = self._next_insertion_order if insertion_order is None else insertion_order
        if order < self._next_insertion_order and insertion_order is not None:
            raise ValueError("restored event insertion order is not monotonic")
        scheduled = replace(
            event,
            insertion_order=order,
            correlation_id=event.correlation_id or event.event_id,
        )
        self._next_insertion_order = order + 1
        self._events[scheduled.event_id] = scheduled
        self._known_ids.add(scheduled.event_id)
        self._pending_ids.add(scheduled.event_id)
        heapq.heappush(self._queue, (_utc_instant(scheduled.scheduled_at), int(scheduled.phase), order, scheduled.event_id, scheduled))
        return scheduled

    def cancel_event(self, event_id: str) -> SimulationEvent:
        self._ensure_healthy()
        if event_id not in self._pending_ids:
            raise ValueError(f"event {event_id!r} is not pending and cannot be cancelled")
        event = self._events[event_id]
        self._pending_ids.remove(event_id)
        self._canceled_ids.add(event_id)
        return event

    def step(self) -> SimulationEvent | None:
        self._ensure_healthy()
        self._discard_cancelled_head()
        if not self._queue:
            return None
        _, _, _, _, event = heapq.heappop(self._queue)
        self._pending_ids.remove(event.event_id)
        handler = self._handlers.get(event.event_type)
        if handler is None:
            exc = KeyError(f"no handler registered for event type {event.event_type!r}")
            self._failed_event = event
            raise SimulationExecutionError(event, exc)

        context = EventContext(self, event)
        prior_active = self._active_event
        self._active_event = event
        try:
            before_state = json.loads(self._state_json)
            next_state = handler(before_state, event, context)
            if not isinstance(next_state, Mapping):
                raise TypeError("event handler must return a state mapping")
            next_state_json = encode_json_object(dict(next_state))
            self._validate_staged_times(context._staged_events, event)
        except Exception as exc:
            self._active_event = prior_active
            self._failed_event = event
            raise SimulationExecutionError(event, exc) from exc

        self._state_json = next_state_json
        self.current_time = event.scheduled_at
        self._applied_events.append(event)
        for name, stream in context._staged_streams.items():
            self._random_streams[name] = stream
        for staged_event in context._staged_events:
            self._insert_event(staged_event)
        self._active_event = prior_active
        return event

    def _validate_staged_times(self, events: list[SimulationEvent], current_event: SimulationEvent) -> None:
        # Validate against both engine-known IDs and sibling events before committing any staged work.
        seen: set[str] = set()
        for event in events:
            self._validate_new_event(event, current_event=current_event)
            if event.event_id in seen:
                raise ValueError(f"duplicate staged event id: {event.event_id}")
            seen.add(event.event_id)

    def _discard_cancelled_head(self) -> None:
        while self._queue and self._queue[0][3] in self._canceled_ids:
            heapq.heappop(self._queue)

    def run_until(self, until: datetime) -> tuple[SimulationEvent, ...]:
        self._ensure_healthy()
        if until.tzinfo is None or until.utcoffset() is None:
            raise ValueError("run_until timestamp must be timezone-aware")
        if _utc_instant(until) < _utc_instant(self.current_time):
            raise ValueError("simulation clock cannot move backwards")
        start_count = len(self._applied_events)
        while True:
            self._discard_cancelled_head()
            if not self._queue or self._queue[0][0] > _utc_instant(until):
                break
            self.step()
        self.current_time = until
        return tuple(self._applied_events[start_count:])

    def snapshot(self) -> SimulationSnapshot:
        self._ensure_healthy()
        pending = tuple(sorted((self._events[event_id] for event_id in self._pending_ids), key=self._event_key))
        canceled = tuple(sorted((self._events[event_id] for event_id in self._canceled_ids), key=self._event_key))
        random_json = encode_json_object({name: stream.state for name, stream in sorted(self._random_streams.items())})
        return SimulationSnapshot(
            config=self.config,
            current_time=self.current_time,
            initial_state_json=self._initial_state_json,
            state_json=self._state_json,
            state_sha256=self.state_sha256,
            pending_events=pending,
            canceled_events=canceled,
            applied_events=tuple(self._applied_events),
            known_event_ids=tuple(sorted(self._known_ids)),
            next_insertion_order=self._next_insertion_order,
            random_streams_json=random_json,
        )

    @classmethod
    def restore(cls, snapshot: SimulationSnapshot, handlers: Mapping[str, Handler]) -> SimulationEngine:
        if not isinstance(snapshot, SimulationSnapshot):
            raise TypeError("snapshot must be a SimulationSnapshot")
        engine = cls(snapshot.config, json.loads(snapshot.initial_state_json), handlers)
        engine.current_time = snapshot.current_time
        engine._state_json = snapshot.state_json
        engine._applied_events = list(snapshot.applied_events)
        engine._known_ids = set(snapshot.known_event_ids)
        engine._next_insertion_order = snapshot.next_insertion_order
        for event in snapshot.pending_events:
            if event.insertion_order < 0 or event.event_id not in engine._known_ids:
                raise ValueError("snapshot pending event is missing a valid insertion record")
            engine._events[event.event_id] = event
            engine._pending_ids.add(event.event_id)
            heapq.heappush(engine._queue, (_utc_instant(event.scheduled_at), int(event.phase), event.insertion_order, event.event_id, event))
        for event in snapshot.canceled_events:
            if event.insertion_order < 0 or event.event_id not in engine._known_ids:
                raise ValueError("snapshot canceled event is missing a valid insertion record")
            engine._events[event.event_id] = event
            engine._canceled_ids.add(event.event_id)
        for event in snapshot.applied_events:
            if event.insertion_order < 0 or event.event_id not in engine._known_ids:
                raise ValueError("snapshot applied event is missing a valid insertion record")
            engine._events[event.event_id] = event
        event_groups = (
            {event.event_id for event in snapshot.pending_events},
            {event.event_id for event in snapshot.canceled_events},
            {event.event_id for event in snapshot.applied_events},
        )
        all_recorded_events = (*snapshot.pending_events, *snapshot.canceled_events, *snapshot.applied_events)
        if sum(map(len, event_groups)) != len(set().union(*event_groups)):
            raise ValueError("snapshot event lifecycle groups overlap")
        if set().union(*event_groups) != engine._known_ids:
            raise ValueError("snapshot known event identifiers do not match lifecycle records")
        max_order = max((event.insertion_order for event in all_recorded_events), default=-1)
        if snapshot.next_insertion_order <= max_order:
            raise ValueError("snapshot next insertion order is not ahead of recorded events")
        if any(_utc_instant(event.scheduled_at) < _utc_instant(snapshot.current_time) for event in snapshot.pending_events):
            raise ValueError("snapshot contains pending events in the simulation past")
        for name, state in json.loads(snapshot.random_streams_json).items():
            if not isinstance(state, int) or isinstance(state, bool) or not 0 <= state < 1 << 64:
                raise ValueError("snapshot random stream state is invalid")
            engine._random_streams[name] = DeterministicRandomStream.from_state(state)
        if _utc_instant(snapshot.current_time) < _utc_instant(snapshot.config.start_at):
            raise ValueError("snapshot clock precedes simulation start")
        if len(engine._known_ids) != len(snapshot.known_event_ids):
            raise ValueError("snapshot contains duplicate event identifiers")
        recorded_orders = [event.insertion_order for event in all_recorded_events]
        if len(recorded_orders) != len(set(recorded_orders)):
            raise ValueError("snapshot contains duplicate insertion orders")
        if any(_utc_instant(event.scheduled_at) > _utc_instant(snapshot.current_time) for event in snapshot.applied_events):
            raise ValueError("snapshot applied-event history is ahead of the simulation clock")
        if engine.state_sha256 != snapshot.state_sha256:
            raise ValueError("restored state hash does not match snapshot")
        return engine

    @classmethod
    def replay(
        cls,
        config: SimulationConfig,
        initial_state: Mapping[str, Any],
        initial_events: tuple[SimulationEvent, ...] | list[SimulationEvent],
        handlers: Mapping[str, Handler],
        *,
        until: datetime | None = None,
    ) -> SimulationEngine:
        """Replay a recorded initial event stream under a pinned handler/order version."""
        engine = cls(config, initial_state, handlers)
        ordered = sorted(initial_events, key=lambda event: event.insertion_order)
        seen_orders: set[int] = set()
        for event in ordered:
            if event.insertion_order < 0 or event.insertion_order in seen_orders:
                raise ValueError("replay events require unique recorded insertion orders")
            if _utc_instant(event.scheduled_at) < _utc_instant(config.start_at):
                raise ValueError("replay event precedes simulation start")
            if event.event_id in engine._known_ids:
                raise ValueError(f"duplicate replay event id: {event.event_id}")
            seen_orders.add(event.insertion_order)
            engine._insert_event(replace(event, insertion_order=-1), insertion_order=event.insertion_order)
        if seen_orders:
            engine._next_insertion_order = max(seen_orders) + 1
        if until is None:
            while engine.step() is not None:
                pass
        else:
            engine.run_until(until)
        return engine

    @staticmethod
    def _event_key(event: SimulationEvent) -> tuple[datetime, int, int, str]:
        return _utc_instant(event.scheduled_at), int(event.phase), event.insertion_order, event.event_id

    def _ensure_healthy(self) -> None:
        if self._failed_event is not None:
            raise RuntimeError(f"simulation is halted after failed event {self._failed_event.event_id!r}")
