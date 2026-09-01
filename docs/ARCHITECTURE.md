# Architecture and provider boundary

The remote brain owns perception, personality planning, deterministic plan validation and execution
evidence. It never drives motors directly.

```text
PerceptionProvider -> Ollama vision -> closed action enum -> Plan
                                                       -> deterministic gates
                                                       -> RobotdClient
BodyOracle --------------------------------------------> execution evidence
Lifecycle events --------------------------------------> JSONL audit
```

## Stable contracts

`RobotdClient` uses newline-delimited JSON-RPC 2.0. A profile selects a Unix socket beside the robot
or a TCP adapter. `BodyOracle` and `SimulatorPerception` use simulator protocol 1. Input frames are
bounded and reject non-standard JSON numbers. No model output bypasses `validate_plan`.

The simulation providers are replaceable:

| Concern | Standalone | Full simulation | Physical target |
| --- | --- | --- | --- |
| Commands | emulated robotd TCP | TCP-to-robotd adapter | robotd Unix socket / future gateway |
| Vision | static protocol JPEG | MuJoCo head camera | future mediad provider |
| Evidence | emulated body oracle | MuJoCo body oracle | hardware safety provider, pending |
| Monitoring | telemetry HTTP | telemetry HTTP | provider-neutral collector, pending |

## Safety boundary

Velocity, duration, capabilities, plan identity and confirmation are deterministic. Autonomous
movement additionally requires simulator perception and the body oracle at configuration load time.
This deliberately keeps physical autonomous locomotion disabled until hardware proximity, fall,
battery and frame-freshness evidence can be evaluated without trusting an LLM statement.

## Failure behavior

One-shot runs fail immediately and return a nonzero exit code. Long-running autonomy records the
cycle error, waits for the configured local interval and starts a fresh cycle. Local model calls do
not have newly shortened deadlines because inference latency depends heavily on model and GPU.
Robotd's own deadman remains the final movement fallback.
