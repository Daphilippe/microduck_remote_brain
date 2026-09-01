from __future__ import annotations

import json
import time

from microduck_remote_brain.telemetry_server import (
    DASHBOARD,
    SimulatorCache,
    read_autonomy_status,
)


def test_dashboard_rejects_unsuccessful_http_responses() -> None:
    assert "response.ok" in DASHBOARD
    assert "HTTP ${response.status}" in DASHBOARD
    assert "Persona autonome" in DASHBOARD


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


def test_autonomy_status_reports_fresh_action(tmp_path) -> None:
    path = tmp_path / "autonomy.json"
    path.write_text(
        json.dumps(
            {
                "state": "idle",
                "message": "Comportement terminé",
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