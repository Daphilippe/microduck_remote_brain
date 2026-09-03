from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .perception import TOF_COLS, TOF_ROWS, DepthObservation

MAP_SCHEMA_VERSION = 4
ODOMETRY_POSE_SOURCE = "robotd_odometry"
INERTIAL_ODOMETRY_POSE_SOURCE = "robotd_inertial_odometry"
UNKNOWN = -1
FREE = 0
OCCUPIED = 100
EXPLORATION_CENTER_CLEAR_MM = 280.0
EXPLORATION_SIDE_CLEAR_MM = 250.0
EXPLORATION_TURN_MIN_MM = 100.0


@dataclass(frozen=True, slots=True)
class Pose2D:
    x_m: float
    y_m: float
    yaw_rad: float
    timestamp_s: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x_m, self.y_m, self.yaw_rad)):
            raise ValueError("pose values must be finite")
        if not math.isfinite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("pose timestamp must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PlanarScan:
    ranges_m: tuple[float | None, ...]
    bearings_rad: tuple[float, ...]
    max_range_m: float
    timestamp_s: float
    frame_id: str

    def __post_init__(self) -> None:
        if len(self.ranges_m) != len(self.bearings_rad):
            raise ValueError("scan ranges and bearings must have the same length")
        if not math.isfinite(self.max_range_m) or self.max_range_m <= 0:
            raise ValueError("scan maximum range must be finite and positive")
        if not math.isfinite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("scan timestamp must be finite and nonnegative")
        if not self.frame_id:
            raise ValueError("scan frame_id must not be empty")
        if any(not math.isfinite(value) for value in self.bearings_rad):
            raise ValueError("scan bearings must be finite")
        if any(
            value is not None and (not math.isfinite(value) or value <= 0)
            for value in self.ranges_m
        ):
            raise ValueError("scan ranges must be positive finite values or None")


@dataclass(frozen=True, slots=True)
class OccupancyGrid:
    resolution_m: float
    width: int
    height: int
    origin_x_m: float
    origin_y_m: float
    cells: tuple[int, ...]
    revision: int
    changed_cells: tuple[int, ...]

    @property
    def coverage_percent(self) -> float:
        observed = sum(value != UNKNOWN for value in self.cells)
        return observed * 100.0 / len(self.cells)


class ExplorationPolicy:
    def __init__(self, *, startup_scan_turns: int = 6) -> None:
        if startup_scan_turns <= 0:
            raise ValueError("startup scan turns must be positive")
        self._startup_scan_turns = startup_scan_turns
        self._startup_attempts = 0
        self._exploration_steps = 0
        self.localized = False

    def startup_action(self) -> str | None:
        if self.localized or self._startup_attempts >= self._startup_scan_turns:
            return None
        self._startup_attempts += 1
        return "turn_left"

    def mark_localized(self) -> None:
        self.localized = True

    def exploration_action(
        self, _grid: OccupancyGrid, depth: DepthObservation
    ) -> str | None:
        if not self.localized:
            return None
        self._exploration_steps += 1
        center = depth.center_clearance_mm or 0.0
        left = depth.left_clearance_mm or 0.0
        right = depth.right_clearance_mm or 0.0
        if depth.drop_hazard_remembered:
            safe_turns = {
                action: clearance
                for action, sector, clearance in (
                    ("turn_left", "left", left),
                    ("turn_right", "right", right),
                )
                if sector not in depth.drop_hazard_sectors
                and clearance >= EXPLORATION_TURN_MIN_MM
            }
            return (
                max(safe_turns.items(), key=lambda item: item[1])[0]
                if safe_turns
                else None
            )
        if center < EXPLORATION_CENTER_CLEAR_MM:
            if max(left, right) < EXPLORATION_TURN_MIN_MM:
                return "back_up"
            return "turn_left" if left >= right else "turn_right"
        if self._exploration_steps % 4 == 0:
            return "turn_left" if left >= right else "turn_right"
        if max(left, right) < EXPLORATION_SIDE_CLEAR_MM:
            return "walk_forward"
        return "curve_left" if left >= right else "curve_right"


def tof_to_planar_scan(
    observation: DepthObservation,
    *,
    timestamp_s: float,
    horizontal_fov_rad: float = math.radians(45.0),
    max_range_m: float = 4.0,
) -> PlanarScan:
    if len(observation.distance_mm) != TOF_ROWS * TOF_COLS:
        raise ValueError("ToF observation must contain 64 zones")
    if not math.isfinite(horizontal_fov_rad) or not 0 < horizontal_fov_rad < math.pi:
        raise ValueError("ToF horizontal field of view must be between zero and pi")

    ranges: list[float | None] = []
    bearings: list[float] = []
    for column in range(TOF_COLS):
        values = [
            observation.distance_mm[row * TOF_COLS + column]
            for row in range(TOF_ROWS - 3)
        ]
        valid = [float(value) / 1000.0 for value in values if value is not None and value > 0]
        ranges.append(min(valid) if valid else None)
        bearings.append(
            -horizontal_fov_rad / 2
            + horizontal_fov_rad * (column + 0.5) / TOF_COLS
        )
    return PlanarScan(
        tuple(ranges), tuple(bearings), max_range_m, timestamp_s, "tof"
    )


class OccupancyGridMapper:
    def __init__(
        self,
        *,
        resolution_m: float = 0.05,
        width: int = 400,
        height: int = 400,
        origin_x_m: float | None = None,
        origin_y_m: float | None = None,
        synchronization_tolerance_s: float = 0.25,
        pose_source: str = ODOMETRY_POSE_SOURCE,
    ) -> None:
        if not math.isfinite(resolution_m) or resolution_m <= 0:
            raise ValueError("map resolution must be finite and positive")
        if width <= 0 or height <= 0:
            raise ValueError("map dimensions must be positive")
        if not math.isfinite(synchronization_tolerance_s) or synchronization_tolerance_s < 0:
            raise ValueError("synchronization tolerance must be finite and nonnegative")
        self._resolution_m = resolution_m
        self._width = width
        self._height = height
        self._origin_x_m = (
            -width * resolution_m / 2 if origin_x_m is None else origin_x_m
        )
        self._origin_y_m = (
            -height * resolution_m / 2 if origin_y_m is None else origin_y_m
        )
        if not math.isfinite(self._origin_x_m) or not math.isfinite(self._origin_y_m):
            raise ValueError("map origin must be finite")
        self._synchronization_tolerance_s = synchronization_tolerance_s
        if not pose_source:
            raise ValueError("map pose source must not be empty")
        self._pose_source = pose_source
        self._evidence = [0] * (width * height)
        self._revision = 0
        self._changed_cells: set[int] = set()

    def set_pose_source(self, pose_source: str) -> None:
        if not pose_source:
            raise ValueError("map pose source must not be empty")
        self._pose_source = pose_source

    def integrate(self, pose: Pose2D, scan: PlanarScan) -> None:
        if abs(pose.timestamp_s - scan.timestamp_s) > self._synchronization_tolerance_s:
            raise ValueError("pose and range scan are not synchronized")
        start = self._world_to_cell(pose.x_m, pose.y_m)
        if start is None:
            raise ValueError("robot pose is outside the configured map")

        changed: set[int] = set()
        for measured_range, bearing in zip(scan.ranges_m, scan.bearings_rad, strict=True):
            ray_range = min(measured_range or scan.max_range_m, scan.max_range_m)
            angle = pose.yaw_rad + bearing
            endpoint = self._world_to_cell(
                pose.x_m + math.cos(angle) * ray_range,
                pose.y_m + math.sin(angle) * ray_range,
            )
            if endpoint is None:
                endpoint = self._clamped_cell(
                    pose.x_m + math.cos(angle) * ray_range,
                    pose.y_m + math.sin(angle) * ray_range,
                )
            cells = _bresenham(start, endpoint)
            has_hit = measured_range is not None and measured_range < scan.max_range_m
            free_cells = cells[:-1] if has_hit else cells
            for cell in free_cells:
                self._update_evidence(cell, -1, changed)
            if has_hit and cells:
                self._update_evidence(cells[-1], 3, changed)

        self._revision += 1
        self._changed_cells = changed

    def snapshot(self) -> OccupancyGrid:
        cells = tuple(_occupancy(value) for value in self._evidence)
        return OccupancyGrid(
            self._resolution_m,
            self._width,
            self._height,
            self._origin_x_m,
            self._origin_y_m,
            cells,
            self._revision,
            tuple(sorted(self._changed_cells)),
        )

    def match_pose(
        self,
        scan: PlanarScan,
        seed: Pose2D,
        *,
        search_radius_m: float = 0.75,
        yaw_radius_rad: float = math.radians(30.0),
        minimum_hits: int = 2,
    ) -> Pose2D | None:
        occupied_endpoints = sum(
            value is not None and value < scan.max_range_m for value in scan.ranges_m
        )
        if occupied_endpoints < minimum_hits or not any(
            _occupancy(evidence) == OCCUPIED for evidence in self._evidence
        ):
            return None
        translation_step = max(self._resolution_m * 2, 0.1)
        yaw_step = math.radians(5.0)
        best_pose: Pose2D | None = None
        best_score = float("-inf")
        best_seed_distance = float("inf")
        offset_steps = math.ceil(search_radius_m / translation_step)
        yaw_steps = math.ceil(yaw_radius_rad / yaw_step)
        for x_step in range(-offset_steps, offset_steps + 1):
            for y_step in range(-offset_steps, offset_steps + 1):
                for angle_step in range(-yaw_steps, yaw_steps + 1):
                    candidate = Pose2D(
                        seed.x_m + x_step * translation_step,
                        seed.y_m + y_step * translation_step,
                        seed.yaw_rad + angle_step * yaw_step,
                        scan.timestamp_s,
                    )
                    score = self._pose_score(scan, candidate)
                    seed_distance = self._seed_distance(candidate, seed, search_radius_m)
                    if score > best_score or (
                        math.isclose(score, best_score) and seed_distance < best_seed_distance
                    ):
                        best_score = score
                        best_pose = candidate
                        best_seed_distance = seed_distance

        if best_pose is None or best_score < minimum_hits * 0.35:
            return None

        fine_translation_step = self._resolution_m
        fine_yaw_step = math.radians(1.0)
        for x_step in range(-2, 3):
            for y_step in range(-2, 3):
                for angle_step in range(-3, 4):
                    candidate = Pose2D(
                        best_pose.x_m + x_step * fine_translation_step,
                        best_pose.y_m + y_step * fine_translation_step,
                        best_pose.yaw_rad + angle_step * fine_yaw_step,
                        scan.timestamp_s,
                    )
                    score = self._pose_score(scan, candidate)
                    seed_distance = self._seed_distance(candidate, seed, search_radius_m)
                    if score > best_score or (
                        math.isclose(score, best_score) and seed_distance < best_seed_distance
                    ):
                        best_score = score
                        best_pose = candidate
                        best_seed_distance = seed_distance
        return best_pose

    @staticmethod
    def _seed_distance(candidate: Pose2D, seed: Pose2D, search_radius_m: float) -> float:
        translation = math.hypot(candidate.x_m - seed.x_m, candidate.y_m - seed.y_m)
        yaw = abs((candidate.yaw_rad - seed.yaw_rad + math.pi) % (2 * math.pi) - math.pi)
        return translation / max(search_radius_m, 1e-9) + yaw

    def _pose_score(self, scan: PlanarScan, pose: Pose2D) -> float:
        score = 0.0
        tolerance_cells = max(2, math.ceil(0.12 / self._resolution_m))
        for measured_range, bearing in zip(scan.ranges_m, scan.bearings_rad, strict=True):
            if measured_range is None or measured_range >= scan.max_range_m:
                continue
            angle = pose.yaw_rad + bearing
            endpoint = self._world_to_cell(
                pose.x_m + math.cos(angle) * measured_range,
                pose.y_m + math.sin(angle) * measured_range,
            )
            if endpoint is None:
                continue
            column, row = endpoint
            nearest_squared: int | None = None
            for row_offset in range(-tolerance_cells, tolerance_cells + 1):
                nearby_row = row + row_offset
                if not 0 <= nearby_row < self._height:
                    continue
                for column_offset in range(-tolerance_cells, tolerance_cells + 1):
                    nearby_column = column + column_offset
                    if not 0 <= nearby_column < self._width:
                        continue
                    distance_squared = column_offset * column_offset + row_offset * row_offset
                    if distance_squared > tolerance_cells * tolerance_cells:
                        continue
                    evidence = self._evidence[nearby_row * self._width + nearby_column]
                    if _occupancy(evidence) != OCCUPIED:
                        continue
                    if nearest_squared is None or distance_squared < nearest_squared:
                        nearest_squared = distance_squared
            if nearest_squared is not None:
                score += math.exp(-0.5 * nearest_squared / (tolerance_cells * 0.5) ** 2)
            elif _occupancy(self._evidence[row * self._width + column]) == FREE:
                score -= 0.2
        return score

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": MAP_SCHEMA_VERSION,
            "resolution_m": self._resolution_m,
            "width": self._width,
            "height": self._height,
            "origin_x_m": self._origin_x_m,
            "origin_y_m": self._origin_y_m,
            "revision": self._revision,
            "pose_source": self._pose_source,
            "evidence": self._evidence,
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path, *, synchronization_tolerance_s: float = 0.25) -> OccupancyGridMapper:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("schema_version") != MAP_SCHEMA_VERSION:
                raise ValueError("unsupported map schema version")
            mapper = cls(
                resolution_m=float(document["resolution_m"]),
                width=int(document["width"]),
                height=int(document["height"]),
                origin_x_m=float(document["origin_x_m"]),
                origin_y_m=float(document["origin_y_m"]),
                synchronization_tolerance_s=synchronization_tolerance_s,
                pose_source=str(document["pose_source"]),
            )
            evidence = document["evidence"]
            if not isinstance(evidence, list) or len(evidence) != mapper._width * mapper._height:
                raise ValueError("map evidence has an invalid size")
            if any(type(value) is not int or not -10 <= value <= 10 for value in evidence):
                raise ValueError("map evidence values must be integers between -10 and 10")
            mapper._evidence = evidence
            mapper._revision = int(document["revision"])
            if mapper._revision < 0:
                raise ValueError("map revision must be nonnegative")
            return mapper
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid occupancy map: {error}") from error

    def _world_to_cell(self, x_m: float, y_m: float) -> tuple[int, int] | None:
        column = math.floor((x_m - self._origin_x_m) / self._resolution_m)
        row = math.floor((y_m - self._origin_y_m) / self._resolution_m)
        if not 0 <= column < self._width or not 0 <= row < self._height:
            return None
        return column, row

    def _clamped_cell(self, x_m: float, y_m: float) -> tuple[int, int]:
        column = math.floor((x_m - self._origin_x_m) / self._resolution_m)
        row = math.floor((y_m - self._origin_y_m) / self._resolution_m)
        return (
            min(max(column, 0), self._width - 1),
            min(max(row, 0), self._height - 1),
        )

    def _update_evidence(
        self, cell: tuple[int, int], delta: int, changed: set[int]
    ) -> None:
        column, row = cell
        index = row * self._width + column
        before = _occupancy(self._evidence[index])
        self._evidence[index] = min(10, max(-10, self._evidence[index] + delta))
        if _occupancy(self._evidence[index]) != before:
            changed.add(index)


