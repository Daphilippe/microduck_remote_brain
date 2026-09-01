#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT=$(dirname -- "$SCRIPT_DIR")
ACTION=${1:-start}
shift || true

case "$ACTION" in
    start) docker compose --file "$PROJECT/compose.yaml" "$@" up --detach --build --wait ;;
    status) docker compose --file "$PROJECT/compose.yaml" "$@" ps ;;
    logs) docker compose --file "$PROJECT/compose.yaml" "$@" logs --follow --tail 100 ;;
    stop) docker compose --file "$PROJECT/compose.yaml" "$@" down ;;
    *) echo "usage: $0 {start|status|logs|stop} [compose options]" >&2; exit 2 ;;
esac