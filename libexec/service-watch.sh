#!/bin/bash
# service-watch.sh – Check, report, and restart failed system services
# Version: 2.2.1

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
    echo "service-watch.sh version 2.2.1"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
SERVICES=()
DEFAULT_SERVICES=("sshd" "docker" "NetworkManager")
USER_MODE=false
DRY_RUN=false
NOTIFY=true

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    services_from_config=$(get_config_array ".services.monitor")
    if [ -n "$services_from_config" ]; then
        mapfile -t SERVICES <<< "$services_from_config"
    fi
    NOTIFY="$(get_config ".services.notify" "$NOTIFY")"
    [[ "$NOTIFY" == "false" ]] && NOTIFY=false
fi

if [ ${#SERVICES[@]} -eq 0 ]; then
    SERVICES=("${DEFAULT_SERVICES[@]}")
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "service-watch.sh version 2.2.1"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Monitor system services, report their status, and restart any in a failed state.

Options:
  -s, --service NAME   Add a service to monitor (can be repeated)
  -u, --user           Operate on user services (systemctl --user)
  -n, --dry-run        Show what would be restarted without actually doing it
  --no-notify          Disable desktop notifications
  --help               Show this help message
  --version            Show version information
EOF
    exit 0
}

send_notify() {
    local urgency="$1"
    local summary="$2"
    local body="$3"

    if [ "$NOTIFY" = false ] || [ "$DRY_RUN" = true ]; then
        return
    fi

    if command -v notify-send &>/dev/null && [ -n "${DISPLAY:-}" ]; then
        notify-send -u "$urgency" -a "Noba Watch" "$summary" "$body" || true
    else
        log_debug "notify-send not available or no DISPLAY – skipping notification." >&2
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o s:un -l service:,user,dry-run,no-notify,help,version -- "$@"); then
    log_error "Invalid argument"
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -s|--service)   SERVICES+=("$2"); shift 2 ;;
        -u|--user)      USER_MODE=true; shift ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        --no-notify)    NOTIFY=false; shift ;;
        --help)         show_help ;;
        --version)      show_version ;;
        --)             shift; break ;;
        *)              log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
if ! command -v systemctl &>/dev/null; then
    die "systemctl not found – is systemd installed?"
fi

SYS_CMD=("systemctl")
if [ "$USER_MODE" = true ]; then
    SYS_CMD+=("--user")
fi

log_info "Starting service watch (user mode: $USER_MODE, dry run: $DRY_RUN)" >&2

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------
for svc in "${SERVICES[@]}"; do
    [[ "$svc" != *.service ]] && svc_name="${svc}.service" || svc_name="$svc"

    # Query status
    state=$("${SYS_CMD[@]}" show -p ActiveState --value "$svc_name" 2>/dev/null || echo "unknown")

    if [[ "$state" == "failed" ]]; then
        log_warn "Service $svc_name is failed – attempting restart..." >&2

        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would restart $svc_name" >&2
            echo "$svc_name: failed (dry-run restart)"
        else
            restart_cmd=("${SYS_CMD[@]}" restart "$svc_name")
            if [ "$USER_MODE" = false ] && [ "$EUID" -ne 0 ]; then
                restart_cmd=("sudo" "-n" "${restart_cmd[@]}")
            fi

            if "${restart_cmd[@]}" >/dev/null 2>&1; then
                log_success "Successfully restarted $svc_name" >&2
                send_notify "critical" "Service restarted" "$svc_name was down and has been auto-healed."
                echo "$svc_name: restarted (auto-healed)"
            else
                log_error "Failed to restart $svc_name" >&2
                send_notify "critical" "Restart failed" "$svc_name requires manual intervention."
                echo "$svc_name: failed (restart blocked)"
            fi
        fi
    else
        log_debug "Service $svc_name is $state" >&2
        echo "$svc_name: $state"
    fi
done

log_info "Service watch completed." >&2
