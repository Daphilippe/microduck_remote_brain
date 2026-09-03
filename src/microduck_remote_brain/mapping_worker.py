from __future__ import annotations

import threading
import time
from typing import Protocol

from .mapping import MappingSession, OccupancyGrid, PlanarScan, Pose2D
from .perception import DepthObservation, DropHazardMemory


class AuditSink(Protocol):
    def write(self, event: str, **facts: object) -> None: ...


class DepthProvider(Protocol):
    def capture_depth(self) -> DepthObservation: ...


class PoseProvider(Protocol):
    @property
    def pose_source(self) -> str: ...

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read(self) -> Pose2D: ...

    def set_map_anchor(self, odom_pose: Pose2D, map_pose: Pose2D) -> None: ...


class MappingWorker:
    def __init__(
        self,
        perception: DepthProvider,
        pose_provider: PoseProvider,
        session: MappingSession,
        audit: AuditSink,
        *,
        map_path: str,
        update_interval_s: float,
    ) -> None:
        self._perception = perception
        self._pose_provider = pose_provider
        self._session = session
        self._audit = audit
        self._map_path = map_path
        self._update_interval_s = update_interval_s
        self._drop_memory = DropHazardMemory()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._localized = False
        self._latest_grid: OccupancyGrid | None = None
        self._latest_depth: DepthObservation | None = None
        self._latest_keyframe: tuple[int, Pose2D, PlanarScan] | None = None

    @property
    def localized(self) -> bool:
        with self._lock:
            return self._localized

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("mapping worker is already running")
        self._pose_provider.connect()
        self._thread = threading.Thread(
            target=self._run,
            name="microduck-mapping",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(2.0, self._update_interval_s * 4.0))
        self._pose_provider.close()

    def latest(self) -> tuple[OccupancyGrid | None, DepthObservation | None]:
        with self._lock:
            return self._latest_grid, self._latest_depth

    def archive_keyframe(self, image_jpeg: bytes) -> None:
        with self._lock:
            keyframe = self._latest_keyframe
        if keyframe is not None:
            revision, pose, scan = keyframe
            self._session.archive_keyframe(revision, pose, scan, image_jpeg)

    def _run(self) -> None:
        while not self._stop.is_set():
            started_at = time.monotonic()
            try:
                self.update_once()
            except (OSError, RuntimeError, ValueError) as error:
                self._audit.write(
                    "mapping.failed",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            elapsed = time.monotonic() - started_at
            self._stop.wait(max(0.0, self._update_interval_s - elapsed))

    def update_once(self) -> None:
        depth = self._drop_memory.update(self._perception.capture_depth())
        odom_pose = self._pose_provider.read()
        pose_source = self._pose_provider.pose_source
        with self._lock:
            localized = self._localized
        if not localized:
            pose = self._session.relocalize(odom_pose, depth)
            if pose is None:
                self._audit.write("localization.unmatched")
                return
            self._pose_provider.set_map_anchor(odom_pose, pose)
            with self._lock:
                self._localized = True
            self._audit.write(
                "localization.acquired",
                pose_source=pose_source,
                x_m=pose.x_m,
                y_m=pose.y_m,
                yaw_rad=pose.yaw_rad,
            )
        else:
            pose = odom_pose
        grid, aligned_pose, scan = self._session.integrate(
            pose,
            depth,
            pose_source=pose_source,
        )
        with self._lock:
            self._latest_grid = grid
            self._latest_depth = depth
            self._latest_keyframe = (grid.revision, aligned_pose, scan)
        self._audit.write(
            "mapping.updated",
            revision=grid.revision,
            changed_cells=len(grid.changed_cells),
            pose_source=pose_source,
            map_path=self._map_path,
        )
