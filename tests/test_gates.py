from __future__ import annotations

from microduck_remote_brain.gates import plan_is_allowed, validate_plan
from microduck_remote_brain.model import GateStatus, Plan


def plan_with(*steps: dict, **overrides: object) -> Plan:
    value = {
        "schema_version": 1,
        "plan_id": "plan-1",
        "goal": "walk then stop",
        "steps": list(steps),
        "requires_confirmation": False,
    }
    value.update(overrides)
    return Plan.from_dict(value)


def walk_step(**arguments: float) -> dict:
    defaults = {
        "linear_velocity": 0.3,
        "angular_velocity": 0.0,
        "duration": 2.0,
    }
    defaults.update(arguments)
    return {"id": "walk-1", "tool": "walk", "arguments": defaults}


def test_bounded_walk_and_stop_are_allowed() -> None:
    plan = plan_with(walk_step(), {"id": "stop-1", "tool": "stop", "arguments": {}})

    decisions = validate_plan(plan)

    assert plan_is_allowed(decisions)
    assert decisions[-1].code == "plan.valid"


def test_velocity_over_limit_is_denied_with_stable_code() -> None:
    decisions = validate_plan(plan_with(walk_step(linear_velocity=0.31)))

    assert not plan_is_allowed(decisions)
    assert decisions[0].status is GateStatus.DENY
    assert decisions[0].code == "walk.linear_velocity_out_of_range"


def test_unknown_tool_fails_closed() -> None:
    plan = plan_with({"id": "raw-1", "tool": "set_motor", "arguments": {"joint": 2}})

    decisions = validate_plan(plan)

    assert decisions[0].code == "tool.unknown"
    assert decisions[0].facts["tool"] == "set_motor"


def test_unknown_walk_argument_is_denied() -> None:
    step = walk_step()
    step["arguments"]["joint"] = 2

    decisions = validate_plan(plan_with(step))

    assert decisions[0].code == "walk.arguments"
    assert decisions[0].facts["unknown"] == ["joint"]


def test_confirmation_prevents_execution() -> None:
    decisions = validate_plan(plan_with(walk_step(), requires_confirmation=True))

    assert not plan_is_allowed(decisions)
    assert decisions[-1].status is GateStatus.NEEDS_CONFIRMATION


def test_duplicate_step_ids_are_denied() -> None:
    step = walk_step()
    decisions = validate_plan(plan_with(step, step))

    assert decisions[0].code == "plan.step_ids"


def test_known_sound_is_allowed() -> None:
    plan = plan_with({"id": "sound-1", "tool": "sound", "arguments": {"tag": "chirp"}})

    assert plan_is_allowed(validate_plan(plan))


def test_unknown_sound_tag_is_denied() -> None:
    plan = plan_with({"id": "sound-1", "tool": "sound", "arguments": {"tag": "speech"}})

    decisions = validate_plan(plan)

    assert decisions[0].code == "sound.unknown_tag"