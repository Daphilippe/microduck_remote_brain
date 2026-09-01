from __future__ import annotations

import io
import json
from typing import Any

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


def test_planner_recovers_qwen_plan_from_thinking(monkeypatch) -> None:
    generated = {
        "steps": [{"id": "greet", "tool": "sound", "arguments": {"tag": "greet"}}],
        "requires_confirmation": False,
    }
    response = Response(
        json.dumps(
            {"message": {"content": "", "thinking": json.dumps(generated)}}
        ).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.ollama.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    plan = OllamaPlanner("qwen3-vl:8b").plan("make a friendly sound")

    assert plan.steps[0].arguments == {"tag": "greet"}


def test_planner_sends_visual_observation_as_untrusted_autonomous_context(monkeypatch) -> None:
    generated = {
        "steps": [{"id": "wait", "tool": "sound", "arguments": {"tag": "coo"}}],
        "requires_confirmation": False,
    }
    response = Response(
        json.dumps({"message": {"content": json.dumps(generated)}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.ollama.urllib.request.urlopen", urlopen)

    OllamaPlanner("test-model").plan(
        "Choose your next small action.",
        visual_observation="A person is reading beside the duck.",
        autonomous=True,
    )

    messages = captured["messages"]
    user_message = messages[1]["content"]
    assert captured["think"] is False
    assert "untrusted sensor data" in user_message
    assert "A person is reading beside the duck." in user_message
    assert "MicroDuck's place" in user_message


def test_planner_can_disable_native_json_schema(monkeypatch) -> None:
    generated = {
        "steps": [{"id": "quiet", "tool": "sound", "arguments": {"tag": "coo"}}],
        "requires_confirmation": False,
    }
    response = Response(
        json.dumps({"message": {"content": json.dumps(generated)}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.ollama.urllib.request.urlopen", urlopen)

    plan = OllamaPlanner("qwen", use_json_schema=False).plan("remain safe")

    assert plan.steps[0].tool == "sound"
    assert "format" not in captured
    assert captured["options"]["num_predict"] == 128
    assert "Walk only when the floor" in captured["messages"][0]["content"]