# Local autonomous brain

Model selection and the target separation between `SceneState`, `PersonaIntent`, and actuators are
detailed in [PERSONA_MODELS.md](PERSONA_MODELS.md). Whisper remains out of scope for this work: the
visual perception and persona paths must operate without speech recognition.

The autonomous loop is deliberately local-first and does not require speech recognition:

1. load and validate the selected TOML profile;
2. verify the Ollama API and required local models;
3. optionally verify Whisper.cpp when both voice paths are configured;
4. capture a frame from a webcam, image file, or simulator camera provider;
5. ask the Ollama scene model for a factual, schema-constrained `SceneState`;
6. ask the separate Ollama persona model for a `PersonaIntent` and bounded voice style;
7. resolve the closed intent vocabulary into a bounded plan with deterministic code;
8. run the existing deterministic gates and executor.

In simulation, each cycle also reads the 8x8 ToF frame. The nearest valid measurements are reduced
to left, center, and right clearance sectors. A blocked center forces a turn toward the clearer side
or a stop when neither side is open; a forward walk requires both visual clearance and sufficient
center depth. Small nearby balls, cubes, toys, and blocks may use the existing `ground_pick`,
`kick_left`, or `kick_right` robot skills. Unknown or larger objects remain obstacles.

The two bottom ToF rows form a conservative floor-continuity band. A sector is marked as a possible
drop when at least half its lower rays have no valid return, or when every valid lower return is
beyond 700 mm. This catches likely platform edges, downward stairs, and voids from the simulated
robot's approximately 20 cm sensor height. A `DropHazardMemory` latch survives camera and persona
cycles and clears only after three consecutive frames with no drop sector. Forward motion and
object-interaction skills are denied while the latch is set. A safe lateral sector may be inspected
by turning; otherwise the only offered action is `stop`.

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

The decision model chooses from this configured vocabulary plus `stop` and the movement actions that
are explicitly enabled. Its only sound modulation is a closed `single` or `double` pattern. A double
pattern emits the same allowed sound twice; the model cannot set volume, pitch, arbitrary files or
raw sound parameters. The code converts the choice to normal `robot.sound` steps, and existing gates
validate every step before it reaches `robotd`.

The decision prompt receives only the three most recent behavior summaries from the current process.
This small session memory helps avoid repeating the same expression without becoming a durable or
unbounded personality store. It never expands the configured action vocabulary.

The activity budget makes physical behavior the default whenever deterministic gates expose at
least one safe option. Fewer than two physical behaviors in the three-entry recent window removes
sound-only and stop choices from the next LLM schema. Physical behavior includes forward walking,
left or right curved wandering, a bounded reverse escape from close obstacles, in-place inspection
turns, and bounded object skills. Reverse escape is unavailable while a drop hazard is remembered.
After two physical behaviors, the persona may choose a quieter expressive cycle before activity is
required again.

Every cycle queries `robot.subscribe` and `robot.mode`. Only loaded and position-compatible skills
enter the persona schema. In walk mode, `sit_toggle` is exposed when its policy is loaded. An
autonomous sit toggle forces a stand toggle at the start of the next cycle,
before camera capture or LLM inference, so an unclear seated view cannot strand the robot. Only then
does locomotion resume. `tap_left` and `tap_right` map to the corresponding kick only for a nearby
entity classified as a ball and only when that kick policy is loaded. In roller mode, leg-dependent kicks,
roulade, and sit/stand are removed; locomotion is interpreted by robotd's roller policy and
`ground_pick` uses the loaded roller crouch policy. Autonomy never switches into roller mode because
the current protocol does not report whether physical rollers are installed.

The occasional-action scheduler offers `sit_toggle` or `sing` after four behaviors with no special
action, while avoiding immediate repetition. `sing` is a bounded `coo`/`chirp`/`coo`
phrase. Native `robot.chorale` is not used for solo behavior because robotd may reject it unless
chorale participation is explicitly enabled and another duck is present.

Insufficient visibility starts a head-only acquisition sequence: left, right, then center. Each
step first verifies a stopped body and then calls `robot.look`; no locomotion command is emitted.
The sequence completes even when the first side view is clear, so the next decision has observations
from both sides and the head returns to center. A remembered drop interrupts scanning and keeps its
higher-priority stop or avoidance behavior.

This acquisition also runs before persona planning when camera capture returns an unusable frame or
when the vision model returns an invalid semantic scene. The failed scene is never passed to the
persona. The worker records `perception.recovery_started`, executes deterministic `stop + look`, and
retries from the new head pose on the next cycle. Local capture and semantic-format failures trigger
the scan; an unreachable Ollama service remains a connection error because head movement cannot
repair it.

