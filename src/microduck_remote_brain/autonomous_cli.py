from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .audit import JsonlAuditLog
from .autonomy import ActuatorResolver, OllamaPersonaModel, PersonaIntent
from .body_oracle import TcpBodyOracle
from .brain_config import BrainConfig, load_brain_config
from .executor import ExecutionError, ExecutionReason, PlanExecutor
from .localization import RobotOdometryProvider
from .mapping import ExplorationPolicy, MappingSession, OccupancyGrid, OccupancyGridMapper
from .mapping_worker import MappingWorker
from .model import Plan
from .perception import (
    CameraPerception,
    DepthObservation,
    DropHazardMemory,
    ImagePerception,
    PerceptionProvider,
    SimulatorPerception,
)
from .prerequisites import PrerequisiteError, verify_local_foundations
from .robotd import RobotCapabilities, RobotdClient
from .vision import OllamaVision


@dataclass(frozen=True, slots=True)
class CycleContext:
    config: BrainConfig
    perception: PerceptionProvider
    vision: OllamaVision
    persona: OllamaPersonaModel
    actuators: ActuatorResolver
    audit: JsonlAuditLog
    pause_file: Path | None
    activity_file: Path | None
    status_file: Path | None
    actions_disabled_file: Path | None
    drop_memory: DropHazardMemory
    mapping_session: MappingSession | None
    mapping_pose_provider: RobotOdometryProvider | None
    mapping_worker: MappingWorker | None
    exploration_policy: ExplorationPolicy
    recent_behaviors: list[str]
    last_behavior: dict[str, object]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MicroDuck's local autonomous perception loop")
    parser.add_argument("--config", type=Path, default=Path("config/microduck.sim.toml"))
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pause-file", type=Path)
    parser.add_argument("--activity-file", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--actions-disabled-file", type=Path)
    parser.add_argument("--pid-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_cycles is not None and args.max_cycles <= 0:
        raise ValueError("--max-cycles must be positive")

    if args.pid_file is not None:
        args.pid_file.parent.mkdir(parents=True, exist_ok=True)
        args.pid_file.write_text(str(os.getpid()), encoding="ascii")
    mapping_pose_provider: RobotOdometryProvider | None = None
    mapping_worker: MappingWorker | None = None
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
        persona = OllamaPersonaModel(
            config.ollama_model,
            persona_prompt=config.persona_prompt,
            sound_actions=config.sound_actions,
            allow_movement=config.allow_movement,
            endpoint=config.ollama_endpoint,
        )
        actuators = ActuatorResolver(
            sound_actions=config.sound_actions,
            allow_movement=config.allow_movement,
        )
        perception = _perception_provider(config)
        audit = JsonlAuditLog(config.audit_path)
        mapping_session = None
        if config.mapping_enabled:
            mapper = _load_mapping(config)
            mapping_pose_provider = RobotOdometryProvider(_robot_client(config))
            mapping_pose_provider.connect()
            mapping_session = MappingSession(
                mapper,
                config.mapping_path,
                keyframe_directory=config.mapping_keyframe_directory,
                horizontal_fov_rad=math.radians(
                    config.mapping_tof_horizontal_fov_degrees
                ),
                max_range_m=config.mapping_max_range_m,
            )
            assert isinstance(perception, SimulatorPerception)
            mapping_worker = MappingWorker(
                SimulatorPerception(config.perception_host, config.perception_port),
                RobotOdometryProvider(_robot_client(config)),
                mapping_session,
                audit,
                map_path=str(config.mapping_path),
                update_interval_s=config.mapping_update_interval_s,
            )
            mapping_worker.start()
        cycle_context = CycleContext(
            config,
            perception,
            vision,
            persona,
            actuators,
            audit,
            args.pause_file,
            args.activity_file,
            args.status_file,
            args.actions_disabled_file,
            DropHazardMemory(),
            mapping_session,
            mapping_pose_provider,
            mapping_worker,
            ExplorationPolicy(),
            [],
            {},
        )
        _write_status(args.status_file, state="starting", message="Persona initialized")
        cycles = 1 if args.once else args.max_cycles
        completed = 0
        actions_were_disabled = False
        while cycles is None or completed < cycles:
            actions_disabled = (
                args.actions_disabled_file is not None
                and args.actions_disabled_file.exists()
            )
            if actions_disabled:
                if not actions_were_disabled:
                    _stop_robot(config)
                    audit.write("actions.disabled")
                actions_were_disabled = True
                _write_status(
                    args.status_file,
                    state="actions_disabled",
                    message="All robot actions are disabled by the safety latch",
                )
                time.sleep(0.1)
                continue
            if actions_were_disabled:
                audit.write("actions.enabled")
                actions_were_disabled = False
            if args.pause_file is not None and args.pause_file.exists():
                _write_status(args.status_file, state="paused", message="Manual control active")
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
        if mapping_worker is not None:
            mapping_worker.stop()
        if mapping_pose_provider is not None:
            mapping_pose_provider.close()
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
    if context.recent_behaviors and context.recent_behaviors[-1] == "sit_toggle":
        return _run_stand_recovery(context)
    _write_status(
        context.status_file,
        state="observing",
        message="Interpreting scene",
        **context.last_behavior,
    )
    capabilities = _robot_capabilities(context.config)
    try:
        image = context.perception.capture()
    except (RuntimeError, ValueError) as error:
        wrapped = ExecutionError(
            ExecutionReason.ROBOT_PROTOCOL,
            f"camera acquisition did not produce a usable scene: {error}",
        )
        return _run_visual_recovery(context, wrapped, None, capabilities, 0)
    mapping_worker = getattr(context, "mapping_worker", None)
    if mapping_worker is not None:
        map_grid, depth = mapping_worker.latest()
        if depth is None and isinstance(context.perception, SimulatorPerception):
            depth = context.drop_memory.update(context.perception.capture_depth())
        if mapping_worker.localized:
            context.exploration_policy.mark_localized()
        mapping_worker.archive_keyframe(image)
    else:
        depth = (
            context.drop_memory.update(context.perception.capture_depth())
            if isinstance(context.perception, SimulatorPerception)
            else None
        )
        map_grid = _update_mapping(context, image, depth)
    if getattr(context, "mapping_session", None) is not None and map_grid is None:
        return _run_localization_scan(context, depth)
    try:
        scene = context.vision.interpret(image)
    except ExecutionError as error:
        if error.reason is not ExecutionReason.ROBOT_PROTOCOL:
            raise
        return _run_visual_recovery(context, error, depth, capabilities, len(image))
    scene_value = scene.to_dict()
    depth_value = depth.to_dict() if depth is not None else None
    capabilities_value = capabilities.to_dict()
    print(f"scene: {json.dumps(scene_value, ensure_ascii=False, allow_nan=False)}")
    context.audit.write(
        "perception.completed",
        scene=scene_value,
        depth=depth_value,
        capabilities=capabilities_value,
        observation=scene.summary,
        image_bytes=len(image),
    )
    _write_status(
        context.status_file,
        state="deciding",
        message="Selecting persona intent",
        scene=scene_value,
        depth=depth_value,
        capabilities=capabilities_value,
        observation=scene.summary,
    )
    exploration_action = (
        context.exploration_policy.exploration_action(map_grid, depth)
        if map_grid is not None and depth is not None
        else None
    )
    intent = (
        PersonaIntent(exploration_action, "single", "curious", "")
        if exploration_action is not None
        else context.persona.decide(
            scene,
            depth=depth,
            capabilities=capabilities,
            recent_behaviors=tuple(context.recent_behaviors),
        )
    )
    intent_value = asdict(intent)
    context.audit.write("persona.decided", intent=intent_value)
    plan = context.actuators.resolve(intent, scene, depth, capabilities)
    plan_value = asdict(plan)
    print(json.dumps(plan_value, indent=2, ensure_ascii=False, allow_nan=False))
    context.audit.write("plan.created", plan=plan_value)
    action_anchor = (
        _capture_action_anchor(context)
        if any(step.tool == "skill" for step in plan.steps)
        else None
    )
    if action_anchor is not None:
        context.audit.write(
            "action.anchor_captured",
            action=intent.action,
            anchor=action_anchor,
        )
    actions = [step.tool for step in plan.steps]
    behavior_status: dict[str, object] = {
        "scene": scene_value,
        "depth": depth_value,
        "capabilities": capabilities_value,
        "observation": scene.summary,
        "intent": intent_value,
        "voice_style": intent.voice_style,
        "utterance": intent.utterance,
        "actions": actions,
        "action_anchor": action_anchor,
    }
    _write_status(
        context.status_file,
        state="acting",
        message="Executing resolved behavior",
        scene=scene_value,
        depth=depth_value,
        capabilities=capabilities_value,
        observation=scene.summary,
        intent=intent_value,
        voice_style=intent.voice_style,
        utterance=intent.utterance,
        actions=actions,
    )
    try:
        if not _execute_plan(
            context.config,
            plan,
            context.audit,
            context.pause_file,
            context.activity_file,
        ):
            return False
    except ExecutionError as error:
        if error.reason is ExecutionReason.INSUFFICIENT_DISPLACEMENT:
            failed_behavior = f"failed:{intent.action}"
            context.recent_behaviors.append(failed_behavior)
            del context.recent_behaviors[:-6]
            context.audit.write(
                "behavior.stalled",
                action=intent.action,
                reason=error.reason,
                message=str(error),
            )
        raise
    context.recent_behaviors.append(intent.action)
    del context.recent_behaviors[:-6]
    context.last_behavior.clear()
    context.last_behavior.update(behavior_status)
    _write_status(
        context.status_file,
        state="idle",
        message="Behavior completed",
        **behavior_status,
    )
    return True


def _update_mapping(
    context: CycleContext, image: bytes, depth: DepthObservation | None
) -> OccupancyGrid | None:
    mapping_session = getattr(context, "mapping_session", None)
    pose_provider = getattr(context, "mapping_pose_provider", None)
    if mapping_session is None or pose_provider is None or depth is None:
        return None
    odom_pose = pose_provider.read()
    pose_source = getattr(pose_provider, "pose_source", "robotd_odometry")
    if not context.exploration_policy.localized:
        pose = mapping_session.relocalize(odom_pose, depth)
        if pose is None:
            context.audit.write("localization.unmatched")
            return None
        pose_provider.set_map_anchor(odom_pose, pose)
        context.exploration_policy.mark_localized()
        context.audit.write(
            "localization.acquired",
            pose_source=pose_source,
            x_m=pose.x_m,
            y_m=pose.y_m,
            yaw_rad=pose.yaw_rad,
        )
    else:
        pose = odom_pose
    grid = mapping_session.update(
        pose,
        depth,
        image,
        pose_source=pose_source,
    )
    context.audit.write(
        "mapping.updated",
        revision=grid.revision,
        changed_cells=len(grid.changed_cells),
        pose_source=pose_source,
        map_path=str(context.config.mapping_path),
    )
    return grid


def _run_localization_scan(
    context: CycleContext, depth: DepthObservation | None
) -> bool:
    action = context.exploration_policy.startup_action()
    if action is None or depth is None or depth.drop_hazard_remembered:
        raise RuntimeError("persistent map localization failed after startup scan")
    clearance = depth.left_clearance_mm if action == "turn_left" else depth.right_clearance_mm
    if clearance is None or clearance < 150.0:
        raise RuntimeError("startup localization turn has insufficient clearance")
    plan = Plan.from_dict(
        {
            "schema_version": 1,
            "plan_id": str(uuid.uuid4()),
            "goal": "Relocalize against the persistent map",
            "steps": [
                {
                    "id": "scan-turn",
                    "tool": "walk",
                    "arguments": {
                        "linear_velocity": 0.0,
                        "angular_velocity": 0.5 if action == "turn_left" else -0.5,
                        "duration": 1.0,
                    },
                },
                {"id": "stop", "tool": "stop", "arguments": {}},
            ],
            "requires_confirmation": False,
        }
    )
    _write_status(
        context.status_file,
        state="localizing",
        message="Rotating to match the persistent map",
        actions=["walk", "stop"],
    )
    context.audit.write("localization.scan", action=action)
    return _execute_plan(
        context.config,
        plan,
        context.audit,
        context.pause_file,
        context.activity_file,
    )


def _run_visual_recovery(
    context: CycleContext,
    error: ExecutionError,
    depth: DepthObservation | None,
    capabilities: RobotCapabilities,
    image_bytes: int,
) -> bool:
    previous = context.recent_behaviors[-1] if context.recent_behaviors else None
    body_reorientation = _visual_recovery_turn(previous, depth)
    scan_action = (
        {"scan_left": "scan_right", "scan_right": "scan_center"}.get(previous)
        if previous is not None
        else None
    )
    action = body_reorientation or scan_action or "scan_left"
    if body_reorientation is not None:
        angular_velocity = 0.5 if action == "reorient_left" else -0.5
        steps = [
            {
                "id": "reorient",
                "tool": "walk",
                "arguments": {
                    "linear_velocity": 0.0,
                    "angular_velocity": angular_velocity,
                    "duration": 1.5,
                },
            },
            {"id": "stop", "tool": "stop", "arguments": {}},
            {"id": "feedback", "tool": "sound", "arguments": {"tag": "chirp"}},
        ]
    else:
        target_y = {"scan_left": 0.35, "scan_right": -0.35, "scan_center": 0.0}[action]
        steps = [
            {"id": "hold-body", "tool": "stop", "arguments": {}},
            {
                "id": "scan",
                "tool": "look",
                "arguments": {
                    "x": 0.5,
                    "y": target_y,
                    "z": 0.0,
                    "neck_pitch": 0.0,
                },
            },
        ]
    plan = Plan.from_dict(
        {
            "schema_version": 1,
            "plan_id": str(uuid.uuid4()),
            "goal": "Acquire a valid semantic scene from a new viewpoint",
            "steps": steps,
            "requires_confirmation": False,
        }
    )
    depth_value = depth.to_dict() if depth is not None else None
    capabilities_value = capabilities.to_dict()
    context.audit.write(
        "perception.recovery_started",
        reason=error.reason,
        message=str(error),
        action=action,
        depth=depth_value,
        capabilities=capabilities_value,
        image_bytes=image_bytes,
    )
    _write_status(
        context.status_file,
        state="acquiring",
        message=(
            "Head scan was insufficient; reorienting the body"
            if body_reorientation is not None
            else "Semantic scene invalid; scanning with the head"
        ),
        depth=depth_value,
        capabilities=capabilities_value,
        intent={"action": action},
        actions=[step.tool for step in plan.steps],
    )
    if not _execute_plan(
        context.config,
        plan,
        context.audit,
        context.pause_file,
        context.activity_file,
    ):
        return False
    context.recent_behaviors.append(action)
    del context.recent_behaviors[:-6]
    context.last_behavior.clear()
    context.last_behavior.update(
        {
            "depth": depth_value,
            "capabilities": capabilities_value,
            "observation": str(error),
            "intent": {"action": action},
            "actions": [step.tool for step in plan.steps],
            "utterance": "",
        }
    )
    _write_status(
        context.status_file,
        state="idle",
        message="Head acquisition completed; semantic vision will retry",
        **context.last_behavior,
    )
    return True


def _visual_recovery_turn(
    previous: str | None, depth: DepthObservation | None
) -> str | None:
    if (
        previous != "scan_center"
        or depth is None
        or depth.drop_hazard_remembered
    ):
        return None
    candidates = {
        "reorient_left": (
            0.0 if "left" in depth.drop_hazard_sectors else depth.left_clearance_mm or 0.0
        ),
        "reorient_right": (
            0.0 if "right" in depth.drop_hazard_sectors else depth.right_clearance_mm or 0.0
        ),
    }
    action, clearance = max(candidates.items(), key=lambda item: item[1])
    return action if clearance >= 100.0 else None


def _run_stand_recovery(context: CycleContext) -> bool:
    plan = Plan.from_dict(
        {
            "schema_version": 1,
            "plan_id": "autonomous-stand-recovery",
            "goal": "Return to standing after autonomous sitting",
            "steps": [
                {"id": "stand-up", "tool": "skill", "arguments": {"name": "sit_toggle"}},
                {"id": "feedback", "tool": "sound", "arguments": {"tag": "chirp"}},
            ],
            "requires_confirmation": False,
        }
    )
    plan_value = asdict(plan)
    context.audit.write("plan.created", plan=plan_value, deterministic_recovery=True)
    _write_status(
        context.status_file,
        state="acting",
        message="Returning to standing before the next observation",
        intent={"action": "stand_up"},
        actions=["skill", "sound"],
    )
    if not _execute_plan(
        context.config,
        plan,
        context.audit,
        context.pause_file,
        context.activity_file,
    ):
        return False
    context.recent_behaviors.append("stand_up")
    del context.recent_behaviors[:-6]
    context.last_behavior.clear()
    context.last_behavior.update(
        {
            "intent": {"action": "stand_up"},
            "actions": ["skill", "sound"],
            "utterance": "",
        }
    )
    _write_status(
        context.status_file,
        state="idle",
        message="Stand recovery completed",
        **context.last_behavior,
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
            state_timeout=3.0,
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


def _robot_capabilities(config: BrainConfig) -> RobotCapabilities:
    robot = _robot_client(config)
    robot.connect()
    try:
        return robot.capabilities()
    finally:
        robot.close()


def _capture_action_anchor(context: CycleContext) -> dict[str, float] | None:
    pose_provider = context.mapping_pose_provider
    if pose_provider is None:
        return None
    pose = pose_provider.read()
    return {
        "x_m": pose.x_m,
        "y_m": pose.y_m,
        "yaw_rad": pose.yaw_rad,
        "timestamp_s": pose.timestamp_s,
    }


def _load_mapping(config: BrainConfig) -> OccupancyGridMapper:
    if config.mapping_path.exists():
        try:
            return OccupancyGridMapper.load(config.mapping_path)
        except ValueError:
            legacy = config.mapping_path.with_name(
                config.mapping_path.stem + ".legacy-schema.json"
            )
            if legacy.exists():
                legacy = config.mapping_path.with_name(
                    config.mapping_path.stem + f".legacy-schema-{int(time.time())}.json"
                )
            config.mapping_path.replace(legacy)
            localization = config.mapping_path.with_name("localization.json")
            if localization.exists():
                localization_legacy = localization.with_name("localization.legacy-schema.json")
                if localization_legacy.exists():
                    localization_legacy = localization.with_name(
                        f"localization.legacy-schema-{int(time.time())}.json"
                    )
                localization.replace(localization_legacy)
    return OccupancyGridMapper(
        resolution_m=config.mapping_resolution_m,
        width=config.mapping_width,
        height=config.mapping_height,
    )


def _stop_robot(config: BrainConfig) -> None:
    robot = _robot_client(config)
    robot.connect()
    try:
        robot.stop()
    finally:
        robot.close()


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
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.01)


if __name__ == "__main__":
    raise SystemExit(main())
