#!/bin/bash
# noba-tui.sh – Terminal UI (dialog) for launching Nobara scripts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
DIALOG="${DIALOG:-dialog}"

# -------------------------------------------------------------------
# Load user configuration (if any) – optional
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Could override DIALOG, etc.
    :
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-tui.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Launch a dialog-based menu to run various Nobara scripts.

Options:
  --help        Show this help message
  --version     Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse arguments (though none are expected)
# -------------------------------------------------------------------
if [ $# -gt 0 ]; then
    case "$1" in
        --help)    show_help ;;
        --version) show_version ;;
        *)         log_error "Unknown option: $1"; show_help ;;
    esac
fi

# -------------------------------------------------------------------
# Ensure dialog is installed
# -------------------------------------------------------------------
if ! command -v "$DIALOG" &>/dev/null; then
    log_error "Dialog ($DIALOG) not found. Please install dialog (e.g., 'sudo dnf install dialog')."
    exit 1
fi

# -------------------------------------------------------------------
# Main menu
# -------------------------------------------------------------------
tempfile=$(mktemp)

$DIALOG --clear --title "Nobara Automation" \
        --menu "Choose a script to run:" 20 50 10 \
        "Backup"      "Run backup-to-nas.sh" \
        "Verify"      "Run backup-verifier.sh" \
        "Checksum"    "Run checksum.sh" \
        "Disk"        "Run disk-sentinel.sh" \
        "Images2PDF"  "Run images-to-pdf.sh" \
        "Organize"    "Run organize-downloads.sh" \
        "Undo"        "Run undo-organizer.sh" \
        "MOTD"        "Show motd-generator.sh" \
        "Dashboard"   "Show noba-dashboard.sh" \
        "ConfigCheck" "Run config-check.sh" \
        "CronSetup"   "Run noba-cron-setup.sh" \
        "Quit"        "" 2> "$tempfile"

choice=$(<"$tempfile")
rm -f "$tempfile"

case $choice in
    Backup)      "$SCRIPT_DIR/backup-to-nas.sh" ;;
    Verify)      "$SCRIPT_DIR/backup-verifier.sh" ;;
    Checksum)    "$SCRIPT_DIR/checksum.sh" ;;
    Disk)        "$SCRIPT_DIR/disk-sentinel.sh" ;;
    Images2PDF)  "$SCRIPT_DIR/images-to-pdf.sh" ;;
    Organize)    "$SCRIPT_DIR/organize-downloads.sh" ;;
    Undo)        "$SCRIPT_DIR/undo-organizer.sh" ;;
    MOTD)        "$SCRIPT_DIR/motd-generator.sh" ;;
    Dashboard)   "$SCRIPT_DIR/noba-dashboard.sh" ;;
    ConfigCheck) "$SCRIPT_DIR/config-check.sh" ;;
    CronSetup)   "$SCRIPT_DIR/noba-cron-setup.sh" ;;
    *)           exit 0 ;;
esac