Even with valid semantics, five consecutive behaviors without a scan start a proactive
left/right/center acquisition. This keeps nearby spatial understanding fresh instead of waiting for
the VLM to admit uncertainty.

If the scene is still invalid after the center view, head movement is considered insufficient. The
recovery controller then rotates the body toward the ToF side with the greatest safe clearance and
restarts acquisition from that new orientation. This reorientation has zero linear velocity and is
suppressed whenever drop memory makes the candidate side unsafe.

Completing the center view forces the next safe choice to be body locomotion rather than another
sound, sit, or scan. Ordinary forward exploration is allowed from 280 mm center clearance, matching
MicroDuck's small footprint; in-place turning remains available down to 100 mm lateral clearance.
These relaxed obstacle margins do not change drop/stair detection. A translation that fails
displacement verification is recorded as `failed:<action>` and
removed from the persona schema for the recent-behavior window, forcing a different exploration
strategy instead of repeating an ineffective command.

Immediate repetition of the same locomotion intent is removed from the schema. After two consecutive
turn or scan behaviors, the next safe choice is restricted to forward or curved translation when
one is available. This prevents valid head acquisition from degenerating into endless orientation
changes without spatial exploration.

Before every scripted skill, autonomy records an `action.anchor_captured` pose containing X, Y, yaw,
and robot time. The anchor uses the mapping session's already connected `RobotOdometryProvider`
when available. Roulade is not currently used as an autonomous filler: it may significantly change
pose and will return only after the deterministic map-based target controller can restore that
anchor. Manual roulade remains available through the command center and gamepad.

Exploration is environment-independent: decisions use relative entity bearings, semantic floor
state, and left/center/right ToF clearance. No room name, map coordinate, route, or apartment-specific
object is encoded in the resolver. The simulation profiles run a new cycle every four seconds.

The telemetry dashboard exposes the live persona state:

- `observing`: the vision model is reading the current head-camera frame;
- `acquiring`: an unusable or invalid scene is being replaced through a head-only scan;
- `deciding`: the persona model is selecting one allowed behavior;
- `acting`: the gated plan is being executed;
- `idle`: the previous behavior completed and its action remains visible;
- `paused`: voice or another manual control currently has priority;
- `actions_disabled`: the persistent dashboard safety latch forbids robot actions;
- `degraded` or `stale`: the latest cycle failed or the worker stopped updating.

Edit the prompt or sound list in the selected profile, then restart the autonomous process. Unknown
sound tags and incomplete Whisper configuration are rejected at startup.

## Simulation

The default profile is [config/microduck.sim.toml](../config/microduck.sim.toml). The normal local
stack starts autonomy in the background. `-NoVoice` disables push-to-talk but keeps autonomy active:

```powershell
.\scripts\local-stack.ps1 -NoVoice
Get-Content .\.local\autonomy.log -Wait
```

For one foreground cycle without a competing background brain:

```powershell
.\scripts\local-stack.ps1 -NoVoice -NoAutonomy
.\scripts\autonomous-brain.ps1 -Once
```

For a bounded observation session:

```powershell
.\scripts\autonomous-brain.ps1 -MaxCycles 10
```

The simulation profile selects the fake Wi-Fi TCP gateway at `127.0.0.1:8765` and enables the
MuJoCo body oracle at `127.0.0.1:7801`. Ollama serves `qwen3.5:0.8b` for structured scene
interpretation and the dedicated `qwen3:0.6b` model for persona decisions.

The simulation profile consumes MuJoCo's onboard `head_camera` through simulator protocol 1. A local
webcam remains available through `perception.source = "camera"`, and an image file through
`perception.source = "image"`; the latter is reread on every cycle.

Physical movement is rejected by configuration until a deterministic hardware safety provider is
implemented. In simulation, movement requires both simulator perception and the body oracle. Every
generated plan still passes through the existing gates. A safe `stop` decision also emits one quiet
`coo`, so an autonomous cycle remains observable even when movement is unsafe.

Raw range discontinuities are not sufficient proof of floor geometry on hardware. Physical stair
protection must use the Rust ToF reprojector with head joints, trunk posture, and gravity before
`allow_movement` is enabled. The simulation latch is intentionally not presented as that missing
hardware certification.

Set `autonomy.interval` in TOML to change the delay between observations. Without `-Once` or
`-MaxCycles`, the launcher runs until interrupted.

The command center's **Disable all actions** control creates `.local/actions-disabled` and sends an
immediate stop. The autonomous worker also checks this file before every cycle. The latch survives
launcher restarts; only **Enable all actions** or deliberate removal of that file re-enables motion.
This is independent of temporary manual-control pause/resume.

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
