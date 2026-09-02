from __future__ import annotations

import json
import time

import pytest

from microduck_remote_brain.telemetry_server import (
    DASHBOARD,
    SimulatorCache,
    actions_are_enabled,
    dispatch_control,
    read_autonomy_status,
)


def test_dashboard_rejects_unsuccessful_http_responses() -> None:
    assert "response.ok" in DASHBOARD
    assert "HTTP ${response.status}" in DASHBOARD
    assert "Scene semantics" in DASHBOARD
    assert "Autonomous persona" in DASHBOARD
    assert "Disable all actions" in DASHBOARD
    assert "/api/actions/disable" in DASHBOARD
    assert "/api/actions/enable" in DASHBOARD
    assert "ToF clearance" in DASHBOARD
    assert "Drop memory" in DASHBOARD
    assert "control.disabled=!actionsEnabled" in DASHBOARD
    assert "setInterval(refresh,33)" in DASHBOARD
    assert "TELEMETRY_HZ = 30.0" not in DASHBOARD


def test_simulator_cache_fans_out_one_read(monkeypatch) -> None:
    calls = 0

    def read(_host: str, _port: int) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"sim_time": 1.0}

    monkeypatch.setattr("microduck_remote_brain.telemetry_server.read_state", read)
    cache = SimulatorCache("127.0.0.1", 7801)

    first = cache.get("state", 1.0)
    second = cache.get("state", 1.0)

    assert first is second
    assert calls == 1


def test_missing_autonomy_status_is_stopped(tmp_path) -> None:
    status = read_autonomy_status(tmp_path / "missing.json")

    assert status["state"] == "stopped"


def test_persistent_action_safety_file_controls_enabled_state(tmp_path) -> None:
    path = tmp_path / "actions-disabled"

    assert actions_are_enabled(path)

    path.touch()

    assert not actions_are_enabled(path)


def test_autonomy_status_reports_fresh_action(tmp_path) -> None:
    path = tmp_path / "autonomy.json"
    path.write_text(
        json.dumps(
            {
                "state": "idle",
                "message": "Behavior completed",
                "updated_at": time.time(),
                "actions": ["stop", "sound"],
                "observation": "clear floor",
            }
        ),
        encoding="utf-8",
    )

    status = read_autonomy_status(path)

    assert status["state"] == "idle"
    assert status["actions"] == ["stop", "sound"]
    age_seconds = status["age_seconds"]
    assert isinstance(age_seconds, int | float)
    assert age_seconds < 1.0


def test_autonomy_status_marks_old_worker_state_stale(tmp_path) -> None:
    path = tmp_path / "autonomy.json"
    path.write_text(
        json.dumps({"state": "observing", "message": "old", "updated_at": 1.0}),
        encoding="utf-8",
    )

    status = read_autonomy_status(path)

    assert status["state"] == "stale"


def test_control_dispatches_bounded_movement_and_chained_skill(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeRobot:
        def __init__(self, *, host: str, port: int) -> None:
            calls.append(("created", host, port))

        def __getattr__(self, name: str):
            return lambda *args, **kwargs: calls.append((name, *args, kwargs))

    monkeypatch.setattr("microduck_remote_brain.telemetry_server.RobotdClient", FakeRobot)

    dispatch_control("127.0.0.1", 8765, {"action": "move", "vx": 0.2, "vyaw": -0.5})
    dispatch_control(
        "127.0.0.1",
        8765,
        {"action": "skill", "skill": "roulade", "notify": True},
    )

    assert ("move_twist", 0.2, 0.0, -0.5, {}) in calls
    assert ("skill", "roulade", {"notify": True}) in calls


def test_control_rejects_out_of_range_movement(monkeypatch) -> None:
    class FakeRobot:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def connect(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("microduck_remote_brain.telemetry_server.RobotdClient", FakeRobot)

    with pytest.raises(ValueError, match="outside its allowed range"):
        dispatch_control("127.0.0.1", 8765, {"action": "move", "vx": 0.31})