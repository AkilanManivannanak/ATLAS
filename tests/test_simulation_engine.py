import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from atlas.simulation import (
    EventPhase,
    SimulationConfig,
    SimulationEngine,
    SimulationEvent,
    SimulationExecutionError,
)

START = datetime(2026, 2, 2, 9, 0, tzinfo=UTC)


def config(seed=31):
    return SimulationConfig("sim-1", START, seed, handler_version="handlers-test-v1")


def event(event_id, phase, *, at=None, event_type="record", payload="{}"):
    return SimulationEvent(event_id, event_type, at or START, phase, payload)


def recording_handler(state, item, context):
    return {**state, "seen": [*state["seen"], item.event_id]}


def test_same_timestamp_order_is_phase_then_insertion_order_and_run_until_is_inclusive():
    handlers = {"record": recording_handler}
    engine = SimulationEngine(config(), {"seen": []}, handlers)
    at = START + timedelta(minutes=1)
    engine.schedule_event(event("monitor-first", EventPhase.MONITORING_AND_SNAPSHOT, at=at))
    engine.schedule_event(event("settle-first", EventPhase.SETTLEMENT, at=at))
    engine.schedule_event(event("funding", EventPhase.FUNDING_AND_COLLATERAL, at=at))
    engine.schedule_event(event("arrival", EventPhase.PAYMENT_ARRIVAL, at=at))
    engine.schedule_event(event("settle-second", EventPhase.SETTLEMENT, at=at))

    applied = engine.run_until(at)
    assert [item.event_id for item in applied] == ["funding", "arrival", "settle-first", "settle-second", "monitor-first"]
    assert engine.get_state()["seen"] == [item.event_id for item in applied]
    assert engine.current_time == at


def test_repeated_local_time_orders_by_utc_instant_across_daylight_saving_fold():
    eastern = ZoneInfo("America/New_York")
    first_0130 = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=0)
    second_0130 = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=1)
    cfg = SimulationConfig("dst-fold", first_0130, 31, handler_version="handlers-test-v1")
    engine = SimulationEngine(cfg, {"seen": []}, {"record": recording_handler})
    engine.schedule_event(event("second-occurrence", EventPhase.SETTLEMENT, at=second_0130))
    engine.schedule_event(event("first-occurrence", EventPhase.SETTLEMENT, at=first_0130))

    applied = engine.run_until(second_0130)

    assert [item.event_id for item in applied] == ["first-occurrence", "second-occurrence"]


