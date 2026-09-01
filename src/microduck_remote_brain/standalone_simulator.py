from __future__ import annotations

import argparse
import base64
import json
import math
import socketserver
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

# A valid 1x1 JPEG keeps the protocol simulator dependency-free. MuJoCo provides real frames.
CAMERA_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////"
    "////////////////////////////////////////2wBDAf//////////////////////////////"
    "////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB"
    "/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAA"
    "AAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAA"
    "AP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAA"
    "AAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oA"
    "DAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EF//xAAUEQEAAAAAAAAA"
    "AAAAAAAAAAAA/9oACAECAQE/EF//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EF//2Q=="
)


@dataclass
class SimulatedBody:
    lock: threading.Lock = field(default_factory=threading.Lock)
    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    sim_time: float = 0.0
    updated_at: float = field(default_factory=time.monotonic)

    def update(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated_at
        self.x += self.vx * elapsed
        self.y += self.vy * elapsed
        self.yaw += self.vyaw * elapsed
        self.sim_time += elapsed
        self.updated_at = now

    def move(self, vx: float, vy: float, vyaw: float) -> None:
        if not all(math.isfinite(value) for value in (vx, vy, vyaw)):
            raise ValueError("movement values must be finite")
        with self.lock:
            self.update()
            self.vx, self.vy, self.vyaw = vx, vy, vyaw

    def stop(self) -> None:
        self.move(0.0, 0.0, 0.0)

    def state(self) -> dict[str, Any]:
        with self.lock:
            self.update()
            return {
                "trunk": [self.x, self.y, 0.22],
                "trunk_z": 0.22,
                "sim_time": self.sim_time,
                "base_velocity": [self.vx, self.vy, self.vyaw],
                "positions": [0.0] * 15,
                "velocities": [0.0] * 15,
                "currents": [0.0] * 15,
                "volts": 7.4,
                "temps_c": [32.0] * 15,
                "imu": {
                    "gravity": [0.0, 0.0, -9.81],
                    "gyro": [0.0, 0.0, self.vyaw],
                    "quat": [1.0, 0.0, 0.0, 0.0],
                },
            }


class RobotHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        body = self.server.body  # type: ignore[attr-defined]
        while line := self.rfile.readline():
            try:
                message = json.loads(line)
                method = message.get("method")
                params = message.get("params", {})
                if method == "robot.move":
                    body.move(float(params["vx"]), float(params["vy"]), float(params["vyaw"]))
                    self._state(body)
                elif method == "robot.stop":
                    body.stop()
                    self._accepted(message)
                    self._state(body)
                elif "id" in message:
                    self._accepted(message)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                self._write({"jsonrpc": "2.0", "error": {"message": str(error)}})

    def _accepted(self, message: dict[str, Any]) -> None:
        self._write(
            {"jsonrpc": "2.0", "id": message["id"], "result": {"accepted": True}}
        )

    def _state(self, body: SimulatedBody) -> None:
        state = body.state()
        self._write(
            {
                "jsonrpc": "2.0",
                "method": "robot.state",
                "params": {"move": {"applied": state["base_velocity"]}},
            }
        )

    def _write(self, value: object) -> None:
        self.wfile.write(json.dumps(value, allow_nan=False).encode() + b"\n")
        self.wfile.flush()


class OracleHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        body = self.server.body  # type: ignore[attr-defined]
        while line := self.rfile.readline():
            try:
                message = json.loads(line)
                operation = message.get("op")
                if operation == "hello":
                    answer: object = {"protocol": 1}
                elif operation in {"read", "slow"}:
                    answer = body.state()
                elif operation == "tof":
                    answer = {"distance_mm": [1200.0] * 64}
                elif operation == "camera":
                    answer = {"jpeg_base64": base64.b64encode(CAMERA_JPEG).decode("ascii")}
                else:
                    answer = {"error": f"unsupported operation: {operation}"}
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                answer = {"error": str(error)}
            self.wfile.write(json.dumps(answer, allow_nan=False).encode() + b"\n")
            self.wfile.flush()


class SimulationServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[socketserver.StreamRequestHandler],
        body: SimulatedBody,
    ) -> None:
        self.body = body
        super().__init__(address, handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone MicroDuck protocol simulator")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--robot-port", type=int, default=8765)
    parser.add_argument("--simulator-port", type=int, default=7801)
    args = parser.parse_args(argv)
    body = SimulatedBody()
    with (
        SimulationServer((args.listen_host, args.robot_port), RobotHandler, body) as robot,
        SimulationServer((args.listen_host, args.simulator_port), OracleHandler, body) as oracle,
    ):
        robot_thread = threading.Thread(target=robot.serve_forever, daemon=True)
        robot_thread.start()
        print(
            f"standalone simulator listening on {args.listen_host}:"
            f"{args.robot_port}/{args.simulator_port}",
            flush=True,
        )
        try:
            oracle.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            robot.shutdown()
            robot_thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())