#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT=$(dirname -- "$SCRIPT_DIR")
CONFIG="$PROJECT/config/microduck.sim.toml"

if [ "${1:-}" = "--config" ]; then
    [ "$#" -ge 2 ] || { echo "--config requires a path" >&2; exit 2; }
    CONFIG=$2
    shift 2
fi

uv sync --project "$PROJECT" --extra vision --dev
exec uv run --project "$PROJECT" microduck-autonomous --config "$CONFIG" "$@"