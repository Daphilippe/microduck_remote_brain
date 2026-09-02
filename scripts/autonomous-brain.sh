#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT=$(dirname -- "$SCRIPT_DIR")
CONFIG="$PROJECT/config/microduck.sim.toml"
STATE_DIR="$PROJECT/.local"
mkdir -p "$STATE_DIR"

if [ "${1:-}" = "--config" ]; then
    [ "$#" -ge 2 ] || { echo "--config requires a path" >&2; exit 2; }
    CONFIG=$2
    shift 2
fi

uv sync --project "$PROJECT" --extra vision --dev
exec uv run --project "$PROJECT" microduck-autonomous --config "$CONFIG" \
    --actions-disabled-file "$STATE_DIR/actions-disabled" "$@"