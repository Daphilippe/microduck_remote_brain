from __future__ import annotations

import json
import math

import pytest

from microduck_remote_brain.mapping import (
    FREE,
    OCCUPIED,
    UNKNOWN,
    ExplorationPolicy,
    MappingSession,
    OccupancyGrid,
    OccupancyGridMapper,
    PlanarScan,
    Pose2D,
    tof_to_planar_scan,
)


def test_ray_marks_free_space_and_occupied_endpoint() -> None:
    mapper = OccupancyGridMapper(
        resolution_m=1.0,
        width=9,
        height=9,
        origin_x_m=-4.0,
        origin_y_m=-4.0,
    )
    pose = Pose2D(0.0, 0.0, 0.0, 1.0)
    scan = PlanarScan((3.0,), (0.0,), 5.0, 1.0, "test_lidar")

    mapper.integrate(pose, scan)
    mapper.integrate(pose, scan)
    grid = mapper.snapshot()

    assert grid.cells[4 * 9 + 4] == FREE
    assert grid.cells[4 * 9 + 6] == FREE
    assert grid.cells[4 * 9 + 7] == OCCUPIED
    assert grid.cells[0] == UNKNOWN
    assert grid.changed_cells


def test_map_round_trip_preserves_evidence(tmp_path) -> None:
    path = tmp_path / "map.json"
    mapper = OccupancyGridMapper(resolution_m=0.5, width=8, height=8)
    pose = Pose2D(0.0, 0.0, 0.0, 2.0)
    scan = PlanarScan((1.0,), (0.0,), 3.0, 2.0, "test_lidar")
    mapper.integrate(pose, scan)
    mapper.save(path)

    restored = OccupancyGridMapper.load(path)

    assert restored.snapshot().cells == mapper.snapshot().cells
    assert restored.snapshot().revision == 1


def test_mapper_rejects_unsynchronized_observation() -> None:
    mapper = OccupancyGridMapper(synchronization_tolerance_s=0.1)
    pose = Pose2D(0.0, 0.0, 0.0, 1.0)
    scan = PlanarScan((1.0,), (0.0,), 3.0, 1.2, "test_lidar")

    with pytest.raises(ValueError, match="not synchronized"):
        mapper.integrate(pose, scan)


def test_mapping_session_persists_map_and_rgb_depth_pose_keyframe(tmp_path) -> None:
    from microduck_remote_brain.perception import DepthObservation

    map_path = tmp_path / "map.json"
    keyframes = tmp_path / "keyframes"
    session = MappingSession(
        OccupancyGridMapper(resolution_m=0.5, width=20, height=20),
        map_path,
        keyframe_directory=keyframes,
    )
    pose = Pose2D(0.0, 0.0, 0.0, 3.0)
    depth = DepthObservation((1000.0,) * 64, 1000.0, 1000.0, 1000.0)

    snapshot = session.update(pose, depth, b"jpeg")

    assert snapshot.revision == 1
    assert map_path.exists()
    assert (tmp_path / "localization.json").exists()
    assert (keyframes / "00000001.jpg").read_bytes() == b"jpeg"
    metadata = json.loads((keyframes / "00000001.json").read_text(encoding="utf-8"))
    assert metadata["pose"]["timestamp_s"] == 3.0
    assert len(metadata["scan"]["ranges_m"]) == 8


def test_mapping_session_aligns_drifted_odometry_before_integration(tmp_path) -> None:
    from microduck_remote_brain.perception import DepthObservation

    map_path = tmp_path / "map.json"
    session = MappingSession(
        OccupancyGridMapper(resolution_m=0.05, width=120, height=120),
        map_path,
    )
    depth = DepthObservation((1000.0,) * 64, 1000.0, 1000.0, 1000.0)
    session.update(Pose2D(0.0, 0.0, 0.0, 1.0), depth, b"first")

    session.update(Pose2D(0.2, -0.15, math.radians(8.0), 2.0), depth, b"second")

    localization = json.loads(
        (tmp_path / "localization.json").read_text(encoding="utf-8")
    )
    aligned = localization["pose"]
    assert math.hypot(aligned["x_m"], aligned["y_m"]) < 0.1
    assert abs(aligned["yaw_rad"]) < math.radians(3.0)


