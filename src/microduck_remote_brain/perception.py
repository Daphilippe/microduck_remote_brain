from __future__ import annotations

import base64
import json
import socket
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, TextIO

from .vision import capture_camera_jpeg, read_image

MAX_FRAME_BYTES = 4 * 1024 * 1024
TOF_ROWS = 8
TOF_COLS = 8
DROP_DISTANCE_MM = 700.0
DROP_MEMORY_CLEAR_FRAMES = 3


@dataclass(frozen=True, slots=True)
class DepthObservation:
    distance_mm: tuple[float | None, ...]
    left_clearance_mm: float | None
    center_clearance_mm: float | None
    right_clearance_mm: float | None
    drop_hazard_sectors: tuple[str, ...] = ()
    drop_hazard_remembered: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "left_clearance_mm": self.left_clearance_mm,
            "center_clearance_mm": self.center_clearance_mm,
            "right_clearance_mm": self.right_clearance_mm,
            "drop_hazard_sectors": list(self.drop_hazard_sectors),
            "drop_hazard_remembered": self.drop_hazard_remembered,
        }


class DropHazardMemory:
    def __init__(self, clear_frames_required: int = DROP_MEMORY_CLEAR_FRAMES) -> None:
        if clear_frames_required <= 0:
            raise ValueError("clear_frames_required must be positive")
        self._clear_frames_required = clear_frames_required
        self._clear_frames = 0
        self._latched = False

    def update(self, observation: DepthObservation) -> DepthObservation:
        if observation.drop_hazard_sectors:
            self._latched = True
            self._clear_frames = 0
        elif self._latched:
            self._clear_frames += 1
            if self._clear_frames >= self._clear_frames_required:
                self._latched = False
                self._clear_frames = 0
        return replace(observation, drop_hazard_remembered=self._latched)


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
        response = self._request("camera")
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

    def capture_depth(self) -> DepthObservation:
        response = self._request("tof")
        raw_distances = response.get("distance_mm")
        if not isinstance(raw_distances, list) or len(raw_distances) != TOF_ROWS * TOF_COLS:
            raise RuntimeError("simulator ToF response must contain 64 distances")
        distances: list[float | None] = []
        for value in raw_distances:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise RuntimeError("simulator ToF distances must be numeric")
            numeric = float(value)
            distances.append(numeric if numeric > 0 else None)
        return DepthObservation(
            tuple(distances),
            _sector_clearance(distances, range(0, 3)),
            _sector_clearance(distances, range(3, 5)),
            _sector_clearance(distances, range(5, 8)),
            _drop_hazard_sectors(distances),
        )

    def _request(self, operation: str) -> dict[str, object]:
        with socket.create_connection((self._host, self._port)) as connection:
            stream = connection.makefile("rw", encoding="utf-8", newline="\n")
            _write(stream, {"op": "hello", "protocol": 1, "joints": 15})
            hello = _read(stream)
            if hello.get("protocol") != 1 or "error" in hello:
                raise RuntimeError("simulator protocol 1 hello was not accepted")
            _write(stream, {"op": operation})
            return _read(stream)


def _sector_clearance(
    distances: list[float | None], columns: range
) -> float | None:
    values = [
        distance
        for index, distance in enumerate(distances)
        if index % TOF_COLS in columns and distance is not None
    ]
    return min(values) if values else None


def _drop_hazard_sectors(distances: list[float | None]) -> tuple[str, ...]:
    sectors = {
        "left": range(0, 3),
        "center": range(3, 5),
        "right": range(5, 8),
    }
    hazards: list[str] = []
    lower_rows = range(TOF_ROWS - 2, TOF_ROWS)
    for name, columns in sectors.items():
        values = [
            distances[row * TOF_COLS + column]
            for row in lower_rows
            for column in columns
        ]
        valid = [value for value in values if value is not None]
        if len(valid) <= len(values) // 2 or (
            valid and min(valid) > DROP_DISTANCE_MM
        ):
            hazards.append(name)
    return tuple(hazards)


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