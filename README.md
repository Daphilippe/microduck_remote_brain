# MicroDuck Remote Brain

Deterministic planning and verification layer for a simulated or physical
MicroDuck. The brain sends high-level intents to `robotd`; it never accesses
motors or `RemoteIo` directly.

The first supported path is deliberately small:

```text
typed walk plan -> deterministic gates -> robotd IPC -> RemoteIo -> MuJoCo
                <- robot.state evidence <-          <- simulator oracle
```

## Installation

See [docs/INSTALL.md](docs/INSTALL.md) for supported prerequisites, the
PowerShell and shell installers, optional voice dependencies, and release
hygiene. The shortest development setup is:

```bash
./scripts/install.sh
uv run pytest
```

On Windows PowerShell, use `.\scripts\install.ps1` followed by
`uv run pytest`. Add `--voice` or `-Voice` only when microphone capture is
needed.

For the complete Windows, WSL2 and Docker workflow, read
[docs/WINDOWS_WSL.md](docs/WINDOWS_WSL.md). The provider boundaries and deferred production work are
documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/TODO.md](docs/TODO.md).

## Standalone contract simulation

The repository includes a dependency-free protocol simulator and a Docker Compose stack. It emulates
the external `robotd`, body, ToF, IMU and camera contracts without requiring the Rust or MuJoCo
repositories:

```powershell
.\scripts\standalone-stack.ps1 start
Start-Process http://localhost:8780
.\scripts\standalone-stack.ps1 stop
```

This is intended for repeatable integration and migration testing. Use the full local simulation
below when MuJoCo physics, the production policy and WSLg rendering are required.

## M1 execution

```bash
microduck-brain plan.json \
    --robot-socket /run/microduck/robotd.sock \
    --simulator-host 127.0.0.1 \
    --simulator-port 7801 \
    --minimum-displacement 0.02 \
    --trace execution.jsonl
```

The simulator arguments are optional. `--minimum-displacement` requires them
and verifies trunk XY displacement after each walk. The TCP BodyOracle is
read-only and is never a robot command path.

### Wire contracts

The robotd transport is newline-delimited JSON-RPC 2.0 over a Unix stream
socket. It sends `robot.subscribe` requests with `{ "hz": 10.0 }`,
`robot.move` notifications with `vx`, `vy` and `vyaw`, and
`robot.stop` requests. Request results must contain `{ "accepted": true }`.
`robot.state` notifications must report finite applied velocity as
`move.applied = [vx, vy, vyaw]`.

The simulator transport is newline-delimited JSON over TCP. Protocol 1 starts
with `{ "op": "hello", "protocol": 1, "joints": 15 }`, which receives
`{ "protocol": 1 }`. An `{ "op": "read" }` request receives
`{ "trunk": [x, y, z], "sim_time": ... }`. All numeric values must be finite.

## Complete local simulation

Run the complete stack from PowerShell:

```powershell
.\scripts\local-stack.ps1
```

The script starts components in this order:

1. the Ollama service on the Windows PC;
2. the visual `microduck_rl` apartment world under WSLg;
3. the production `robotd` runtime connected to MuJoCo through `RemoteIo`;
4. simulated ToF and the duck voice bank through WSLg PulseAudio;
5. a TCP gateway on `127.0.0.1:8765` representing the Wi-Fi hop;
6. the Windows-hosted MuJoCo telemetry dashboard on `0.0.0.0:8780`, reading
    the WSL simulator through localhost and adding a Windows Firewall rule for private networks;
7. the autonomous camera/personality loop, enabled for bounded MuJoCo movement;
8. the Windows push-to-talk loop, Whisper.cpp, Ollama planning, gates, and actions.

The telemetry dashboard is reachable from another PC at the Ethernet IPv4
address printed by the launcher, for example `http://<lan-ip>:8780`. It reads
the live MuJoCo protocol and displays joint positions and velocities, currents,
trunk pose, simulation time, IMU gravity/gyro/quaternion, nominal voltage and
temperatures, plus the simulated VL53L5CX 8x8 ToF frame. Both PCs must be on the
same private network. The native MuJoCo window remains local to the
Windows/WSLg session; it is not a network video stream.

