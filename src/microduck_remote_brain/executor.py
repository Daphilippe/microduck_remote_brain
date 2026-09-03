from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .gates import plan_is_allowed, validate_plan
from .model import ActionStep, Plan


class ExecutionReason(StrEnum):
    PLAN_DENIED = "plan.denied"
    CONNECTION_FAILED = "connection.failed"
    MOVEMENT_NOT_OBSERVED = "movement.not_observed"
    STOP_NOT_OBSERVED = "stop.not_observed"
    INSUFFICIENT_DISPLACEMENT = "movement.insufficient_displacement"
    ROBOT_PROTOCOL = "robot.protocol"
    ORACLE_PROTOCOL = "oracle.protocol"
    TRANSCRIPTION_FAILED = "transcription.failed"


class ExecutionError(RuntimeError):
    def __init__(self, reason: ExecutionReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RobotState:
    revision: int
    linear_velocity: float
    angular_velocity: float
    odom_x_m: float | None = None
    odom_y_m: float | None = None
    odom_yaw_rad: float | None = None
    timestamp_s: float | None = None
    lateral_velocity: float = 0.0
    gravity: tuple[float, float, float] | None = None
    gyroscope: tuple[float, float, float] | None = None
    quaternion: tuple[float, float, float, float] | None = None
    joints: tuple[float, ...] = ()
    joint_targets: tuple[float, ...] = ()

    @property
    def is_moving(self) -> bool:
        return not self.is_stopped()

    def is_stopped(self, tolerance: float = 1e-3) -> bool:
        return abs(self.linear_velocity) <= tolerance and abs(self.angular_velocity) <= tolerance


@dataclass(frozen=True, slots=True)
class BodySnapshot:
    trunk_x: float
    trunk_y: float
    sim_time: float
    yaw: float = 0.0


class RobotClient(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...

    def subscribe(self, hz: int) -> object: ...

    def move(self, linear_velocity: float, angular_velocity: float) -> None: ...

    def stop(self) -> None: ...

    def sound(self, tag: str) -> None: ...

    def skill(self, name: str) -> None: ...

    def look(self, x: float, y: float, z: float, neck_pitch: float = 0.0) -> None: ...

    def next_state(self, after_revision: int, timeout: float) -> RobotState: ...


class BodyOracle(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read(self) -> BodySnapshot: ...


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event: str
    plan_id: str
    step_id: str | None
    monotonic_time: float
    reason: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)


class PlanExecutor:
    def __init__(
        self,
        robot: RobotClient,
        *,
        oracle: BodyOracle | None = None,
        minimum_displacement: float | None = None,
        state_timeout: float = 1.0,
        refresh_hz: int = 10,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        event_sink: Callable[[LifecycleEvent], None] | None = None,
    ) -> None:
        if minimum_displacement is not None and (
            not math.isfinite(minimum_displacement) or minimum_displacement < 0
        ):
            raise ValueError("minimum_displacement must be finite and nonnegative")
        if minimum_displacement is not None and oracle is None:
            raise ValueError("minimum_displacement requires a BodyOracle")
        if not math.isfinite(state_timeout) or state_timeout <= 0:
            raise ValueError("state_timeout must be finite and positive")
        if isinstance(refresh_hz, bool) or not isinstance(refresh_hz, int) or refresh_hz <= 0:
            raise ValueError("refresh_hz must be a positive integer")
        self._robot = robot
        self._oracle = oracle
        self._minimum_displacement = minimum_displacement
        self._state_timeout = state_timeout
        self._refresh_hz = refresh_hz
        self._clock = clock
        self._sleep = sleep
        self._event_sink = event_sink
        self._revision = 0

    def execute(self, plan: Plan) -> tuple[LifecycleEvent, ...]:
        decisions = validate_plan(plan)
        if not plan_is_allowed(decisions):
            codes = [decision.code for decision in decisions if decision.status != "allow"]
            raise ExecutionError(ExecutionReason.PLAN_DENIED, ", ".join(codes))

        events: list[LifecycleEvent] = []

        def record(
            event: str,
            step_id: str | None = None,
            *,
            reason: str | None = None,
            **facts: Any,
        ) -> None:
            item = LifecycleEvent(
                event=event,
                plan_id=plan.plan_id,
                step_id=step_id,
                monotonic_time=self._clock(),
                reason=reason,
                facts=facts,
            )
            events.append(item)
            if self._event_sink is not None:
                self._event_sink(item)

        record("plan.started")
        try:
            self._robot.connect()
            self._robot.subscribe(self._refresh_hz)
            if self._oracle is not None:
                self._oracle.connect()
            for step in plan.steps:
                record("step.started", step.id, tool=step.tool)
                if step.tool == "walk":
                    self._execute_walk(step)
                elif step.tool == "stop":
                    self._stop_and_verify()
                elif step.tool == "skill":
                    self._robot.skill(str(step.arguments["name"]))
                elif step.tool == "look":
                    self._robot.look(
                        float(step.arguments["x"]),
                        float(step.arguments["y"]),
                        float(step.arguments["z"]),
                        float(step.arguments["neck_pitch"]),
                    )
                else:
                    self._robot.sound(str(step.arguments["tag"]))
                record("step.completed", step.id)
        except ExecutionError as error:
            record("plan.failed", reason=error.reason)
            raise
        except (OSError, TimeoutError, ValueError) as error:
            wrapped = ExecutionError(ExecutionReason.CONNECTION_FAILED, str(error))
            record("plan.failed", reason=wrapped.reason)
            raise wrapped from error
        else:
            record("plan.completed")
            return tuple(events)
        finally:
            if self._oracle is not None:
                self._oracle.close()
            self._robot.close()

    def _execute_walk(self, step: ActionStep) -> None:
        linear = float(step.arguments["linear_velocity"])
        angular = float(step.arguments["angular_velocity"])
        duration = float(step.arguments["duration"])
        oracle = self._oracle
        before = oracle.read() if oracle is not None and abs(linear) > 1e-3 else None
        primary_error: Exception | None = None
        try:
            deadline = self._clock() + duration
            observed_motion = False
            while self._clock() < deadline:
                self._robot.move(linear, angular)
                if not observed_motion:
                    observed_motion = self._wait_for_motion()
                remaining = deadline - self._clock()
                if remaining > 0:
                    self._sleep(min(1.0 / self._refresh_hz, remaining))
        except (ExecutionError, OSError, TimeoutError, ValueError) as error:
            primary_error = error
            raise
        finally:
            try:
                self._stop_and_verify()
            except (ExecutionError, OSError, TimeoutError, ValueError):
                if primary_error is None:
                    raise

        if before is not None and self._minimum_displacement is not None and oracle is not None:
            after = oracle.read()
            displacement = math.hypot(
                after.trunk_x - before.trunk_x, after.trunk_y - before.trunk_y
            )
            if displacement < self._minimum_displacement:
                raise ExecutionError(
                    ExecutionReason.INSUFFICIENT_DISPLACEMENT,
                    f"XY displacement {displacement:.6g} is below {self._minimum_displacement:.6g}",
                )

    def _stop_and_verify(self) -> None:
        self._robot.stop()
        for _ in range(self._maximum_state_samples()):
            state = self._fresh_state(ExecutionReason.STOP_NOT_OBSERVED)
            if state.is_stopped():
                return
        raise ExecutionError(
            ExecutionReason.STOP_NOT_OBSERVED,
            "robot.state did not report stopped applied velocity before timeout",
        )

    def _wait_for_motion(self) -> bool:
        for _ in range(self._maximum_state_samples()):
            state = self._fresh_state(ExecutionReason.MOVEMENT_NOT_OBSERVED)
            if state.is_moving:
                return True
        raise ExecutionError(
            ExecutionReason.MOVEMENT_NOT_OBSERVED,
            "robot.state did not report nonzero applied velocity before timeout",
        )

    def _maximum_state_samples(self) -> int:
        return max(1, math.ceil(self._state_timeout * self._refresh_hz) + 1)

    def _fresh_state(
        self,
        timeout_reason: ExecutionReason = ExecutionReason.ROBOT_PROTOCOL,
        timeout: float | None = None,
    ) -> RobotState:
        try:
            state = self._robot.next_state(
                self._revision, self._state_timeout if timeout is None else timeout
            )
        except TimeoutError as error:
            raise ExecutionError(timeout_reason, str(error)) from error
        if state.revision <= self._revision:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL,
                "robot.state was not newer than the previous evidence",
            )
        self._revision = state.revision
        return state