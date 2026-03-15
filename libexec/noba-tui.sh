#!/bin/bash
# noba-tui.sh – Terminal UI (dialog) for launching Nobara scripts
# Version: 2.2.3

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: noba-tui.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "noba-tui.sh version 2.2.3"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

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
    echo "noba-tui.sh version 2.2.3"
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

# FIX #4 – run_script: guard against missing / non-executable scripts
# Previous issue: if a script was absent or not executable, the
# pipeline silently produced no output and the programbox closed
# immediately with no user-visible error.
# Fix: test -x before doing anything else and show an error dialog.
run_script() {
    local script="$1"
    local title="$2"
    local extra_args=()

    if [[ ! -x "$script" ]]; then
        $DIALOG --title "Error" --msgbox \
            "Script not found or not executable:\n\n$script" 8 65
        return 1
    fi

    # Ask for common flags
    if $DIALOG --title "$title Options" --yesno "Run with --dry-run?" 7 40; then
        extra_args+=("--dry-run")
    fi
    if $DIALOG --title "$title Options" --yesno "Run with --verbose?" 7 40; then
        extra_args+=("--verbose")
    fi

    # Run script and pipe live output to programbox, stripping ANSI color codes
    "$script" "${extra_args[@]}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | \
        $DIALOG --title "Running: $title" --programbox 22 80
}

# -------------------------------------------------------------------
# Pre-flight checks & Setup
# -------------------------------------------------------------------
if ! command -v "$DIALOG" &>/dev/null; then
    die "Dialog ($DIALOG) not found. Please install it (e.g., 'sudo dnf install dialog')."
fi

# -------------------------------------------------------------------
# Main menu
# -------------------------------------------------------------------
while true; do
    # If user presses ESC or Cancel, exit loop directly via the if statement
    if ! choice=$($DIALOG --clear --title "Nobara Automation Suite" \
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
        "Quit"        "Exit TUI" 3>&1 1>&2 2>&3 3>&-); then
        break
    fi

    case $choice in
        Backup)      run_script "$SCRIPT_DIR/backup-to-nas.sh"       "Backup" ;;
        Verify)      run_script "$SCRIPT_DIR/backup-verifier.sh"     "Verify Backups" ;;
        Cloud)       run_script "$SCRIPT_DIR/cloud-backup.sh"        "Cloud Sync" ;;
        Disk)        run_script "$SCRIPT_DIR/disk-sentinel.sh"       "Disk Sentinel" ;;
        Organize)    run_script "$SCRIPT_DIR/organize-downloads.sh"  "Organize Downloads" ;;
        Undo)        run_script "$SCRIPT_DIR/undo-organizer.sh"      "Undo Organizer" ;;
        Report)      run_script "$SCRIPT_DIR/system-report.sh"       "System Report" ;;
        Digest)      run_script "$SCRIPT_DIR/noba-daily-digest.sh"   "Daily Digest" ;;
        Watch)       run_script "$SCRIPT_DIR/service-watch.sh"       "Service Watch" ;;
        Checksum)    run_script "$SCRIPT_DIR/checksum.sh"            "Checksum Tool" ;;
        Images2PDF)  run_script "$SCRIPT_DIR/images-to-pdf.sh"       "Images to PDF" ;;
        ConfigCheck) run_script "$SCRIPT_DIR/config-check.sh"        "Config Check" ;;
        CronSetup)   run_script "$SCRIPT_DIR/noba-cron-setup.sh"     "Cron Setup" ;;
        MOTD)
            if [[ ! -x "$SCRIPT_DIR/motd-generator.sh" ]]; then
                $DIALOG --title "Error" --msgbox \
                    "Script not found or not executable:\n\n$SCRIPT_DIR/motd-generator.sh" 8 65
            else
                "$SCRIPT_DIR/motd-generator.sh" \
                    | sed 's/\x1b\[[0-9;]*m//g' \
                    | $DIALOG --title "MOTD" --programbox 22 75
            fi
            ;;
        Web)
            if [[ ! -x "$SCRIPT_DIR/noba-web.sh" ]]; then
                $DIALOG --title "Error" --msgbox \
                    "Script not found or not executable:\n\n$SCRIPT_DIR/noba-web.sh" 8 65
            else
                "$SCRIPT_DIR/noba-web.sh" &
                $DIALOG --title "Web Dashboard" \
                    --msgbox "Dashboard started in the background.\nCheck http://localhost:8080" 7 45
            fi
            ;;
        Quit|"") break ;;
    esac
done

clear