def test_scan_matcher_recovers_pose_near_persistent_obstacles() -> None:
    mapper = OccupancyGridMapper(
        resolution_m=0.1,
        width=80,
        height=80,
        origin_x_m=-4.0,
        origin_y_m=-4.0,
    )
    mapped_pose = Pose2D(0.0, 0.0, 0.0, 1.0)
    scan = PlanarScan((1.0, 1.0), (-0.2, 0.2), 3.0, 1.0, "lidar")
    mapper.integrate(mapped_pose, scan)

    match = mapper.match_pose(
        PlanarScan(scan.ranges_m, scan.bearings_rad, 3.0, 2.0, "lidar"),
        Pose2D(0.15, -0.1, 0.1, 2.0),
        search_radius_m=0.3,
    )

    assert match is not None
    assert abs(match.x_m) <= 0.2
    assert abs(match.y_m) <= 0.2


def test_exploration_policy_scans_then_prefers_open_space() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy(startup_scan_turns=2)
    assert policy.startup_action() == "turn_left"
    assert policy.startup_action() == "turn_left"
    assert policy.startup_action() is None
    policy.mark_localized()
    grid = OccupancyGridMapper(width=20, height=20).snapshot()

    action = policy.exploration_action(
        grid,
        DepthObservation((), 900.0, 900.0, 700.0),
    )

    assert action == "curve_left"


def test_exploration_policy_turns_away_from_blocked_center() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy()
    policy.mark_localized()
    grid = OccupancyGridMapper(width=20, height=20).snapshot()

    action = policy.exploration_action(
        grid,
        DepthObservation((), 300.0, 200.0, 800.0),
    )

    assert action == "turn_right"


def test_exploration_policy_never_turns_into_a_remembered_drop() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy()
    policy.mark_localized()
    grid = OccupancyGridMapper(width=20, height=20).snapshot()

    action = policy.exploration_action(
        grid,
        DepthObservation(
            (),
            900.0,
            200.0,
            400.0,
            drop_hazard_remembered=True,
            drop_hazard_sectors=("left",),
        ),
    )

    assert action == "turn_right"


def test_exploration_policy_translates_with_moderate_center_clearance() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy()
    policy.mark_localized()
    grid = OccupancyGridMapper(width=20, height=20).snapshot()

    action = policy.exploration_action(
        grid,
        DepthObservation((), 314.0, 355.0, 367.0),
    )

    assert action in {"curve_left", "curve_right", "walk_forward"}


def test_exploration_policy_walks_straight_when_only_center_is_clear() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy()
    policy.mark_localized()
    grid = OccupancyGridMapper(width=20, height=20).snapshot()

    action = policy.exploration_action(
        grid,
        DepthObservation((), 220.0, 350.0, 230.0),
    )

    assert action == "walk_forward"


def test_exploration_policy_continues_after_map_reaches_quarter_coverage() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy()
    policy.mark_localized()
    grid = OccupancyGrid(
        0.05,
        2,
        2,
        0.0,
        0.0,
        (FREE, FREE, UNKNOWN, UNKNOWN),
        1,
        (),
    )

    action = policy.exploration_action(
        grid,
        DepthObservation((), 900.0, 900.0, 700.0),
    )

    assert action == "curve_left"


def test_exploration_policy_backs_up_when_no_turn_has_clearance() -> None:
    from microduck_remote_brain.perception import DepthObservation

    policy = ExplorationPolicy()
    policy.mark_localized()
    grid = OccupancyGridMapper(width=20, height=20).snapshot()

    action = policy.exploration_action(
        grid,
        DepthObservation((), 65.0, 72.0, 85.0),
    )

    assert action == "back_up"


def test_planar_mapping_ignores_floor_facing_tof_rows() -> None:
    from microduck_remote_brain.perception import DepthObservation

    distances = [1000.0] * 64
    for row in range(5, 8):
        distances[row * 8 + 3] = 150.0

    scan = tof_to_planar_scan(
        DepthObservation(tuple(distances), 1000.0, 1000.0, 1000.0),
        timestamp_s=1.0,
    )

    assert scan.ranges_m[3] == 1.0