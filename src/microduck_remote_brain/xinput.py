from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from enum import IntFlag


class Button(IntFlag):
    DPAD_UP = 0x0001
    DPAD_DOWN = 0x0002
    DPAD_LEFT = 0x0004
    DPAD_RIGHT = 0x0008
    START = 0x0010
    BACK = 0x0020
    LEFT_THUMB = 0x0040
    RIGHT_THUMB = 0x0080
    LEFT_BUMPER = 0x0100
    RIGHT_BUMPER = 0x0200
    A = 0x1000
    B = 0x2000
    X = 0x4000
    Y = 0x8000


class _Gamepad(ctypes.Structure):
    _fields_ = [
        ("buttons", ctypes.c_ushort),
        ("left_trigger", ctypes.c_ubyte),
        ("right_trigger", ctypes.c_ubyte),
        ("left_x", ctypes.c_short),
        ("left_y", ctypes.c_short),
        ("right_x", ctypes.c_short),
        ("right_y", ctypes.c_short),
    ]


class _State(ctypes.Structure):
    _fields_ = [("packet_number", ctypes.c_uint), ("gamepad", _Gamepad)]


@dataclass(frozen=True, slots=True)
class GamepadState:
    buttons: Button
    left_trigger: float
    right_trigger: float
    left_x: float
    left_y: float
    right_x: float
    right_y: float


def _axis(value: int) -> float:
    divisor = 32767.0 if value >= 0 else 32768.0
    return max(-1.0, min(1.0, value / divisor))


class XInputDevice:
    def __init__(self, index: int = 0) -> None:
        if not hasattr(ctypes, "WinDLL"):
            raise RuntimeError("XInput is only available on Windows")
        library = None
        for name in ("xinput1_4", "xinput9_1_0", "xinput1_3"):
            try:
                library = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        if library is None:
            raise RuntimeError("no XInput library is available")
        self._get_state = library.XInputGetState
        self._get_state.argtypes = [ctypes.c_uint, ctypes.POINTER(_State)]
        self._get_state.restype = ctypes.c_uint
        self._index = index

    def read(self) -> GamepadState:
        state = _State()
        result = self._get_state(self._index, ctypes.byref(state))
        if result != 0:
            raise RuntimeError(f"XInput controller {self._index} is not connected")
        gamepad = state.gamepad
        return GamepadState(
            buttons=Button(gamepad.buttons),
            left_trigger=gamepad.left_trigger / 255.0,
            right_trigger=gamepad.right_trigger / 255.0,
            left_x=_axis(gamepad.left_x),
            left_y=_axis(gamepad.left_y),
            right_x=_axis(gamepad.right_x),
            right_y=_axis(gamepad.right_y),
        )


def is_connected(index: int = 0) -> bool:
    try:
        XInputDevice(index).read()
    except RuntimeError:
        return False
    return True


def wait_for_button(button: Button, index: int = 0) -> None:
    device = XInputDevice(index)
    was_pressed = bool(device.read().buttons & button)
    while True:
        pressed = bool(device.read().buttons & button)
        if pressed and not was_pressed:
            return
        was_pressed = pressed
        time.sleep(0.02)