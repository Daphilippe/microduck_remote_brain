from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from .audit import JsonlAuditLog
from .autonomy import OllamaAutonomousPlanner
from .body_oracle import TcpBodyOracle
from .brain_config import BrainConfig, load_brain_config
from .executor import ExecutionError, PlanExecutor
from .perception import CameraPerception, ImagePerception, PerceptionProvider, SimulatorPerception
from .prerequisites import PrerequisiteError, verify_local_foundations
from .robotd import RobotdClient
from .vision import OllamaVision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MicroDuck's local autonomous perception loop")
    parser.add_argument("--config", type=Path, default=Path("config/microduck.sim.toml"))
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_cycles is not None and args.max_cycles <= 0:
        raise ValueError("--max-cycles must be positive")

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
        cycles = 1 if args.once else args.max_cycles
        completed = 0
        while cycles is None or completed < cycles:
            try:
                image = perception.capture()
                observation = vision.describe(image)
                print(f"observation: {observation}")
                audit.write("perception.completed", observation=observation, image_bytes=len(image))
                plan = planner.plan(observation)
                plan_value = asdict(plan)
                print(json.dumps(plan_value, indent=2, ensure_ascii=False, allow_nan=False))
                audit.write("plan.created", plan=plan_value)
                PlanExecutor(
                    _robot_client(config),
                    oracle=(
                        TcpBodyOracle(config.oracle_host, config.oracle_port)
                        if config.oracle_enabled
                        else None
                    ),
                    minimum_displacement=(
                        config.minimum_displacement if config.oracle_enabled else None
                    ),
                    event_sink=audit.lifecycle,
                ).execute(plan)
                completed += 1
            except (ExecutionError, OSError, RuntimeError, ValueError) as error:
                audit.write("cycle.failed", error_type=type(error).__name__, message=str(error))
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


def _perception_provider(config: BrainConfig) -> PerceptionProvider:
    if config.perception_source == "image":
        assert config.image_path is not None
        return ImagePerception(config.image_path)
    if config.perception_source == "simulator":
        return SimulatorPerception(config.perception_host, config.perception_port)
    return CameraPerception(config.camera_device)


def _robot_client(config: BrainConfig) -> RobotdClient:
    if config.robot_transport == "unix":
        return RobotdClient(config.robot_socket)
    return RobotdClient(host=config.robot_host, port=config.robot_port)


if __name__ == "__main__":
    raise SystemExit(main())
