from __future__ import annotations

import json
import socket
import subprocess
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .xinput import is_connected


class ControlPanel:
    def __init__(
        self,
        root: tk.Tk,
        host: str = "127.0.0.1",
        port: int = 7801,
        gamepad_status: Path | None = None,
    ) -> None:
        self._root = root
        self._host = host
        self._port = port
        self._gamepad_status = gamepad_status
        self._interaction = tk.BooleanVar(value=False)
        self._gamepad = tk.StringVar(value="Checking...")
        self._axes = tk.StringVar(value="Left stick: unavailable")
        self._command = tk.StringVar(value="Command: unavailable")

        root.title("MicroDuck Simulation Controls")
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=16)
        frame.grid()

        ttk.Checkbutton(
            frame,
            text="Mouse interaction",
            variable=self._interaction,
            command=self._set_interaction,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="When enabled, use Ctrl + drag in the MuJoCo window.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 14)
        )
        ttk.Label(frame, text="Gamepad:").grid(row=2, column=0, sticky="w")
        ttk.Label(frame, textvariable=self._gamepad).grid(row=2, column=1, sticky="w")
        ttk.Label(frame, textvariable=self._axes).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Label(frame, textvariable=self._command).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        ttk.Button(frame, text="Refresh", command=self._refresh_gamepad).grid(
            row=5, column=0, sticky="ew", pady=(10, 0), padx=(0, 5)
        )
        ttk.Button(frame, text="Open joy.cpl", command=self._open_game_controllers).grid(
            row=5, column=1, sticky="ew", pady=(10, 0), padx=(5, 0)
        )
        self._refresh_gamepad()
        root.after(2000, self._poll_gamepad)

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        with socket.create_connection((self._host, self._port), timeout=2.0) as connection:
            stream = connection.makefile("rw", encoding="utf-8", newline="\n")
            stream.write(
                json.dumps(
                    {"op": "hello", "protocol": 1, "joints": 15}, allow_nan=False
                )
                + "\n"
            )
            stream.flush()
            hello = json.loads(stream.readline())
            if hello.get("protocol") != 1:
                raise RuntimeError("simulator protocol mismatch")
            stream.write(json.dumps(payload, allow_nan=False) + "\n")
            stream.flush()
            return json.loads(stream.readline())

    def _set_interaction(self) -> None:
        try:
            answer = self._request(
                {"op": "interaction", "enabled": self._interaction.get()}
            )
            if answer.get("enabled") is not self._interaction.get():
                raise RuntimeError("simulator rejected interaction mode")
        except (OSError, RuntimeError, json.JSONDecodeError) as error:
            self._interaction.set(False)
            self._gamepad.set(f"Simulator error: {error}")

    def _refresh_gamepad(self) -> None:
        xinput_connected = is_connected()
        self._gamepad.set("XInput detected" if xinput_connected else "No XInput stream")
        if self._gamepad_status is None or not self._gamepad_status.exists():
            return
        try:
            state = json.loads(self._gamepad_status.read_text(encoding="utf-8"))
            fresh = time.monotonic() - float(state["updated_at"]) < 1.0
            if xinput_connected and fresh and state.get("connected") is True:
                self._gamepad.set("Connected to simulator")
            elif xinput_connected and fresh:
                self._gamepad.set("Controller found; reconnecting to simulator")
            elif xinput_connected:
                self._gamepad.set("Controller found; client unavailable")
            self._axes.set(
                f"Left stick: x={state['left_x']:+.2f}, y={state['left_y']:+.2f} "
                f"({state['mode']})"
            )
            self._command.set(
                f"Command: vx={state['vx']:+.2f}, vy={state['vy']:+.2f}, "
                f"yaw={state['vyaw']:+.2f}"
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._axes.set("Left stick: unreadable status")

    def _poll_gamepad(self) -> None:
        self._refresh_gamepad()
        self._root.after(2000, self._poll_gamepad)

    @staticmethod
    def _open_game_controllers() -> None:
        subprocess.Popen(["control.exe", "joy.cpl"])


def main() -> int:
    root = tk.Tk()
    status = Path(__file__).resolve().parents[2] / ".local" / "gamepad-state.json"
    ControlPanel(root, gamepad_status=status)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())