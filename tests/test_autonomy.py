from __future__ import annotations

import io
import json
from typing import Any

from microduck_remote_brain.autonomy import ActuatorResolver, OllamaPersonaModel, PersonaIntent
from microduck_remote_brain.perception import DepthObservation
from microduck_remote_brain.robotd import RobotCapabilities
from microduck_remote_brain.scene import SceneState


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def scene(
    summary: str,
    *,
    free_floor: str = "unknown",
    visibility: str = "good",
    hazards: list[str] | None = None,
) -> SceneState:
    return SceneState.from_dict(
        {
            "summary": summary,
            "entities": [],
            "free_floor": free_floor,
            "visibility": visibility,
            "hazards": hazards or [],
        }
    )


def decision(action: str, *, sound_pattern: str = "single") -> str:
    return json.dumps(
        {
            "action": action,
            "sound_pattern": sound_pattern,
            "voice_style": "curious",
            "utterance": "",
        }
    )


def depth(left: float, center: float, right: float) -> DepthObservation:
    return DepthObservation((), left, center, right)


def capabilities(
    mode: str = "walk",
    skills: tuple[str, ...] = (
        "sit_toggle",
        "ground_pick",
        "kick_left",
        "kick_right",
        "roulade",
    ),
) -> RobotCapabilities:
    return RobotCapabilities(mode, frozenset(skills))


def test_passive_autonomy_recovers_qwen_decision_from_thinking(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": "", "thinking": decision("coo")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    intent = OllamaPersonaModel("qwen").decide(scene("The room is dark."))
    plan = ActuatorResolver().resolve(intent, scene("The room is dark."))

    assert [step.tool for step in plan.steps] == ["sound"]
    assert plan.steps[0].arguments == {"tag": "coo"}
    assert captured["format"]["properties"]["action"]["enum"] == [
        "coo",
        "inquire",
        "chirp",
        "stop",
    ]
    assert captured["options"]["num_ctx"] == 4096


def test_movement_decision_becomes_bounded_plan(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("walk_forward")}}).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomy.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    current_scene = scene("Clear empty floor.", free_floor="clear")
    intent = OllamaPersonaModel("qwen", allow_movement=True).decide(current_scene)
    plan = ActuatorResolver(allow_movement=True).resolve(intent, current_scene)

    assert [step.tool for step in plan.steps] == ["walk", "stop", "sound"]
    assert plan.steps[0].arguments == {
        "linear_velocity": 0.3,
        "angular_velocity": 0.0,
        "duration": 4.0,
    }


def test_stop_decision_remains_observable(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("stop")}}).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomy.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    current_scene = scene("Walls are close.", free_floor="blocked")
    intent = OllamaPersonaModel("qwen").decide(current_scene)
    plan = ActuatorResolver().resolve(intent, current_scene)

    assert [step.tool for step in plan.steps] == ["stop", "sound"]
    assert plan.steps[1].arguments == {"tag": "coo"}


