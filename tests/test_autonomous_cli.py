from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from microduck_remote_brain.autonomous_cli import (
    _capture_action_anchor,
    _run_cycle,
    _run_localization_scan,
    _run_stand_recovery,
    _run_visual_recovery,
    _update_mapping,
    _write_status,
)
from microduck_remote_brain.autonomy import ActuatorResolver
from microduck_remote_brain.episode_memory import EpisodeMemory
from microduck_remote_brain.executor import ExecutionError, ExecutionReason
from microduck_remote_brain.mapping import (
    ExplorationPolicy,
    MappingSession,
    OccupancyGridMapper,
    Pose2D,
)
from microduck_remote_brain.perception import DepthObservation
from microduck_remote_brain.robotd import RobotCapabilities
from microduck_remote_brain.scene import SceneState


def test_status_write_retries_transient_windows_sharing_violation(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "autonomy-state.json"
    original_replace = Path.replace
    attempts = 0

    def replace(source: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("file is temporarily open")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace)

    _write_status(path, state="observing", message="Interpreting scene")

    assert attempts == 2
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "observing"


def test_stand_recovery_runs_without_perception(monkeypatch, tmp_path) -> None:
    plans = []

    class FakeAudit:
        def write(self, *_args, **_kwargs) -> None:
            pass

    def execute(_config, plan, *_args) -> bool:
        plans.append(plan)
        return True

    monkeypatch.setattr("microduck_remote_brain.autonomous_cli._execute_plan", execute)
    context = SimpleNamespace(
        config=object(),
        audit=FakeAudit(),
        pause_file=None,
        activity_file=None,
        status_file=tmp_path / "status.json",
        recent_behaviors=["walk_forward", "sit_toggle"],
        last_behavior={},
    )

    assert _run_stand_recovery(context)

    assert [step.tool for step in plans[0].steps] == ["skill", "sound"]
    assert plans[0].steps[0].arguments == {"name": "sit_toggle"}
    assert context.recent_behaviors[-1] == "stand_up"
    assert context.last_behavior["intent"] == {"action": "stand_up"}


def test_invalid_semantic_scene_triggers_head_scan_without_persona(
    monkeypatch, tmp_path
) -> None:
    plans = []

    class FakePerception:
        def capture(self) -> bytes:
            return b"jpeg"

    class InvalidVision:
        def interpret(self, _image: bytes):
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL,
                "Ollama vision returned an invalid scene state",
            )

    class ForbiddenPersona:
        def decide(self, *_args, **_kwargs):
            raise AssertionError("persona must not receive an invalid scene")

    class FakeAudit:
        def write(self, *_args, **_kwargs) -> None:
            pass

    def execute(_config, plan, *_args) -> bool:
        plans.append(plan)
        return True

    monkeypatch.setattr("microduck_remote_brain.autonomous_cli._execute_plan", execute)
    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._robot_capabilities",
        lambda _config: RobotCapabilities("walk", frozenset()),
    )
    context = SimpleNamespace(
        config=object(),
        perception=FakePerception(),
        vision=InvalidVision(),
        persona=ForbiddenPersona(),
        audit=FakeAudit(),
        pause_file=None,
        activity_file=None,
        status_file=tmp_path / "status.json",
        recent_behaviors=[],
        last_behavior={},
    )

    assert _run_cycle(context)
    assert _run_cycle(context)

    assert [[step.tool for step in plan.steps] for plan in plans] == [
        ["stop", "look"],
        ["stop", "look"],
    ]
    assert plans[0].steps[1].arguments["y"] == 0.35
    assert plans[1].steps[1].arguments["y"] == -0.35
    assert context.recent_behaviors[-2:] == ["scan_left", "scan_right"]


