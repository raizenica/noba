#!/bin/bash
set -euo pipefail

# ==============================
# Script directory and library
# ==============================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# ==============================
# Default configuration
# ==============================
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
DRY_RUN=false
FORCE_URGENCY=""   # If set, overrides automatic urgency detection

# Load user configuration (if any)
load_config
if [ "${CONFIG_LOADED:-false}" = true ]; then
    LOG_FILE="$(get_config ".backup_notify.log_file" "$LOG_FILE")"
fi

# ==============================
# Helper functions
# ==============================
show_version() {
    echo "backup-notify.sh version 2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Send a desktop notification about the last backup status.

Options:
  --log-file FILE       Use FILE instead of the default log
  --urgency URG         Override urgency (low, normal, critical)
  --dry-run             Show what would be sent without actually notifying
  --help                Show this help message
  --version             Show version information
EOF
    exit 0
}

send_notification() {
    local urgency="$1"
    local summary="$2"
    local body="$3"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would send notification:"
        log_info "  urgency: $urgency"
        log_info "  summary: $summary"
        log_info "  body: $body"
        return
    fi

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
# Use getopt for proper option parsing
if ! PARSED_ARGS=$(getopt -o '' -l log-file:,urgency:,dry-run,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --log-file)
            LOG_FILE="$2"
            shift 2
            ;;
        --urgency)
            FORCE_URGENCY="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            show_help
            ;;
        --version)
            show_version
            ;;
        --)
            shift
            break
            ;;
        *)
            log_error "Internal error parsing arguments."
            exit 1
            ;;
    esac
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
if [ -n "$FORCE_URGENCY" ]; then
    urgency="$FORCE_URGENCY"
    # Derive summary from last line (simple version)
    case "$last_line" in
        *[Ee][Rr][Rr][Oo][Rr]*) summary="⚠ Backup Failed" ;;
        *[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee]*) summary="✅ Backup Completed" ;;
        *) summary="ℹ Backup Status Unknown" ;;
    esac
else
    case "$last_line" in
        *[Ee][Rr][Rr][Oo][Rr]*)
            urgency="critical"
            summary="⚠ Backup Failed"
            ;;
        *[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee]*)
            urgency="normal"
            summary="✅ Backup Completed"
            ;;
        *)
            urgency="low"
            summary="ℹ Backup Status Unknown"
            ;;
    esac
fi

# ==============================
# Send notification
# ==============================
send_notification "$urgency" "$summary" "$last_line"

# If dry run, also show the determined values
if [ "$DRY_RUN" = true ]; then
    log_info "Determined urgency: $urgency"
    log_info "Determined summary: $summary"
fi
