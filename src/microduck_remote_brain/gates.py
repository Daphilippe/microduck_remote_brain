from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from .model import ActionStep, GateDecision, GateStatus, Plan

SCHEMA_VERSION = 1
MAX_STEPS = 16
MAX_LINEAR_VELOCITY = 0.3
MAX_ANGULAR_VELOCITY = 1.5
MAX_DURATION = 10.0
SOUND_TAGS = frozenset({"alarm", "greet", "inquire", "peck", "chirp", "coo"})
SKILL_NAMES = frozenset({"sit_toggle", "ground_pick", "kick_left", "kick_right", "roulade"})


def _decision(gate: str, status: GateStatus, code: str, **facts: Any) -> GateDecision:
    return GateDecision(gate=gate, status=status, code=code, facts=facts)


def _finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _validate_walk(step: ActionStep) -> GateDecision:
    expected = {"linear_velocity", "angular_velocity", "duration"}
    supplied = set(step.arguments)
    if supplied != expected:
        return _decision(
            "capability",
            GateStatus.DENY,
            "walk.arguments",
            step_id=step.id,
            missing=sorted(expected - supplied),
            unknown=sorted(supplied - expected),
        )

    linear = step.arguments["linear_velocity"]
    angular = step.arguments["angular_velocity"]
    duration = step.arguments["duration"]
    if not all(_finite_number(value) for value in (linear, angular, duration)):
        return _decision(
            "format", GateStatus.DENY, "walk.not_finite", step_id=step.id
        )
    if abs(linear) > MAX_LINEAR_VELOCITY:
        return _decision(
            "safety",
            GateStatus.DENY,
            "walk.linear_velocity_out_of_range",
            step_id=step.id,
            value=linear,
            limit=MAX_LINEAR_VELOCITY,
        )
    if abs(angular) > MAX_ANGULAR_VELOCITY:
        return _decision(
            "safety",
            GateStatus.DENY,
            "walk.angular_velocity_out_of_range",
            step_id=step.id,
            value=angular,
            limit=MAX_ANGULAR_VELOCITY,
        )
    if duration <= 0 or duration > MAX_DURATION:
        return _decision(
            "safety",
            GateStatus.DENY,
            "walk.duration_out_of_range",
            step_id=step.id,
            value=duration,
            maximum=MAX_DURATION,
        )
    return _decision("capability", GateStatus.ALLOW, "walk.valid", step_id=step.id)


def _validate_stop(step: ActionStep) -> GateDecision:
    if step.arguments:
        return _decision(
            "capability",
            GateStatus.DENY,
            "stop.arguments",
            step_id=step.id,
            unknown=sorted(step.arguments),
        )
    return _decision("capability", GateStatus.ALLOW, "stop.valid", step_id=step.id)


def _validate_sound(step: ActionStep) -> GateDecision:
    if set(step.arguments) != {"tag"}:
        return _decision(
            "capability",
            GateStatus.DENY,
            "sound.arguments",
            step_id=step.id,
            unknown=sorted(set(step.arguments) - {"tag"}),
        )
    tag = step.arguments["tag"]
    if not isinstance(tag, str) or tag not in SOUND_TAGS:
        return _decision(
            "capability",
            GateStatus.DENY,
            "sound.unknown_tag",
            step_id=step.id,
            tag=tag,
            allowed=sorted(SOUND_TAGS),
        )
    return _decision("capability", GateStatus.ALLOW, "sound.valid", step_id=step.id)


def _validate_skill(step: ActionStep) -> GateDecision:
    if set(step.arguments) != {"name"}:
        return _decision(
            "capability",
            GateStatus.DENY,
            "skill.arguments",
            step_id=step.id,
            unknown=sorted(set(step.arguments) - {"name"}),
        )
    name = step.arguments["name"]
    if not isinstance(name, str) or name not in SKILL_NAMES:
        return _decision(
            "capability",
            GateStatus.DENY,
            "skill.unknown_name",
            step_id=step.id,
            name=name,
            allowed=sorted(SKILL_NAMES),
        )
    return _decision("capability", GateStatus.ALLOW, "skill.valid", step_id=step.id)


def _validate_look(step: ActionStep) -> GateDecision:
    expected = {"x", "y", "z", "neck_pitch"}
    if set(step.arguments) != expected:
        return _decision("capability", GateStatus.DENY, "look.arguments", step_id=step.id)
    if not all(_finite_number(step.arguments[name]) for name in expected):
        return _decision("format", GateStatus.DENY, "look.not_finite", step_id=step.id)
    if not 0.05 <= step.arguments["x"] <= 2.0 or abs(step.arguments["y"]) > 2.0:
        return _decision("safety", GateStatus.DENY, "look.target_out_of_range", step_id=step.id)
    if abs(step.arguments["z"]) > 2.0 or abs(step.arguments["neck_pitch"]) > 1.0:
        return _decision("safety", GateStatus.DENY, "look.target_out_of_range", step_id=step.id)
    return _decision("capability", GateStatus.ALLOW, "look.valid", step_id=step.id)


def validate_plan(plan: Plan) -> tuple[GateDecision, ...]:
    decisions: list[GateDecision] = []
    if plan.schema_version != SCHEMA_VERSION:
        return (
            _decision(
                "format",
                GateStatus.DENY,
                "plan.unsupported_schema",
                actual=plan.schema_version,
                supported=SCHEMA_VERSION,
            ),
        )
    if not plan.plan_id or not plan.goal:
        return (
            _decision("format", GateStatus.DENY, "plan.missing_identity"),
        )
    if not plan.steps or len(plan.steps) > MAX_STEPS:
        return (
            _decision(
                "format",
                GateStatus.DENY,
                "plan.step_count",
                actual=len(plan.steps),
                maximum=MAX_STEPS,
            ),
        )

    identifiers = [step.id for step in plan.steps]
    has_missing_id = any(not identifier for identifier in identifiers)
    has_duplicate_id = len(set(identifiers)) != len(identifiers)
    if has_missing_id or has_duplicate_id:
        return (
            _decision("format", GateStatus.DENY, "plan.step_ids"),
        )

    validators = {
        "walk": _validate_walk,
        "stop": _validate_stop,
        "sound": _validate_sound,
        "skill": _validate_skill,
        "look": _validate_look,
    }
    for step in plan.steps:
        validator = validators.get(step.tool)
        if validator is None:
            decisions.append(
                _decision(
                    "capability",
                    GateStatus.DENY,
                    "tool.unknown",
                    step_id=step.id,
                    tool=step.tool,
                )
            )
            continue
        decisions.append(validator(step))

    if plan.requires_confirmation:
        decisions.append(
            _decision(
                "confirmation",
                GateStatus.NEEDS_CONFIRMATION,
                "plan.confirmation_required",
            )
        )
    elif all(decision.status is GateStatus.ALLOW for decision in decisions):
        decisions.append(_decision("plan", GateStatus.ALLOW, "plan.valid"))
    return tuple(decisions)


def plan_is_allowed(decisions: Iterable[GateDecision]) -> bool:
    decisions = tuple(decisions)
    return bool(decisions) and all(decision.status is GateStatus.ALLOW for decision in decisions)