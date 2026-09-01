from __future__ import annotations

import base64
import io
import json

import pytest

from microduck_remote_brain.perception import SimulatorPerception


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