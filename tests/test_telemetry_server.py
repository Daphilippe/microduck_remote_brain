from __future__ import annotations

from microduck_remote_brain.telemetry_server import DASHBOARD, SimulatorCache


def test_dashboard_rejects_unsuccessful_http_responses() -> None:
    assert "response.ok" in DASHBOARD
    assert "HTTP ${response.status}" in DASHBOARD


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