def test_persona_can_enable_robot_sound_commands(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("greet")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    current_scene = scene("A familiar person arrived.")
    intent = OllamaPersonaModel(
        "qwen",
        persona_prompt="You are a sociable MicroDuck.",
        sound_actions=("greet", "coo"),
    ).decide(current_scene)
    plan = ActuatorResolver(sound_actions=("greet", "coo")).resolve(intent, current_scene)

    assert plan.steps[0].arguments == {"tag": "greet"}
    assert "You are a sociable MicroDuck." in captured["messages"][0]["content"]


def test_persona_can_choose_a_bounded_double_sound(monkeypatch) -> None:
    response = Response(
        json.dumps(
            {
                "message": {
                    "content": decision("chirp", sound_pattern="double")
                }
            }
        ).encode()
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomy.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    current_scene = scene("A familiar person is playing nearby.")
    intent = OllamaPersonaModel("qwen").decide(current_scene)
    plan = ActuatorResolver().resolve(intent, current_scene)

    assert [step.arguments for step in plan.steps] == [
        {"tag": "chirp"},
        {"tag": "chirp"},
    ]


def test_persona_receives_bounded_recent_behavior_context(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("coo")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    OllamaPersonaModel("qwen").decide(
        scene("The floor is clear.", free_floor="clear"),
        recent_behaviors=("coo", "stop+coo"),
    )

    content = captured["messages"][0]["content"]
    assert "Recent behaviors, oldest first: coo, stop+coo" in content


def test_resolver_downgrades_movement_when_scene_is_unsafe() -> None:
    current_scene = scene("An obstacle is ahead.", free_floor="blocked", hazards=["obstacle"])

    plan = ActuatorResolver(allow_movement=True).resolve(
        PersonaIntent("walk_forward", "single", "concerned", ""),
        current_scene,
    )

    assert [step.tool for step in plan.steps] == ["stop", "sound"]


def test_resolver_allows_cautious_turn_when_floor_is_unknown() -> None:
    current_scene = scene("The surroundings are uncertain.")

    plan = ActuatorResolver(allow_movement=True).resolve(
        PersonaIntent("turn_left", "single", "curious", "Let me look around."),
        current_scene,
    )

    assert plan.steps[0].tool == "walk"
    assert plan.steps[0].arguments["angular_velocity"] == 0.5


def test_persona_scans_head_when_scene_context_is_insufficient(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("scan_left")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("The surroundings are uncertain."),
        recent_behaviors=("coo",),
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["scan_left"]


def test_near_floor_does_not_block_safe_motion(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("walk_forward")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)
    current_scene = SceneState.from_dict(
        {
            "summary": "An open checkered floor is visible ahead.",
            "entities": [
                {
                    "kind": "floor",
                    "bearing": "center",
                    "proximity": "near",
                    "confidence": 0.98,
                }
            ],
            "free_floor": "clear",
            "visibility": "good",
            "hazards": [],
        }
    )

    intent = OllamaPersonaModel("qwen", allow_movement=True).decide(
        current_scene,
        recent_behaviors=("greet", "coo"),
    )
    plan = ActuatorResolver(allow_movement=True).resolve(intent, current_scene)

    assert captured["format"]["properties"]["action"]["enum"] == [
        "walk_forward",
        "curve_left",
        "curve_right",
        "turn_left",
        "turn_right",
    ]
    assert plan.steps[0].tool == "walk"
    assert plan.steps[0].arguments["linear_velocity"] == 0.3


def test_no_hazard_label_does_not_block_forward_motion() -> None:
    current_scene = scene(
        "The floor is clear and no hazard is visible.",
        free_floor="clear",
        hazards=["none"],
    )

    plan = ActuatorResolver(allow_movement=True).resolve(
        PersonaIntent("walk_forward", "single", "curious", "Let's explore."),
        current_scene,
    )

    assert plan.steps[0].tool == "walk"
    assert plan.steps[0].arguments["linear_velocity"] == 0.3


def test_tof_obstacle_forces_turn_toward_clearer_side(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("turn_left")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)
    current_scene = scene("An obstacle is directly ahead.", hazards=[])
    current_depth = depth(900, 240, 500)

    intent = OllamaPersonaModel("qwen", allow_movement=True).decide(
        current_scene, depth=current_depth
    )
    plan = ActuatorResolver(allow_movement=True).resolve(
        intent, current_scene, current_depth
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["turn_left"]
    assert "left_clearance_mm" in captured["messages"][0]["content"]
    assert plan.steps[0].arguments["angular_velocity"] == 0.5


def test_first_safe_cycle_offers_only_physical_behavior(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("curve_left")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("An unfamiliar open space.", free_floor="clear"),
        depth=depth(600, 450, 550),
    )

    actions = captured["format"]["properties"]["action"]["enum"]
    assert actions == [
        "walk_forward",
        "curve_left",
        "curve_right",
        "turn_left",
        "turn_right",
    ]
    assert "stop" not in actions
    assert "coo" not in actions


def test_tof_clearance_overrides_uncertain_ordinary_visual_obstacle() -> None:
    current_scene = SceneState.from_dict(
        {
            "summary": "An unfamiliar object is nearby but the path continues.",
            "entities": [
                {
                    "kind": "furniture",
                    "bearing": "left",
                    "proximity": "near",
                    "confidence": 0.8,
                }
            ],
            "free_floor": "unknown",
            "visibility": "good",
            "hazards": ["possible obstacle"],
        }
    )
    current_depth = depth(450, 420, 430)

    plan = ActuatorResolver(allow_movement=True).resolve(
        PersonaIntent("walk_forward", "single", "curious", "Let's investigate."),
        current_scene,
        current_depth,
    )

    assert plan.steps[0].tool == "walk"
    assert plan.steps[0].arguments["linear_velocity"] == 0.3


def test_tof_obstacle_backs_up_when_both_sides_are_blocked(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("back_up")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("Surrounded by obstacles."), depth=depth(200, 180, 220)
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["back_up"]


def test_remembered_center_drop_forces_inspection_and_blocks_forward(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("turn_left")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)
    remembered_drop = DepthObservation(
        (), 900, 900, 600, ("center",), drop_hazard_remembered=True
    )
    current_scene = scene("A possible stair edge was seen below.", free_floor="clear")

    intent = OllamaPersonaModel("qwen", allow_movement=True).decide(
        current_scene, depth=remembered_drop
    )
    plan = ActuatorResolver(allow_movement=True).resolve(
        intent, current_scene, remembered_drop
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["turn_left"]
    assert plan.steps[0].arguments["linear_velocity"] == 0.0


def test_drop_across_all_sectors_forces_stop(monkeypatch) -> None:
    response = Response(json.dumps({"message": {"content": decision("stop")}}).encode())
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)
    drop = DepthObservation(
        (), 1000, 1000, 1000, ("left", "center", "right"), True
    )

    OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("A drop is visible below."), depth=drop
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["stop"]


def test_near_ball_can_be_captured_with_existing_ground_pick_skill() -> None:
    current_scene = SceneState.from_dict(
        {
            "summary": "A small ball is on the floor directly ahead.",
            "entities": [
                {
                    "kind": "ball",
                    "bearing": "center",
                    "proximity": "near",
                    "confidence": 0.98,
                }
            ],
            "free_floor": "blocked",
            "visibility": "good",
            "hazards": [],
        }
    )
    current_depth = depth(700, 260, 700)

    plan = ActuatorResolver(allow_movement=True).resolve(
        PersonaIntent("ground_pick", "single", "curious", "Got it."),
        current_scene,
        current_depth,
        capabilities(),
    )

    assert [step.tool for step in plan.steps] == ["skill", "sound"]
    assert plan.steps[0].arguments == {"name": "ground_pick"}


def test_scan_moves_head_only_after_holding_body_still() -> None:
    current_scene = scene("Visibility is uncertain.", visibility="unknown")

    plan = ActuatorResolver(allow_movement=True).resolve(
        PersonaIntent("scan_right", "single", "curious", "Looking around."),
        current_scene,
    )

    assert [step.tool for step in plan.steps] == ["stop", "look"]
    assert plan.steps[1].arguments == {
        "x": 0.5,
        "y": -0.35,
        "z": 0.0,
        "neck_pitch": 0.0,
    }


def test_head_scan_completes_left_right_center_sequence(monkeypatch) -> None:
    responses = iter(
        [
            Response(json.dumps({"message": {"content": decision(action)}}).encode())
            for action in ("scan_left", "scan_right", "scan_center")
        ]
    )
    captured_actions: list[list[str]] = []

    def urlopen(request, **_kwargs):
        captured_actions.append(
            json.loads(request.data)["format"]["properties"]["action"]["enum"]
        )
        return next(responses)

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)
    model = OllamaPersonaModel("qwen", allow_movement=True)

    first = model.decide(scene("Too dark.", visibility="poor"))
    second = model.decide(
        scene("Left side is visible.", free_floor="clear"),
        recent_behaviors=(first.action,),
    )
    model.decide(
        scene("Right side is visible.", free_floor="clear"),
        recent_behaviors=(first.action, second.action),
    )

    assert captured_actions == [["scan_left"], ["scan_right"], ["scan_center"]]


def test_walk_mode_offers_occasional_loaded_special_actions(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("roulade")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    intent = OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("Open space.", free_floor="clear"),
        depth=depth(900, 900, 900),
        capabilities=capabilities(),
        recent_behaviors=("walk_forward", "curve_left", "coo", "turn_right"),
    )
    plan = ActuatorResolver(allow_movement=True).resolve(
        intent,
        scene("Open space.", free_floor="clear"),
        depth(900, 900, 900),
        capabilities(),
    )

    assert captured["format"]["properties"]["action"]["enum"] == [
        "roulade",
        "sit_toggle",
        "sing",
    ]
    assert plan.steps[0].arguments == {"name": "roulade"}


def test_roller_mode_filters_leg_dependent_special_actions(monkeypatch) -> None:
    response = Response(json.dumps({"message": {"content": decision("sing")}}).encode())
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("Open space.", free_floor="clear"),
        depth=depth(900, 900, 900),
        capabilities=capabilities(mode="roller"),
        recent_behaviors=("walk_forward", "curve_left", "coo", "turn_right"),
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["sing"]


def test_sit_toggle_is_followed_by_stand_recovery(monkeypatch) -> None:
    response = Response(
        json.dumps({"message": {"content": decision("sit_toggle")}}).encode()
    )
    captured: dict[str, Any] = {}

    def urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return response

    monkeypatch.setattr("microduck_remote_brain.autonomy.urllib.request.urlopen", urlopen)

    OllamaPersonaModel("qwen", allow_movement=True).decide(
        scene("A calm open area.", free_floor="clear"),
        depth=depth(500, 500, 500),
        capabilities=capabilities(),
        recent_behaviors=("sit_toggle",),
    )

    assert captured["format"]["properties"]["action"]["enum"] == ["sit_toggle"]