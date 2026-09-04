from __future__ import annotations

import base64
import io
import json

import pytest

from microduck_remote_brain.perception import (
    DepthObservation,
    DropHazardMemory,
    SimulatorPerception,
)


class FakeConnection:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.stream = io.StringIO("".join(json.dumps(item) + "\n" for item in responses))
        self.sent: list[dict[str, object]] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def makefile(self, *_args: object, **_kwargs: object) -> FakeConnection:
        return self

    def write(self, payload: str) -> int:
        self.sent.append(json.loads(payload))
        return len(payload)

    def flush(self) -> None:
        pass

    def readline(self, size: int = -1) -> str:
        return self.stream.readline(size)


def test_simulator_perception_reads_embedded_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    jpeg = b"jpeg-frame"
    connection = FakeConnection(
        [{"protocol": 1}, {"jpeg_base64": base64.b64encode(jpeg).decode("ascii")}]
    )
    monkeypatch.setattr(
        "microduck_remote_brain.perception.socket.create_connection",
        lambda *_args: connection,
    )

    result = SimulatorPerception("127.0.0.1", 7801).capture()

    assert result == jpeg
    assert connection.sent == [
        {"op": "hello", "protocol": 1, "joints": 15},
        {"op": "camera"},
    ]


def test_simulator_perception_rejects_invalid_camera_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection([{"protocol": 1}, {"jpeg_base64": "not base64"}])
    monkeypatch.setattr(
        "microduck_remote_brain.perception.socket.create_connection",
        lambda *_args: connection,
    )

    with pytest.raises(RuntimeError, match="base64"):
        SimulatorPerception("127.0.0.1", 7801).capture()


def test_simulator_perception_summarizes_tof_clearance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distances = []
    for _row in range(8):
        distances.extend([900, 900, 900, 240, 240, 500, 500, 500])
    connection = FakeConnection([{"protocol": 1}, {"distance_mm": distances}])
    monkeypatch.setattr(
        "microduck_remote_brain.perception.socket.create_connection",
        lambda *_args: connection,
    )

    depth = SimulatorPerception("127.0.0.1", 7801).capture_depth()

    assert depth.left_clearance_mm == 900
    assert depth.center_clearance_mm == 240
    assert depth.right_clearance_mm == 500
    assert len(depth.distance_mm) == 64
    assert connection.sent[-1] == {"op": "tof"}


def test_camera_aligned_depth_overlaps_tof_columns_for_sensor_baseline() -> None:
    distances = [900.0] * 64
    distances[2] = 180.0
    depth = DepthObservation(tuple(distances), 180.0, 900.0, 900.0)

    assert depth.center_clearance_mm == 900.0
    assert depth.camera_aligned_clearance_mm("center") == 180.0
    assert depth.to_dict()["camera_to_tof_lateral_mm"] == 22.5


def test_tof_detects_and_remembers_lower_field_drop_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distances = [450] * 64
    for row in (6, 7):
        for column in (3, 4):
            distances[row * 8 + column] = 1200
    connection = FakeConnection([{"protocol": 1}, {"distance_mm": distances}])
    monkeypatch.setattr(
        "microduck_remote_brain.perception.socket.create_connection",
        lambda *_args: connection,
    )
    memory = DropHazardMemory(clear_frames_required=3)

    detected = memory.update(SimulatorPerception("127.0.0.1", 7801).capture_depth())
    clear = type(detected)((), 450, 450, 450)

    assert detected.drop_hazard_sectors == ("center",)
    assert detected.drop_hazard_remembered is True
    assert memory.update(clear).drop_hazard_remembered is True
    assert memory.update(clear).drop_hazard_remembered is True
    assert memory.update(clear).drop_hazard_remembered is False