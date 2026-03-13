#!/bin/bash
# noba-tui.sh – Terminal UI (dialog) for launching Nobara scripts
# Improved version with output viewing and common options

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
DIALOG="${DIALOG:-dialog}"
TEMP_DIR="${TEMP_DIR:-/tmp/noba-tui}"
mkdir -p "$TEMP_DIR"

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
    echo "noba-tui.sh version 2.0"
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

cleanup() {
    rm -f "$TEMP_DIR"/*.tmp
}

run_script() {
    local script="$1"
    local title="$2"
    local extra_args=()

    # Ask for common flags (optional)
    if $DIALOG --yesno "Run with --dry-run?" 0 0; then
        extra_args+=("--dry-run")
    fi
    if $DIALOG --yesno "Run with --verbose?" 0 0; then
        extra_args+=("--verbose")
    fi

    local output_file="$TEMP_DIR/output.tmp"
    $DIALOG --infobox "Running $title...\n\nPlease wait." 0 0
    if "$script" "${extra_args[@]}" > "$output_file" 2>&1; then
        $DIALOG --textbox "$output_file" 20 70
    else
        $DIALOG --textbox "$output_file" 20 70 --title "Error - $title"
    fi
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

trap cleanup EXIT

# -------------------------------------------------------------------
# Main menu
# -------------------------------------------------------------------
while true; do
    choice=$($DIALOG --clear --title "Nobara Automation" \
        --menu "Choose a script to run:" 20 60 12 \
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
        "Web"         "Start noba-web.sh" \
        "Quit"        "Exit" 3>&1 1>&2 2>&3 3>&-)

    case $choice in
        Backup)      run_script "$SCRIPT_DIR/backup-to-nas.sh" "Backup" ;;
        Verify)      run_script "$SCRIPT_DIR/backup-verifier.sh" "Verify" ;;
        Checksum)    run_script "$SCRIPT_DIR/checksum.sh" "Checksum" ;;
        Disk)        run_script "$SCRIPT_DIR/disk-sentinel.sh" "Disk Sentinel" ;;
        Images2PDF)  run_script "$SCRIPT_DIR/images-to-pdf.sh" "Images to PDF" ;;
        Organize)    run_script "$SCRIPT_DIR/organize-downloads.sh" "Organize Downloads" ;;
        Undo)        run_script "$SCRIPT_DIR/undo-organizer.sh" "Undo Organizer" ;;
        MOTD)        "$SCRIPT_DIR/motd-generator.sh" | $DIALOG --programbox "MOTD" 20 70 ;;
        Dashboard)   "$SCRIPT_DIR/noba-dashboard.sh" | $DIALOG --programbox "Dashboard" 20 70 ;;
        ConfigCheck) run_script "$SCRIPT_DIR/config-check.sh" "Config Check" ;;
        CronSetup)   run_script "$SCRIPT_DIR/noba-cron-setup.sh" "Cron Setup" ;;
        Web)         "$SCRIPT_DIR/noba-web.sh" & ;;
        Quit|"")     break ;;
    esac
done

clear
