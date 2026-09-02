from __future__ import annotations

import argparse

import pytest

from microduck_remote_brain.voice_cli import _execute_text


def test_voice_execution_is_blocked_by_global_action_latch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disabled = tmp_path / "actions-disabled"
    disabled.touch()
    args = argparse.Namespace(actions_disabled_file=disabled)
    planner_called = False

    def fail_if_planner_is_created(*_args, **_kwargs):
        nonlocal planner_called
        planner_called = True
        raise AssertionError("planner must not run while actions are disabled")

    monkeypatch.setattr(
        "microduck_remote_brain.voice_cli.OllamaPlanner", fail_if_planner_is_created
    )

    with pytest.raises(RuntimeError, match="all robot actions are disabled"):
        _execute_text("walk forward", args)

    assert planner_called is False
