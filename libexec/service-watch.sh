#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# service-watch.sh – Check, report, and restart failed system services & containers
# Version: 2.4.0

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: service-watch.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "service-watch.sh version 2.4.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
SERVICES=()
DEFAULT_SERVICES=("sshd" "docker" "NetworkManager")
USER_MODE=false
DRY_RUN=false
NOTIFY=true

if command -v get_config &>/dev/null; then
    services_from_config=$(get_config_array ".services.monitor")
    if [[ -n "$services_from_config" ]]; then
        mapfile -t SERVICES <<< "$services_from_config"
    fi
    NOTIFY="$(get_config ".services.notify" "$NOTIFY")"
fi

if [[ ${#SERVICES[@]} -eq 0 ]]; then
    SERVICES=("${DEFAULT_SERVICES[@]}")
fi

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [SERVICE...]

Check status of systemd services. If failed, attempt to restart them
and send a desktop/webhook notification.

Options:
  -u, --user       Check systemd user services instead of system ones
  -n, --dry-run    Report status without attempting restarts
  -q, --quiet      Suppress notifications
  --help           Show this message
  --version        Show version
EOF
    exit 0
}

send_notify() {
    local level="$1"
    local title="$2"
    local msg="$3"
    if [[ "$NOTIFY" == true ]]; then
        send_alert "$level" "Noba Watchdog: $title" "$msg"
    fi
}

# -------------------------------------------------------------------
# Parse Arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -u|--user)    USER_MODE=true; shift ;;
        -n|--dry-run) DRY_RUN=true; shift ;;
        -q|--quiet)   NOTIFY=false; shift ;;
        -h|--help)    show_help ;;
        --version)    echo "service-watch.sh version 2.4.0"; exit 0 ;;
        -*)           log_error "Unknown option: $1"; exit 1 ;;
        *)            SERVICES+=("$1"); shift ;;
    esac
done

check_deps systemctl

if [[ "$USER_MODE" == true ]]; then
    SYS_CMD=("systemctl" "--user")
else
    SYS_CMD=("systemctl")
fi

# -------------------------------------------------------------------
# Container helpers (docker: / podman: prefix support)
# -------------------------------------------------------------------
detect_runtime() {
    if command -v docker &>/dev/null; then
        echo "docker"
    elif command -v podman &>/dev/null; then
        echo "podman"
    else
        echo ""
    fi
}

check_container() {
    local runtime="$1"
    local ct_name="$2"

    if [[ -z "$runtime" ]]; then
        log_error "No container runtime found (docker/podman) for $ct_name" >&2
        echo "no-runtime"
        return
    fi

    # Get the container state; "running", "exited", "dead", "created", or empty
    local state
    state=$("$runtime" inspect --format '{{.State.Status}}' "$ct_name" 2>/dev/null || echo "not-found")
    echo "$state"
}

restart_container() {
    local runtime="$1"
    local ct_name="$2"

    if "$runtime" restart "$ct_name" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

log_info "Checking services: ${SERVICES[*]}"

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------
CONTAINER_RUNTIME=""

for svc in "${SERVICES[@]}"; do

    # ── Container targets (docker:name or podman:name) ─────────────
    if [[ "$svc" == docker:* ]] || [[ "$svc" == podman:* ]]; then
        prefix="${svc%%:*}"
        ct_name="${svc#*:}"

        if [[ -z "$ct_name" ]]; then
            log_error "Empty container name in: $svc" >&2
            echo "$svc: invalid-config"
            continue
        fi

        # Use the explicit runtime from the prefix, or auto-detect
        if [[ "$prefix" == "docker" ]]; then
            rt="docker"
        elif [[ "$prefix" == "podman" ]]; then
            rt="podman"
        fi

        if ! command -v "$rt" &>/dev/null; then
            log_error "$rt not found for $ct_name" >&2
            echo "$svc: no-runtime"
            continue
        fi

        state=$(check_container "$rt" "$ct_name")

        if [[ "$state" == "running" ]]; then
            log_debug "Container $ct_name ($rt) is running"
            echo "$svc: running"
        elif [[ "$state" == "not-found" ]]; then
            log_warn "Container $ct_name ($rt) not found" >&2
            echo "$svc: not-found"
        elif [[ "$state" == "exited" ]] || [[ "$state" == "dead" ]] || [[ "$state" == "created" ]]; then
            log_warn "Container $ct_name ($rt) is $state – attempting restart..." >&2

            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY RUN] Would restart container $ct_name via $rt" >&2
                echo "$svc: $state (dry-run restart)"
            else
                if restart_container "$rt" "$ct_name"; then
                    log_success "Container $ct_name restarted via $rt" >&2
                    send_notify "warn" "Container restarted" "$ct_name was $state and has been auto-healed via $rt."
                    echo "$svc: restarted (auto-healed)"
                else
                    log_error "Failed to restart container $ct_name via $rt" >&2
                    send_notify "error" "Container restart failed" "$ct_name ($rt) requires manual intervention."
                    echo "$svc: $state (restart failed)"
                fi
            fi
        else
            log_warn "Container $ct_name ($rt) is in unexpected state: $state" >&2
            echo "$svc: $state"
        fi

        continue
    fi

    # ── Systemd service targets ───────────────────────────────────
    if [[ "$svc" != *.service ]]; then
        svc_name="${svc}.service"
    else
        svc_name="$svc"
    fi

    # Query status
    state=$("${SYS_CMD[@]}" show -p ActiveState --value "$svc_name" 2>/dev/null || echo "unknown")

    if [[ "$state" == "failed" ]]; then
        log_warn "Service $svc_name is failed – attempting restart..." >&2

        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] Would restart $svc_name" >&2
            echo "$svc_name: failed (dry-run restart)"
        else
            restart_cmd=("${SYS_CMD[@]}" restart "$svc_name")
            if [[ "$USER_MODE" == false ]] && [[ "$EUID" -ne 0 ]]; then
                restart_cmd=("sudo" "-n" "${restart_cmd[@]}")
            fi

            if "${restart_cmd[@]}" >/dev/null 2>&1; then
                log_success "Successfully restarted $svc_name" >&2
                send_notify "warn" "Service restarted" "$svc_name was down and has been auto-healed."
                echo "$svc_name: restarted (auto-healed)"
            else
                log_error "Failed to restart $svc_name" >&2
                send_notify "error" "Restart failed" "$svc_name requires manual intervention."
                echo "$svc_name: failed (restart blocked)"
            fi
        fi
    else
        log_debug "Service $svc_name is $state"
        echo "$svc_name: $state"
    fi
done
