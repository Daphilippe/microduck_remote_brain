from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from .executor import ExecutionError, ExecutionReason
from .model import Plan

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "tool": {"enum": ["walk", "stop", "sound"]},
                    "arguments": {"type": "object"},
                },
                "required": ["id", "tool", "arguments"],
                "additionalProperties": False,
            },
        },
        "requires_confirmation": {"type": "boolean"},
    },
    "required": ["steps", "requires_confirmation"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You convert a user request into a short MicroDuck action plan.
Return only data matching the supplied JSON schema.

Available actions:
- walk(linear_velocity, angular_velocity, duration): linear velocity in [-0.3, 0.3] m/s,
  angular velocity in [-1.5, 1.5] rad/s, duration in (0, 10] seconds.
- stop(): explicitly stop locomotion.
- sound(tag): tag is one of alarm, greet, inquire, peck, chirp, coo.

Use 0.3 m/s for a clearly visible forward walk in simulation. Add stop after every walk. End every
safe plan with sound tag chirp so the simulated duck gives audible feedback. Never invent tools,
motor commands, joint commands, or policy names. Set requires_confirmation to true when the request
is ambiguous or unsafe.
"""


class OllamaPlanner:
    def __init__(
        self,
        model: str,
        *,
        endpoint: str = "http://127.0.0.1:11434/api/chat",
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._endpoint = endpoint
        self._timeout = timeout

    def plan(self, user_text: str) -> Plan:
        payload = {
            "model": self._model,
            "stream": False,
            "format": PLAN_SCHEMA,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                result = json.load(response)
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            raise ExecutionError(
                ExecutionReason.CONNECTION_FAILED, f"Ollama failed: {error}"
            ) from error

        try:
            content = result["message"]["content"]
            generated = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "Ollama returned an invalid structured plan"
            ) from error
        if not isinstance(generated, dict):
            raise ExecutionError(
                ExecutionReason.ROBOT_PROTOCOL, "Ollama plan content must be an object"
            )

        steps = generated.get("steps")
        if not isinstance(steps, list):
            raise ExecutionError(ExecutionReason.ROBOT_PROTOCOL, "Ollama plan has no steps")
        if not any(isinstance(step, dict) and step.get("tool") == "sound" for step in steps):
            steps.append({"id": "feedback", "tool": "sound", "arguments": {"tag": "chirp"}})
        return Plan.from_dict(
            {
                "schema_version": 1,
                "plan_id": str(uuid.uuid4()),
                "goal": user_text,
                "steps": steps,
                "requires_confirmation": generated.get("requires_confirmation", False),
            }
        )