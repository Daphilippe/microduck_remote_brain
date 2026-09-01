#!/usr/bin/env bash
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/' >&2
    exit 1
fi

if [[ "${1:-}" == "--voice" ]]; then
    uv sync --project "$PROJECT" --dev --extra voice
elif [[ $# -eq 0 ]]; then
    uv sync --project "$PROJECT" --dev
else
    printf 'Usage: %s [--voice]\n' "$0" >&2
    exit 2
fi

printf '%s\n' 'Installation complete. Run: uv run pytest'