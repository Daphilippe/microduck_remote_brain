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
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFilter


def _scaled(points: Sequence[tuple[int, int]], scale: int) -> list[tuple[int, int]]:
    return [(x * scale, y * scale) for x, y in points]


def _box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    scale: int,
    **kwargs: Any,
) -> None:
    draw.rectangle(tuple(value * scale for value in xy), **kwargs)


def _render_camera_jpeg() -> bytes:
    scale = 2
    image = Image.new("RGB", (640 * scale, 480 * scale), "#b8c5ca")
    draw = ImageDraw.Draw(image)

    draw.polygon(_scaled([(0, 0), (640, 0), (640, 278), (0, 278)], scale), fill="#c8c1b5")
    draw.polygon(_scaled([(0, 0), (640, 0), (602, 48), (42, 48)], scale), fill="#e4dfd6")
    draw.polygon(_scaled([(0, 0), (42, 48), (42, 279), (0, 340)], scale), fill="#aaa296")
    draw.polygon(_scaled([(640, 0), (602, 48), (602, 279), (640, 340)], scale), fill="#978f85")

    _box(draw, (57, 54, 391, 225), scale, fill="#343b3f")
    _box(draw, (64, 61, 384, 218), scale, fill="#9ab0b7")
    for top, bottom, color in (
        (61, 100, "#9fb9c2"),
        (100, 147, "#d3b9a0"),
        (147, 218, "#56616a"),
    ):
        _box(draw, (64, top, 384, bottom), scale, fill=color)
    skyline = [
        (64, 132, 96, 218, "#59646a"),
        (92, 111, 131, 218, "#3f4d55"),
        (126, 142, 174, 218, "#687279"),
        (169, 98, 213, 218, "#46545c"),
        (208, 126, 248, 218, "#606c73"),
        (243, 116, 292, 218, "#394851"),
        (287, 145, 337, 218, "#5a666e"),
        (332, 121, 384, 218, "#445159"),
    ]
    for left, top, right, bottom, color in skyline:
        _box(draw, (left, top, right, bottom), scale, fill=color)
        for window_y in range(top + 10, bottom - 5, 16):
            for window_x in range(left + 7, right - 4, 12):
                color = "#e6c57c" if (window_x + window_y) % 3 else "#829096"
                _box(draw, (window_x, window_y, window_x + 4, window_y + 6), scale, fill=color)
    draw.ellipse(tuple(value * scale for value in (316, 76, 330, 90)), fill="#f2d6a1")
    for x in (167, 274):
        _box(draw, (x, 58, x + 7, 220), scale, fill="#30383c")
    _box(draw, (61, 142, 387, 149), scale, fill="#30383c")
    _box(draw, (55, 218, 394, 229), scale, fill="#71665a")

    floor = [(0, 278), (640, 278), (640, 480), (0, 480)]
    draw.polygon(_scaled(floor, scale), fill="#a8754e")
    vanishing_x, horizon = 322, 270
    for x in range(-80, 741, 44):
        draw.line(_scaled([(vanishing_x, horizon), (x, 480)], scale), fill="#765039", width=scale)
    for y in (291, 315, 346, 387, 438):
        draw.line(_scaled([(0, y), (640, y)], scale), fill="#7f573c", width=scale)
    for index, y in enumerate(range(285, 470, 18)):
        draw.line(_scaled([(0, y), (640, y)], scale), fill="#b98459", width=scale)
        if index % 2 == 0:
            draw.line(_scaled([(150, y), (156, y)], scale), fill="#6f4933", width=scale)

    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        tuple(value * scale for value in (60, 337, 492, 472)), fill=(28, 22, 19, 95)
    )
    shadow_draw.ellipse(
        tuple(value * scale for value in (444, 265, 625, 350)), fill=(28, 22, 19, 85)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(11 * scale))
    image = Image.alpha_composite(image.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(image)

    draw.polygon(_scaled([(85, 347), (422, 330), (512, 420), (122, 456)], scale), fill="#405b5b")
    draw.polygon(_scaled([(101, 354), (408, 340), (480, 413), (133, 441)], scale), fill="#c5a76d")
    for offset in (0, 18, 36):
        draw.line(
            _scaled([(118 + offset, 360), (168 + offset, 433)], scale),
            fill="#9a8357",
            width=scale,
        )

    draw.polygon(_scaled([(38, 243), (242, 236), (271, 355), (52, 379)], scale), fill="#54483f")
    draw.polygon(_scaled([(48, 230), (231, 225), (247, 309), (54, 322)], scale), fill="#80766e")
    draw.polygon(_scaled([(54, 301), (247, 291), (273, 347), (55, 365)], scale), fill="#6d625a")
    draw.polygon(_scaled([(55, 303), (147, 298), (151, 342), (59, 351)], scale), fill="#988d82")
    draw.polygon(_scaled([(151, 298), (242, 293), (260, 336), (154, 343)], scale), fill="#8d8278")
    draw.polygon(_scaled([(43, 250), (68, 247), (69, 346), (49, 350)], scale), fill="#61564f")
    draw.polygon(_scaled([(225, 240), (248, 247), (263, 337), (241, 331)], scale), fill="#5d524b")
    draw.polygon(_scaled([(73, 265), (117, 262), (126, 300), (80, 303)], scale), fill="#b88461")
    draw.polygon(_scaled([(181, 257), (222, 255), (233, 294), (189, 297)], scale), fill="#485e61")
    for x in (68, 237):
        _box(draw, (x, 346, x + 9, 382), scale, fill="#3a312c")

    draw.polygon(_scaled([(202, 340), (383, 330), (439, 379), (239, 394)], scale), fill="#4d3b30")
    draw.polygon(_scaled([(212, 327), (372, 321), (413, 360), (238, 371)], scale), fill="#9f744e")
    draw.polygon(_scaled([(238, 371), (413, 360), (413, 372), (239, 385)], scale), fill="#765138")
    for x, y, radius, color in (
        (293, 337, 11, "#d7d2c2"),
        (328, 337, 7, "#59736a"),
        (353, 334, 5, "#c98658"),
    ):
        bounds = (x - radius, y - radius // 2, x + radius, y + radius // 2)
        draw.ellipse(tuple(value * scale for value in bounds), fill=color)
    draw.line(_scaled([(292, 330), (296, 317)], scale), fill="#574238", width=2 * scale)

    _box(draw, (448, 105, 591, 258), scale, fill="#4c4038")
    for shelf_y in (146, 190, 232):
        _box(draw, (452, shelf_y, 587, shelf_y + 6), scale, fill="#2f2925")
    book_colors = ("#b26750", "#4f7371", "#c1a15e", "#7e6261", "#d3c4a7")
    for shelf, base_y in enumerate((145, 189, 231)):
        for index in range(7):
            left = 458 + index * 17
            height = 21 + (index * 7 + shelf * 5) % 18
            _box(
                draw,
                (left, base_y - height, left + 10 + index % 3, base_y),
                scale,
                fill=book_colors[(index + shelf) % len(book_colors)],
            )

    draw.polygon(_scaled([(443, 265), (595, 266), (610, 326), (437, 326)], scale), fill="#67574b")
    _box(draw, (460, 189, 579, 275), scale, fill="#292e2f")
    _box(draw, (467, 196, 572, 264), scale, fill="#17262b")
    draw.polygon(_scaled([(469, 198), (570, 198), (570, 232), (469, 252)], scale), fill="#314950")
    _box(draw, (516, 275, 525, 288), scale, fill="#302a26")

    _box(draw, (604, 161, 611, 295), scale, fill="#34302d")
    draw.polygon(_scaled([(574, 155), (626, 155), (616, 198), (584, 198)], scale), fill="#d2b778")
    draw.ellipse(tuple(value * scale for value in (578, 286, 625, 299)), fill="#4b4037")

    _box(draw, (407, 230, 416, 301), scale, fill="#75543a")
    draw.ellipse(tuple(value * scale for value in (386, 287, 440, 312)), fill="#7a5135")
    for points in (
        [(410, 252), (385, 235), (391, 217), (414, 245)],
        [(413, 256), (433, 232), (430, 214), (410, 247)],
        [(411, 269), (379, 264), (370, 247), (408, 258)],
        [(414, 271), (443, 259), (450, 242), (416, 259)],
    ):
        draw.polygon(_scaled(points, scale), fill="#48674e")

    draw.ellipse(tuple(value * scale for value in (345, 153, 366, 178)), fill="#8b654f")
    draw.polygon(_scaled([(349, 175), (363, 175), (373, 229), (339, 229)], scale), fill="#3f595c")
    draw.polygon(_scaled([(342, 226), (354, 226), (350, 279), (338, 279)], scale), fill="#4b4847")
    draw.polygon(_scaled([(358, 226), (369, 226), (378, 276), (366, 278)], scale), fill="#454241")
    draw.line(_scaled([(345, 183), (329, 222)], scale), fill="#805e4c", width=6 * scale)
    draw.line(_scaled([(367, 184), (382, 216)], scale), fill="#805e4c", width=6 * scale)
    draw.ellipse(tuple(value * scale for value in (343, 151, 369, 165)), fill="#3b302b")

    _box(draw, (15, 89, 35, 272), scale, fill="#ddd4c5")
    draw.polygon(_scaled([(7, 84), (43, 84), (35, 280), (15, 280)], scale), fill="#d8cec0")
    for y in range(102, 260, 32):
        draw.line(_scaled([(13, y), (38, y - 2)], scale), fill="#aaa092", width=scale)

    light = Image.new("RGBA", image.size, (0, 0, 0, 0))
    light_draw = ImageDraw.Draw(light)
    light_draw.polygon(
        _scaled([(62, 218), (388, 218), (551, 480), (169, 480)], scale),
        fill=(255, 220, 161, 28),
    )
    image = Image.alpha_composite(image.convert("RGBA"), light)
    image = image.resize((640, 480), Image.Resampling.LANCZOS).convert("RGB")
    with BytesIO() as output:
        image.save(output, format="JPEG", quality=92, optimize=True)
        return output.getvalue()


CAMERA_JPEG = _render_camera_jpeg()


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
        yaw = body.yaw
        self._write(
            {
                "jsonrpc": "2.0",
                "method": "robot.state",
                "params": {
                    "t": state["sim_time"],
                    "move": {"applied": state["base_velocity"]},
                    "safety": {"gravity": [0.0, 0.0, -1.0]},
                    "imu": {
                        "gyro": state["imu"]["gyro"],
                        "quat": [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)],
                    },
                    "joints": state["positions"],
                    "targets": state["positions"],
                    "odom": {"position": [body.x, body.y, 0.22], "yaw": yaw},
                },
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