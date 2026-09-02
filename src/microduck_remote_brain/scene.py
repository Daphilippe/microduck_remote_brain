from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SceneEntity:
    kind: str
    bearing: str
    proximity: str
    confidence: float

    @classmethod
    def from_dict(cls, value: object) -> SceneEntity:
        if not isinstance(value, dict):
            raise ValueError("scene entity must be an object")
        if set(value) != {"kind", "bearing", "proximity", "confidence"}:
            raise ValueError("scene entity has invalid fields")
        kind = value["kind"]
        bearing = value["bearing"]
        proximity = value["proximity"]
        confidence = value["confidence"]
        if not isinstance(kind, str) or not kind:
            raise ValueError("scene entity kind must be a non-empty string")
        if bearing not in {"left", "center", "right", "unknown"}:
            raise ValueError("scene entity bearing is invalid")
        if proximity not in {"near", "mid", "far", "unknown"}:
            raise ValueError("scene entity proximity is invalid")
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            raise ValueError("scene entity confidence must be a number")
        numeric_confidence = float(confidence)
        if not 0.0 <= numeric_confidence <= 1.0:
            raise ValueError("scene entity confidence must be between zero and one")
        return cls(kind, bearing, proximity, numeric_confidence)


@dataclass(frozen=True, slots=True)
class SceneState:
    summary: str
    entities: tuple[SceneEntity, ...]
    free_floor: str
    visibility: str
    hazards: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> SceneState:
        if not isinstance(value, dict):
            raise ValueError("scene state must be an object")
        required = {"summary", "entities", "free_floor", "visibility", "hazards"}
        if set(value) != required:
            raise ValueError("scene state has invalid fields")
        summary = value["summary"]
        entities = value["entities"]
        free_floor = value["free_floor"]
        visibility = value["visibility"]
        hazards = value["hazards"]
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("scene summary must be a non-empty string")
        if not isinstance(entities, list):
            raise ValueError("scene entities must be an array")
        if free_floor not in {"clear", "blocked", "unknown"}:
            raise ValueError("scene free_floor is invalid")
        if visibility not in {"good", "poor", "unknown"}:
            raise ValueError("scene visibility is invalid")
        if not isinstance(hazards, list) or any(
            not isinstance(hazard, str) or not hazard for hazard in hazards
        ):
            raise ValueError("scene hazards must be an array of non-empty strings")
        return cls(
            summary.strip(),
            tuple(SceneEntity.from_dict(entity) for entity in entities),
            free_floor,
            visibility,
            tuple(hazards),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "entities": [
                {
                    "kind": entity.kind,
                    "bearing": entity.bearing,
                    "proximity": entity.proximity,
                    "confidence": entity.confidence,
                }
                for entity in self.entities
            ],
            "free_floor": self.free_floor,
            "visibility": self.visibility,
            "hazards": list(self.hazards),
        }