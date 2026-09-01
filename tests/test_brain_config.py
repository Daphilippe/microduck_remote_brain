from __future__ import annotations

import pytest

from microduck_remote_brain.brain_config import load_brain_config


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