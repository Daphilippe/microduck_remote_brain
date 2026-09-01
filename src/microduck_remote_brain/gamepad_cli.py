from __future__ import annotations

import argparse
import json
import time
from enum import StrEnum
from pathlib import Path

from .executor import ExecutionError
from .robotd import RobotdClient
from .xinput import Button, GamepadState, XInputDevice

DEADZONE = 0.1
MAX_LINEAR = 0.3
MIN_WALKING_SPEED = 0.2
MAX_ANGULAR = 1.5
MAX_HEAD = 2.5
BODY_MAX_Z_UP = 0.010
BODY_MAX_Z_DOWN = 0.025
BODY_MAX_ANGLE = 0.2618
TRIGGER_THRESHOLD = 0.3


class Mode(StrEnum):
    DRIVE = "drive"
    HEAD = "head"
    BODY = "body"


def _deadzone(value: float) -> float:
    return 0.0 if abs(value) < DEADZONE else value


def _walking_speed(value: float) -> float:
    value = _deadzone(value)
    if value == 0.0:
        return 0.0
    normalized = (abs(value) - DEADZONE) / (1.0 - DEADZONE)
    speed = MIN_WALKING_SPEED + normalized * (MAX_LINEAR - MIN_WALKING_SPEED)
    return speed if value > 0.0 else -speed


class GamepadController:
    def __init__(self, robot: RobotdClient) -> None:
        self.robot = robot
        self.mode = Mode.DRIVE
        self.drive_active = False
        self.last_twist = (0.0, 0.0, 0.0)
        self.previous = GamepadState(Button(0), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def transport_lost(self, state: GamepadState | None = None) -> None:
        self.drive_active = False
        self.last_twist = (0.0, 0.0, 0.0)
        if state is not None:
            self.previous = state

    def update(self, state: GamepadState) -> None:
        pressed = state.buttons & ~self.previous.buttons
        if pressed & Button.START:
            self.robot.toggle_enable()
        if pressed & Button.Y:
            self.mode = Mode.DRIVE if self.mode is Mode.HEAD else Mode.HEAD
        if pressed & Button.B:
            leaving = self.mode is Mode.BODY
            self.mode = Mode.DRIVE if leaving else Mode.BODY
            if leaving:
                self.robot.pose(0.0, 0.0, 0.0, active=False)
        for button, skill in (
            (Button.A, "ground_pick"),
            (Button.X, "roulade"),
            (Button.LEFT_BUMPER, "kick_left"),
            (Button.RIGHT_BUMPER, "kick_right"),
            (Button.DPAD_DOWN, "sit_toggle"),
        ):
            if pressed & button:
                self.robot.skill(skill)

        left_x = _deadzone(state.left_x)
        left_y = _deadzone(state.left_y)
        right_x = _deadzone(state.right_x)
        right_y = _deadzone(state.right_y)
        self.robot.mouth(max(state.left_trigger, state.right_trigger))
        if self.previous.right_trigger < TRIGGER_THRESHOLD <= state.right_trigger:
            self.robot.sound("chirp")
        if state.left_trigger >= TRIGGER_THRESHOLD:
            self.robot.sound("wheee", True, notify=True)
        elif self.previous.left_trigger >= TRIGGER_THRESHOLD:
            self.robot.sound("wheee", False, notify=True)

        if self.mode is Mode.DRIVE:
            twist = (_walking_speed(left_y), -left_x * MAX_LINEAR, -right_x * MAX_ANGULAR)
            self.last_twist = twist
            moving = any(value != 0.0 for value in twist)
            if moving:
                self.robot.move_twist(*twist)
            elif self.drive_active:
                self.robot.stop()
            self.drive_active = moving
        elif self.mode is Mode.HEAD:
            self.last_twist = (0.0, 0.0, 0.0)
            if self.drive_active:
                self.robot.stop()
                self.drive_active = False
            self.robot.head(
                right_y * MAX_HEAD,
                -left_y * MAX_HEAD,
                -left_x * MAX_HEAD,
                right_x * MAX_HEAD,
            )
        else:
            self.last_twist = (0.0, 0.0, 0.0)
            if self.drive_active:
                self.robot.stop()
                self.drive_active = False
            self.robot.pose(
                left_y * (BODY_MAX_Z_UP if left_y >= 0.0 else BODY_MAX_Z_DOWN),
                right_x * BODY_MAX_ANGLE,
                right_y * BODY_MAX_ANGLE,
                active=True,
            )
        self.previous = state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive simulated MicroDuck with an Xbox controller"
    )
    parser.add_argument("--robot-host", default="127.0.0.1")
    parser.add_argument("--robot-port", type=int, default=8765)
    parser.add_argument("--controller", type=int, default=0)
    parser.add_argument("--hz", type=int, default=50)
    parser.add_argument("--pause-file", type=Path)
    parser.add_argument("--status-file", type=Path)
    return parser


