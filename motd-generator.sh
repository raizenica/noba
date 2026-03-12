#!/bin/bash
# motd-generator.sh – Custom Message of the Day with system status

set -u
set -o pipefail

# Configuration
QUOTE_FILE="${QUOTE_FILE:-$HOME/.config/quotes.txt}"  # one quote per line, optional
SHOW_UPDATES=true
SHOW_BACKUP=true

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
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
    df -h / /home 2>/dev/null | awk 'NR>1 {printf "  %-10s %6s used of %s (%s)\n", $6, $3, $2, $5}'
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
        echo "  No backup log found."
    fi
}

print_updates() {
    echo -e "${YELLOW}Pending Updates:${NC}"
    local updates=0
    if command -v dnf &>/dev/null; then
        updates=$(dnf check-update -q 2>/dev/null | wc -l)
        echo "  DNF packages : $updates updates available"
    fi
    if command -v flatpak &>/dev/null; then
        flatpak_updates=$(flatpak update --appstream 2>/dev/null | grep -c "^ [1-9]")
        echo "  Flatpaks     : $flatpak_updates updates available"
    fi
    if [ $updates -eq 0 ] && [ $flatpak_updates -eq 0 ]; then
        echo "  All packages are up to date."
    fi
}

print_quote() {
    if [ -f "$QUOTE_FILE" ]; then
        quote=$(shuf -n 1 "$QUOTE_FILE" 2>/dev/null)
        if [ -n "$quote" ]; then
            echo -e "${BLUE}Quote of the day:${NC}"
            echo "  \"$quote\""
        fi
    elif command -v curl &>/dev/null; then
        # Fallback: fetch a random quote from internet
        quote=$(curl -s --max-time 2 "https://api.quotable.io/random" | jq -r '.content + " – " + .author' 2>/dev/null)
        if [ -n "$quote" ] && [ "$quote" != "null – null" ]; then
            echo -e "${BLUE}Quote of the day:${NC}"
            echo "  $quote"
        fi
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
