from __future__ import annotations

import base64
import io
import json
from typing import Any

from microduck_remote_brain.vision import OllamaVision


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_ollama_vision_sends_image_and_returns_observation(monkeypatch) -> None:
    response = Response(json.dumps({"message": {"content": "A clear floor."}}).encode())
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.vision.urllib.request.urlopen", urlopen)

    observation = OllamaVision("vision-model").describe(b"jpeg-data")

    assert observation == "A clear floor."
    assert captured["think"] is False
    assert captured["options"]["num_predict"] == 192
    message = captured["messages"][0]
    assert message["images"] == [base64.b64encode(b"jpeg-data").decode("ascii")]
    assert "Do not choose an action" in message["content"]