def _write_status(
    path: Path | None,
    *,
    connected: bool,
    controller: GamepadController,
    state: GamepadState | None = None,
) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "connected": connected,
                    "updated_at": time.monotonic(),
                    "mode": controller.mode,
                    "left_x": state.left_x if state is not None else 0.0,
                    "left_y": state.left_y if state is not None else 0.0,
                    "vx": controller.last_twist[0],
                    "vy": controller.last_twist[1],
                    "vyaw": controller.last_twist[2],
                },
                allow_nan=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return
    for attempt in range(3):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(0.01)
        except OSError:
            return


def main(argv: list[str] | None = None) -> int:  # pylint: disable=too-many-statements
    args = _parser().parse_args(argv)
    device = XInputDevice(args.controller)
    robot = RobotdClient(host=args.robot_host, port=args.robot_port)
    controller = GamepadController(robot)
    gamepad_connected = False
    robot_connected = False
    next_status = 0.0
    print("Waiting for Xbox controller. Right stick press is reserved for push-to-talk.")
    try:
        while True:
            started = time.monotonic()
            if args.pause_file is not None and args.pause_file.exists():
                if robot_connected and controller.drive_active:
                    try:
                        robot.stop()
                    except (OSError, ExecutionError):
                        robot.close()
                        robot_connected = False
                    controller.transport_lost()
                time.sleep(0.05)
                continue
            if not robot_connected:
                try:
                    robot.connect()
                except (OSError, ExecutionError):
                    _write_status(
                        args.status_file, connected=False, controller=controller
                    )
                    time.sleep(0.5)
                    continue
                robot_connected = True
                print("Gamepad client connected to simulator.")
            try:
                state = device.read()
            except RuntimeError:
                if gamepad_connected:
                    gamepad_connected = False
                    print("Xbox controller disconnected; sending stop.")
                    try:
                        robot.stop()
                    except (OSError, ExecutionError):
                        robot.close()
                        robot_connected = False
                    controller.transport_lost()
                _write_status(args.status_file, connected=False, controller=controller)
                time.sleep(0.5)
                continue
            if not gamepad_connected:
                gamepad_connected = True
                print("Xbox controller connected.")
            try:
                controller.update(state)
            except (OSError, ExecutionError) as error:
                print(f"Simulator connection lost; reconnecting: {error}")
                robot.close()
                robot_connected = False
                controller.transport_lost(state)
                _write_status(args.status_file, connected=False, controller=controller)
                time.sleep(0.5)
                continue
            if args.status_file is not None and started >= next_status:
                _write_status(
                    args.status_file,
                    connected=True,
                    controller=controller,
                    state=state,
                )
                next_status = started + 0.1
            time.sleep(max(0.0, 1.0 / args.hz - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        if robot_connected:
            try:
                robot.stop()
                robot.mouth(0.0)
            except (OSError, ExecutionError):
                pass
        robot.close()


if __name__ == "__main__":
    raise SystemExit(main())