from __future__ import annotations

from microduck_remote_brain.mapping import MappingSession, OccupancyGridMapper, Pose2D
from microduck_remote_brain.mapping_worker import MappingWorker
from microduck_remote_brain.perception import DepthObservation


def test_worker_publishes_each_depth_and_odometry_acquisition(tmp_path) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class FakePerception:
        def capture_depth(self) -> DepthObservation:
            return DepthObservation((1000.0,) * 64, 1000.0, 1000.0, 1000.0)

    class FakePoseProvider:
        pose_source = "test_odometry"

        def connect(self) -> None:
            pass

        def close(self) -> None:
            pass

        def read(self) -> Pose2D:
            return Pose2D(0.0, 0.0, 0.0, 1.0)

        def set_map_anchor(self, odom_pose: Pose2D, map_pose: Pose2D) -> None:
            del odom_pose, map_pose
            pass

    class FakeAudit:
        def write(self, event: str, **facts: object) -> None:
            events.append((event, facts))

    map_path = tmp_path / "occupancy-map.json"
    worker = MappingWorker(
        FakePerception(),
        FakePoseProvider(),
        MappingSession(
            OccupancyGridMapper(resolution_m=0.1, width=80, height=80),
            map_path,
        ),
        FakeAudit(),
        map_path=str(map_path),
        update_interval_s=0.2,
    )

    worker.update_once()

    grid, depth = worker.latest()
    assert grid is not None
    assert grid.revision == 1
    assert depth is not None
    assert worker.latest_pose == Pose2D(0.0, 0.0, 0.0, 1.0)
    assert map_path.exists()
    update = next(facts for event, facts in events if event == "mapping.updated")
    assert update["revision"] == 1
    assert update["pose_source"] == "test_odometry"
