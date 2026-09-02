from __future__ import annotations

import threading
from io import BytesIO

from PIL import Image

from microduck_remote_brain.body_oracle import TcpBodyOracle
from microduck_remote_brain.executor import PlanExecutor
from microduck_remote_brain.model import Plan
from microduck_remote_brain.perception import SimulatorPerception
from microduck_remote_brain.robotd import RobotdClient
from microduck_remote_brain.standalone_simulator import (
    OracleHandler,
    RobotHandler,
    SimulatedBody,
    SimulationServer,
)


def test_standalone_simulator_executes_plan_over_loopback() -> None:
    body = SimulatedBody()
    with (
        SimulationServer(("127.0.0.1", 0), RobotHandler, body) as robot_server,
        SimulationServer(("127.0.0.1", 0), OracleHandler, body) as oracle_server,
    ):
        threads = [
            threading.Thread(target=robot_server.serve_forever),
            threading.Thread(target=oracle_server.serve_forever),
        ]
        for thread in threads:
            thread.start()
        try:
            robot_port = robot_server.server_address[1]
            oracle_port = oracle_server.server_address[1]
            plan = Plan.from_dict(
                {
                    "schema_version": 1,
                    "plan_id": "integration-plan",
                    "goal": "exercise loopback contracts",
                    "steps": [
                        {
                            "id": "walk",
                            "tool": "walk",
                            "arguments": {
                                "linear_velocity": 0.1,
                                "angular_velocity": 0.0,
                                "duration": 0.05,
                            },
                        }
                    ],
                }
            )

            events = PlanExecutor(
                RobotdClient(host="127.0.0.1", port=robot_port),
                oracle=TcpBodyOracle("127.0.0.1", oracle_port),
                minimum_displacement=0.001,
            ).execute(plan)
            frame = SimulatorPerception("127.0.0.1", oracle_port).capture()

            assert events[-1].event == "plan.completed"
            assert frame.startswith(b"\xff\xd8")
            with Image.open(BytesIO(frame)) as image:
                assert image.size == (640, 480)
        finally:
            robot_server.shutdown()
            oracle_server.shutdown()
            for thread in threads:
                thread.join()