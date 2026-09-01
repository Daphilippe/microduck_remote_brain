# Local autonomous brain

The autonomous loop is deliberately local-first and does not require speech recognition:

1. load and validate the selected TOML profile;
2. verify the Ollama API and required local models;
3. optionally verify Whisper.cpp when both voice paths are configured;
4. capture a frame from a webcam, image file, or simulator camera provider;
5. ask the local vision model for a factual observation;
6. ask the local decision model what MicroDuck would do;
7. translate the closed decision vocabulary into a bounded plan;
8. run the existing deterministic gates and executor.

Whisper.cpp is optional. The autonomous visual/personality loop never invokes it. When both
`voice.executable` and `voice.model` are present in a profile, preflight checks their files so the
same profile can also describe a voice-capable installation. Ollama remains mandatory and must be
reachable at the profile's `ollama.tags_endpoint`.

Install the visual capability. Add `--extra voice` only for push-to-talk:

```powershell
uv sync --extra vision --dev
uv sync --extra vision --extra voice --dev
```

## Personality and sounds

The `[persona]` table is MicroDuck's durable character definition. `prompt` describes temperament,
social behavior and safety priorities. `sound_actions` is the exact sound vocabulary offered to the
LLM. Supported robot commands are `alarm`, `greet`, `inquire`, `peck`, `chirp`, and `coo`.

The decision model chooses from this configured vocabulary plus `stop`. The code converts that
choice to a normal `robot.sound` or `robot.stop` plan, and existing gates validate it before the
command reaches `robotd`. This makes sounds part of autonomous expression rather than unconditional
feedback after every observation.

Edit the prompt or sound list in the selected profile, then restart the autonomous process. Unknown
sound tags and incomplete Whisper configuration are rejected at startup.

## Simulation

The default profile is [config/microduck.sim.toml](../config/microduck.sim.toml). Start the simulation
stack without push-to-talk, then run one autonomous cycle:

```powershell
.\scripts\local-stack.ps1 -NoVoice
.\scripts\autonomous-brain.ps1 -Once
```

For a bounded observation session:

```powershell
.\scripts\autonomous-brain.ps1 -MaxCycles 10
```

The simulation profile selects the fake Wi-Fi TCP gateway at `127.0.0.1:8765` and enables the
MuJoCo body oracle at `127.0.0.1:7801`. The installed `qwen3-vl:8b` model handles perception and
decision locally.

The simulation profile consumes MuJoCo's onboard `head_camera` through simulator protocol 1. A local
webcam remains available through `perception.source = "camera"`, and an image file through
`perception.source = "image"`; the latter is reread on every cycle.

Physical movement is rejected by configuration until a deterministic hardware safety provider is
implemented. In simulation, movement requires both simulator perception and the body oracle. Every
generated plan still passes through the existing gates.

Set `autonomy.interval` in TOML to change the delay between observations. Without `-Once` or
`-MaxCycles`, the launcher runs until interrupted.

## Physical MicroDuck

[config/microduck.physical.example.toml](../config/microduck.physical.example.toml) is the migration
template. It changes only providers and capabilities:

- `robot.transport = "unix"` talks directly to physical `robotd` through its socket;
- `oracle.enabled = false` removes the simulator-only position oracle;
- `[perception]` selects the local development camera until the `mediad` provider is implemented;
- the same persona, local Ollama pipeline, sound plans, gates, and executor remain unchanged.

Create a machine-specific physical profile outside version control, verify its camera really shows
the duck's forward field of view, and launch it on Linux:

```bash
./scripts/autonomous-brain.sh --config /etc/microduck/brain.toml --once
```

For a remote physical robot, use `robot.transport = "tcp"` with the physical authenticated gateway's
host and port. The current fake gateway is simulation-only and must not be exposed as a production
robot transport.

No image segmentation service is required for the first implementation because the local vision
model consumes JPEG frames directly. If segmentation is added later, its first provider must bind to
localhost and expose only derived masks or labels to this loop; remote image processing should remain
an explicit opt-in fallback.
