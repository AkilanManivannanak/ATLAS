"""Deterministic discrete-event simulation primitives."""

from .engine import (
    EventContext,
    SimulationConfig,
    SimulationEngine,
    SimulationExecutionError,
    SimulationSnapshot,
)
from .events import EVENT_ORDERING_VERSION, EventPhase, SimulationEvent
from .rng import DeterministicRandomStream, derive_stream_seed

__all__ = [
    "EVENT_ORDERING_VERSION",
    "DeterministicRandomStream",
    "EventContext",
    "EventPhase",
    "SimulationConfig",
    "SimulationEngine",
    "SimulationEvent",
    "SimulationExecutionError",
    "SimulationSnapshot",
    "derive_stream_seed",
]
