from __future__ import annotations

import base64
import io
import json
from typing import Any

import pytest

from microduck_remote_brain.executor import ExecutionError
from microduck_remote_brain.vision import OllamaVision


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_ollama_vision_sends_image_and_returns_scene(monkeypatch) -> None:
    scene_value = {
        "summary": "A clear floor.",
        "entities": [],
        "free_floor": "clear",
        "visibility": "good",
        "hazards": [],
        "visual_content": "informative",
    }
    response = Response(
        json.dumps({"message": {"content": json.dumps(scene_value)}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.vision.urllib.request.urlopen", urlopen)

    scene = OllamaVision("vision-model").interpret(b"jpeg-data")

    assert scene.summary == "A clear floor."
    assert scene.free_floor == "clear"
    assert captured["think"] is False
    assert captured["options"]["num_ctx"] == 4096
    assert captured["format"]["properties"]["free_floor"]["enum"] == [
        "clear",
        "blocked",
        "unknown",
    ]
    assert captured["format"]["properties"]["visual_content"]["enum"] == [
        "informative",
        "uniform",
        "unknown",
    ]
    assert captured["options"]["num_predict"] == 320
    message = captured["messages"][0]
    assert message["images"] == [base64.b64encode(b"jpeg-data").decode("ascii")]
    assert "continuous traversable floor area" in message["content"]
    assert "ordinary floor pattern is not a hazard" in message["content"]
    assert "visibly small enough for MicroDuck to manipulate" in message["content"]
    assert "Do not choose an action" in message["content"]


def test_ollama_vision_rejects_unstructured_output(monkeypatch) -> None:
    response = Response(json.dumps({"message": {"content": "A clear floor."}}).encode())
    monkeypatch.setattr(
        "microduck_remote_brain.vision.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(ExecutionError, match="invalid scene state"):
        OllamaVision("vision-model").interpret(b"jpeg-data")
