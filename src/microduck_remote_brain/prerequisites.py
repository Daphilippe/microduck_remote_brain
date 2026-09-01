from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


class PrerequisiteError(RuntimeError):
    pass


def verify_local_foundations(
    *,
    whisper_executable: Path | None = None,
    whisper_model: Path | None = None,
    ollama_models: tuple[str, ...],
    ollama_tags_endpoint: str = "http://127.0.0.1:11434/api/tags",
    timeout: float = 3.0,
) -> None:
    if (whisper_executable is None) != (whisper_model is None):
        raise PrerequisiteError("Whisper executable and model must be configured together")
    missing_files = [
        str(path)
        for path in (whisper_executable, whisper_model)
        if path is not None and not path.is_file()
    ]
    if missing_files:
        raise PrerequisiteError(f"Whisper.cpp is not ready; missing: {', '.join(missing_files)}")

    try:
        with urllib.request.urlopen(ollama_tags_endpoint, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise PrerequisiteError(
            f"Ollama is not reachable at {ollama_tags_endpoint}: {error}"
        ) from error

    installed = {
        model.get("name")
        for model in payload.get("models", [])
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    }
    missing_models = sorted(set(ollama_models) - installed)
    if missing_models:
        commands = ", ".join(f"ollama pull {model}" for model in missing_models)
        names = ", ".join(missing_models)
        raise PrerequisiteError(f"Ollama models are missing: {names} ({commands})")
