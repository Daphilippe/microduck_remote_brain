# Windows, WSL2 and Docker guide

This guide describes the supported development setup on Windows. Run PowerShell commands from
`F:\Microduck\microduck_remote_brain` unless another directory is shown.

## Architecture

There are two complementary simulation modes.

### Standalone contract simulation

Docker Compose starts a dependency-free simulator, the telemetry web service and, optionally, the
autonomous brain. The simulator implements the same external contracts used by the real stack:

```text
browser :8780 -> telemetry -> simulator :7801
brain            -> robotd contract :8765
brain            -> body/camera oracle :7801
brain            -> Ollama on Windows :11434
```

This mode verifies configuration, networking, planning, gates, telemetry and migration profiles. It
does not reproduce MuJoCo dynamics or the production walking policy.

### Full MuJoCo simulation

`scripts/local-stack.ps1` starts the production Rust runtime and MuJoCo in WSL2. WSLg renders the
native simulator window. Windows runs Ollama, gamepad input, push-to-talk, the control panel and the
telemetry HTTP server. Hosting HTTP on Windows is intentional: WSL2 localhost forwarding is not
reliably reachable from another computer on the LAN.
The TCP gateway on `127.0.0.1:8765` adapts the Unix `robotd` socket for Windows clients. The body
server on `127.0.0.1:7801` provides state, ToF and the simulated head camera.

The autonomous simulation profile now reads that head camera. It no longer uses the PC webcam.

## Prerequisites

Install:

1. Windows 11 or a current Windows 10 release with WSL2 support;
2. WSL2 with Ubuntu 22.04 and WSLg;
3. Docker Desktop using the WSL2 backend, only for the standalone Compose mode;
4. Python 3.12 and `uv` on Windows;
5. Ollama on Windows for autonomous inference;
6. Git and PowerShell 7 or Windows PowerShell 5.1.

Verify the host:

```powershell
wsl --status
wsl --list --verbose
docker info
uv --version
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Ubuntu must appear with version `2`. In Docker Desktop, enable **Use the WSL 2 based engine** and
integration for `Ubuntu-22.04`.

## Install the Python project

```powershell
Set-ExecutionPolicy -Scope Process Bypass
uv sync --dev --extra vision --extra voice
uv run pytest
uv run ruff check .
uv run pylint src/microduck_remote_brain
uv run pyright --project pyproject.toml
```

`--extra vision` is needed only for a Windows webcam. MuJoCo frames and image files use the standard
library. `--extra voice` installs microphone capture support; Whisper.cpp remains an external tool.

## Start the standalone stack

Start Docker Desktop, then run:

```powershell
.\scripts\standalone-stack.ps1 start
Start-Process http://localhost:8780
```

Useful operations:

```powershell
.\scripts\standalone-stack.ps1 status
.\scripts\standalone-stack.ps1 logs
.\scripts\standalone-stack.ps1 stop
```

To include autonomous inference, first pull the configured model and make Ollama reachable from
containers:

```powershell
ollama pull qwen3-vl:8b
$env:OLLAMA_HOST = "0.0.0.0:11434"
ollama serve
.\scripts\standalone-stack.ps1 start -WithAutonomy
```

Docker reaches the Windows service as `host.docker.internal`. Keep autonomous movement disabled in
the Docker profile unless testing the protocol gate deliberately. Audit records are stored in the
Compose volume `brain-state`.

## Start the full MuJoCo stack

The full stack expects sibling runtime and simulation worktrees documented by the workspace setup.
From PowerShell:

```powershell
.\scripts\local-stack.ps1 -NoVoice
.\scripts\local-stack.ps1 -Action status
.\scripts\autonomous-brain.ps1 -Once
```

The startup sequence is:

1. synchronize Windows and WSL Python environments;
2. verify or start Ollama on Windows;
3. start MuJoCo and `robotd` under WSL2;
4. expose `robotd` through the localhost TCP adapter;
5. start telemetry on Windows port `8780`, reading the WSL body server through localhost;
6. start the gamepad and optional voice clients;
7. run autonomy separately with `microduck.sim.toml`.

Stop every managed process with:

```powershell
.\scripts\local-stack.ps1 -Action stop
```

## Access telemetry from another computer

The full launcher prints the selected Ethernet IPv4 address. On another machine on the same private
network, open `http://<windows-ip>:8780`.

Check the endpoint before changing the firewall:

```powershell
Invoke-RestMethod http://127.0.0.1:8780/api/health
Get-NetTCPConnection -LocalPort 8780 -State Listen
Get-NetConnectionProfile
```

The launcher creates a Windows Firewall rule for private profiles. Do not enable that rule on a
public network. A yellow **Disconnected** status means the web server is alive but the simulator is
not returning valid data; it no longer displays fabricated default telemetry as a connected robot.
The launcher validates both `http://127.0.0.1:8780/api/health` and the selected LAN address before it
prints **Network telemetry**.

## Configuration profiles

- `config/microduck.sim.toml`: full MuJoCo stack on the same Windows/WSL machine;
- `config/microduck.docker.toml`: Compose service names and Windows Ollama bridge;
- `config/microduck.physical.example.toml`: template for a Linux host beside the physical robot.

The brain depends on providers rather than MuJoCo internals. Migration changes `[robot]`,
`[perception]` and `[oracle]`; personality and plan gates remain unchanged. Unknown TOML fields,
invalid ports and unsafe movement/provider combinations fail at startup.

## Troubleshooting

### Docker daemon unavailable

If PowerShell reports `//./pipe/docker_engine`, start Docker Desktop and wait until `docker info`
succeeds. Compose syntax can still be checked without starting containers:

```powershell
docker compose -f compose.yaml config
```

### WSL service fails to import the package

Windows virtual environments cannot run inside Linux. Synchronize the dedicated WSL environment:

```powershell
wsl.exe -d Ubuntu-22.04 -- bash -lc `
  "cd /mnt/f/Microduck/microduck_remote_brain && UV_PROJECT_ENVIRONMENT=~/.venvs/microduck_remote_brain uv sync --dev"
```

### Telemetry is reachable but disconnected

```powershell
.\scripts\local-stack.ps1 -Action status
Get-Content .\.local\telemetry-error.log
Test-NetConnection 127.0.0.1 -Port 7801
Invoke-RestMethod http://127.0.0.1:8780/api/health
Invoke-RestMethod http://<windows-ip>:8780/api/health
```

### Ollama is slow

Inference calls intentionally do not add new short timeouts in the local setup. Large local models
may legitimately take several minutes. Check GPU and model activity with `nvidia-smi` and
`ollama ps` before treating a long response as a failure.

## Physical migration

Do not enable physical autonomous movement yet. Copy the physical example outside the repository,
set the Unix socket or future remote gateway, and keep `allow_movement = false`:

```bash
sudo install -d -o "$USER" /var/lib/microduck
cp config/microduck.physical.example.toml /etc/microduck/brain.toml
./scripts/autonomous-brain.sh --config /etc/microduck/brain.toml --once
```

Physical movement remains rejected until a deterministic hardware sensor gate is implemented. The
future `mediad` perception provider must replace local camera indexing for remote onboard video.
