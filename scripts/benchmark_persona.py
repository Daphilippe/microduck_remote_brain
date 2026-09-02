from __future__ import annotations

import argparse
import statistics
import time

from microduck_remote_brain.autonomy import ActuatorResolver, OllamaPersonaModel
from microduck_remote_brain.scene import SceneState

SCENES = (
    {
        "summary": "The room is quiet and the floor ahead is clear.",
        "entities": [],
        "free_floor": "clear",
        "visibility": "good",
        "hazards": [],
    },
    {
        "summary": "A person is standing close to the robot.",
        "entities": [
            {"kind": "person", "bearing": "center", "proximity": "near", "confidence": 0.95}
        ],
        "free_floor": "unknown",
        "visibility": "good",
        "hazards": [],
    },
    {
        "summary": "An obstacle blocks the floor ahead.",
        "entities": [
            {"kind": "box", "bearing": "center", "proximity": "near", "confidence": 0.91}
        ],
        "free_floor": "blocked",
        "visibility": "good",
        "hazards": ["obstacle_ahead"],
    },
    {
        "summary": "The image is dark and the surroundings cannot be determined.",
        "entities": [],
        "free_floor": "unknown",
        "visibility": "poor",
        "hazards": [],
    },
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark compact Ollama persona models")
    parser.add_argument("models", nargs="*", default=["qwen3:0.6b", "qwen3:1.7b"])
    parser.add_argument("--rounds", type=int, default=2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.rounds <= 0:
        raise ValueError("--rounds must be positive")
    scenes = tuple(SceneState.from_dict(value) for value in SCENES)
    resolver = ActuatorResolver(allow_movement=True)
    for model_name in args.models:
        model = OllamaPersonaModel(model_name, allow_movement=True)
        model.decide(scenes[0])
        latencies: list[float] = []
        rates: list[float] = []
        actions: list[str] = []
        recent_behaviors: list[str] = []
        for _ in range(args.rounds):
            for scene in scenes:
                started = time.perf_counter()
                intent = model.decide(scene, recent_behaviors=tuple(recent_behaviors))
                plan = resolver.resolve(intent, scene)
                latencies.append((time.perf_counter() - started) * 1000)
                actions.append(f"{intent.action}->{'+'.join(step.tool for step in plan.steps)}")
                recent_behaviors.append(intent.action)
                del recent_behaviors[:-3]
                if model.last_metrics is not None:
                    rates.append(model.last_metrics.tokens_per_second)
        ordered = sorted(latencies)
        p95_index = max(0, min(len(ordered) - 1, round(0.95 * len(ordered) + 0.5) - 1))
        median_rate = statistics.median(rates) if rates else 0.0
        print(
            f"{model_name}: samples={len(latencies)} "
            f"p50={statistics.median(latencies):.1f}ms p95={ordered[p95_index]:.1f}ms "
            f"decode={median_rate:.1f}tok/s"
        )
        print(f"  actions: {', '.join(actions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())