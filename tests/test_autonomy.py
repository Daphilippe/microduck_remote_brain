from __future__ import annotations

import io
import json
from typing import Any

from microduck_remote_brain.autonomy import OllamaAutonomousPlanner


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_passive_autonomy_recovers_qwen_decision_from_thinking(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": "", "thinking": '{"action":"coo"}'}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    plan = OllamaAutonomousPlanner("qwen").plan("The room is dark.")

    assert [step.tool for step in plan.steps] == ["sound"]
    assert plan.steps[0].arguments == {"tag": "coo"}
    assert captured["format"]["properties"]["action"]["enum"] == [
        "coo",
        "inquire",
        "chirp",
        "stop",
    ]


def test_movement_decision_becomes_bounded_plan(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": '{"action":"walk_forward"}'}}).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomy.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    plan = OllamaAutonomousPlanner("qwen", allow_movement=True).plan("Clear empty floor.")

    assert [step.tool for step in plan.steps] == ["walk", "stop", "sound"]
    assert plan.steps[0].arguments["linear_velocity"] == 0.1


def test_persona_can_enable_robot_sound_commands(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": '{"action":"greet"}'}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    plan = OllamaAutonomousPlanner(
        "qwen",
        persona_prompt="You are a sociable MicroDuck.",
        sound_actions=("greet", "coo"),
    ).plan("A familiar person arrived.")

    assert plan.steps[0].arguments == {"tag": "greet"}
    assert "You are a sociable MicroDuck." in captured["messages"][0]["content"]


def test_persona_can_choose_a_bounded_double_sound(monkeypatch) -> None:
    response = Response(
        json.dumps(
            {
                "message": {
                    "content": '{"action":"chirp","sound_pattern":"double"}'
                }
            }
        ).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomy.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    plan = OllamaAutonomousPlanner("qwen").plan("A familiar person is playing nearby.")

    assert [step.arguments for step in plan.steps] == [
        {"tag": "chirp"},
        {"tag": "chirp"},
    ]