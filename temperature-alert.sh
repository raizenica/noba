#!/bin/bash
# temperature-alert.sh – Alert if CPU temp exceeds threshold

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# Defaults
THRESHOLD=85
CHECK_INTERVAL=60
ONE_SHOT=false

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    THRESHOLD="$(get_config ".disk.threshold" "$THRESHOLD")"
    # Optionally read interval from config if you define it
fi

show_version() {
    echo "temperature-alert.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Monitor CPU temperature and send notifications when it exceeds a threshold.

Options:
  --threshold TEMP   Set alert threshold in °C (default: $THRESHOLD)
  --interval SECS    Check every SECS seconds (default: $CHECK_INTERVAL)
  --one-shot         Check once and exit (useful for cron)
  --help             Show this help message
  --version          Show version information
EOF
    exit 0
}

# Parse arguments
PARSED_ARGS=$(getopt -o '' -l threshold:,interval:,one-shot,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --threshold) THRESHOLD="$2"; shift 2 ;;
        --interval)  CHECK_INTERVAL="$2"; shift 2 ;;
        --one-shot)  ONE_SHOT=true; shift ;;
        --help)      show_help ;;
        --version)   show_version ;;
        --)          shift; break ;;
        *)           break ;;
    esac
done

# Function to check temperature and notify
check_temperature() {
    if ! command -v sensors &>/dev/null; then
        log_error "lm_sensors not installed. Please install with: sudo dnf install lm_sensors"
        return 1
    fi

    local temp
    temp=$(sensors | grep -E "Package id 0|Core" | awk '{print $3}' | sed 's/+//;s/°C//' | sort -nr | head -1)

    if [ -z "$temp" ]; then
        log_warn "Could not read CPU temperature. Check sensors output."
        return 1
    fi

    local temp_int="${temp%.*}"
    if [ "$temp_int" -ge "$THRESHOLD" ]; then
        local summary="⚠ CPU Overheat: ${temp}°C"
        local body="Temperature exceeded threshold of ${THRESHOLD}°C"
        log_warn "$summary - $body"

        if command -v notify-send &>/dev/null && [ -n "${DISPLAY:-}" ]; then
            notify-send -u critical "$summary" "$body"
        else
            logger -t temperature-alert "$summary $body"
            echo "$summary $body" | wall 2>/dev/null || true
        fi
    else
        log_debug "Temperature normal: ${temp}°C"
    fi
}

# Trap signals for clean exit
trap 'log_info "Exiting on signal"; exit 0' INT TERM

# Main
if [ "$ONE_SHOT" = true ]; then
    check_temperature
    exit $?
fi

log_info "Starting temperature monitor (threshold=${THRESHOLD}°C, interval=${CHECK_INTERVAL}s)"
while true; do
    check_temperature
    sleep "$CHECK_INTERVAL"
done
