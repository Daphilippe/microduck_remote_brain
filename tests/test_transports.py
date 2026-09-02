from __future__ import annotations

import io
import json
import math
from typing import Any

import pytest

from microduck_remote_brain.body_oracle import TcpBodyOracle
from microduck_remote_brain.executor import ExecutionError, ExecutionReason
from microduck_remote_brain.robotd import RobotdClient


def line(value: dict[str, Any]) -> str:
    return json.dumps(value) + "\n"


class FakeSocket:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.reader = io.StringIO("".join(line(response) for response in responses))
        self.sent: list[dict[str, Any]] = []
        self.connected_to: object = None
        self.timeout: float | None = None
        self.closed = False

    def connect(self, address: object) -> None:
        self.connected_to = address

    def makefile(self, *_args: object, **_kwargs: object) -> io.StringIO:
        return self.reader

    def sendall(self, payload: bytes) -> None:
        self.sent.append(json.loads(payload))

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def close(self) -> None:
        self.closed = True


def test_robotd_frames_and_interleaved_state(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSocket(
        {"jsonrpc": "2.0", "id": 1, "result": {"accepted": True}},
        {
            "jsonrpc": "2.0",
            "method": "robot.state",
            "params": {"move": {"requested": [0.2, 0.0, 0.0], "applied": [0.2, 0.0, 0.0]}},
        },
        {"jsonrpc": "2.0", "id": 2, "result": {"accepted": True}},
    )
    monkeypatch.setattr("microduck_remote_brain.robotd.socket.AF_UNIX", 1, raising=False)
    monkeypatch.setattr("microduck_remote_brain.robotd.socket.socket", lambda *args: connection)
    client = RobotdClient("/run/robotd.sock")

    client.connect()
    client.subscribe(10)
    client.move(0.2, 0.1)
    state = client.next_state(0, 1.0)
    client.stop()

    assert connection.connected_to == "/run/robotd.sock"
    assert connection.sent == [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "robot.subscribe",
            "params": {"hz": 10.0},
        },
        {
            "jsonrpc": "2.0",
            "method": "robot.move",
            "params": {"vx": 0.2, "vy": 0.0, "vyaw": 0.1},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "robot.stop", "params": {}},
    ]
    assert (state.revision, state.linear_velocity, state.angular_velocity) == (1, 0.2, 0.0)


def test_robotd_rejects_unaccepted_response(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSocket({"jsonrpc": "2.0", "id": 1, "result": {"accepted": False}})
    monkeypatch.setattr("microduck_remote_brain.robotd.socket.AF_UNIX", 1, raising=False)
    monkeypatch.setattr("microduck_remote_brain.robotd.socket.socket", lambda *args: connection)
    client = RobotdClient("/run/robotd.sock")
    client.connect()

    with pytest.raises(ExecutionError) as caught:
        client.subscribe(10)

    assert caught.value.reason is ExecutionReason.ROBOT_PROTOCOL


def test_robotd_rejects_non_standard_json_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSocket()
    connection.reader = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"result":{"accepted":NaN}}\n'
    )
    monkeypatch.setattr("microduck_remote_brain.robotd.socket.AF_UNIX", 1, raising=False)
    monkeypatch.setattr("microduck_remote_brain.robotd.socket.socket", lambda *args: connection)
    client = RobotdClient("/run/robotd.sock")
    client.connect()

    with pytest.raises(ExecutionError, match="invalid robotd JSON") as caught:
        client.subscribe(10)

    assert caught.value.reason is ExecutionReason.ROBOT_PROTOCOL


def test_robotd_tcp_transport_and_sound(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSocket(
        {"jsonrpc": "2.0", "id": 1, "result": {"accepted": True}},
    )
    monkeypatch.setattr(
        "microduck_remote_brain.robotd.socket.create_connection",
        lambda *args, **kwargs: connection,
    )
    client = RobotdClient(host="127.0.0.1", port=8765)

    client.connect()
    client.sound("chirp")

    assert connection.sent == [
        {"jsonrpc": "2.0", "id": 1, "method": "robot.sound", "params": {"tag": "chirp"}}
    ]


def test_robotd_reports_mode_and_loaded_skill_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSocket(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "accepted": True,
                "sitstand": "sitstand.onnx",
                "ground_pick": "roller_crouch.onnx",
                "kick_left": None,
                "kick_right": None,
                "roulade": "roulade.onnx",
            },
        },
        {"jsonrpc": "2.0", "id": 2, "result": {"mode": "roller"}},
    )
    monkeypatch.setattr(
        "microduck_remote_brain.robotd.socket.create_connection",
        lambda *args, **kwargs: connection,
    )
    client = RobotdClient(host="127.0.0.1", port=8765)

    client.connect()
    capabilities = client.capabilities()

    assert capabilities.mode == "roller"
    assert capabilities.skills == frozenset({"sit_toggle", "ground_pick", "roulade"})
    assert [message["method"] for message in connection.sent] == [
        "robot.subscribe",
        "robot.mode",
    ]


def test_robotd_look_accepts_gaze_result_without_generic_accepted_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSocket(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "head": {
                    "neck_pitch": 0.0,
                    "head_pitch": 0.1,
                    "head_yaw": 0.2,
                    "head_roll": 0.0,
                },
                "clamped": False,
            },
        },
    )
    monkeypatch.setattr(
        "microduck_remote_brain.robotd.socket.create_connection",
        lambda *args, **kwargs: connection,
    )
    client = RobotdClient(host="127.0.0.1", port=8765)

    client.connect()
    client.look(0.5, 0.3, 0.1)

    assert connection.sent[0]["method"] == "robot.look"


def test_body_oracle_protocol_1_hello_and_read(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSocket(
        {"protocol": 1},
        {
            "trunk": [1.25, -0.5, 0.116],
            "sim_time": 4.0,
            "imu": {"quat": [0.7071068, 0.0, 0.0, 0.7071068]},
        },
    )
    monkeypatch.setattr(
        "microduck_remote_brain.body_oracle.socket.create_connection",
        lambda *args: connection,
    )
    oracle = TcpBodyOracle("127.0.0.1", 9000)

    oracle.connect()
    snapshot = oracle.read()

    assert connection.sent == [
        {"op": "hello", "protocol": 1, "joints": 15},
        {"op": "read"},
    ]
    assert (snapshot.trunk_x, snapshot.trunk_y, snapshot.sim_time) == (1.25, -0.5, 4.0)
    assert snapshot.yaw == pytest.approx(math.pi / 2)