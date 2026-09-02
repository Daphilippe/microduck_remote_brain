from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from microduck_remote_brain.autonomous_cli import _run_stand_recovery, _write_status


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