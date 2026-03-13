#!/bin/bash
# noba-dashboard.sh – Detailed terminal dashboard for Nobara automation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# Load configuration (once is enough)
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
    # You can add dashboard‑specific configs here later
    :
fi

# Colors (already in noba-lib.sh, but redefined here for convenience)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
LOG_DIR="$HOME/.local/share"
BACKUP_LOG="$LOG_DIR/backup-to-nas.log"
DISK_LOG="$LOG_DIR/disk-sentinel.log"
ORGANIZER_LOG="$LOG_DIR/download-organizer.log"
UNDO_LOG="$LOG_DIR/download-organizer-undo.log"

# Helper to strip ANSI color codes
strip_ansi() {
    echo "$1" | sed 's/\x1b\[[0-9;]*m//g'
}

# Helper to print section headers
section() {
    echo -e "${CYAN}─── $1 ───────────────────────────────────────────────────${NC}"
}

# System info
system_info() {
    section "System"
    echo "  Hostname : $(hostname)"
    echo "  Uptime   : $(uptime -p | sed 's/up //')"
    echo "  Load     : $(uptime | awk -F'load average:' '{print $2}')"
    echo "  Memory   : $(free -h | awk '/^Mem:/ {printf "%s/%s (%.1f%%)", $3, $2, $3/$2*100}')"
}

# Disk usage
disk_usage() {
    section "Disk Usage"
    df -h | grep -E '^/dev/' | while read -r line; do
        read -r _ size used _ use_percent mount <<< "$line"
        # Skip snap mounts
        if [[ "$mount" == /var/lib/snapd/snap/* ]]; then
            continue
        fi
        percent=${use_percent%\%}
        if [ "$percent" -ge 90 ]; then
            color="$RED"
        elif [ "$percent" -ge 75 ]; then
            color="$YELLOW"
        else
            color="$GREEN"
        fi
        echo -e "  ${color}${mount}${NC} : ${use_percent} used (${used}/${size})"
    done
}

# Last backup status – clean, with timestamp and stripped ANSI codes
backup_status() {
    section "Backup"
    if [ ! -f "$BACKUP_LOG" ]; then
        echo "  No backup log found."
        return
    fi

    # Find the most recent line indicating a real backup completion
    last_complete=$(grep -E "Backup finished" "$BACKUP_LOG" | tail -1)
    if [ -n "$last_complete" ]; then
        # Extract timestamp (format: "========== Backup finished at YYYY-MM-DD HH:MM:SS ==========")
        timestamp=$(echo "$last_complete" | sed -n 's/.*at \(.*\) =.*/\1/p')
        if [ -n "$timestamp" ]; then
            echo "  Last backup: ${GREEN}${timestamp}${NC}"
        else
            echo "  Last backup: ${GREEN}recently${NC} (no timestamp)"
        fi
        status="${GREEN}✓ OK${NC}"
        echo "  Status      : $status"
    else
        # No completed backup; show last log line (stripped)
        last_line=$(strip_ansi "$(tail -1 "$BACKUP_LOG")")
        if echo "$last_line" | grep -qi "error"; then
            status="${RED}✗ ERROR${NC}"
        elif echo "$last_line" | grep -qi "dry run"; then
            status="${YELLOW}ℹ DRY RUN${NC}"
        else
            status="${YELLOW}? UNKNOWN${NC}"
        fi
        echo "  Last run    : $status"
        echo "  Last log line: $last_line"
    fi
}

# Download organizer summary
organizer_status() {
    section "Download Organizer"
    if [ -f "$ORGANIZER_LOG" ]; then
        moved=$(grep -c "Moved:" "$ORGANIZER_LOG" 2>/dev/null || echo 0)
        last_move=$(grep "Moved:" "$ORGANIZER_LOG" | tail -1 | sed 's/.*Moved: //')
        echo "  Files moved: $moved"
        if [ -n "$last_move" ]; then
            echo "  Last move  : $last_move"
        fi
        if [ -f "$UNDO_LOG" ] && [ -s "$UNDO_LOG" ]; then
            undo_count=$(wc -l < "$UNDO_LOG")
            echo -e "  ${YELLOW}Undo log: $undo_count pending actions${NC}"
        fi
    else
        echo "  No organizer log yet."
    fi
}

# Disk sentinel alerts
disk_alerts() {
    section "Disk Sentinel"
    if [ -f "$DISK_LOG" ]; then
        warnings=$(grep -E "WARNING|exceeded" "$DISK_LOG" | tail -3)
        if [ -n "$warnings" ]; then
            echo "  Recent alerts:"
            echo "$warnings" | while read -r line; do
                echo "    $line"
            done
        else
            echo "  No recent disk warnings."
        fi
    else
        echo "  No disk sentinel log."
    fi
}

# Pending downloads
pending_downloads() {
    section "Pending Downloads"
    download_dir="${DOWNLOAD_DIR:-$HOME/Downloads}"
    if [ -d "$download_dir" ]; then
        count=$(find "$download_dir" -maxdepth 1 -type f | wc -l)
        if [ "$count" -gt 0 ]; then
            echo "  $count file(s) waiting in Downloads:"
            find "$download_dir" -maxdepth 1 -type f -printf "    %f\n" | head -5
            if [ "$count" -gt 5 ]; then
                echo "    ... and $((count - 5)) more"
            fi
        else
            echo "  No files waiting."
        fi
    fi
}

# Updates
updates_status() {
    section "Updates"
    dnf_updates=0
    flatpak_updates=0
    if command -v dnf &>/dev/null; then
        dnf_updates=$(dnf check-update -q 2>/dev/null | wc -l)
        echo "  DNF updates : $dnf_updates"
    fi
    if command -v flatpak &>/dev/null; then
        flatpak_updates=$(flatpak update --appstream 2>/dev/null | grep -c "^ [1-9]")
        echo "  Flatpak updates : $flatpak_updates"
    fi
    if [ "$dnf_updates" -eq 0 ] && [ "$flatpak_updates" -eq 0 ]; then
        echo "  System is up to date."
    fi
}

# Main
clear
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                 NOBA DASHBOARD – $(date '+%Y-%m-%d %H:%M')              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"

system_info
echo ""
disk_usage
echo ""
backup_status
echo ""
organizer_status
echo ""
disk_alerts
echo ""
pending_downloads
echo ""
updates_status

echo -e "${BLUE}────────────────────────────────────────────────────────────${NC}"
