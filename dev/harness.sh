#!/usr/bin/env bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# harness.sh — Dev server lifecycle manager for NOBA
#
# Manages a development instance of noba-web on a separate port so
# Claude can code → restart → test → verify in a loop.
#
# Usage:
#   dev/harness.sh start        Start dev server (port 8099)
#   dev/harness.sh stop         Stop dev server
#   dev/harness.sh restart      Restart dev server
#   dev/harness.sh status       Check if running
#   dev/harness.sh logs [N]     Tail last N lines of logs (default: 50)
#   dev/harness.sh curl PATH    Authenticated curl to the dev server
#   dev/harness.sh health       Quick health check
#   dev/harness.sh screenshot   Take a dashboard screenshot (via eye.py)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

DEV_PORT="${NOBA_DEV_PORT:-8099}"
DEV_HOST="${NOBA_DEV_HOST:-127.0.0.1}"
DEV_PID="/tmp/noba-dev-server.pid"
DEV_LOG="/tmp/noba-dev-server.log"
DEV_TOKEN_FILE="/tmp/noba-dev-token"

SERVER_DIR="$PROJECT_ROOT/share/noba-web/server"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

_info()  { echo -e "${BLUE}[harness]${NC} $*"; }
_ok()    { echo -e "${GREEN}[harness]${NC} $*"; }
_warn()  { echo -e "${YELLOW}[harness]${NC} $*"; }
_err()   { echo -e "${RED}[harness]${NC} $*" >&2; }

_is_running() {
    if [[ -f "$DEV_PID" ]]; then
        local pid
        pid=$(<"$DEV_PID")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$DEV_PID"
    fi
    return 1
}

_wait_ready() {
    local max_wait="${1:-15}"
    local url="http://${DEV_HOST}:${DEV_PORT}/api/health"
    for i in $(seq 1 "$max_wait"); do
        if curl -sf "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

_get_token() {
    if [[ -f "$DEV_TOKEN_FILE" ]]; then
        cat "$DEV_TOKEN_FILE"
        return 0
    fi

    local user="${NOBA_DEV_USER:-raizen}"
    local pass="${NOBA_DEV_PASS:-}"

    if [[ -z "$pass" ]]; then
        _warn "Set NOBA_DEV_PASS to enable authenticated requests"
        return 1
    fi

    local response
    response=$(curl -sf "http://${DEV_HOST}:${DEV_PORT}/api/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$user\",\"password\":\"$pass\"}" 2>/dev/null) || {
        _err "Login failed"
        return 1
    }

    local token
    token=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)

    if [[ -n "$token" ]]; then
        echo "$token" > "$DEV_TOKEN_FILE"
        echo "$token"
        return 0
    fi
    _err "No token in response"
    return 1
}

cmd_start() {
    if _is_running; then
        _warn "Dev server already running (PID $(cat "$DEV_PID"))"
        return 0
    fi

    _info "Starting dev server on ${DEV_HOST}:${DEV_PORT}..."

    # Use a different PID file to not conflict with production
    PORT="$DEV_PORT" HOST="$DEV_HOST" PID_FILE="$DEV_PID" \
        python3 -m uvicorn server.app:app \
        --host "$DEV_HOST" --port "$DEV_PORT" \
        --app-dir "$PROJECT_ROOT/share/noba-web" \
        --log-level info \
        > "$DEV_LOG" 2>&1 &

    local pid=$!
    echo "$pid" > "$DEV_PID"

    if _wait_ready 15; then
        _ok "Dev server started (PID $pid, port $DEV_PORT)"
        # Show health
        curl -sf "http://${DEV_HOST}:${DEV_PORT}/api/health" | python3 -m json.tool 2>/dev/null || true
    else
        _err "Server failed to start. Check logs:"
        tail -20 "$DEV_LOG"
        rm -f "$DEV_PID"
        return 1
    fi
}

cmd_stop() {
    if ! _is_running; then
        _warn "Dev server not running"
        return 0
    fi

    local pid
    pid=$(<"$DEV_PID")
    _info "Stopping dev server (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$DEV_PID" "$DEV_TOKEN_FILE"
    _ok "Stopped"
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    if _is_running; then
        local pid
        pid=$(<"$DEV_PID")
        _ok "Running (PID $pid, port $DEV_PORT)"
        curl -sf "http://${DEV_HOST}:${DEV_PORT}/api/health" | python3 -m json.tool 2>/dev/null || true
    else
        _warn "Not running"
        return 1
    fi
}

cmd_logs() {
    local lines="${1:-50}"
    if [[ -f "$DEV_LOG" ]]; then
        tail -n "$lines" "$DEV_LOG"
    else
        _warn "No log file found"
    fi
}

cmd_curl() {
    local path="$1"
    shift

    if ! _is_running; then
        _err "Dev server not running. Start it first."
        return 1
    fi

    local token
    token=$(_get_token 2>/dev/null) || true

    local auth_header=()
    if [[ -n "${token:-}" ]]; then
        auth_header=(-H "Authorization: Bearer $token")
    fi

    curl -sf "http://${DEV_HOST}:${DEV_PORT}${path}" \
        "${auth_header[@]}" \
        "$@" | python3 -m json.tool 2>/dev/null || \
    curl -sf "http://${DEV_HOST}:${DEV_PORT}${path}" \
        "${auth_header[@]}" \
        "$@"
}

cmd_health() {
    curl -sf "http://${DEV_HOST}:${DEV_PORT}/api/health" | python3 -m json.tool
}

cmd_screenshot() {
    if ! _is_running; then
        _err "Dev server not running. Start it first."
        return 1
    fi
    python3 "$SCRIPT_DIR/eye.py" --port "$DEV_PORT" --host "$DEV_HOST" "$@"
}

cmd_help() {
    cat <<EOF
NOBA Dev Server Harness

Usage: $0 <command> [args...]

Commands:
  start              Start the dev server (port $DEV_PORT)
  stop               Stop the dev server
  restart            Restart the dev server
  status             Check if dev server is running
  logs [N]           Show last N lines of server log (default: 50)
  curl PATH [opts]   Authenticated curl request to dev server
  health             Quick health check
  screenshot [opts]  Take UI screenshot (passes args to eye.py)
  help               Show this help

Environment:
  NOBA_DEV_PORT      Dev server port (default: 8099)
  NOBA_DEV_HOST      Dev server host (default: 127.0.0.1)
  NOBA_DEV_USER      Login username (default: raizen)
  NOBA_DEV_PASS      Login password (required for auth)

Examples:
  $0 start
  $0 curl /api/stats
  $0 curl /api/me
  $0 screenshot dashboard --mobile
  $0 logs 100
EOF
}

# --- Main ---
case "${1:-help}" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    status)     cmd_status ;;
    logs)       shift; cmd_logs "${1:-50}" ;;
    curl)       shift; cmd_curl "$@" ;;
    health)     cmd_health ;;
    screenshot) shift; cmd_screenshot "$@" ;;
    help|--help|-h) cmd_help ;;
    *)          _err "Unknown command: $1"; cmd_help; exit 1 ;;
esac
