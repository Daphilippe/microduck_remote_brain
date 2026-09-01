#!/bin/bash
set -euo pipefail

ACTION="${1:?action is required}"
SCENE="${2:-apartment}"
WORKSPACE="${3:-/mnt/f/Microduck}"
RUNTIME="$WORKSPACE/.worktrees/microduck-sim"
SIMULATION="$WORKSPACE/.worktrees/microduck-rl-sim"
BRAIN="$WORKSPACE/microduck_remote_brain"
STATE="$HOME/.cache/duck-sim-remote-brain"
SIMULATION_PYTHON="$HOME/.venvs/microduck_rl_sim/bin/python"
BRAIN_PYTHON="$HOME/.venvs/microduck_remote_brain/bin/python"
GATEWAY_PID="$STATE/wifi-gateway.pid"
TELEMETRY_PID="$STATE/telemetry.pid"

export CARGO_TARGET_DIR="$HOME/.cache/microduck-sim-target"
export DUCK_SIM_RL="$SIMULATION"
export DUCK_SIM_PYTHON="$SIMULATION_PYTHON"
export DUCK_SIM_KEYFRAME=HOME
export DUCK_SIM_SCENE="$SCENE"
export DUCK_SIM_AUDIO_DEVICE=pulse
export DUCK_SIM_STATE="$STATE"

stop_gateway() {
    [[ -f "$GATEWAY_PID" ]] || return 0
    pid="$(tr -dc '0-9' < "$GATEWAY_PID")"
    rm -f "$GATEWAY_PID"
    [[ -n "$pid" && -r "/proc/$pid/cmdline" ]] || return 0
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q wifi_gateway || return 0
    kill "$pid" 2>/dev/null || true
}

stop_telemetry() {
    [[ -f "$TELEMETRY_PID" ]] || return 0
    pid="$(tr -dc '0-9' < "$TELEMETRY_PID")"
    rm -f "$TELEMETRY_PID"
    [[ -n "$pid" && -r "/proc/$pid/cmdline" ]] || return 0
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q telemetry_server || return 0
    kill "$pid" 2>/dev/null || true
}

rollback_start() {
    status=$?
    stop_gateway
    stop_telemetry
    cd "$RUNTIME"
    scripts/duck-sim down >/dev/null 2>&1 || true
    exit "$status"
}

wait_for_gateway() {
    for _ in $(seq 1 40); do
        if "$BRAIN_PYTHON" -c \
            "import socket; s=socket.create_connection(('127.0.0.1', 8765), 0.25); s.close()" \
            2>/dev/null; then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

case "$ACTION" in
    start)
        trap rollback_start ERR
        command -v aplay >/dev/null || {
            echo "alsa-utils is required in WSL" >&2
            exit 1
        }
        if ! "$SIMULATION_PYTHON" -c \
            "from mjlab_microduck.sim.body_server import main" >/dev/null 2>&1; then
            cd "$SIMULATION"
            UV_PROJECT_ENVIRONMENT="$HOME/.venvs/microduck_rl_sim" uv sync
        fi
        cd "$BRAIN"
        UV_PROJECT_ENVIRONMENT="$HOME/.venvs/microduck_remote_brain" uv sync --dev

        export DUCK_SIM_VIEWER=1
        cd "$RUNTIME"
        scripts/duck-sim

        mkdir -p "$STATE"
        stop_gateway
        setsid nohup "$BRAIN_PYTHON" -m microduck_remote_brain.wifi_gateway \
            --listen-host 127.0.0.1 \
            --listen-port 8765 \
            --robot-socket "$STATE/duck.sock" \
            > "$STATE/wifi-gateway.log" 2>&1 &
        echo "$!" > "$GATEWAY_PID"
        if ! wait_for_gateway; then
            cat "$STATE/wifi-gateway.log" >&2
            exit 1
        fi
        setsid nohup "$BRAIN_PYTHON" -m microduck_remote_brain.telemetry_server \
            --listen-host 0.0.0.0 --listen-port 8780 \
            --simulator-host 127.0.0.1 --simulator-port 7801 \
            > "$STATE/telemetry.log" 2>&1 &
        echo "$!" > "$TELEMETRY_PID"
        trap - ERR
        ;;
    status)
        cd "$RUNTIME"
        scripts/duck-sim status
        scripts/duck-sim realtime
        wait_for_gateway || {
            echo "fake Wi-Fi gateway is not reachable" >&2
            exit 1
        }
        "$BRAIN_PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1', 8780), 1); s.close()"
        ;;
    stop)
        stop_gateway
        stop_telemetry
        cd "$RUNTIME"
        scripts/duck-sim down
        ;;
    *)
        echo "unknown action: $ACTION" >&2
        exit 2
        ;;
esac