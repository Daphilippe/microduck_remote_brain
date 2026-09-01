from __future__ import annotations

import io
import json

from microduck_remote_brain.ollama import OllamaPlanner


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_planner_parses_structured_steps_and_adds_feedback(monkeypatch) -> None:
    generated = {
        "steps": [
            {
                "id": "walk",
                "tool": "walk",
                "arguments": {
                    "linear_velocity": 0.3,
                    "angular_velocity": 0.0,
                    "duration": 2.0,
                },
            }
        ],
        "requires_confirmation": False,
    }
    response = Response(
        json.dumps({"message": {"content": json.dumps(generated)}}).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.ollama.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    plan = OllamaPlanner("test-model").plan("walk forward")

    assert [step.tool for step in plan.steps] == ["walk", "sound"]
    assert plan.steps[-1].arguments == {"tag": "chirp"}