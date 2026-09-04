from __future__ import annotations

from microduck_remote_brain.episode_memory import EpisodeMemory
from microduck_remote_brain.perception import DepthObservation
from microduck_remote_brain.scene import SceneState


def scene(summary: str) -> SceneState:
    return SceneState.from_dict(
        {
            "summary": summary,
            "entities": [],
            "free_floor": "clear",
            "visibility": "good",
            "hazards": [],
        }
    )


def uniform_scene(summary: str) -> SceneState:
    value = scene(summary).to_dict()
    value["visual_content"] = "uniform"
    return SceneState.from_dict(value)


def interest_scene(summary: str, entities: list[dict[str, object]]) -> SceneState:
    value = scene(summary).to_dict()
    value["entities"] = entities
    return SceneState.from_dict(value)


def test_episode_context_is_prepared_asynchronously_within_budget() -> None:
    memory = EpisodeMemory(context_budget=450)
    try:
        for index in range(12):
            memory.remember(scene(f"Observed place {index}"), None, "walk_forward")
        memory.close()

        context = memory.context()

        assert len(context) <= 450
        assert "Observed place 11" in context
        assert "Observed place 0" not in context
        assert '"outcome":"completed"' in context
    finally:
        memory.close()


def test_release_starts_a_new_variable_length_memory_segment() -> None:
    memory = EpisodeMemory()
    try:
        memory.remember(scene("A red ball is ahead"), None, "walk_forward")
        memory.remember(scene("The red ball is near"), None, "stop", release=True)
        memory.close()

        context = memory.context()

        assert "The red ball is near" in context
        assert "A red ball is ahead" not in context
    finally:
        memory.close()


def test_disappeared_approached_interest_triggers_turn_around_toward_clear_side() -> None:
    memory = EpisodeMemory()
    try:
        memory.remember(
            interest_scene(
                "A red ball is centered nearby",
                [
                    {
                        "kind": "ball",
                        "bearing": "center",
                        "proximity": "mid",
                        "confidence": 0.9,
                    }
                ],
            ),
            DepthObservation((), 400.0, 300.0, 500.0),
            "walk_forward",
        )

        action = memory.departure_action(
            scene("The ball is now too close to see"),
            DepthObservation((), 600.0, 180.0, 300.0),
        )

        assert action == "turn_around_left"
    finally:
        memory.close()


def test_visible_interest_does_not_trigger_departure() -> None:
    memory = EpisodeMemory()
    try:
        previous = interest_scene(
            "A ball is ahead",
            [
                {
                    "kind": "ball",
                    "bearing": "center",
                    "proximity": "mid",
                    "confidence": 0.9,
                }
            ],
        )
        memory.remember(previous, None, "walk_forward")

        assert memory.departure_action(previous, DepthObservation((), 500, 500, 500)) is None
    finally:
        memory.close()


def test_episode_records_camera_axis_used_for_semantic_scene() -> None:
    memory = EpisodeMemory()
    try:
        memory.remember(
            scene("A chair is centered in the image"),
            None,
            "curve_left",
            camera_axis="left",
        )
        memory.close()

        assert '"camera_axis":"left"' in memory.context()
    finally:
        memory.close()


def test_uniform_left_and_right_views_trigger_turn_around_toward_clear_side() -> None:
    memory = EpisodeMemory()
    try:
        memory.remember(
            uniform_scene("Only a plain white wall is visible left"),
            None,
            "scan_right",
            camera_axis="left",
        )

        action = memory.uniform_panorama_action(
            uniform_scene("Only the same plain wall is visible right"),
            DepthObservation((), 600.0, 250.0, 300.0),
            "right",
        )

        assert action == "turn_around_left"
    finally:
        memory.close()


def test_single_uniform_view_does_not_trigger_turn_around() -> None:
    memory = EpisodeMemory()
    try:
        assert (
            memory.uniform_panorama_action(
                uniform_scene("A plain surface is visible right"),
                DepthObservation((), 600.0, 250.0, 300.0),
                "right",
            )
            is None
        )
    finally:
        memory.close()