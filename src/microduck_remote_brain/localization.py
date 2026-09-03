from __future__ import annotations

import math
import time
from collections.abc import Callable

from .mapping import INERTIAL_ODOMETRY_POSE_SOURCE, ODOMETRY_POSE_SOURCE, Pose2D
from .robotd import RobotdClient


class RobotOdometryProvider:
    def __init__(
        self,
        robot: RobotdClient,
        *,
        subscription_hz: int = 10,
        timeout_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._robot = robot
        self._subscription_hz = subscription_hz
        self._timeout_s = timeout_s
        self._clock = clock
        self._revision = 0
        self._odom_anchor: Pose2D | None = None
        self._map_anchor: Pose2D | None = None
        self._last_raw_pose: Pose2D | None = None
        self._fused_pose: Pose2D | None = None
        self._pose_source = ODOMETRY_POSE_SOURCE

    @property
    def pose_source(self) -> str:
        return self._pose_source

    def connect(self) -> None:
        self._robot.connect()
        self._robot.subscribe(self._subscription_hz)

    def close(self) -> None:
        self._robot.close()

    def read(self) -> Pose2D:
        state = self._robot.next_state(self._revision, self._timeout_s)
        self._revision = state.revision
        if (
            state.odom_x_m is None
            or state.odom_y_m is None
            or state.odom_yaw_rad is None
        ):
            raise RuntimeError("robot.state does not provide odometry for mapping")
        timestamp = state.timestamp_s if state.timestamp_s is not None else self._clock()
        raw_pose = Pose2D(state.odom_x_m, state.odom_y_m, state.odom_yaw_rad, timestamp)
        odom_pose = self._fuse(raw_pose, state)
        if self._odom_anchor is None or self._map_anchor is None:
            return odom_pose
        yaw_delta = self._map_anchor.yaw_rad - self._odom_anchor.yaw_rad
        delta_x = odom_pose.x_m - self._odom_anchor.x_m
        delta_y = odom_pose.y_m - self._odom_anchor.y_m
        return Pose2D(
            self._map_anchor.x_m
            + math.cos(yaw_delta) * delta_x
            - math.sin(yaw_delta) * delta_y,
            self._map_anchor.y_m
            + math.sin(yaw_delta) * delta_x
            + math.cos(yaw_delta) * delta_y,
            _normalize_angle(odom_pose.yaw_rad + yaw_delta),
            timestamp,
        )

    def _fuse(self, raw_pose: Pose2D, state: object) -> Pose2D:
        if any(
            getattr(state, field, None) is not None
            for field in ("gravity", "gyroscope", "quaternion")
        ):
            self._pose_source = INERTIAL_ODOMETRY_POSE_SOURCE
        previous_raw = self._last_raw_pose
        previous_fused = self._fused_pose
        self._last_raw_pose = raw_pose
        if previous_raw is None or previous_fused is None:
            self._fused_pose = raw_pose
            return raw_pose

        delta_time = raw_pose.timestamp_s - previous_raw.timestamp_s
        if delta_time <= 0.0 or delta_time > self._timeout_s:
            self._fused_pose = raw_pose
            return raw_pose

        linear_velocity = float(getattr(state, "linear_velocity", 0.0))
        lateral_velocity = float(getattr(state, "lateral_velocity", 0.0))
        angular_velocity = float(getattr(state, "angular_velocity", 0.0))
        gyroscope = getattr(state, "gyroscope", None)
        gyro_z = float(gyroscope[2]) if gyroscope is not None else angular_velocity

        raw_delta_x = raw_pose.x_m - previous_raw.x_m
        raw_delta_y = raw_pose.y_m - previous_raw.y_m
        raw_delta_yaw = _normalize_angle(raw_pose.yaw_rad - previous_raw.yaw_rad)
        speed = math.hypot(linear_velocity, lateral_velocity)
        expected_translation = speed * delta_time
        expected_rotation = max(abs(angular_velocity), abs(gyro_z)) * delta_time
        translation_limit = max(0.03, expected_translation * 2.5 + 0.02)
        rotation_limit = max(0.05, expected_rotation * 2.5 + 0.03)

        gravity = getattr(state, "gravity", None)
        upright = gravity is None or _upright(gravity)
        translation_valid = upright and math.hypot(raw_delta_x, raw_delta_y) <= translation_limit
        rotation_valid = abs(raw_delta_yaw) <= rotation_limit

        heading = previous_fused.yaw_rad
        predicted_delta_x = (
            math.cos(heading) * linear_velocity - math.sin(heading) * lateral_velocity
        ) * delta_time
        predicted_delta_y = (
            math.sin(heading) * linear_velocity + math.cos(heading) * lateral_velocity
        ) * delta_time
        if translation_valid:
            delta_x = 0.85 * raw_delta_x + 0.15 * predicted_delta_x
            delta_y = 0.85 * raw_delta_y + 0.15 * predicted_delta_y
        else:
            delta_x = delta_y = 0.0

        inertial_delta_yaw = gyro_z * delta_time
        if rotation_valid:
            delta_yaw = 0.7 * raw_delta_yaw + 0.3 * inertial_delta_yaw
        else:
            delta_yaw = inertial_delta_yaw
        fused = Pose2D(
            previous_fused.x_m + delta_x,
            previous_fused.y_m + delta_y,
            _normalize_angle(previous_fused.yaw_rad + delta_yaw),
            raw_pose.timestamp_s,
        )
        self._fused_pose = fused
        return fused

    def set_map_anchor(self, odom_pose: Pose2D, map_pose: Pose2D) -> None:
        self._odom_anchor = odom_pose
        self._map_anchor = map_pose


def _normalize_angle(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _upright(gravity: tuple[float, float, float]) -> bool:
    magnitude = math.sqrt(sum(component * component for component in gravity))
    return magnitude > 0.5 and gravity[2] / magnitude < -0.7