# Architecture and provider boundary

The remote brain owns perception, personality planning, deterministic plan validation and execution
evidence. It never drives motors directly.

```text
PerceptionProvider -> Ollama scene model -> SceneState
Body sensors ------------------------------> SceneState
                                 |
                                 v
                          Ollama persona model -> PersonaIntent
                                            |
                                            v
                                    deterministic resolver -> Plan
                                                    |
                                                    v
                                            deterministic gates
                                                    |
                                                    v
                                                RobotdClient
BodyOracle ------------------------------------------------------> execution evidence
Lifecycle events ------------------------------------------------> JSONL audit
```

Ollama is the default model provider. Scene and persona inference use separate compact model names
behind separate contracts, even though they share one Ollama endpoint. llama.cpp is not part of
the current runtime; it is only a possible future provider for an on-robot text model.

## Stable contracts

`RobotdClient` uses newline-delimited JSON-RPC 2.0. A profile selects a Unix socket beside the robot
or a TCP adapter. `BodyOracle` and `SimulatorPerception` use simulator protocol 1. Input frames are
bounded and reject non-standard JSON numbers. The scene model emits a validated `SceneState`; the
persona model emits a validated `PersonaIntent`; deterministic code alone creates the `Plan`. No
model output bypasses `validate_plan`.

The current persona is intentionally active. When deterministic gates expose physical options, at
least two entries in each three-behavior window must be locomotion or object interaction. The
locomotion vocabulary is `walk_forward`, `curve_left`, `curve_right`, `back_up`, `turn_left`, and
`turn_right`. These intents depend only on relative scene facts and left/center/right depth, never
on a named map or stored route. Ordinary semantic uncertainty may be tolerated when ToF confirms
clearance; the remembered drop boundary remains absolute and disables reverse escape too.

`robot.subscribe` capability names and `robot.mode` are refreshed before every persona decision.
They constrain the schema itself: unavailable policies cannot be selected, and roller mode removes
walk-only scripted behaviors. Head scans are represented as deterministic `stop` plus `robot.look`
plans, so acquisition changes camera direction without moving the trunk.

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

Simulation adds a deterministic depth boundary before intent resolution. The lower two rows of the
8x8 ToF frame identify possible floor discontinuities in three horizontal sectors. Drop evidence is
latched until three subsequent clear observations, so rotating the camera cannot immediately erase
a recently observed void. The latch forbids translation and scripted object interactions.

A separate persistent action-disable file is checked by both the autonomous worker and telemetry
control surface. Activating it issues `robot.stop`; HTTP control then rejects every non-stop action.
It is intentionally independent of the temporary ownership files used by voice and gamepad input.

## Failure behavior

One-shot runs fail immediately and return a nonzero exit code. Long-running autonomy records the
cycle error, waits for the configured local interval and starts a fresh cycle. Local model calls do
not have newly shortened deadlines because inference latency depends heavily on model and GPU.
Robotd's own deadman remains the final movement fallback.

## Navigation boundary

The current theremin is a hand-distance musical mode, not a laser or waypoint follower. Future A-to-B
movement uses the architecture in [NAVIGATION.md](NAVIGATION.md): an LLM, UI, or detector supplies a
bounded relative target, while a deterministic controller closes the loop on body X/Y/yaw, ToF,
drop memory, progress, and timeout. `BodySnapshot` now preserves simulator yaw as the first required
odometry contract. The waypoint executor is not yet marked complete.
