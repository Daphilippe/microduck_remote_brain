from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from microduck_remote_brain.autonomous_cli import (
    _run_cycle,
    _run_stand_recovery,
    _write_status,
)
from microduck_remote_brain.executor import ExecutionError, ExecutionReason
from microduck_remote_brain.robotd import RobotCapabilities


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