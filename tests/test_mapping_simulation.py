from __future__ import annotations

import math
from dataclasses import dataclass

from microduck_remote_brain.mapping import OccupancyGridMapper, PlanarScan, Pose2D


@dataclass(frozen=True, slots=True)
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float


WORLD = (
    Segment(-3.0, -2.5, 3.0, -2.5),
    Segment(3.0, -2.5, 3.0, 2.5),
    Segment(3.0, 2.5, -3.0, 2.5),
    Segment(-3.0, 2.5, -3.0, -2.5),
    Segment(-0.8, -2.5, -0.8, 0.4),
    Segment(-0.8, 1.1, -0.8, 2.5),
    Segment(0.65, -0.35, 1.05, -0.35),
    Segment(1.05, -0.35, 1.05, 0.05),
    Segment(1.05, 0.05, 0.65, 0.05),
    Segment(0.65, 0.05, 0.65, -0.35),
    Segment(1.65, 1.0, 3.0, 1.0),
)
BEARINGS = tuple(math.radians(-120.0 + index * 4.0) for index in range(61))
MAX_RANGE_M = 5.0


def _ray_segment_distance(
    x: float, y: float, angle: float, segment: Segment
) -> float | None:
    ray_x = math.cos(angle)
    ray_y = math.sin(angle)
    segment_x = segment.x2 - segment.x1
    segment_y = segment.y2 - segment.y1
    cross = ray_x * segment_y - ray_y * segment_x
    if abs(cross) < 1e-9:
        return None
    offset_x = segment.x1 - x
    offset_y = segment.y1 - y
    ray_distance = (offset_x * segment_y - offset_y * segment_x) / cross
    segment_fraction = (offset_x * ray_y - offset_y * ray_x) / cross
    if ray_distance <= 0.0 or not 0.0 <= segment_fraction <= 1.0:
        return None
    return ray_distance


def _scan(pose: Pose2D, sample: int) -> PlanarScan:
    ranges: list[float | None] = []
    for index, bearing in enumerate(BEARINGS):
        distances = (
            _ray_segment_distance(pose.x_m, pose.y_m, pose.yaw_rad + bearing, segment)
            for segment in WORLD
        )
        measured = min((value for value in distances if value is not None), default=MAX_RANGE_M)
        if measured >= MAX_RANGE_M or (index * 7 + sample * 11) % 29 == 0:
            ranges.append(None)
            continue
        gait_wobble = 0.012 * math.sin(index * 0.71 + sample * 1.37)
        ranges.append(max(0.05, measured + gait_wobble))
    return PlanarScan(tuple(ranges), BEARINGS, MAX_RANGE_M, pose.timestamp_s, "sim_lidar")


def _pose_error(actual: Pose2D, expected: Pose2D) -> tuple[float, float]:
    translation = math.hypot(actual.x_m - expected.x_m, actual.y_m - expected.y_m)
    yaw = abs((actual.yaw_rad - expected.yaw_rad + math.pi) % (2 * math.pi) - math.pi)
    return translation, yaw


def test_scan_matching_aligns_noisy_microduck_motion_in_difficult_room() -> None:
    mapper = OccupancyGridMapper(
        resolution_m=0.05,
        width=160,
        height=140,
        origin_x_m=-4.0,
        origin_y_m=-3.5,
    )
    reference_trajectory = (
        Pose2D(-2.2, -1.6, 0.10, 1.0),
        Pose2D(-1.5, -1.35, 0.25, 2.0),
        Pose2D(-1.05, -0.65, 0.85, 3.0),
        Pose2D(-1.15, 0.55, 1.35, 4.0),
        Pose2D(-0.45, 1.45, 0.35, 5.0),
        Pose2D(0.55, 1.65, -0.10, 6.0),
        Pose2D(1.55, 1.35, -0.45, 7.0),
        Pose2D(1.8, 0.45, -1.15, 8.0),
        Pose2D(1.45, -0.55, -1.95, 9.0),
        Pose2D(0.35, -1.25, -2.75, 10.0),
    )
    for sample, pose in enumerate(reference_trajectory):
        mapper.integrate(pose, _scan(pose, sample))

    translations: list[float] = []
    yaws: list[float] = []
    for sample, truth in enumerate(reference_trajectory[2:9], start=20):
        drifted = Pose2D(
            truth.x_m + 0.22 + 0.06 * math.sin(sample),
            truth.y_m - 0.17 + 0.05 * math.cos(sample * 0.7),
            truth.yaw_rad + math.radians(9.0 + 2.0 * math.sin(sample * 0.5)),
            truth.timestamp_s + 20.0,
        )
        scan = _scan(
            Pose2D(truth.x_m, truth.y_m, truth.yaw_rad, drifted.timestamp_s),
            sample,
        )
        match = mapper.match_pose(
            scan,
            drifted,
            search_radius_m=0.45,
            yaw_radius_rad=math.radians(18.0),
            minimum_hits=12,
        )

        assert match is not None
        translation, yaw = _pose_error(match, truth)
        translations.append(translation)
        yaws.append(yaw)

    translation_rmse = math.sqrt(sum(error * error for error in translations) / len(translations))
    yaw_rmse = math.sqrt(sum(error * error for error in yaws) / len(yaws))
    assert translation_rmse < 0.09
    assert yaw_rmse < math.radians(3.0)
    assert max(translations) < 0.15
