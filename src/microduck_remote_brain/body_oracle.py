from __future__ import annotations

import json
import math
import socket
from typing import Any, TypeGuard

from .executor import BodySnapshot, ExecutionError, ExecutionReason


class TcpBodyOracle:
    def __init__(self, host: str, port: int, *, timeout: float = 1.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._socket: socket.socket | None = None
        self._reader: Any = None

    def connect(self) -> None:
        if self._socket is not None:
            raise ExecutionError(ExecutionReason.ORACLE_PROTOCOL, "BodyOracle is already connected")
        connection = socket.create_connection((self._host, self._port), self._timeout)
        try:
            connection.settimeout(self._timeout)
            self._reader = connection.makefile("r", encoding="utf-8", newline="\n")
            self._socket = connection
            self._send({"op": "hello", "protocol": 1, "joints": 15})
            response = self._receive()
            if response.get("protocol") != 1 or "error" in response:
                raise ExecutionError(
                    ExecutionReason.ORACLE_PROTOCOL, "BodyOracle protocol 1 hello was not accepted"
                )
        except BaseException:
            if self._reader is not None:
                self._reader.close()
                self._reader = None
            connection.close()
            self._socket = None
            raise

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def read(self) -> BodySnapshot:
        self._send({"op": "read"})
        response = self._receive()
        trunk = response.get("trunk")
        if not isinstance(trunk, list) or len(trunk) != 3 or "error" in response:
            raise ExecutionError(
                ExecutionReason.ORACLE_PROTOCOL, "invalid BodyOracle read response"
            )
        trunk_x = trunk[0]
        trunk_y = trunk[1]
        sim_time = response.get("sim_time")
        if (
            not _finite_number(trunk_x)
            or not _finite_number(trunk_y)
            or not _finite_number(sim_time)
        ):
            raise ExecutionError(
                ExecutionReason.ORACLE_PROTOCOL,
                "BodyOracle trunk x/y and sim_time must be finite numbers",
            )
        return BodySnapshot(float(trunk_x), float(trunk_y), float(sim_time))

    def _send(self, message: dict[str, Any]) -> None:
        if self._socket is None:
            raise ExecutionError(ExecutionReason.ORACLE_PROTOCOL, "BodyOracle is not connected")
        payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        self._socket.sendall(payload)

    def _receive(self) -> dict[str, Any]:
        if self._reader is None:
            raise ExecutionError(ExecutionReason.ORACLE_PROTOCOL, "BodyOracle is not connected")
        try:
            line = self._reader.readline()
        except (OSError, TimeoutError, UnicodeError) as error:
            raise ExecutionError(ExecutionReason.ORACLE_PROTOCOL, str(error)) from error
        if not line:
            raise ExecutionError(
                ExecutionReason.ORACLE_PROTOCOL, "BodyOracle closed the connection"
            )
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExecutionError(
                ExecutionReason.ORACLE_PROTOCOL, "invalid BodyOracle JSON"
            ) from error
        if not isinstance(message, dict):
            raise ExecutionError(
                ExecutionReason.ORACLE_PROTOCOL, "BodyOracle message must be an object"
            )
        return message


def _finite_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)