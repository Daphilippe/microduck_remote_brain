from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SOUND_ACTIONS = frozenset({"alarm", "greet", "inquire", "peck", "chirp", "coo"})


@dataclass(frozen=True, slots=True)
class BrainConfig:  # pylint: disable=too-many-instance-attributes
    persona_prompt: str
    sound_actions: tuple[str, ...]
    ollama_model: str
    vision_model: str
    ollama_endpoint: str
    ollama_tags_endpoint: str
    perception_source: str
    camera_device: int
    image_path: Path | None
    perception_host: str
    perception_port: int
    robot_transport: str
    robot_host: str | None
    robot_port: int | None
    robot_socket: str | None
    oracle_enabled: bool
    oracle_host: str
    oracle_port: int
    minimum_displacement: float
    allow_movement: bool
    interval: float
    mapping_enabled: bool
    mapping_path: Path
    mapping_keyframe_directory: Path | None
    mapping_resolution_m: float
    mapping_width: int
    mapping_height: int
    mapping_update_interval_s: float
    mapping_tof_horizontal_fov_degrees: float
    mapping_max_range_m: float
    whisper_executable: Path | None
    whisper_model: Path | None
    audit_path: Path


def load_brain_config(  # pylint: disable=too-many-locals,too-many-statements
    path: Path,
) -> BrainConfig:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot load brain config {path}: {error}") from error

    _reject_unknown(
        document,
        {
            "persona",
            "ollama",
            "perception",
            "robot",
            "oracle",
            "autonomy",
            "mapping",
            "voice",
            "audit",
        },
        "root",
    )
    persona = _table(document, "persona")
    ollama = _table(document, "ollama")
    perception = _table(document, "perception")
    robot = _table(document, "robot")
    oracle = _table(document, "oracle")
    autonomy = _table(document, "autonomy")
    mapping = _table(document, "mapping", required=False)
    voice = _table(document, "voice", required=False)
    audit = _table(document, "audit", required=False)

    _reject_unknown(persona, {"prompt", "sound_actions"}, "persona")
    _reject_unknown(ollama, {"model", "vision_model", "endpoint", "tags_endpoint"}, "ollama")
    _reject_unknown(perception, {"source", "camera", "image", "host", "port"}, "perception")
    _reject_unknown(robot, {"transport", "host", "port", "socket"}, "robot")
    _reject_unknown(oracle, {"enabled", "host", "port", "minimum_displacement"}, "oracle")
    _reject_unknown(autonomy, {"allow_movement", "interval"}, "autonomy")
    _reject_unknown(
        mapping,
        {
            "enabled",
            "path",
            "keyframe_directory",
            "resolution_m",
            "width",
            "height",
            "update_interval",
            "tof_horizontal_fov_degrees",
            "max_range_m",
        },
        "mapping",
    )
    _reject_unknown(voice, {"executable", "model"}, "voice")
    _reject_unknown(audit, {"path"}, "audit")

    sound_actions = tuple(persona.get("sound_actions", ("coo", "inquire", "chirp")))
    if not sound_actions or any(action not in SOUND_ACTIONS for action in sound_actions):
        raise ValueError("persona.sound_actions must contain supported robot sound tags")

    source = str(perception.get("source", "camera"))
    if source not in {"camera", "image", "simulator"}:
        raise ValueError("perception.source must be 'camera', 'image', or 'simulator'")
    image_path = _optional_path(path, perception.get("image"))
    if source == "image" and image_path is None:
        raise ValueError("perception.image is required for the image source")

    transport = str(robot.get("transport", "tcp"))
    if transport not in {"tcp", "unix"}:
        raise ValueError("robot.transport must be 'tcp' or 'unix'")
    robot_socket = str(robot["socket"]) if transport == "unix" else None
    robot_host = str(robot.get("host", "127.0.0.1")) if transport == "tcp" else None
    robot_port = int(robot.get("port", 8765)) if transport == "tcp" else None

    whisper_executable = _optional_path(path, voice.get("executable"))
    whisper_model = _optional_path(path, voice.get("model"))
    if (whisper_executable is None) != (whisper_model is None):
        raise ValueError("voice.executable and voice.model must be configured together")

    config = BrainConfig(
        persona_prompt=str(persona["prompt"]),
        sound_actions=sound_actions,
        ollama_model=str(ollama["model"]),
        vision_model=str(ollama.get("vision_model", ollama["model"])),
        ollama_endpoint=str(ollama.get("endpoint", "http://127.0.0.1:11434/api/chat")),
        ollama_tags_endpoint=str(
            ollama.get("tags_endpoint", "http://127.0.0.1:11434/api/tags")
        ),
        perception_source=source,
        camera_device=int(perception.get("camera", 0)),
        image_path=image_path,
        perception_host=str(perception.get("host", oracle.get("host", "127.0.0.1"))),
        perception_port=int(perception.get("port", oracle.get("port", 7801))),
        robot_transport=transport,
        robot_host=robot_host,
        robot_port=robot_port,
        robot_socket=robot_socket,
        oracle_enabled=bool(oracle.get("enabled", False)),
        oracle_host=str(oracle.get("host", "127.0.0.1")),
        oracle_port=int(oracle.get("port", 7801)),
        minimum_displacement=float(oracle.get("minimum_displacement", 0.02)),
        allow_movement=bool(autonomy.get("allow_movement", False)),
        interval=float(autonomy.get("interval", 15.0)),
        mapping_enabled=bool(mapping.get("enabled", False)),
        mapping_path=_optional_path(path, mapping.get("path"))
        or path.parent / "occupancy-map.json",
        mapping_keyframe_directory=_optional_path(path, mapping.get("keyframe_directory")),
        mapping_resolution_m=float(mapping.get("resolution_m", 0.05)),
        mapping_width=int(mapping.get("width", 400)),
        mapping_height=int(mapping.get("height", 400)),
        mapping_update_interval_s=float(mapping.get("update_interval", 0.2)),
        mapping_tof_horizontal_fov_degrees=float(
            mapping.get("tof_horizontal_fov_degrees", 45.0)
        ),
        mapping_max_range_m=float(mapping.get("max_range_m", 4.0)),
        whisper_executable=whisper_executable,
        whisper_model=whisper_model,
        audit_path=_optional_path(path, audit.get("path")) or path.parent / "brain-audit.jsonl",
    )
    if not 1 <= config.perception_port <= 65535:
        raise ValueError("perception.port must be between 1 and 65535")
    if config.robot_port is not None and not 1 <= config.robot_port <= 65535:
        raise ValueError("robot.port must be between 1 and 65535")
    if not 1 <= config.oracle_port <= 65535:
        raise ValueError("oracle.port must be between 1 and 65535")
    if config.interval < 0 or not math.isfinite(config.interval):
        raise ValueError("autonomy.interval must be finite and nonnegative")
    if config.minimum_displacement < 0 or not math.isfinite(config.minimum_displacement):
        raise ValueError("oracle.minimum_displacement must be finite and nonnegative")
    if config.mapping_resolution_m <= 0 or not math.isfinite(config.mapping_resolution_m):
        raise ValueError("mapping.resolution_m must be finite and positive")
    if config.mapping_width <= 0 or config.mapping_height <= 0:
        raise ValueError("mapping width and height must be positive")
    if config.mapping_update_interval_s <= 0 or not math.isfinite(
        config.mapping_update_interval_s
    ):
        raise ValueError("mapping.update_interval must be finite and positive")
    if not 0 < config.mapping_tof_horizontal_fov_degrees < 180:
        raise ValueError("mapping.tof_horizontal_fov_degrees must be between 0 and 180")
    if config.mapping_max_range_m <= 0 or not math.isfinite(config.mapping_max_range_m):
        raise ValueError("mapping.max_range_m must be finite and positive")
    if not _http_url(config.ollama_endpoint) or not _http_url(config.ollama_tags_endpoint):
        raise ValueError("Ollama endpoints must be absolute HTTP(S) URLs")
    if config.allow_movement and (
        config.perception_source != "simulator" or not config.oracle_enabled
    ):
        raise ValueError(
            "autonomous movement currently requires simulator perception and the body oracle"
        )
    if config.mapping_enabled and config.perception_source != "simulator":
        raise ValueError(
            "mapping currently requires a depth perception provider"
        )
    return config


def _table(document: dict[str, Any], name: str, *, required: bool = True) -> dict[str, Any]:
    value = document.get(name)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"brain config requires a [{name}] table")
    return value


def _optional_path(config_path: Path, value: object) -> Path | None:
    if value is None or value == "":
        return None
    result = Path(str(value)).expanduser()
    return result if result.is_absolute() else config_path.parent / result


def _reject_unknown(table: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} configuration fields: {', '.join(unknown)}")


def _http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
