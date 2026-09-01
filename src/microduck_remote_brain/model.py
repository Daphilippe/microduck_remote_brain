from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GateStatus(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True, slots=True)
class GateDecision:
    gate: str
    status: GateStatus
    code: str
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActionStep:
    id: str
    tool: str
    arguments: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ActionStep:
        return cls(
            id=str(value.get("id", "")),
            tool=str(value.get("tool", "")),
            arguments=dict(value.get("arguments", {})),
        )


@dataclass(frozen=True, slots=True)
class Plan:
    schema_version: int
    plan_id: str
    goal: str
    steps: tuple[ActionStep, ...]
    requires_confirmation: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Plan:
        raw_steps = value.get("steps", [])
        return cls(
            schema_version=value.get("schema_version", 0),
            plan_id=str(value.get("plan_id", "")),
            goal=str(value.get("goal", "")),
            steps=tuple(ActionStep.from_dict(step) for step in raw_steps),
            requires_confirmation=bool(value.get("requires_confirmation", False)),
        )