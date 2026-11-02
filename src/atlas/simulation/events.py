"""Deterministic scheduling records and versioned event ordering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any


EVENT_ORDERING_VERSION = "atlas-event-order-v1"


class EventPhase(IntEnum):
    """Same-timestamp ordering contract. Lower values are processed first."""

    SYSTEM_STATE = 10
    FUNDING_AND_COLLATERAL = 20
    PAYMENT_ARRIVAL = 30
    ELIGIBILITY_AND_QUEUE = 40
    SETTLEMENT = 50
    PARTICIPANT_DECISION = 60
    MONITORING_AND_SNAPSHOT = 70


def canonical_json_object(payload_json: str) -> dict[str, Any]:
    def reject_float(_: str) -> None:
        raise ValueError("simulation event payloads cannot contain floating-point numbers")

    def reject_constant(_: str) -> None:
        raise ValueError("simulation event payloads cannot contain non-standard numeric constants")

    try:
        payload = json.loads(payload_json, parse_float=reject_float, parse_constant=reject_constant)
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("simulation event payload must be valid JSON text") from exc
    if not isinstance(payload, dict):
        raise ValueError("simulation event payload must encode a JSON object")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if canonical != payload_json:
        raise ValueError("simulation event payload must use canonical JSON encoding")
    return payload


def encode_json_object(value: dict[str, Any]) -> str:
    def validate(item: Any, path: str) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            raise ValueError(f"simulation state cannot contain floating-point value at {path}")
        if isinstance(item, list):
            for index, child in enumerate(item):
                validate(child, f"{path}[{index}]")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"simulation state keys must be strings at {path}")
                validate(child, f"{path}.{key}")
            return
        raise ValueError(f"simulation state contains unsupported value {type(item).__name__} at {path}")

    if not isinstance(value, dict):
        raise TypeError("simulation state must be a JSON object")
    validate(value, "$state")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("simulation state must contain JSON-compatible values without NaN") from exc
    canonical_json_object(encoded)
    return encoded


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    event_id: str
    event_type: str
    scheduled_at: datetime
    phase: EventPhase
    payload_json: str = "{}"
    insertion_order: int = -1
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id is required")
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type is required")
        if not isinstance(self.scheduled_at, datetime) or self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if not isinstance(self.phase, EventPhase):
            raise TypeError("phase must be an EventPhase value")
        if not isinstance(self.insertion_order, int) or isinstance(self.insertion_order, bool) or self.insertion_order < -1:
            raise ValueError("insertion_order must be -1 before scheduling or a non-negative integer")
        if self.correlation_id is not None and (not isinstance(self.correlation_id, str) or not self.correlation_id.strip()):
            raise ValueError("correlation_id must be a non-empty string when supplied")
        if self.causation_id is not None and (not isinstance(self.causation_id, str) or not self.causation_id.strip()):
            raise ValueError("causation_id must be a non-empty string when supplied")
        canonical_json_object(self.payload_json)
