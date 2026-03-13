#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# motd-generator.sh – Custom Message of the Day with system status

set -u
set -o pipefail

# Configuration
QUOTE_FILE="${QUOTE_FILE:-$HOME/.config/quotes.txt}"
SHOW_UPDATES=true
SHOW_BACKUP=true

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}    Nobara System Status – $(date '+%A, %B %d, %Y %H:%M')${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
}

print_system_info() {
    echo -e "${YELLOW}System Info:${NC}"
    echo "  Hostname : $(hostname)"
    echo "  Uptime   : $(uptime -p | sed 's/up //')"
    echo "  Load     : $(uptime | awk -F'load average:' '{print $2}')"
    echo "  Memory   : $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
}

print_disk_usage() {
    echo -e "${YELLOW}Disk Usage:${NC}"
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
        echo -e "  ${color}${mount}${NC} : ${use_percent} used (${used}/${size})"
    done
}

print_backup_status() {
    local backup_log="$HOME/.local/share/backup-to-nas.log"
    if [ -f "$backup_log" ]; then
        last_backup=$(tail -5 "$backup_log" | grep -E "Backup finished|ERROR" | tail -1)
        if echo "$last_backup" | grep -q "ERROR"; then
            echo -e "${RED}Last backup: ✗ FAILED${NC}"
        elif echo "$last_backup" | grep -q "Backup finished"; then
            echo -e "${GREEN}Last backup: ✓ OK${NC}"
        else
            echo -e "${YELLOW}Last backup: Unknown${NC}"
        fi
        echo "  $(tail -1 "$backup_log")"
    else
        echo -e "${YELLOW}No backup log found. Run 'backup-to-nas.sh' to start.${NC}"
    fi
}

print_updates() {
    echo -e "${YELLOW}Pending Updates:${NC}"
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
        # dnf check-update returns 100 when updates available, 0 when none
        # We just count lines, but if command times out, updates may be empty
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
        # Use timeout and silent mode to avoid hanging
        quote=$(curl -s --max-time 2 "https://api.quotable.io/random" 2>/dev/null | jq -r '.content + " – " + .author' 2>/dev/null)
        [ "$quote" = "null – null" ] && quote=""
    fi
    if [ -n "$quote" ]; then
        echo -e "${CYAN}Quote of the day:${NC}"
        echo "  $quote"
    fi
}

# Main
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
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
