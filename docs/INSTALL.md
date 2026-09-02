# Installation

This document describes the supported installation paths for the initial
`microduck-remote-brain` release.

## Requirements

The package requires:

- Python 3.12 or newer;
- [uv](https://docs.astral.sh/uv/) for environment and dependency management;
- a checked-out copy of this project.

The core planner, safety gates, robotd client, and simulator transports use
only the Python standard library. The optional `voice` extra adds NumPy and
SoundDevice for microphone capture. Whisper.cpp and Ollama are separate
programs and are not Python dependencies.

## Install the development environment

From the project directory, run one of the platform-specific installers:

```powershell
.\scripts\install.ps1
```

```bash
./scripts/install.sh
```

Both commands create or update the project environment from `uv.lock` and
install the test and lint tools. To include microphone support, add `-Voice`
to PowerShell or `--voice` to the shell installer:

```powershell
.\scripts\install.ps1 -Voice
```

```bash
./scripts/install.sh --voice
```

The equivalent direct command is `uv sync --dev`, or
`uv sync --dev --extra voice`.

## Verify the installation

Run the complete local checks:

```bash
uv run pytest
uv run ruff check .
uv run pylint src/microduck_remote_brain
```

On Windows PowerShell, use the same `uv run` commands. The package can also
be tested without activating `.venv` manually because `uv run` selects it.

## Optional voice stack

Voice execution additionally requires:

1. an Ollama installation with a model available locally, for example the
   model passed with `--ollama-model`;
2. a Whisper.cpp executable and a compatible model file;
3. a working input device visible to SoundDevice.

Pass their paths explicitly to `microduck-voice` with `--whisper-exe` and
`--whisper-model`. Use `--microphone` with a device index or name when the
default device is not suitable. Text mode does not need the voice extra,
Whisper.cpp, or a microphone.

## Full simulator stack

The full `scripts/local-stack.ps1` launcher is a development integration
scenario, not a production installer. It additionally expects:

- Windows PowerShell, WSL2 with the `Ubuntu-22.04` distribution, and WSLg;
- `npm` and the dependencies of `Open_Duck_Mini_Viewer`;
- the sibling `microduck_rl` project and its MuJoCo simulator environment;
- the MicroDuck Rust runtime worktree;
- Ollama and Whisper.cpp for voice control;
- an Xbox-compatible controller for gamepad control.

Run it only after those projects and environments are installed:

```powershell
.\scripts\local-stack.ps1
```

The command center writes the persistent safety latch to `.local/actions-disabled`. This local file
is intentionally preserved by launcher restarts. Use **Enable all actions** in the dashboard to
clear it explicitly after checking the scene and robot state.

The fake Wi-Fi gateway binds to localhost and has no authentication. It is
simulation-only and must not be exposed to an untrusted network.

## Release hygiene and personal data

Do not publish `.local/`, `*.jsonl`, audio recordings, transcripts, local
model files, IP addresses, usernames, absolute paths, or device names. These
files are ignored by this project, but always inspect `git status` and the
release archive before publishing. Configure microphone and network values
through command-line arguments rather than committing local defaults.