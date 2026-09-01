from __future__ import annotations

import base64
import json
import socket
from pathlib import Path
from typing import Protocol, TextIO

from .vision import capture_camera_jpeg, read_image

MAX_FRAME_BYTES = 4 * 1024 * 1024


class PerceptionProvider(Protocol):
    def capture(self) -> bytes: ...


class CameraPerception:
    def __init__(self, device: int) -> None:
        self._device = device

    def capture(self) -> bytes:
        return capture_camera_jpeg(self._device)


class ImagePerception:
    def __init__(self, path: Path) -> None:
        self._path = path

    def capture(self) -> bytes:
        return read_image(self._path)


class SimulatorPerception:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def capture(self) -> bytes:
        with socket.create_connection((self._host, self._port)) as connection:
            stream = connection.makefile("rw", encoding="utf-8", newline="\n")
            _write(stream, {"op": "hello", "protocol": 1, "joints": 15})
            hello = _read(stream)
            if hello.get("protocol") != 1 or "error" in hello:
                raise RuntimeError("simulator protocol 1 hello was not accepted")
            _write(stream, {"op": "camera"})
            response = _read(stream)
        encoded = response.get("jpeg_base64")
        if not isinstance(encoded, str):
            raise RuntimeError("simulator camera response has no JPEG frame")
        try:
            image = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise RuntimeError("simulator returned invalid base64 camera data") from error
        if not image or len(image) > MAX_FRAME_BYTES:
            raise RuntimeError("simulator camera frame has an invalid size")
        return image


def _write(stream: TextIO, message: dict[str, object]) -> None:
    payload = json.dumps(message, separators=(",", ":"), allow_nan=False)
    stream.write(payload + "\n")
    stream.flush()


def _read(stream: TextIO) -> dict[str, object]:
    line = stream.readline(MAX_FRAME_BYTES * 2)
    if not line or not line.endswith("\n"):
        raise RuntimeError("simulator closed an incomplete response")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise RuntimeError("simulator returned invalid JSON") from error
    if not isinstance(value, dict) or "error" in value:
        raise RuntimeError(f"simulator rejected camera request: {value!r}")
    return value