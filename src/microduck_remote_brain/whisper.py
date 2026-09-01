from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .executor import ExecutionError, ExecutionReason


class WhisperCppTranscriber:
    def __init__(self, executable: Path, model: Path, *, language: str = "auto") -> None:
        self._executable = executable
        self._model = model
        self._language = language

    def transcribe(self, audio_path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="microduck-whisper-") as directory:
            output = Path(directory) / "transcript"
            command = [
                str(self._executable),
                "-m",
                str(self._model),
                "-f",
                str(audio_path),
                "-l",
                self._language,
                "-nt",
                "-np",
                "-otxt",
                "-of",
                str(output),
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as error:
                raise ExecutionError(
                    ExecutionReason.CONNECTION_FAILED, f"Whisper failed to start: {error}"
                ) from error
            transcript_path = output.with_suffix(".txt")
            if completed.returncode != 0 or not transcript_path.exists():
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise ExecutionError(
                    ExecutionReason.CONNECTION_FAILED,
                    f"Whisper failed with exit {completed.returncode}: {detail}",
                )
            transcript = transcript_path.read_text(encoding="utf-8").strip()
            if not transcript:
                raise ExecutionError(
                    ExecutionReason.TRANSCRIPTION_FAILED, "Whisper returned an empty transcript"
                )
            return transcript