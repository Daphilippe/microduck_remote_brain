from __future__ import annotations

from typing import Any

import pytest

from microduck_remote_brain.gamepad_cli import (
    GamepadController,
    Mode,
    _walking_speed,
    _write_status,
)
from microduck_remote_brain.xinput import Button, GamepadState

NO_BUTTONS = Button(0)


class FakeRobot:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: self.calls.append((name, *args, kwargs))


def state(
    *,
    buttons: Button = NO_BUTTONS,
    left_x: float = 0.0,
    left_y: float = 0.0,
    right_x: float = 0.0,
) -> GamepadState:
    return GamepadState(buttons, 0.0, 0.0, left_x, left_y, right_x, 0.0)


def test_drive_axes_match_padd_signs_and_limits() -> None:
    robot = FakeRobot()
    controller = GamepadController(robot)  # type: ignore[arg-type]

    controller.update(state(left_x=1.0, left_y=1.0, right_x=1.0))

    move = next(call for call in robot.calls if call[0] == "move_twist")
    assert move[1:4] == pytest.approx((0.3, -0.3, -1.5))


def test_forward_stick_uses_a_visible_gait_range_after_deadzone() -> None:
    assert _walking_speed(0.09) == 0.0
    assert _walking_speed(0.1) == pytest.approx(0.2)
    assert _walking_speed(0.65) == pytest.approx(0.261111, abs=1e-6)
    assert _walking_speed(1.0) == pytest.approx(0.3)
    assert _walking_speed(-0.65) == pytest.approx(-0.261111, abs=1e-6)


def test_idle_gamepad_does_not_override_another_client() -> None:
    robot = FakeRobot()
    controller = GamepadController(robot)  # type: ignore[arg-type]

    controller.update(state())

    assert not any(call[0] in {"move_twist", "stop"} for call in robot.calls)


def test_releasing_sticks_sends_one_stop() -> None:
    robot = FakeRobot()
    controller = GamepadController(robot)  # type: ignore[arg-type]

    controller.update(state(left_y=1.0))
    controller.update(state())
    controller.update(state())

    assert sum(call[0] == "stop" for call in robot.calls) == 1


def test_transport_loss_resets_motion_without_replaying_held_button() -> None:
    robot = FakeRobot()
    controller = GamepadController(robot)  # type: ignore[arg-type]
    held = state(buttons=Button.START, left_y=1.0)
    controller.update(held)

    controller.transport_lost(held)
    controller.update(held)

    assert controller.drive_active
    assert sum(call[0] == "toggle_enable" for call in robot.calls) == 1


def test_locked_status_file_does_not_stop_gamepad_client(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = GamepadController(FakeRobot())  # type: ignore[arg-type]
    replace_attempts = 0

    def locked_replace(_source: Any, _target: Any) -> None:
        nonlocal replace_attempts
        replace_attempts += 1
        raise PermissionError("status file is temporarily locked")

    monkeypatch.setattr(type(tmp_path), "replace", locked_replace)
    monkeypatch.setattr("microduck_remote_brain.gamepad_cli.time.sleep", lambda _: None)

    _write_status(tmp_path / "gamepad-state.json", connected=True, controller=controller)

    assert replace_attempts == 3


def test_expected_button_edges_dispatch_skills_and_modes() -> None:
    robot = FakeRobot()
    controller = GamepadController(robot)  # type: ignore[arg-type]
    buttons = Button.START | Button.A | Button.X | Button.LEFT_BUMPER | Button.DPAD_DOWN

    controller.update(state(buttons=buttons))
    controller.update(state(buttons=Button.Y))

    assert any(call[0] == "toggle_enable" for call in robot.calls)
    assert {call[1] for call in robot.calls if call[0] == "skill"} == {
        "ground_pick",
        "roulade",
        "kick_left",
        "sit_toggle",
    }
    assert controller.mode is Mode.HEAD


def test_canonical_held_buttons_chain_roll_switch_mode_and_shutdown(monkeypatch) -> None:
    robot = FakeRobot()
    controller = GamepadController(robot)  # type: ignore[arg-type]
    now = 10.0
    monkeypatch.setattr("microduck_remote_brain.gamepad_cli.time.monotonic", lambda: now)

    controller.update(state(buttons=Button.X | Button.DPAD_UP | Button.BACK))
    now += 3.1
    controller.update(state(buttons=Button.X | Button.DPAD_UP | Button.BACK))

    assert ("skill", "roulade", {"notify": True}) in robot.calls
    assert ("set_mode", "roller", {}) in robot.calls
    assert ("shutdown", {}) in robot.calls