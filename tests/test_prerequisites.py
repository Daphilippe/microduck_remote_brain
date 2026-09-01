from __future__ import annotations

import io
import json

import pytest

from microduck_remote_brain.prerequisites import PrerequisiteError, verify_local_foundations


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_foundations_do_not_require_whisper(monkeypatch) -> None:
    response = Response(json.dumps({"models": [{"name": "brain:latest"}]}).encode())
    monkeypatch.setattr(
        "microduck_remote_brain.prerequisites.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    verify_local_foundations(ollama_models=("brain:latest",))


def test_foundations_require_all_local_ollama_models(tmp_path, monkeypatch) -> None:
    whisper = tmp_path / "whisper.exe"
    model = tmp_path / "whisper.bin"
    whisper.touch()
    model.touch()
    response = Response(
        json.dumps({"models": [{"name": "planner:latest"}]}).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.prerequisites.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(PrerequisiteError, match="vision:latest"):
        verify_local_foundations(
            whisper_executable=whisper,
            whisper_model=model,
            ollama_models=("planner:latest", "vision:latest"),
        )