from __future__ import annotations

import argparse
import json
import math
import sys
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from .body_oracle import TcpBodyOracle
from .executor import ExecutionError, LifecycleEvent, PlanExecutor
from .model import Plan
from .robotd import RobotdClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute a gated MicroDuck JSON plan")
    parser.add_argument("plan", type=Path, help="path to the JSON plan")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--robot-socket", help="robotd Unix socket path")
    transport.add_argument("--robot-host", help="fake Wi-Fi TCP gateway host")
    parser.add_argument("--robot-port", type=int, default=8765, help="fake Wi-Fi TCP gateway port")
    parser.add_argument("--simulator-host", help="simulator BodyOracle TCP host")
    parser.add_argument("--simulator-port", type=int, help="simulator BodyOracle TCP port")
    parser.add_argument("--minimum-displacement", type=float, help="required MuJoCo XY distance")
    parser.add_argument("--trace", type=Path, help="write lifecycle events as JSONL")
    return parser


def _load_plan(path: Path) -> Plan:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read plan: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid plan JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise ValueError("plan JSON root must be an object")
    try:
        return Plan.from_dict(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid plan shape: {error}") from error


def _validate_arguments(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    simulator_configured = args.simulator_host is not None or args.simulator_port is not None
    if simulator_configured and (args.simulator_host is None or args.simulator_port is None):
        parser.error("--simulator-host and --simulator-port must be provided together")
    if args.simulator_port is not None and not 1 <= args.simulator_port <= 65535:
        parser.error("--simulator-port must be between 1 and 65535")
    if not 1 <= args.robot_port <= 65535:
        parser.error("--robot-port must be between 1 and 65535")
    if args.minimum_displacement is not None:
        if not simulator_configured:
            parser.error("--minimum-displacement requires simulator host and port")
        if not math.isfinite(args.minimum_displacement) or args.minimum_displacement < 0:
            parser.error("--minimum-displacement must be finite and nonnegative")


def _write_event(stream: TextIO, event: LifecycleEvent) -> None:
    stream.write(json.dumps(asdict(event), separators=(",", ":"), allow_nan=False) + "\n")
    stream.flush()


def _error_payload(code: str, message: str) -> str:
    return json.dumps({"status": "error", "code": code, "message": message}, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_arguments(args, parser)
    try:
        plan = _load_plan(args.plan)
    except ValueError as error:
        print(_error_payload("plan.invalid", str(error)), file=sys.stderr)
        return 2

    oracle = None
    if args.simulator_host is not None:
        oracle = TcpBodyOracle(args.simulator_host, args.simulator_port)

    trace_context: Any = nullcontext(None)
    if args.trace is not None:
        try:
            trace_context = args.trace.open("w", encoding="utf-8", newline="\n")
        except OSError as error:
            print(_error_payload("trace.open_failed", str(error)), file=sys.stderr)
            return 2

    try:
        with trace_context as trace_stream:
            sink = None if trace_stream is None else lambda event: _write_event(trace_stream, event)
            robot = (
                RobotdClient(args.robot_socket)
                if args.robot_socket is not None
                else RobotdClient(host=args.robot_host, port=args.robot_port)
            )
            executor = PlanExecutor(
                robot,
                oracle=oracle,
                minimum_displacement=args.minimum_displacement,
                event_sink=sink,
            )
            executor.execute(plan)
    except ExecutionError as error:
        print(_error_payload(str(error.reason), str(error)), file=sys.stderr)
        return 1
    except OSError as error:
        print(_error_payload("trace.write_failed", str(error)), file=sys.stderr)
        return 2

    print(json.dumps({"status": "ok", "plan_id": plan.plan_id}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())