def test_unusable_camera_frame_triggers_head_scan_before_vision(
    monkeypatch, tmp_path
) -> None:
    plans = []

    class UnreadyPerception:
        def capture(self) -> bytes:
            raise RuntimeError("camera frame is not ready")

    class ForbiddenVision:
        def interpret(self, _image: bytes):
            raise AssertionError("vision must not receive an unusable camera frame")

    class FakeAudit:
        def write(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._execute_plan",
        lambda _config, plan, *_args: plans.append(plan) or True,
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._robot_capabilities",
        lambda _config: RobotCapabilities("walk", frozenset()),
    )
    context = SimpleNamespace(
        config=object(),
        perception=UnreadyPerception(),
        vision=ForbiddenVision(),
        audit=FakeAudit(),
        pause_file=None,
        activity_file=None,
        status_file=tmp_path / "status.json",
        recent_behaviors=[],
        last_behavior={},
    )

    assert _run_cycle(context)

    assert [step.tool for step in plans[0].steps] == ["stop", "look"]
    assert context.recent_behaviors == ["scan_left"]


def test_failed_complete_head_scan_reorients_body_toward_clearer_side(
    monkeypatch, tmp_path
) -> None:
    plans = []

    class FakeAudit:
        def write(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._execute_plan",
        lambda _config, plan, *_args: plans.append(plan) or True,
    )
    context = SimpleNamespace(
        config=object(),
        audit=FakeAudit(),
        pause_file=None,
        activity_file=None,
        status_file=tmp_path / "status.json",
        recent_behaviors=["scan_left", "scan_right", "scan_center"],
        last_behavior={},
    )
    error = ExecutionError(
        ExecutionReason.ROBOT_PROTOCOL,
        "Ollama vision returned an invalid scene state",
    )

    assert _run_visual_recovery(
        context,
        error,
        DepthObservation((), 500.0, 200.0, 300.0),
        RobotCapabilities("walk", frozenset()),
        100,
    )

    assert [step.tool for step in plans[0].steps] == ["walk", "stop", "sound"]
    assert plans[0].steps[0].arguments == {
        "linear_velocity": 0.0,
        "angular_velocity": 0.5,
        "duration": 1.5,
    }
    assert context.recent_behaviors[-1] == "reorient_left"


def test_invalid_scene_recovery_scans_up_after_right_view(monkeypatch) -> None:
    plans = []
    context = SimpleNamespace(
        config=object(),
        audit=SimpleNamespace(write=lambda *_args, **_kwargs: None),
        pause_file=None,
        activity_file=None,
        status_file=None,
        recent_behaviors=["scan_left", "scan_right"],
        last_behavior={},
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._execute_plan",
        lambda _config, plan, *_args: plans.append(plan) or True,
    )

    assert _run_visual_recovery(
        context,
        ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "invalid scene"),
        None,
        RobotCapabilities("walk", frozenset()),
        100,
    )

    assert context.recent_behaviors[-1] == "scan_up"
    assert plans[0].steps[1].arguments["z"] == 0.35


def test_mapping_update_uses_simulator_pose_depth_and_image(tmp_path) -> None:
    events = []

    class FakePoseProvider:
        def read(self) -> Pose2D:
            return Pose2D(0.0, 0.0, 0.0, 4.0)

        def set_map_anchor(self, _odom_pose: Pose2D, _map_pose: Pose2D) -> None:
            pass

    class FakeAudit:
        def write(self, event, **facts) -> None:
            events.append((event, facts))

    map_path = tmp_path / "map.json"
    context = SimpleNamespace(
        config=SimpleNamespace(mapping_path=map_path),
        mapping_session=MappingSession(
            OccupancyGridMapper(resolution_m=0.5, width=20, height=20),
            map_path,
            keyframe_directory=tmp_path / "keyframes",
        ),
        mapping_pose_provider=FakePoseProvider(),
        exploration_policy=ExplorationPolicy(),
        audit=FakeAudit(),
    )
    depth = DepthObservation((1000.0,) * 64, 1000.0, 1000.0, 1000.0)

    _update_mapping(context, b"jpeg", depth)

    assert map_path.exists()
    mapping_event = next(facts for event, facts in events if event == "mapping.updated")
    assert mapping_event["revision"] == 1
    assert mapping_event["changed_cells"] > 0
    assert mapping_event["map_path"] == str(map_path)


