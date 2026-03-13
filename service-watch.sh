#!/bin/bash
# service-watch.sh – Check and restart failed system services

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
SERVICES=("sshd" "docker" "NetworkManager")
USER_MODE=false
DRY_RUN=false
NOTIFY=true

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config || true
if [ "$CONFIG_LOADED" = true ]; then
    # Read services array from config
    services_from_config=$(get_config_array ".services.monitor")
    if [ -n "$services_from_config" ]; then
        mapfile -t SERVICES <<< "$services_from_config"
    fi
    # Optional: read notify setting from config
    NOTIFY="$(get_config ".services.notify" "$NOTIFY")"
    [[ "$NOTIFY" == "false" ]] && NOTIFY=false
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "service-watch.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Monitor system services and restart any that are in a failed state.

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

# Send desktop notification (if enabled and not dry run)
send_notify() {
    local urgency="$1"
    local summary="$2"
    local body="$3"
    if [ "$NOTIFY" = false ] || [ "$DRY_RUN" = true ]; then
        return
    fi
    if command -v notify-send &>/dev/null && [ -n "${DISPLAY:-}" ]; then
        notify-send -u "$urgency" "$summary" "$body"
    else
        log_debug "notify-send not available – skipping notification."
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o s:un -l service:,user,dry-run,no-notify,help,version -- "$@"); then
    show_help
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
        *)              break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
if ! command -v systemctl &>/dev/null; then
    log_error "systemctl not found – is systemd installed?"
    exit 1
fi

SYSTEMCTL_CMD="systemctl"
if [ "$USER_MODE" = true ]; then
    SYSTEMCTL_CMD="systemctl --user"
    # Ensure user service manager is available
    if ! systemctl --user is-system-running &>/dev/null; then
        log_warn "User service manager not available – continuing anyway."
    fi
fi

log_info "Starting service watch (user mode: $USER_MODE, dry run: $DRY_RUN)"
log_debug "Monitoring services: ${SERVICES[*]}"

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------
for svc in "${SERVICES[@]}"; do
    log_debug "Checking service: $svc"
    # Check if service is in failed state
    if $SYSTEMCTL_CMD is-failed "$svc" &>/dev/null; then
        log_warn "Service $svc is failed – restarting..."

        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would restart $svc"
            send_notify "normal" "[DRY RUN] Would restart $svc" "Service was failed"
        else
            # Attempt restart
            if $SYSTEMCTL_CMD restart "$svc"; then
                log_info "Successfully restarted $svc"
                send_notify "critical" "Service restarted" "$svc was down and has been restarted"
            else
                log_error "Failed to restart $svc"
                send_notify "critical" "Failed to restart $svc" "Manual intervention required"
            fi
        fi
    else
        log_debug "Service $svc is OK"
    fi
done

log_info "Service watch completed."
