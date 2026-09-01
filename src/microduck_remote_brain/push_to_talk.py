from __future__ import annotations

import importlib
import queue
import time
import wave
from pathlib import Path
from typing import Any


class AudioRecorder:
    def __init__(self, *, sample_rate: int = 16000, device: str | int | None = None) -> None:
        self._sample_rate = sample_rate
        self._device = device
        self._frames: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._stream: Any = None
        self._started_at = 0.0

    def start(self) -> None:
        sound = importlib.import_module("sounddevice")

        def capture(indata: Any, _frames: int, _time: Any, status: Any) -> None:
            if status:
                print(f"audio status: {status}")
            self._frames.put(indata.copy())

        self._stream = sound.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=capture,
        )
        self._stream.start()
        self._started_at = time.monotonic()

    def stop(self, output: Path) -> None:
        np = importlib.import_module("numpy")

        if self._stream is None:
            raise RuntimeError("recording has not started")
        remaining = 0.1 - (time.monotonic() - self._started_at)
        if remaining > 0:
            time.sleep(remaining)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        blocks = []
        while not self._frames.empty():
            blocks.append(self._frames.get())
        if not blocks:
            raise RuntimeError("the microphone returned no samples")
        samples = np.concatenate(blocks, axis=0)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        with wave.Wave_write(str(output)) as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(self._sample_rate)
            stream.writeframes(pcm.tobytes())


class GamepadTrigger:
    def __init__(self, button: int = 0x0080) -> None:
        from .xinput import Button, XInputDevice

        self._button = Button(button)
        self._device = XInputDevice()
        self._was_pressed = bool(self._device.read().buttons & self._button)
        print(f"XInput push-to-talk button mask: 0x{button:04x}")

    def wait(self, message: str) -> None:
        from .xinput import wait_for_button

        print(message, flush=True)
        wait_for_button(self._button)


class KeyboardTrigger:
    def wait(self, message: str) -> None:
        input(f"{message} Press Enter.")