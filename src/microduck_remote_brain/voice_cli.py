from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .body_oracle import TcpBodyOracle
from .executor import ExecutionError, PlanExecutor
from .ollama import OllamaPlanner
from .push_to_talk import AudioRecorder, GamepadTrigger, KeyboardTrigger
from .robotd import RobotdClient
from .whisper import WhisperCppTranscriber


def _audio_device(value: str) -> str | int:
    return int(value) if value.isdecimal() else value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local MicroDuck voice-to-action loop")
    parser.add_argument("--robot-host", default="127.0.0.1")
    parser.add_argument("--robot-port", type=int, default=8765)
    parser.add_argument("--simulator-host", default="127.0.0.1")
    parser.add_argument("--simulator-port", type=int, default=7801)
    parser.add_argument("--minimum-displacement", type=float, default=0.02)
    parser.add_argument("--ollama-model", default="ministral-3-14b:latest")
    parser.add_argument("--whisper-exe", type=Path)
    parser.add_argument("--whisper-model", type=Path)
    parser.add_argument("--microphone", type=_audio_device)
    parser.add_argument("--trigger", choices=("gamepad", "keyboard"), default="gamepad")
    parser.add_argument("--gamepad-button", type=int, default=0x0080)
    parser.add_argument("--gamepad-pause-file", type=Path)
    parser.add_argument("--pid-file", type=Path)
    parser.add_argument("--text", help="skip audio and execute one text command")
    parser.add_argument("--once", action="store_true")
    return parser


def _execute_text(text: str, args: argparse.Namespace) -> None:
    plan = OllamaPlanner(args.ollama_model).plan(text)
    print(json.dumps(asdict(plan), indent=2, ensure_ascii=False))
    executor = PlanExecutor(
        RobotdClient(host=args.robot_host, port=args.robot_port),
        oracle=TcpBodyOracle(args.simulator_host, args.simulator_port),
        minimum_displacement=args.minimum_displacement,
    )
    pause_file = args.gamepad_pause_file
    try:
        if pause_file is not None:
            pause_file.parent.mkdir(parents=True, exist_ok=True)
            pause_file.touch()
            time.sleep(0.1)
        executor.execute(plan)
    finally:
        if pause_file is not None:
            pause_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.pid_file is not None:
        args.pid_file.parent.mkdir(parents=True, exist_ok=True)
        args.pid_file.write_text(str(os.getpid()), encoding="ascii")
    try:
        if args.text:
            _execute_text(args.text, args)
            return 0
        if args.whisper_exe is None or args.whisper_model is None:
            raise ValueError("--whisper-exe and --whisper-model are required for voice input")

        trigger = (
            GamepadTrigger(args.gamepad_button)
            if args.trigger == "gamepad"
            else KeyboardTrigger()
        )
        transcriber = WhisperCppTranscriber(args.whisper_exe, args.whisper_model)
        while True:
            with tempfile.TemporaryDirectory(prefix="microduck-voice-") as directory:
                audio = Path(directory) / "command.wav"
                recorder = AudioRecorder(device=args.microphone)
                trigger.wait("Start push-to-talk.")
                recorder.start()
                trigger.wait("Recording. Stop push-to-talk.")
                recorder.stop(audio)
                transcript = transcriber.transcribe(audio)
                print(f"transcript: {transcript}")
                _execute_text(transcript, args)
            if args.once:
                return 0
    except (ExecutionError, OSError, RuntimeError, ValueError) as error:
        print(f"voice pipeline failed: {error}")
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if args.pid_file is not None:
            args.pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())