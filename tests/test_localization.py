from __future__ import annotations

import math

import pytest

from microduck_remote_brain.executor import RobotState
from microduck_remote_brain.localization import RobotOdometryProvider
from microduck_remote_brain.mapping import Pose2D


class FakeRobot:
    def __init__(self, state: RobotState) -> None:
        self.state = state
        self.calls: list[object] = []

    def connect(self) -> None:
        self.calls.append("connect")

    def subscribe(self, hz: int) -> object:
        self.calls.append(("subscribe", hz))
        return {"accepted": True}

    def next_state(self, after_revision: int, timeout: float) -> RobotState:
        self.calls.append(("next_state", after_revision, timeout))
        return self.state

    def close(self) -> None:
        self.calls.append("close")


def test_robot_odometry_provider_uses_robot_state_pose() -> None:
    robot = FakeRobot(RobotState(4, 0.0, 0.0, 1.25, -0.5, 0.75, 12.5))
    provider = RobotOdometryProvider(robot)  # type: ignore[arg-type]

    provider.connect()
    pose = provider.read()
    provider.close()

    assert (pose.x_m, pose.y_m, pose.yaw_rad, pose.timestamp_s) == (1.25, -0.5, 0.75, 12.5)
    assert robot.calls == [
        "connect",
        ("subscribe", 10),
        ("next_state", 0, 2.0),
        "close",
    ]


def test_robot_odometry_provider_refuses_missing_pose() -> None:
    provider = RobotOdometryProvider(  # type: ignore[arg-type]
        FakeRobot(RobotState(1, 0.0, 0.0))
    )

    with pytest.raises(RuntimeError, match="does not provide odometry"):
        provider.read()


def test_robot_odometry_provider_applies_map_anchor() -> None:
    robot = FakeRobot(RobotState(1, 0.0, 0.0, 1.0, 2.0, 0.0, 1.0))
    provider = RobotOdometryProvider(robot)  # type: ignore[arg-type]
    provider.set_map_anchor(
        Pose2D(1.0, 2.0, 0.0, 1.0),
        Pose2D(5.0, 6.0, 0.5, 1.0),
    )
    robot.state = RobotState(2, 0.0, 0.0, 2.0, 2.0, 0.0, 2.0)

    pose = provider.read()

    assert pose.x_m == pytest.approx(5.0 + math.cos(0.5))
    assert pose.y_m == pytest.approx(6.0 + math.sin(0.5))
    assert pose.yaw_rad == pytest.approx(0.5)


def test_robot_odometry_provider_rejects_stationary_odom_jump() -> None:
    robot = FakeRobot(
        RobotState(
            1,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            gravity=(0.0, 0.0, -1.0),
            gyroscope=(0.0, 0.0, 0.0),
        )
    )
    provider = RobotOdometryProvider(robot)  # type: ignore[arg-type]
    first = provider.read()
    robot.state = RobotState(
        2,
        0.0,
        0.0,
        2.0,
        -1.5,
        1.0,
        1.1,
        gravity=(0.0, 0.0, -1.0),
        gyroscope=(0.0, 0.0, 0.0),
    )

    second = provider.read()

    assert second.x_m == pytest.approx(first.x_m)
    assert second.y_m == pytest.approx(first.y_m)
    assert second.yaw_rad == pytest.approx(first.yaw_rad)
    assert provider.pose_source == "robotd_inertial_odometry"


def test_robot_odometry_provider_uses_gyro_for_continuous_heading() -> None:
    robot = FakeRobot(
        RobotState(
            1,
            0.0,
            0.5,
            0.0,
            0.0,
            0.0,
            1.0,
            gravity=(0.0, 0.0, -1.0),
            gyroscope=(0.0, 0.0, 0.5),
        )
    )
    provider = RobotOdometryProvider(robot)  # type: ignore[arg-type]
    provider.read()
    robot.state = RobotState(
        2,
        0.0,
        0.5,
        0.0,
        0.0,
        0.2,
        1.2,
        gravity=(0.0, 0.0, -1.0),
        gyroscope=(0.0, 0.0, 0.5),
    )

    pose = provider.read()

    assert 0.1 <= pose.yaw_rad <= 0.2