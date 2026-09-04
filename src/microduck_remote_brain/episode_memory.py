from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from .perception import DepthObservation
from .scene import SceneState

DEFAULT_CONTEXT_BUDGET = 2600
DEFAULT_MAX_EPISODES = 24
APPROACH_ACTIONS = frozenset({"walk_forward", "curve_left", "curve_right"})
IGNORED_INTEREST_KINDS = frozenset(
    {"floor", "flooring", "ground", "room", "sky", "person", "human", "child", "animal", "pet"}
)


@dataclass(frozen=True, slots=True)
class Episode:
    sequence: int
    camera_axis: str
    scene: dict[str, object]
    depth: dict[str, object] | None
    action: str
    outcome: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "camera_axis": self.camera_axis,
            "scene": self.scene,
            "depth": self.depth,
            "action": self.action,
            "outcome": self.outcome,
        }


class EpisodeMemory:
    def __init__(
        self,
        *,
        context_budget: int = DEFAULT_CONTEXT_BUDGET,
        max_episodes: int = DEFAULT_MAX_EPISODES,
    ) -> None:
        if context_budget <= 0 or max_episodes <= 0:
            raise ValueError("episode memory limits must be positive")
        self._context_budget = context_budget
        self._max_episodes = max_episodes
        self._episodes: list[Episode] = []
        self._sequence = 0
        self._context = ""
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="episode-memory")
        self._pending: Future[str] | None = None

    def remember(
        self,
        scene: SceneState,
        depth: DepthObservation | None,
        action: str,
        *,
        outcome: str = "completed",
        release: bool = False,
        camera_axis: str = "center",
    ) -> None:
        if camera_axis not in {"left", "right", "up", "down", "center"}:
            raise ValueError("camera_axis is invalid")
        with self._lock:
            self._sequence += 1
            episode = Episode(
                self._sequence,
                camera_axis,
                scene.to_dict(),
                depth.to_dict() if depth is not None else None,
                action,
                outcome,
            )
            if release:
                self._episodes = [episode]
            else:
                self._episodes.append(episode)
                del self._episodes[:-self._max_episodes]
            snapshot = tuple(self._episodes)
            self._pending = self._executor.submit(
                _render_context, snapshot, self._context_budget
            )

    def context(self) -> str:
        with self._lock:
            pending = self._pending
            if pending is not None and pending.done():
                self._context = pending.result()
                self._pending = None
            return self._context

    def departure_action(
        self, scene: SceneState, depth: DepthObservation | None
    ) -> str | None:
        if scene.visibility != "good" or depth is None or depth.drop_hazard_remembered:
            return None
        with self._lock:
            if not self._episodes or self._episodes[-1].action not in APPROACH_ACTIONS:
                return None
            previous_entities = self._episodes[-1].scene.get("entities")
        if not isinstance(previous_entities, list):
            return None
        interests = {
            str(entity.get("kind", "")).strip().lower()
            for entity in previous_entities
            if isinstance(entity, dict)
            and entity.get("bearing") == "center"
            and entity.get("proximity") in {"mid", "near"}
            and isinstance(entity.get("confidence"), int | float)
            and float(entity["confidence"]) >= 0.65
            and str(entity.get("kind", "")).strip().lower() not in IGNORED_INTEREST_KINDS
        }
        visible_kinds = {entity.kind.strip().lower() for entity in scene.entities}
        if not interests or interests & visible_kinds:
            return None
        candidates = {
            "turn_around_left": (
                0.0 if "left" in depth.drop_hazard_sectors else depth.left_clearance_mm or 0.0
            ),
            "turn_around_right": (
                0.0 if "right" in depth.drop_hazard_sectors else depth.right_clearance_mm or 0.0
            ),
        }
        action, clearance = max(candidates.items(), key=lambda item: item[1])
        return action if clearance >= 100.0 else None

    def close(self) -> None:
        self._executor.shutdown(wait=True)


def _render_context(episodes: tuple[Episode, ...], budget: int) -> str:
    selected: list[dict[str, object]] = []
    for episode in reversed(episodes):
        candidate = [episode.to_dict(), *selected]
        rendered = json.dumps(candidate, separators=(",", ":"), allow_nan=False)
        if len(rendered) > budget:
            break
        selected = candidate
    return json.dumps(selected, separators=(",", ":"), allow_nan=False) if selected else ""