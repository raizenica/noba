#!/bin/bash
# noba-tui.sh – Terminal UI (dialog) for launching Nobara scripts
# Version: 2.2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
DIALOG="${DIALOG:-dialog}"

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    DIALOG="$(get_config ".tui.dialog_cmd" "$DIALOG")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-tui.sh version 2.2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Launch an interactive dialog-based menu to run various Nobara scripts.

Options:
  --help        Show this help message
  --version     Show version information
EOF
    exit 0
}

run_script() {
    local script="$1"
    local title="$2"
    local extra_args=()

    # Ask for common flags
    if $DIALOG --title "$title Options" --yesno "Run with --dry-run?" 7 40; then
        extra_args+=("--dry-run")
    fi
    if $DIALOG --title "$title Options" --yesno "Run with --verbose?" 7 40; then
        extra_args+=("--verbose")
    fi

    # Run script and pipe live output to programbox, stripping ANSI color codes
    # so dialog doesn't render garbage text.
    "$script" "${extra_args[@]}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | \
        $DIALOG --title "Running: $title" --programbox 22 80
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if [ $# -gt 0 ]; then
    case "$1" in
        --help)    show_help ;;
        --version) show_version ;;
        *)         log_error "Unknown option: $1"; show_help ;;
    esac
fi

# -------------------------------------------------------------------
# Pre-flight checks & Setup
# -------------------------------------------------------------------
if ! command -v "$DIALOG" &>/dev/null; then
    die "Dialog ($DIALOG) not found. Please install it (e.g., 'sudo dnf install dialog')."
fi

# Use the library's safe temp dir creator with automatic trap cleanup
# shellcheck disable=SC2034
TEMP_DIR=$(make_temp_dir_auto "noba-tui.XXXXXXXXXX")

# -------------------------------------------------------------------
# Main menu
# -------------------------------------------------------------------
while true; do
    choice=$($DIALOG --clear --title "Nobara Automation Suite" \
        --cancel-label "Exit" \
        --menu "Choose a script to execute:" 22 65 15 \
        "Backup"      "Run backup-to-nas.sh" \
        "Verify"      "Run backup-verifier.sh" \
        "Cloud"       "Run cloud-backup.sh" \
        "Disk"        "Run disk-sentinel.sh" \
        "Organize"    "Run organize-downloads.sh" \
        "Undo"        "Run undo-organizer.sh" \
        "Report"      "Run system-report.sh" \
        "Digest"      "Run noba-daily-digest.sh" \
        "Watch"       "Run service-watch.sh" \
        "Checksum"    "Run checksum.sh" \
        "Images2PDF"  "Run images-to-pdf.sh" \
        "ConfigCheck" "Run config-check.sh" \
        "CronSetup"   "Run noba-cron-setup.sh" \
        "MOTD"        "Show motd-generator.sh" \
        "Web"         "Start noba-web.sh dashboard" \
        "Quit"        "Exit TUI" 3>&1 1>&2 2>&3 3>&-)

    # If user presses ESC or Cancel, exit loop
    if [ $? -ne 0 ]; then
        break
    fi

    case $choice in
        Backup)      run_script "$SCRIPT_DIR/backup-to-nas.sh" "Backup" ;;
        Verify)      run_script "$SCRIPT_DIR/backup-verifier.sh" "Verify Backups" ;;
        Cloud)       run_script "$SCRIPT_DIR/cloud-backup.sh" "Cloud Sync" ;;
        Disk)        run_script "$SCRIPT_DIR/disk-sentinel.sh" "Disk Sentinel" ;;
        Organize)    run_script "$SCRIPT_DIR/organize-downloads.sh" "Organize Downloads" ;;
        Undo)        run_script "$SCRIPT_DIR/undo-organizer.sh" "Undo Organizer" ;;
        Report)      run_script "$SCRIPT_DIR/system-report.sh" "System Report" ;;
        Digest)      run_script "$SCRIPT_DIR/noba-daily-digest.sh" "Daily Digest" ;;
        Watch)       run_script "$SCRIPT_DIR/service-watch.sh" "Service Watch" ;;
        Checksum)    run_script "$SCRIPT_DIR/checksum.sh" "Checksum Tool" ;;
        Images2PDF)  run_script "$SCRIPT_DIR/images-to-pdf.sh" "Images to PDF" ;;
        ConfigCheck) run_script "$SCRIPT_DIR/config-check.sh" "Config Check" ;;
        CronSetup)   run_script "$SCRIPT_DIR/noba-cron-setup.sh" "Cron Setup" ;;
        MOTD)        "$SCRIPT_DIR/motd-generator.sh" | sed 's/\x1b\[[0-9;]*m//g' | $DIALOG --title "MOTD" --programbox 22 75 ;;
        Web)
            "$SCRIPT_DIR/noba-web.sh" &
            $DIALOG --title "Web Dashboard" --msgbox "Dashboard started in the background.\nCheck http://localhost:8080" 7 45
            ;;
        Quit|"")     break ;;
    esac
done

clear
