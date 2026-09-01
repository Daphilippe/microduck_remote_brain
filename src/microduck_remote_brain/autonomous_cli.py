from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .audit import JsonlAuditLog
from .autonomy import OllamaAutonomousPlanner
from .body_oracle import TcpBodyOracle
from .brain_config import BrainConfig, load_brain_config
from .executor import ExecutionError, PlanExecutor
from .model import Plan
from .perception import CameraPerception, ImagePerception, PerceptionProvider, SimulatorPerception
from .prerequisites import PrerequisiteError, verify_local_foundations
from .robotd import RobotdClient
from .vision import OllamaVision


@dataclass(frozen=True, slots=True)
class CycleContext:
    config: BrainConfig
    perception: PerceptionProvider
    vision: OllamaVision
    planner: OllamaAutonomousPlanner
    audit: JsonlAuditLog
    pause_file: Path | None
    activity_file: Path | None
    status_file: Path | None
    recent_behaviors: list[str]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MicroDuck's local autonomous perception loop")
    parser.add_argument("--config", type=Path, default=Path("config/microduck.sim.toml"))
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pause-file", type=Path)
    parser.add_argument("--activity-file", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--pid-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_cycles is not None and args.max_cycles <= 0:
        raise ValueError("--max-cycles must be positive")

    if args.pid_file is not None:
        args.pid_file.parent.mkdir(parents=True, exist_ok=True)
        args.pid_file.write_text(str(os.getpid()), encoding="ascii")
    try:
        config = load_brain_config(args.config)
        verify_local_foundations(
            whisper_executable=config.whisper_executable,
            whisper_model=config.whisper_model,
            ollama_models=(config.ollama_model, config.vision_model),
            ollama_tags_endpoint=config.ollama_tags_endpoint,
        )
        voice_status = "with optional Whisper" if config.whisper_executable else "without Whisper"
        print(f"foundations ready: Ollama is available {voice_status}")
        vision = OllamaVision(config.vision_model, endpoint=config.ollama_endpoint)
        planner = OllamaAutonomousPlanner(
            config.ollama_model,
            persona_prompt=config.persona_prompt,
            sound_actions=config.sound_actions,
            allow_movement=config.allow_movement,
            endpoint=config.ollama_endpoint,
        )
        perception = _perception_provider(config)
        audit = JsonlAuditLog(config.audit_path)
        cycle_context = CycleContext(
            config,
            perception,
            vision,
            planner,
            audit,
            args.pause_file,
            args.activity_file,
            args.status_file,
            [],
        )
        _write_status(args.status_file, state="starting", message="Persona initialisé")
        cycles = 1 if args.once else args.max_cycles
        completed = 0
        while cycles is None or completed < cycles:
            if args.pause_file is not None and args.pause_file.exists():
                _write_status(args.status_file, state="paused", message="Contrôle manuel actif")
                time.sleep(0.1)
                continue
            try:
                if not _run_cycle(cycle_context):
                    continue
                completed += 1
            except (ExecutionError, OSError, RuntimeError, ValueError) as error:
                audit.write("cycle.failed", error_type=type(error).__name__, message=str(error))
                _write_status(
                    args.status_file,
                    state="degraded",
                    message=str(error),
                )
                if args.once:
                    raise
                print(f"autonomous cycle failed; continuing: {error}")
                time.sleep(max(1.0, config.interval))
                continue
            if cycles is None or completed < cycles:
                time.sleep(config.interval)
        return 0
    except (ExecutionError, OSError, PrerequisiteError, RuntimeError, ValueError) as error:
        print(f"autonomous brain failed: {error}")
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if args.activity_file is not None:
            args.activity_file.unlink(missing_ok=True)
        if args.pid_file is not None:
            args.pid_file.unlink(missing_ok=True)


def _perception_provider(config: BrainConfig) -> PerceptionProvider:
    if config.perception_source == "image":
        assert config.image_path is not None
        return ImagePerception(config.image_path)
    if config.perception_source == "simulator":
        return SimulatorPerception(config.perception_host, config.perception_port)
    return CameraPerception(config.camera_device)


def _run_cycle(context: CycleContext) -> bool:
    _write_status(context.status_file, state="observing", message="Observation de la scène")
    image = context.perception.capture()
    observation = context.vision.describe(image)
    print(f"observation: {observation}")
    context.audit.write(
        "perception.completed", observation=observation, image_bytes=len(image)
    )
    _write_status(
        context.status_file,
        state="deciding",
        message="Choix d'une action",
        observation=observation,
    )
    plan = context.planner.plan(
        observation,
        recent_behaviors=tuple(context.recent_behaviors),
    )
    plan_value = asdict(plan)
    print(json.dumps(plan_value, indent=2, ensure_ascii=False, allow_nan=False))
    context.audit.write("plan.created", plan=plan_value)
    actions = [step.tool for step in plan.steps]
    _write_status(
        context.status_file,
        state="acting",
        message="Exécution du comportement",
        observation=observation,
        actions=actions,
    )
    if not _execute_plan(
        context.config,
        plan,
        context.audit,
        context.pause_file,
        context.activity_file,
    ):
        return False
    behavior = "+".join(
        str(step.arguments.get("tag", step.tool)) for step in plan.steps
    )
    context.recent_behaviors.append(behavior)
    del context.recent_behaviors[:-3]
    _write_status(
        context.status_file,
        state="idle",
        message="Comportement terminé",
        observation=observation,
        actions=actions,
    )
    return True


def _execute_plan(
    config: BrainConfig,
    plan: Plan,
    audit: JsonlAuditLog,
    pause_file: Path | None,
    activity_file: Path | None,
) -> bool:
    if activity_file is not None:
        activity_file.parent.mkdir(parents=True, exist_ok=True)
        activity_file.touch()
    try:
        if pause_file is not None and pause_file.exists():
            audit.write("cycle.deferred", reason="manual control became active")
            return False
        PlanExecutor(
            _robot_client(config),
            oracle=(
                TcpBodyOracle(config.oracle_host, config.oracle_port)
                if config.oracle_enabled
                else None
            ),
            minimum_displacement=(config.minimum_displacement if config.oracle_enabled else None),
            event_sink=audit.lifecycle,
        ).execute(plan)
        return True
    finally:
        if activity_file is not None:
            activity_file.unlink(missing_ok=True)


def _robot_client(config: BrainConfig) -> RobotdClient:
    if config.robot_transport == "unix":
        return RobotdClient(config.robot_socket)
    return RobotdClient(host=config.robot_host, port=config.robot_port)


def _write_status(path: Path | None, *, state: str, message: str, **facts: object) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"state": state, "message": message, "updated_at": time.time(), **facts},
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
