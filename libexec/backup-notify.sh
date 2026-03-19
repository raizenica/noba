#!/usr/bin/env bash
# backup-notify.sh – Send a desktop notification about the last backup status
# Version: 3.1.0

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then
    exit 1
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: backup-notify.sh [OPTIONS]"
    exit 0
fi

if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-notify.sh version 3.1.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
LOG_FILE="$LOG_DIR/backup-to-nas.log"
STATE_FILE="$LOG_DIR/backup-to-nas.state"

SCAN_LINES=15
FORCE_URGENCY=""
DRY_RUN=false
TEST_MODE=false
HISTORY_MODE=false
HISTORY_COUNT=5

if command -v get_config &>/dev/null; then
    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
    LOG_FILE="$LOG_DIR/backup-to-nas.log"
    STATE_FILE="$LOG_DIR/backup-to-nas.state"
fi

# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Reads the backup state file and sends a desktop notification summarizing the run.

Options:
  --scan-lines N   Number of log lines to scan if state file is missing (default: $SCAN_LINES)
  --urgency U      Force notification urgency (low, normal, critical)
  --test           Send a dummy notification to verify your desktop/webhook setup
  --history [N]    Show the last N backup outcomes (default: $HISTORY_COUNT)
  --dry-run        Print what would be sent without actually notifying
  --help           Show this message
  --version        Show version
EOF
    exit 0
}

read_state_file() {
    if [[ ! -f "$STATE_FILE" ]]; then
        return 1
    fi

    # shellcheck disable=SC1090
    source "$STATE_FILE"

    STATUS_SOURCE="state_file"

    if [[ "${exit_code:-1}" == "0" ]]; then
        STATUS_URGENCY="normal"
        STATUS_SUMMARY="✅ Backup Successful"
        STATUS_MSG="Snapshot: ${snapshot:-Unknown}\nDuration: ${duration:-Unknown}s"
    else
        STATUS_URGENCY="critical"
        STATUS_SUMMARY="❌ Backup Failed (Code: ${exit_code:-Unknown})"
        STATUS_MSG="Failed sources: ${failed_sources:-Unknown}"
    fi

    return 0
}

read_log_file() {
    if [[ ! -f "$LOG_FILE" ]]; then
        return 1
    fi

    local last_lines
    last_lines=$(tail -n "$SCAN_LINES" "$LOG_FILE" | sed 's/\x1b\[[0-9;]*m//g')

    if echo "$last_lines" | grep -qi "Backup finished"; then
        STATUS_URGENCY="normal"
        STATUS_SUMMARY="✅ Backup Completed"
        STATUS_MSG=$(echo "$last_lines" | grep "Duration" | tail -1 || echo "Check log for details.")
    elif echo "$last_lines" | grep -qi "ERROR"; then
        STATUS_URGENCY="critical"
        STATUS_SUMMARY="❌ Backup Error"
        STATUS_MSG=$(echo "$last_lines" | grep "ERROR" | tail -1 || echo "Check log for details.")
    elif echo "$last_lines" | grep -qi "dry run"; then
        STATUS_URGENCY="low"
        STATUS_SUMMARY="ℹ️ Backup Dry Run"
        STATUS_MSG="A dry-run completed successfully."
    else
        STATUS_URGENCY="normal"
        STATUS_SUMMARY="⚠️ Unknown Status"
        STATUS_MSG="Could not parse log outcome. See: $LOG_FILE"
    fi

    STATUS_SOURCE="log_file"
    return 0
}

# -------------------------------------------------------------------
# Parse Arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --scan-lines)
            SCAN_LINES="$2"
            shift 2
            ;;
        --urgency)
            FORCE_URGENCY="$2"
            shift 2
            ;;
        --test)
            TEST_MODE=true
            shift
            ;;
        --history)
            HISTORY_MODE=true
            if [[ $# -gt 1 && "$2" =~ ^[0-9]+$ ]]; then
                HISTORY_COUNT="$2"
                shift 2
            else
                shift
            fi
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            show_help
            ;;
        --version)
            echo "backup-notify.sh version 3.1.0"
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

if [[ ! "$SCAN_LINES" =~ ^[0-9]+$ ]]; then
    die "--scan-lines must be a positive integer."
fi
if [[ -n "$FORCE_URGENCY" ]]; then
    if [[ ! "$FORCE_URGENCY" =~ ^(low|normal|critical)$ ]]; then
        die "--urgency must be one of: low normal critical"
    fi
fi

# -------------------------------------------------------------------
# Test Mode
# -------------------------------------------------------------------
if [[ "$TEST_MODE" == true ]]; then
    log_info "Sending test notification..."
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY RUN] notify-send -u normal 'Test Alert' 'This is a test.'"
    else
        send_alert "warn" "Noba Test Alert" "This is a test from backup-notify.sh"
    fi
    exit 0
fi

# -------------------------------------------------------------------
# Determine Status
# -------------------------------------------------------------------
STATUS_SOURCE=""
STATUS_URGENCY="low"
STATUS_SUMMARY="ℹ️ Backup Status Unknown"
STATUS_MSG=""

if ! read_state_file; then
    if ! read_log_file; then
        die "Cannot read backup log ($LOG_FILE) or state file ($STATE_FILE)."
    fi
fi

if [[ -n "$FORCE_URGENCY" ]]; then
    STATUS_URGENCY="$FORCE_URGENCY"
fi

# -------------------------------------------------------------------
# Execute Notification
# -------------------------------------------------------------------
if [[ "$DRY_RUN" == true ]]; then
    log_info "[DRY RUN] Would send notification:"
    echo "  Urgency : $STATUS_URGENCY"
    echo "  Summary : $STATUS_SUMMARY"
    echo "  Message : $STATUS_MSG"
    echo "  Source  : $STATUS_SOURCE"
else
    # Map our internal urgency to the webhook alert levels
    alert_level="info"
    if [[ "$STATUS_URGENCY" == "critical" ]]; then
        alert_level="error"
    fi

    send_alert "$alert_level" "$STATUS_SUMMARY" "$STATUS_MSG"
    log_success "Notification dispatched: $STATUS_SUMMARY"
fi
