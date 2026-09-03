from __future__ import annotations

import re
from pathlib import Path

import pytest

from microduck_remote_brain.brain_config import load_brain_config


@pytest.mark.parametrize(
    "profile",
    ["microduck.sim.toml", "microduck.docker.toml", "microduck.physical.example.toml"],
)
def test_shipped_profiles_separate_compact_ollama_models(profile: str) -> None:
    project = Path(__file__).parents[1]

    config = load_brain_config(project / "config" / profile)

    assert config.ollama_model == "qwen3:0.6b"
    assert config.vision_model == "qwen3.5:0.8b"


@pytest.mark.parametrize("profile", ["microduck.sim.toml", "microduck.docker.toml"])
def test_autonomous_simulation_profiles_use_active_cadence(profile: str) -> None:
    project = Path(__file__).parents[1]

    config = load_brain_config(project / "config" / profile)

    assert config.allow_movement is True
    assert config.interval == 4.0
    assert config.mapping_enabled is True
    assert config.mapping_keyframe_directory is not None


def test_local_stack_uses_compact_voice_model_only_when_voice_is_enabled() -> None:
    project = Path(__file__).parents[1]
    script = (project / "scripts" / "local-stack.ps1").read_text(encoding="utf-8")

    assert '[string]$OllamaModel = "qwen3:0.6b"' in script
    assert "qwen3-vl:8b" not in script
    assert len(re.findall(r"if \(-not \$NoVoice\) \{\s+Assert-OllamaModel\s+\}", script)) == 2


def test_config_switches_from_simulator_tcp_to_physical_socket(tmp_path) -> None:
    config_path = tmp_path / "physical.toml"
    config_path.write_text(
        """
[persona]
prompt = "You are a gentle duck."
sound_actions = ["greet", "coo"]
[ollama]
model = "local-model"
[perception]
source = "camera"
camera = 2
[robot]
transport = "unix"
socket = "/run/microduck/robotd.sock"
[oracle]
enabled = false
[autonomy]
allow_movement = false
interval = 20
""",
        encoding="utf-8",
    )

    config = load_brain_config(config_path)

    assert config.persona_prompt == "You are a gentle duck."
    assert config.sound_actions == ("greet", "coo")
    assert config.robot_socket == "/run/microduck/robotd.sock"
    assert config.robot_host is None
    assert config.oracle_enabled is False
    assert config.whisper_executable is None


def test_config_rejects_unknown_fields(tmp_path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(
        """
[persona]
prompt = "duck"
[ollama]
model = "model"
[perception]
source = "camera"
[robot]
transport = "tcp"
typo_port = 8765
[oracle]
enabled = false
[autonomy]
allow_movement = false
interval = 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown robot.*typo_port"):
        load_brain_config(config_path)


def test_config_rejects_invalid_transport_port(tmp_path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(
        """
[persona]
prompt = "duck"
[ollama]
model = "model"
[perception]
source = "camera"
[robot]
transport = "tcp"
port = 70000
[oracle]
enabled = false
[autonomy]
allow_movement = false
interval = 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="robot.port"):
        load_brain_config(config_path)


def test_physical_profile_cannot_enable_movement_without_sensor_gate(tmp_path) -> None:
    config_path = tmp_path / "unsafe.toml"
    config_path.write_text(
        """
[persona]
prompt = "duck"
[ollama]
model = "model"
[perception]
source = "camera"
[robot]
transport = "unix"
socket = "/run/microduck/robotd.sock"
[oracle]
enabled = false
[autonomy]
allow_movement = true
interval = 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="movement currently requires simulator"):
        load_brain_config(config_path)


def test_mapping_rejects_camera_only_physical_profile(tmp_path) -> None:
    config_path = tmp_path / "unsafe-map.toml"
    config_path.write_text(
        """
[persona]
prompt = "duck"
[ollama]
model = "model"
[perception]
source = "camera"
[robot]
transport = "unix"
socket = "/run/microduck/robotd.sock"
[oracle]
enabled = false
[autonomy]
allow_movement = false
[mapping]
enabled = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mapping currently requires a depth"):
        load_brain_config(config_path)