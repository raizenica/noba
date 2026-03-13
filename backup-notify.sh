#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# backup-notify.sh – Send desktop notification about last backup status

set -u
set -o pipefail

LOG_FILE="$HOME/.local/share/backup-to-nas.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "No backup log found." >&2
    exit 1
fi

# Get the last line of the log
last_line=$(tail -1 "$LOG_FILE" 2>/dev/null)

# Determine success/failure
if echo "$last_line" | grep -qi "error"; then
    urgency="critical"
    summary="⚠ Backup Failed"
elif echo "$last_line" | grep -qi "complete"; then
    urgency="normal"
    summary="✅ Backup Completed"
else
    urgency="low"
    summary="ℹ Backup Status Unknown"
fi

# Send notification
if command -v notify-send &>/dev/null; then
    notify-send -u "$urgency" "$summary" "$last_line"
elif command -v kdialog &>/dev/null; then
    kdialog --passivepopup "$last_line" 5 --title "$summary"
else
    echo "$summary: $last_line"
fi