class MappingSession:
    def __init__(
        self,
        mapper: OccupancyGridMapper,
        map_path: Path,
        *,
        keyframe_directory: Path | None = None,
        horizontal_fov_rad: float = math.radians(45.0),
        max_range_m: float = 4.0,
    ) -> None:
        self._mapper = mapper
        self._map_path = map_path
        self._keyframe_directory = keyframe_directory
        self._horizontal_fov_rad = horizontal_fov_rad
        self._max_range_m = max_range_m
        self._localization_path = map_path.with_name("localization.json")

    def previous_pose(self) -> Pose2D | None:
        if not self._localization_path.is_file():
            return None
        try:
            document = json.loads(self._localization_path.read_text(encoding="utf-8"))
            pose = document["pose"]
            return Pose2D(
                float(pose["x_m"]),
                float(pose["y_m"]),
                float(pose["yaw_rad"]),
                float(pose["timestamp_s"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def relocalize(self, odom_pose: Pose2D, depth: DepthObservation) -> Pose2D | None:
        previous = self.previous_pose()
        if previous is None:
            return odom_pose
        scan = tof_to_planar_scan(
            depth,
            timestamp_s=odom_pose.timestamp_s,
            horizontal_fov_rad=self._horizontal_fov_rad,
            max_range_m=self._max_range_m,
        )
        seed = Pose2D(
            previous.x_m,
            previous.y_m,
            previous.yaw_rad,
            odom_pose.timestamp_s,
        )
        return self._mapper.match_pose(scan, seed)

    def update(
        self,
        pose: Pose2D,
        depth: DepthObservation,
        image_jpeg: bytes,
        *,
        pose_source: str = ODOMETRY_POSE_SOURCE,
    ) -> OccupancyGrid:
        snapshot, aligned_pose, scan = self.integrate(
            pose,
            depth,
            pose_source=pose_source,
        )
        if self._keyframe_directory is not None:
            self._archive_keyframe(snapshot.revision, aligned_pose, scan, image_jpeg)
        return snapshot

    def integrate(
        self,
        pose: Pose2D,
        depth: DepthObservation,
        *,
        pose_source: str = ODOMETRY_POSE_SOURCE,
    ) -> tuple[OccupancyGrid, Pose2D, PlanarScan]:
        scan = tof_to_planar_scan(
            depth,
            timestamp_s=pose.timestamp_s,
            horizontal_fov_rad=self._horizontal_fov_rad,
            max_range_m=self._max_range_m,
        )
        aligned_pose = self._mapper.match_pose(scan, pose) or pose
        self._mapper.set_pose_source(pose_source)
        self._mapper.integrate(aligned_pose, scan)
        self._mapper.save(self._map_path)
        snapshot = self._mapper.snapshot()
        self._save_localization(snapshot.revision, aligned_pose, pose_source)
        return snapshot, aligned_pose, scan

    def archive_keyframe(
        self, revision: int, pose: Pose2D, scan: PlanarScan, image_jpeg: bytes
    ) -> None:
        if self._keyframe_directory is not None:
            self._archive_keyframe(revision, pose, scan, image_jpeg)

    def _save_localization(self, revision: int, pose: Pose2D, pose_source: str) -> None:
        document = {
            "schema_version": MAP_SCHEMA_VERSION,
            "revision": revision,
            "pose_source": pose_source,
            "localized": True,
            "pose": {
                "x_m": pose.x_m,
                "y_m": pose.y_m,
                "yaw_rad": pose.yaw_rad,
                "timestamp_s": pose.timestamp_s,
            },
        }
        temporary = self._localization_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(self._localization_path)

    def _archive_keyframe(
        self, revision: int, pose: Pose2D, scan: PlanarScan, image_jpeg: bytes
    ) -> None:
        if not image_jpeg:
            raise ValueError("mapping keyframe image must not be empty")
        assert self._keyframe_directory is not None
        self._keyframe_directory.mkdir(parents=True, exist_ok=True)
        stem = f"{revision:08d}"
        image_path = self._keyframe_directory / f"{stem}.jpg"
        metadata_path = self._keyframe_directory / f"{stem}.json"
        image_path.write_bytes(image_jpeg)
        metadata = {
            "schema_version": MAP_SCHEMA_VERSION,
            "revision": revision,
            "image": image_path.name,
            "pose": {
                "x_m": pose.x_m,
                "y_m": pose.y_m,
                "yaw_rad": pose.yaw_rad,
                "timestamp_s": pose.timestamp_s,
            },
            "scan": {
                "frame_id": scan.frame_id,
                "timestamp_s": scan.timestamp_s,
                "max_range_m": scan.max_range_m,
                "ranges_m": scan.ranges_m,
                "bearings_rad": scan.bearings_rad,
            },
        }
        temporary = metadata_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(metadata, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(metadata_path)


def _occupancy(evidence: int) -> int:
    if evidence <= -2:
        return FREE
    if evidence >= 2:
        return OCCUPIED
    return UNKNOWN


def _bresenham(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = dx + dy
    result: list[tuple[int, int]] = []
    while True:
        result.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return result
        twice_error = 2 * error
        if twice_error >= dy:
            error += dy
            x0 += step_x
        if twice_error <= dx:
            error += dx
            y0 += step_y