from __future__ import annotations

from collections.abc import Iterable

import pytest

from microduck_remote_brain.executor import (
    BodySnapshot,
    ExecutionError,
    ExecutionReason,
    PlanExecutor,
    RobotState,
)
from microduck_remote_brain.model import Plan


def plan_with(*steps: dict) -> Plan:
    return Plan.from_dict(
        {
            "schema_version": 1,
            "plan_id": "plan-1",
            "goal": "execute M1 plan",
            "steps": list(steps),
        }
    )


def walk_step() -> dict:
    return {
        "id": "walk-1",
        "tool": "walk",
        "arguments": {"linear_velocity": 0.2, "angular_velocity": 0.0, "duration": 0.2},
    }


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration


class FakeRobot:
    def __init__(self, states: Iterable[RobotState]) -> None:
        self.states = iter(states)
        self.calls: list[object] = []

    def connect(self) -> None:
        self.calls.append("connect")

    def close(self) -> None:
        self.calls.append("close")

    def subscribe(self, hz: int) -> None:
        self.calls.append(("subscribe", hz))

    def move(self, linear_velocity: float, angular_velocity: float) -> None:
        self.calls.append(("move", linear_velocity, angular_velocity))

    def stop(self) -> None:
        self.calls.append("stop")

    def sound(self, tag: str) -> None:
        self.calls.append(("sound", tag))

    def next_state(self, after_revision: int, timeout: float) -> RobotState:
        self.calls.append(("state", after_revision, timeout))
        try:
            return next(self.states)
        except StopIteration as error:
            raise TimeoutError("no more fake states") from error


class FakeOracle:
    def __init__(self, snapshots: Iterable[BodySnapshot]) -> None:
        self.snapshots = iter(snapshots)
        self.calls: list[str] = []

    def connect(self) -> None:
        self.calls.append("connect")

    def close(self) -> None:
        self.calls.append("close")

    def read(self) -> BodySnapshot:
        self.calls.append("read")
        return next(self.snapshots)


def execute(
    robot: FakeRobot,
    plan: Plan,
    oracle: FakeOracle | None = None,
    minimum: float | None = None,
):
    clock = FakeClock()
    return PlanExecutor(
        robot,
        oracle=oracle,
        minimum_displacement=minimum,
        clock=clock,
        sleep=clock.sleep,
    ).execute(plan)


def test_allowed_walk_and_stop_execute_in_sequence() -> None:
    robot = FakeRobot(
        [
            RobotState(1, 0.2, 0.0),
            RobotState(2, 0.0, 0.0),
            RobotState(3, 0.0, 0.0),
        ]
    )
    plan = plan_with(walk_step(), {"id": "stop-1", "tool": "stop", "arguments": {}})

    events = execute(robot, plan)

    assert robot.calls.count(("move", 0.2, 0.0)) == 2
    assert robot.calls.count("stop") == 2
    assert [(event.event, event.step_id) for event in events] == [
        ("plan.started", None),
        ("step.started", "walk-1"),
        ("step.completed", "walk-1"),
        ("step.started", "stop-1"),
        ("step.completed", "stop-1"),
        ("plan.completed", None),
    ]
    assert all(event.plan_id == "plan-1" for event in events)


def test_walk_waits_for_smoothed_velocity_to_become_nonzero() -> None:
    robot = FakeRobot(
        [
            RobotState(1, 0.0, 0.0),
            RobotState(2, 0.04, 0.0),
            RobotState(3, 0.0, 0.0),
        ]
    )

    execute(robot, plan_with(walk_step()))

    assert robot.calls.count(("state", 0, 1.0)) == 1
    assert ("state", 1, 1.0) in robot.calls


def test_denied_plan_fails_before_connection() -> None:
    robot = FakeRobot([])
    denied = plan_with(
        {
            "id": "walk-1",
            "tool": "walk",
            "arguments": {"linear_velocity": 1.0, "angular_velocity": 0.0, "duration": 1.0},
        }
    )

    with pytest.raises(ExecutionError, match="walk.linear_velocity_out_of_range") as caught:
        execute(robot, denied)

    assert caught.value.reason is ExecutionReason.PLAN_DENIED
    assert robot.calls == []


def test_walk_failure_still_issues_explicit_stop() -> None:
    robot = FakeRobot([RobotState(1, 0.0, 0.0), RobotState(2, 0.0, 0.0)])

    with pytest.raises(ExecutionError) as caught:
        execute(robot, plan_with(walk_step()))

    assert caught.value.reason is ExecutionReason.MOVEMENT_NOT_OBSERVED
    assert "stop" in robot.calls


def test_no_observed_movement_has_stable_reason() -> None:
    robot = FakeRobot([RobotState(1, 0.0, 0.0), RobotState(2, 0.0, 0.0)])

    with pytest.raises(ExecutionError) as caught:
        execute(robot, plan_with(walk_step()))

    assert caught.value.reason == "movement.not_observed"


def test_insufficient_displacement_fails_after_verified_stop() -> None:
    robot = FakeRobot([RobotState(1, 0.2, 0.0), RobotState(2, 0.0, 0.0)])
    oracle = FakeOracle(
        [BodySnapshot(1.0, 2.0, 0.0), BodySnapshot(1.01, 2.0, 0.2)]
    )

    with pytest.raises(ExecutionError) as caught:
        execute(robot, plan_with(walk_step()), oracle, minimum=0.02)

    assert caught.value.reason is ExecutionReason.INSUFFICIENT_DISPLACEMENT
    assert robot.calls[-2:] == [("state", 1, 1.0), "close"]


def test_sound_is_dispatched_as_a_discrete_action() -> None:
    robot = FakeRobot([])
    plan = plan_with({"id": "sound-1", "tool": "sound", "arguments": {"tag": "chirp"}})

    execute(robot, plan)

    assert ("sound", "chirp") in robot.calls