def test_unmatched_startup_localization_runs_bounded_turn(monkeypatch) -> None:
    plans = []
    context = SimpleNamespace(
        exploration_policy=ExplorationPolicy(startup_scan_turns=2),
        status_file=None,
        audit=SimpleNamespace(write=lambda *_args, **_kwargs: None),
        config=object(),
        pause_file=None,
        activity_file=None,
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._execute_plan",
        lambda _config, plan, *_args: plans.append(plan) or True,
    )

    assert _run_localization_scan(
        context, DepthObservation((), 900.0, 900.0, 900.0)
    )
    assert plans[0].steps[0].arguments == {
        "linear_velocity": 0.0,
        "angular_velocity": 0.5,
        "duration": 1.0,
    }


def test_action_anchor_reuses_robot_odometry_pose() -> None:
    class FakePoseProvider:
        def read(self) -> Pose2D:
            return Pose2D(1.25, -0.5, 0.75, 7.0)

    context = SimpleNamespace(
        mapping_pose_provider=FakePoseProvider(),
    )

    assert _capture_action_anchor(context) == {
        "x_m": 1.25,
        "y_m": -0.5,
        "yaw_rad": 0.75,
        "timestamp_s": 7.0,
    }


def test_cycle_turns_around_when_approached_interest_disappears(
    monkeypatch, tmp_path
) -> None:
    plans = []
    memory = EpisodeMemory()
    approached_scene = SceneState.from_dict(
        {
            "summary": "A red ball is centered nearby",
            "entities": [
                {
                    "kind": "ball",
                    "bearing": "center",
                    "proximity": "mid",
                    "confidence": 0.9,
                }
            ],
            "free_floor": "clear",
            "visibility": "good",
            "hazards": [],
        }
    )
    current_scene = SceneState.from_dict(
        {
            "summary": "The ball is now too close to see",
            "entities": [],
            "free_floor": "clear",
            "visibility": "good",
            "hazards": [],
        }
    )

    class FakePerception:
        def capture(self) -> bytes:
            return b"jpeg"

        def capture_depth(self) -> DepthObservation:
            return DepthObservation((), 600.0, 180.0, 300.0)

    class ForbiddenPersona:
        def decide(self, *_args, **_kwargs):
            raise AssertionError("deterministic memory recovery must bypass the persona")

    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli.SimulatorPerception", FakePerception
    )
    memory.remember(approached_scene, None, "walk_forward")
    context = SimpleNamespace(
        config=object(),
        perception=FakePerception(),
        vision=SimpleNamespace(interpret=lambda _image: current_scene),
        persona=ForbiddenPersona(),
        actuators=ActuatorResolver(allow_movement=True),
        audit=SimpleNamespace(write=lambda *_args, **_kwargs: None),
        pause_file=None,
        activity_file=None,
        status_file=tmp_path / "status.json",
        drop_memory=SimpleNamespace(update=lambda value: value),
        mapping_session=None,
        mapping_pose_provider=None,
        mapping_worker=None,
        exploration_policy=ExplorationPolicy(),
        episode_memory=memory,
        recent_behaviors=["walk_forward"],
        last_behavior={},
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._robot_capabilities",
        lambda _config: RobotCapabilities("walk", frozenset()),
    )
    monkeypatch.setattr(
        "microduck_remote_brain.autonomous_cli._execute_plan",
        lambda _config, plan, *_args: plans.append(plan) or True,
    )
    try:
        assert _run_cycle(context)
    finally:
        memory.close()

    assert context.recent_behaviors[-1] == "turn_around_left"
    assert plans[0].steps[0].arguments["duration"] == 6.3