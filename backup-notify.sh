#!/bin/bash
set -euo pipefail

# Script directory and library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# ==============================
# Default configuration
# ==============================
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"

# Load user configuration (if any)
load_config
if [ "${CONFIG_LOADED:-false}" = true ]; then
    # Override defaults with config values (if defined)
    LOG_FILE="$(get_config ".backup_notify.log_file" "$LOG_FILE")"
fi

# ==============================
# Helper functions
# ==============================
show_version() {
    echo "backup-notify.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Send a desktop notification about the last backup status.

Options:
  --help            Show this help message
  --version         Show version information
  --log-file FILE   Use FILE instead of the default log
EOF
    exit 0
}

send_notification() {
    local urgency="$1"
    local summary="$2"
    local body="$3"

    if command -v notify-send &>/dev/null; then
        notify-send -u "$urgency" "$summary" "$body"
    elif command -v kdialog &>/dev/null; then
        kdialog --passivepopup "$body" 5 --title "$summary"
    else
        # Fallback to console
        echo "$summary: $body"
    fi
}

# ==============================
# Parse command line arguments
# ==============================
while [[ $# -gt 0 ]]; do
    case $1 in
        --help) show_help ;;
        --version) show_version ;;
        --log-file)
            if [[ -z "${2:-}" ]]; then
                log_error "--log-file requires an argument"
                exit 1
            fi
            LOG_FILE="$2"
            shift
            ;;
        *)  echo "Unknown option: $1" >&2
            show_help
            ;;
    esac
    shift
done

# ==============================
# Validate log file
# ==============================
if [ ! -r "$LOG_FILE" ]; then
    log_error "Cannot read backup log: $LOG_FILE"
    exit 1
fi

# ==============================
# Read last line of log
# ==============================
last_line="$(tail -1 "$LOG_FILE" 2>/dev/null || true)"
if [ -z "$last_line" ]; then
    log_error "Log file is empty or could not be read: $LOG_FILE"
    exit 1
fi

# ==============================
# Determine notification urgency and summary
# ==============================
case "$last_line" in
    *[Ee][Rr][Rr][Oo][Rr]*) urgency="critical"; summary="⚠ Backup Failed" ;;
    *[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee]*) urgency="normal"; summary="✅ Backup Completed" ;;
    *) urgency="low"; summary="ℹ Backup Status Unknown" ;;
esac

# ==============================
# Send notification
# ==============================
send_notification "$urgency" "$summary" "$last_line"