def test_scheduling_rejects_past_naive_duplicate_and_future_order_regression():
    engine = SimulationEngine(config(), {"seen": []}, {"record": recording_handler})
    with pytest.raises(ValueError, match="past"):
        engine.schedule_event(event("past", EventPhase.SETTLEMENT, at=START - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="timezone-aware"):
        engine.schedule_event(SimulationEvent("naive", "record", datetime(2026, 2, 2), EventPhase.SETTLEMENT))
    engine.schedule_event(event("same", EventPhase.SETTLEMENT))
    with pytest.raises(ValueError, match="duplicate"):
        engine.schedule_event(event("same", EventPhase.SETTLEMENT))

    def regressing_handler(state, item, context):
        context.schedule_event(event("regression", EventPhase.PAYMENT_ARRIVAL, at=item.scheduled_at))
        return state

    engine2 = SimulationEngine(config(), {"seen": []}, {"bad": regressing_handler})
    engine2.schedule_event(event("decision", EventPhase.PARTICIPANT_DECISION, event_type="bad"))
    with pytest.raises(SimulationExecutionError, match="earlier phase"):
        engine2.step()
    assert engine2.get_state() == {"seen": []}


def test_cancel_only_pending_events_and_cancelled_events_are_not_dispatched():
    engine = SimulationEngine(config(), {"seen": []}, {"record": recording_handler})
    pending = engine.schedule_event(event("pending", EventPhase.SETTLEMENT))
    engine.cancel_event(pending.event_id)
    assert engine.step() is None
    assert engine.get_state()["seen"] == []
    with pytest.raises(ValueError, match="not pending"):
        engine.cancel_event(pending.event_id)

    applied = engine.schedule_event(event("applied", EventPhase.SETTLEMENT))
    engine.step()
    with pytest.raises(ValueError, match="not pending"):
        engine.cancel_event(applied.event_id)


def test_snapshot_restore_continues_pending_events_and_random_streams_exactly():
    def random_handler(state, item, context):
        draw = context.random_stream("arrivals-bank-a").randbelow(100_000)
        return {**state, "draws": [*state["draws"], draw], "seen": [*state["seen"], item.event_id]}

    handlers = {"random": random_handler}
    engine = SimulationEngine(config(), {"draws": [], "seen": []}, handlers)
    engine.schedule_event(event("first", EventPhase.PAYMENT_ARRIVAL, event_type="random"))
    engine.schedule_event(event("second", EventPhase.PAYMENT_ARRIVAL, at=START + timedelta(seconds=1), event_type="random"))
    engine.schedule_event(event("cancel-me", EventPhase.MONITORING_AND_SNAPSHOT, at=START + timedelta(seconds=2)))
    engine.cancel_event("cancel-me")
    engine.step()
    snapshot = engine.snapshot()
    restored = SimulationEngine.restore(snapshot, handlers)
    engine.run_until(START + timedelta(seconds=3))
    restored.run_until(START + timedelta(seconds=3))
    assert restored.state_sha256 == engine.state_sha256
    assert restored.event_log == engine.event_log
    assert restored.snapshot().random_streams_json == engine.snapshot().random_streams_json


def test_replay_with_same_event_stream_seed_and_handler_version_is_identical():
    def random_handler(state, item, context):
        draw = context.random_stream("participant-1").randbelow(1_000)
        return {"values": [*state["values"], draw], "event_ids": [*state["event_ids"], item.event_id]}

    handlers = {"random": random_handler}
    source = SimulationEngine(config(seed=99), {"values": [], "event_ids": []}, handlers)
    recorded = (
        source.schedule_event(event("a", EventPhase.PAYMENT_ARRIVAL, event_type="random")),
        source.schedule_event(event("b", EventPhase.PAYMENT_ARRIVAL, at=START + timedelta(seconds=1), event_type="random")),
    )
    source.run_until(START + timedelta(seconds=2))
    replayed = SimulationEngine.replay(config(seed=99), {"values": [], "event_ids": []}, recorded, handlers, until=START + timedelta(seconds=2))
    assert replayed.state_sha256 == source.state_sha256
    assert replayed.event_log == source.event_log


def test_handler_failure_rolls_back_state_schedules_and_random_draws_then_halts():
    def failing_handler(state, item, context):
        state["values"].append("mutated-copy")
        context.random_stream("isolated").next_uint64()
        context.schedule_event(event("side-effect", EventPhase.SETTLEMENT, at=START + timedelta(seconds=1)))
        raise RuntimeError("intentional test failure")

    engine = SimulationEngine(config(), {"values": []}, {"fail": failing_handler})
    prior_stream_value = engine.random_stream_state("isolated")
    engine.schedule_event(event("fault", EventPhase.SETTLEMENT, event_type="fail"))
    with pytest.raises(SimulationExecutionError, match="intentional test failure"):
        engine.step()
    assert engine.get_state() == {"values": []}
    assert engine.current_time == START
    assert engine.event_log == ()
    assert engine.random_stream_state("isolated") == prior_stream_value
    assert engine.failed_event.event_id == "fault"
    with pytest.raises(RuntimeError, match="halted"):
        engine.step()


def test_named_random_streams_are_independent_of_creation_order_and_checkpointable():
    first = SimulationEngine(config(), {}, {})
    second = SimulationEngine(config(), {}, {})
    a = [first.random_stream("agent-a").next_uint64() for _ in range(2)]
    second.random_stream("agent-b").next_uint64()
    b = [second.random_stream("agent-a").next_uint64() for _ in range(2)]
    assert a == b
    snapshot = first.snapshot()
    resumed = SimulationEngine.restore(snapshot, {})
    assert first.random_stream("agent-a").next_uint64() == resumed.random_stream("agent-a").next_uint64()


def test_failed_or_invalid_state_payloads_cannot_enter_authoritative_simulation_state():
    def invalid_handler(state, item, context):
        return {"amount": 1.25}

    engine = SimulationEngine(config(), {"amount": 1}, {"invalid": invalid_handler})
    engine.schedule_event(event("float", EventPhase.SETTLEMENT, event_type="invalid"))
    with pytest.raises(SimulationExecutionError, match="floating-point"):
        engine.step()
    assert engine.get_state() == {"amount": 1}


def test_event_context_propagates_correlation_and_causation_ids():
    generated = []

    def parent_handler(state, item, context):
        context.schedule_event(event("child", EventPhase.SETTLEMENT, at=item.scheduled_at))
        return state

    engine = SimulationEngine(config(), {"seen": []}, {"parent": parent_handler, "record": recording_handler})
    root = engine.schedule_event(event("root", EventPhase.SYSTEM_STATE, event_type="parent"))
    engine.step()
    child = engine.step()
    generated.append(child)
    assert root.correlation_id == "root"
    assert generated[0].correlation_id == "root"
    assert generated[0].causation_id == "root"


def test_snapshot_json_roundtrip_restores_checkpoint_and_verifies_hash():
    handlers = {"record": recording_handler}
    engine = SimulationEngine(config(), {"seen": []}, handlers)
    engine.schedule_event(event("done", EventPhase.SETTLEMENT))
    engine.schedule_event(event("later", EventPhase.MONITORING_AND_SNAPSHOT, at=START + timedelta(seconds=4)))
    engine.step()
    snapshot_json = engine.snapshot().to_json()
    restored_snapshot = type(engine.snapshot()).from_json(snapshot_json)
    restored = SimulationEngine.restore(restored_snapshot, handlers)
    assert restored.state_sha256 == engine.state_sha256
    assert restored.snapshot().to_json() == snapshot_json
    restored.run_until(START + timedelta(seconds=5))
    assert restored.get_state()["seen"] == ["done", "later"]


def test_snapshot_rejects_tampered_state_payload():
    engine = SimulationEngine(config(), {"balance_minor": 100}, {})
    serialized = engine.snapshot().to_json()
    tampered = json.loads(serialized)
    tampered["state_json"] = '{"balance_minor":99}'
    with pytest.raises(ValueError, match="hash"):
        type(engine.snapshot()).from_json(json.dumps(tampered, sort_keys=True, separators=(",", ":")))