The MuJoCo model's `head_camera` is rendered at 640x480 and 10 fps. The autonomous simulation
profile and dashboard both consume this camera; the PC webcam is not used by that profile. The
dashboard exposes it as MJPEG at `/api/camera/stream` and as a single JPEG at
`/api/camera.jpg`. Rendering uses a private MuJoCo state copy so camera work
does not hold the physics lock or reduce `robotd`'s 50 Hz control rate. This
MJPEG transport is for local simulation; the physical MicroDuck is expected to
use the hardware H.264/WebRTC path provided by `mediad`.

The controller mapping matches `padd`:

| Control | Simulated MicroDuck action |
| --- | --- |
| Left stick | Forward/backward and lateral motion |
| Right stick X | Turn |
| Start | Enable or disable the policy |
| Y | Toggle head mode; both sticks pose the head |
| B | Toggle body-pose mode; sticks lean and crouch |
| A | Ground pick |
| X | Roulade; hold to chain |
| LB / RB | Left / right kick |
| D-pad down | Sit / stand |
| RT | Open mouth and chirp on press |
| LT | Open mouth and hold the wheee sound |
| Right stick press | Push-to-talk start/stop |

The gamepad client starts with the local stack and waits safely if the pad is
asleep. A disconnect sends `robot.stop`; `robotd`'s deadman remains the final
fallback. When no active gamepad slot is available for push-to-talk, the
launcher uses Enter as the voice trigger.

If the launcher reports that the controller is paired without an input stream,
press the Xbox button until it remains steadily lit and run `joy.cpl`. If the
controller does not appear there, remove and pair it again in Windows Bluetooth
settings. The gamepad client polls continuously and does not need a restart
after the controller becomes available.

The microphone can be selected with `-Microphone`, using a SoundDevice index
or device name. No machine-specific device is assumed by the project.

Useful commands:

```powershell
.\scripts\local-stack.ps1 -NoVoice
.\scripts\local-stack.ps1 -NoVoice -NoAutonomy
.\scripts\local-stack.ps1 -Action status
.\scripts\local-stack.ps1 -Action text -Text "Walk forward for four seconds"
.\scripts\local-stack.ps1 -Action stop
```

The launcher does not require activating the Python virtual environment
manually. Use `-TelemetryPort` when port `8780` is already occupied.
`-NoVoice` keeps the autonomous personality running; use `-NoAutonomy` only when a fully manual
simulation is required. Voice, autonomous actions and gamepad commands use separate activity files
so they do not command the robot simultaneously. The telemetry dashboard's **Persona autonome**
section shows each live observe/decide/act cycle and the last completed behavior.

The TCP gateway is intentionally simulation-only and has no authentication. It
creates a real network boundary on one PC without pretending to implement RF.
The physical deployment will replace this gateway with the project's remote
Wi-Fi/WebRTC transport while keeping the plan, gates, and `robotd` intents.

Scenario files live in the `microduck_rl` worktree. The default launcher scene
is `apartment`; pass `-Scene` to select another `scene_<name>.xml` world.

### Mouse interaction

Enable **Mouse interaction** in the `MicroDuck Simulation Controls` window. The
mode preselects the duck's trunk and gates all mouse-applied forces. When the
box is cleared, pending mouse forces are removed and dragging controls only the
camera. The applied wrench lets the duck be lifted, pushed, turned, dropped,
and allowed to recover naturally.

| Mouse gesture | Effect |
| --- | --- |
| `Ctrl` + left drag | Rotate the selected body |
| `Ctrl` + right drag | Move it in the vertical plane |
| `Ctrl` + `Shift` + right drag | Move it in the horizontal plane |
| Drag without `Ctrl` | Move the camera |
