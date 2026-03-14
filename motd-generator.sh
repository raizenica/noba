#!/bin/bash
# motd-generator.sh – Custom Message of the Day with system status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
QUOTE_FILE="${QUOTE_FILE:-$HOME/.config/quotes.txt}"
SHOW_UPDATES=true
SHOW_BACKUP=true
NO_COLOR=false

# Colors (disabled if NO_COLOR=true)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    QUOTE_FILE="$(get_config ".motd.quote_file" "$QUOTE_FILE")"
    # Expand tilde if present
    QUOTE_FILE="${QUOTE_FILE/#\~/$HOME}"
    SHOW_UPDATES="$(get_config ".motd.show_updates" "$SHOW_UPDATES")"
    SHOW_BACKUP="$(get_config ".motd.show_backup" "$SHOW_BACKUP")"
    # Convert string "true"/"false" to boolean if needed (get_config returns string)
    [[ "$SHOW_UPDATES" == "false" ]] && SHOW_UPDATES=false
    [[ "$SHOW_BACKUP" == "false" ]] && SHOW_BACKUP=false
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Usage: $0"
    echo "Generates a dynamic Message of the Day (MOTD)."
    exit 0
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "motd-generator.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Display a colorful Message of the Day with system status.

Options:
  --no-color       Disable colored output
  --no-updates     Hide pending updates section
  --no-backup      Hide backup status section
  --help           Show this help message
  --version        Show version information
EOF
    exit 0
}

# Print with or without color based on NO_COLOR
color_echo() {
    local color="$1"
    shift
    if [ "$NO_COLOR" = true ]; then
        echo "$*"
    else
        echo -e "${color}$*${NC}"
    fi
}

print_header() {
    color_echo "$BLUE" "════════════════════════════════════════════════════════════"
    color_echo "$GREEN" "    Nobara System Status – $(date '+%A, %B %d, %Y %H:%M')"
    color_echo "$BLUE" "════════════════════════════════════════════════════════════"
}

print_system_info() {
    color_echo "$YELLOW" "System Info:"
    echo "  Hostname : $(hostname)"
    echo "  Uptime   : $(uptime -p | sed 's/up //')"
    echo "  Load     : $(uptime | awk -F'load average:' '{print $2}')"
    echo "  Memory   : $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
}

print_disk_usage() {
    color_echo "$YELLOW" "Disk Usage:"
    df -h | grep '^/dev/' | while read -r line; do
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
        if [ "$NO_COLOR" = true ]; then
            echo "  ${mount} : ${use_percent} used (${used}/${size})"
        else
            echo -e "  ${color}${mount}${NC} : ${use_percent} used (${used}/${size})"
        fi
    done
}

print_backup_status() {
    local backup_log="$HOME/.local/share/backup-to-nas.log"
    color_echo "$YELLOW" "Backup Status:"
    if [ -f "$backup_log" ]; then
        last_backup=$(tail -5 "$backup_log" | grep -E "Backup finished|ERROR" | tail -1)
        if echo "$last_backup" | grep -q "ERROR"; then
            color_echo "$RED" "  Last backup: ✗ FAILED"
        elif echo "$last_backup" | grep -q "Backup finished"; then
            color_echo "$GREEN" "  Last backup: ✓ OK"
        else
            color_echo "$YELLOW" "  Last backup: Unknown"
        fi
        # Show last log line (stripped of ANSI)
        last_line=$(tail -1 "$backup_log" | sed 's/\x1b\[[0-9;]*m//g')
        echo "  $last_line"
    else
        color_echo "$YELLOW" "  No backup log found. Run 'backup-to-nas.sh' to start."
    fi
}

print_updates() {
    color_echo "$YELLOW" "Pending Updates:"
    local any_updates=false
    local dnf_timeout=5
    local flatpak_timeout=5

    # DNF updates with timeout
    if command -v dnf &>/dev/null; then
        if command -v timeout &>/dev/null; then
            updates=$(timeout "$dnf_timeout" dnf check-update -q 2>/dev/null | wc -l)
        else
            updates=$(dnf check-update -q 2>/dev/null | wc -l)
        fi
        if [ -n "$updates" ] && [ "$updates" -gt 0 ]; then
            echo "  DNF : $updates updates available"
            any_updates=true
        elif [ -z "$updates" ]; then
            echo "  DNF : check timed out (skipped)"
        fi
    fi

    # Flatpak updates with timeout
    if command -v flatpak &>/dev/null; then
        if command -v timeout &>/dev/null; then
            flatpak_updates=$(timeout "$flatpak_timeout" flatpak remote-ls --updates 2>/dev/null | wc -l)
        else
            flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | wc -l)
        fi
        if [ -n "$flatpak_updates" ] && [ "$flatpak_updates" -gt 0 ]; then
            echo "  Flatpak : $flatpak_updates updates available"
            any_updates=true
        elif [ -z "$flatpak_updates" ]; then
            echo "  Flatpak : check timed out (skipped)"
        fi
    fi

    if [ "$any_updates" = false ]; then
        echo "  All packages are up to date."
    fi
}

print_quote() {
    local quote=""
    if [ -f "$QUOTE_FILE" ]; then
        quote=$(shuf -n 1 "$QUOTE_FILE" 2>/dev/null)
    elif command -v curl &>/dev/null && command -v jq &>/dev/null; then
        quote=$(curl -s --max-time 2 "https://api.quotable.io/random" 2>/dev/null | jq -r '.content + " – " + .author' 2>/dev/null)
        [ "$quote" = "null – null" ] && quote=""
    fi
    if [ -n "$quote" ]; then
        color_echo "$CYAN" "Quote of the day:"
        echo "  $quote"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o '' -l no-color,no-updates,no-backup,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --no-color)   NO_COLOR=true; shift ;;
        --no-updates) SHOW_UPDATES=false; shift ;;
        --no-backup)  SHOW_BACKUP=false; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *) log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
print_header
print_system_info
echo ""
print_disk_usage
echo ""
if [ "$SHOW_BACKUP" = true ]; then
    print_backup_status
    echo ""
fi
if [ "$SHOW_UPDATES" = true ]; then
    print_updates
    echo ""
fi
print_quote
color_echo "$BLUE" "════════════════════════════════════════════════════════════"
