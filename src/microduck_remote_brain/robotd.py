from __future__ import annotations

import json
import math
import socket
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, TypeGuard

from .executor import ExecutionError, ExecutionReason, RobotState

MAX_MESSAGE_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class RobotCapabilities:
    mode: str
    skills: frozenset[str]

    def to_dict(self) -> dict[str, object]:
        return {"mode": self.mode, "skills": sorted(self.skills)}


class RobotdClient:
    def __init__(
        self,
        socket_path: str | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        if (socket_path is None) == (host is None):
            raise ValueError("configure exactly one robotd transport")
        if host is not None and port is None:
            raise ValueError("TCP robotd transport requires a port")
        self._socket_path = socket_path
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None
        self._reader: Any = None
        self._request_id = 0
        self._revision = 0
        self._states: deque[RobotState] = deque()

    def connect(self) -> None:
        if self._socket is not None:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "robotd client is already connected"
            )
        if self._host is not None:
            connection = socket.create_connection((self._host, self._port), timeout=5.0)
        else:
            unix_family = getattr(socket, "AF_UNIX", None)
            if unix_family is None:
                raise ExecutionError(
                    ExecutionReason.CONNECTION_FAILED,
                    "this platform does not support Unix domain sockets",
                )
            connection = socket.socket(unix_family, socket.SOCK_STREAM)
        try:
            if self._socket_path is not None:
                connection.connect(self._socket_path)
            self._reader = connection.makefile("r", encoding="utf-8", newline="\n")
        except BaseException:
            connection.close()
            raise
        self._socket = connection

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def subscribe(self, hz: int) -> dict[str, Any]:
        result = self._request_result("robot.subscribe", {"hz": hz})
        if result.get("accepted") is not True:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL,
                "robotd did not accept robot.subscribe",
            )
        return result

    def capabilities(self, hz: int = 1) -> RobotCapabilities:
        subscribed = self.subscribe(hz)
        mode_result = self._request_result("robot.mode", {})
        mode = mode_result.get("mode")
        if mode not in {"walk", "roller"}:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "robotd returned an invalid drive mode"
            )
        skill_fields = {
            "sit_toggle": "sitstand",
            "ground_pick": "ground_pick",
            "kick_left": "kick_left",
            "kick_right": "kick_right",
            "roulade": "roulade",
        }
        skills = frozenset(
            skill
            for skill, field in skill_fields.items()
            if isinstance(subscribed.get(field), str)
        )
        return RobotCapabilities(mode, skills)

    def move(self, linear_velocity: float, angular_velocity: float) -> None:
        self.move_twist(linear_velocity, 0.0, angular_velocity)

    def move_twist(self, vx: float, vy: float, vyaw: float) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "method": "robot.move",
                "params": {"vx": vx, "vy": vy, "vyaw": vyaw},
            }
        )

    def stop(self) -> None:
        self._request("robot.stop", {})
        self._states.clear()

    def sound(self, tag: str, hold: bool | None = None, *, notify: bool = False) -> None:
        params: dict[str, Any] = {"tag": tag}
        if hold is not None:
            params["hold"] = hold
        if notify:
            self._notify("robot.sound", params)
        else:
            self._request("robot.sound", params)

    def toggle_enable(self) -> None:
        self._request("robot.enable", {"on": False, "toggle": True})

    def init(self) -> None:
        self._request("robot.init", {})

    def relax(self) -> None:
        self._request("robot.relax", {})

    def skill(self, name: str, *, notify: bool = False) -> None:
        params = {"skill": name}
        if notify:
            self._notify("robot.do", params)
        else:
            self._request("robot.do", params)

    def head(self, neck_pitch: float, head_pitch: float, head_yaw: float, head_roll: float) -> None:
        self._notify(
            "robot.head",
            {
                "neck_pitch": neck_pitch,
                "head_pitch": head_pitch,
                "head_yaw": head_yaw,
                "head_roll": head_roll,
            },
        )

    def look(self, x: float, y: float, z: float, neck_pitch: float = 0.0) -> None:
        self._request_result(
            "robot.look", {"x": x, "y": y, "z": z, "neck_pitch": neck_pitch}
        )

    def pose(self, z: float, roll: float, pitch: float, *, active: bool) -> None:
        self._notify(
            "robot.pose", {"z": z, "roll": roll, "pitch": pitch, "active": active}
        )

    def mouth(self, opening: float) -> None:
        self._notify("robot.mouth", {"open": opening})

    def theremin(self, active: bool) -> None:
        self._request("robot.theremin", {"active": active})

    def chorale(self, active: bool, piece: int | None = None) -> None:
        params: dict[str, Any] = {"active": active}
        if piece is not None:
            params["piece"] = piece
        self._request("robot.chorale", params)

    def shutdown(self) -> None:
        self._request("robot.shutdown", {})

    def set_mode(self, mode: str) -> None:
        self._request("robot.setMode", {"mode": mode})

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def next_state(self, after_revision: int, timeout: float) -> RobotState:
        deadline = time.monotonic() + timeout
        while True:
            while self._states:
                state = self._states.popleft()
                if state.revision > after_revision:
                    return state
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for fresh robot.state")
            self._read_message(remaining)

    def _request(self, method: str, params: dict[str, Any]) -> None:
        result = self._request_result(method, params)
        if result.get("accepted") is not True:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL,
                f"robotd did not accept {method}",
            )

    def _request_result(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = self._read_message(None)
            if message.get("id") != request_id:
                if "id" in message:
                    raise ExecutionError(
                        ExecutionReason.ROBOT_PROTOCOL,
                        f"unexpected robotd response id {message.get('id')!r}",
                    )
                continue
            if "error" in message:
                raise ExecutionError(
                    ExecutionReason.ROBOT_PROTOCOL,
                    f"robotd rejected {method}: {message['error']!r}",
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise ExecutionError(
                    ExecutionReason.ROBOT_PROTOCOL,
                    f"robotd returned an invalid result for {method}",
                )
            return result

    def _send(self, message: dict[str, Any]) -> None:
        if self._socket is None:
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "robotd client is not connected")
        payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        self._socket.sendall(payload)

    def _read_message(self, timeout: float | None) -> dict[str, Any]:
        if self._socket is None or self._reader is None:
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "robotd client is not connected")
        self._socket.settimeout(timeout)
        try:
            line = self._reader.readline(MAX_MESSAGE_BYTES + 1)
        except TimeoutError:
            raise
        except (OSError, UnicodeError) as error:
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, str(error)) from error
        if not line:
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "robotd closed the connection")
        if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES or not line.endswith("\n"):
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "robotd message exceeds the framing limit"
            )
        try:
            message = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as error:
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "invalid robotd JSON") from error
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "invalid robotd JSON-RPC envelope")
        if message.get("method") == "robot.state":
            self._states.append(self._parse_state(message.get("params")))
        return message

    def _parse_state(self, params: Any) -> RobotState:
        if not isinstance(params, dict):
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "robot.state params must be an object"
            )
        movement = params.get("move")
        if not isinstance(movement, dict):
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "robot.state move must be an object"
            )
        applied = movement.get("applied")
        if not isinstance(applied, list) or len(applied) != 3:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL,
                "robot.state move.applied must contain vx, vy, and vyaw",
            )
        linear = applied[0]
        lateral = applied[1]
        angular = applied[2]
        if not all(_finite_number(value) for value in (linear, lateral, angular)):
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL,
                "robot.state applied velocity must contain finite values",
            )
        odom_x: float | None = None
        odom_y: float | None = None
        odom_yaw: float | None = None
        timestamp: float | None = None
        odom = params.get("odom")
        if odom is not None:
            if not isinstance(odom, dict):
                raise ExecutionError(
                    ExecutionReason.ROBOT_PROTOCOL, "robot.state odom must be an object"
                )
            position = odom.get("position")
            yaw = odom.get("yaw")
            if (
                not isinstance(position, list)
                or len(position) < 2
                or not _finite_number(position[0])
                or not _finite_number(position[1])
                or not _finite_number(yaw)
            ):
                raise ExecutionError(
                    ExecutionReason.ROBOT_PROTOCOL,
                    "robot.state odom must contain finite x, y, and yaw values",
                )
            odom_x = float(position[0])
            odom_y = float(position[1])
            odom_yaw = float(yaw)
        state_time = params.get("t")
        if state_time is not None:
            if not _finite_number(state_time) or float(state_time) < 0:
                raise ExecutionError(
                    ExecutionReason.ROBOT_PROTOCOL,
                    "robot.state timestamp must be finite and nonnegative",
                )
            timestamp = float(state_time)
        gravity_values = _optional_vector(
            params.get("safety"), "gravity", 3, "robot.state safety"
        )
        imu = params.get("imu")
        gyroscope_values = _optional_vector(imu, "gyro", 3, "robot.state imu")
        quaternion_values = _optional_vector(imu, "quat", 4, "robot.state imu")
        gravity = (
            None
            if gravity_values is None
            else (gravity_values[0], gravity_values[1], gravity_values[2])
        )
        gyroscope = (
            None
            if gyroscope_values is None
            else (gyroscope_values[0], gyroscope_values[1], gyroscope_values[2])
        )
        quaternion = (
            None
            if quaternion_values is None
            else (
                quaternion_values[0],
                quaternion_values[1],
                quaternion_values[2],
                quaternion_values[3],
            )
        )
        joints = _optional_number_list(params.get("joints"), "robot.state joints")
        targets = _optional_number_list(params.get("targets"), "robot.state targets")
        self._revision += 1
        return RobotState(
            self._revision,
            float(linear),
            float(angular),
            odom_x,
            odom_y,
            odom_yaw,
            timestamp,
            float(lateral),
            gravity,
            gyroscope,
            quaternion,
            joints,
            targets,
        )


def _finite_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _optional_vector(
    container: Any, key: str, length: int, description: str
) -> tuple[float, ...] | None:
    if container is None:
        return None
    if not isinstance(container, dict):
        raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, f"{description} must be an object")
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != length or not all(
        _finite_number(item) for item in value
    ):
        raise ExecutionError(
            ExecutionReason.ROBOT_PROTOCOL,
            f"{description}.{key} must contain {length} finite values",
        )
    return tuple(float(item) for item in value)


def _optional_number_list(value: Any, description: str) -> tuple[float, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(_finite_number(item) for item in value):
        raise ExecutionError(
            ExecutionReason.ROBOT_PROTOCOL, f"{description} must contain finite values"
        )
    return tuple(float(item) for item in value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")