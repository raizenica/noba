#!/usr/bin/env bash
# noba-dashboard.sh – Detailed terminal dashboard for Nobara automation
# Version: 3.0.0

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
REFRESH_INTERVAL=0

LOG_DIR="$(get_config ".dashboard.log_dir" "$LOG_DIR")"
REFRESH_INTERVAL="$(get_config ".dashboard.refresh_interval" "$REFRESH_INTERVAL")"

BACKUP_LOG="${BACKUP_LOG:-$LOG_DIR/backup-to-nas.log}"
DISK_LOG="${DISK_LOG:-$LOG_DIR/disk-sentinel.log}"
ORGANIZER_LOG="${ORGANIZER_LOG:-$LOG_DIR/organize-downloads.log}"
UNDO_LOG="${UNDO_LOG:-$LOG_DIR/undo-organizer.log}"

[[ -f "$LOG_DIR/download-organizer.log" && ! -f "$ORGANIZER_LOG" ]] && \
    ORGANIZER_LOG="$LOG_DIR/download-organizer.log"

[[ -f "$LOG_DIR/download-organizer-undo.log" && ! -f "$UNDO_LOG" ]] && \
    UNDO_LOG="$LOG_DIR/download-organizer-undo.log"

# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------

show_version() {
    echo "noba-dashboard.sh version 3.0.0 (lib $NOBA_LIB_VERSION)"
    exit 0
}

show_help() {
cat <<EOF
Usage: $0 [OPTIONS]

Display a real-time Nobara automation dashboard.

Options:
  -w, --watch SECS   Refresh every SECS seconds
  -1, --once         Run once (default)
  --help             Show help
  --version          Show version
EOF
exit 0
}

PARSED_ARGS=$(getopt -o w:1 -l watch:,once,help,version -- "$@") \
    || { log_error "Invalid arguments"; exit 1; }

eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -w|--watch) REFRESH_INTERVAL="$2"; shift 2 ;;
        -1|--once)  REFRESH_INTERVAL=0; shift ;;
        --help)     show_help ;;
        --version)  show_version ;;
        --) shift; break ;;
        *) die "Invalid option $1" ;;
    esac
done

[[ "$REFRESH_INTERVAL" =~ ^[0-9]+$ ]] || \
    die "Refresh interval must be numeric"

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

section() {
    printf "%b─── %s ───────────────────────────────────────────────%b\n" \
        "$CYAN" "$1" "$NC"
}

strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g' <<< "$1"
}

# -------------------------------------------------------------------
# System Info
# -------------------------------------------------------------------

system_info() {

    section "System"

    printf "  Hostname : %s\n" "$(hostname)"

    uptime -p | sed 's/up //' | awk '{printf "  Uptime   : %s\n",$0}'

    printf "  Load     : %s\n" "$(uptime | awk -F'load average:' '{print $2}')"

    read -r _ mem_total mem_used _ <<< \
        "$(free -b | awk '/Mem:/ {print $1,$2,$3,$4}')"

    if [[ "$mem_total" -gt 0 ]]; then

        mem_percent=$(awk "BEGIN {printf \"%.1f\", $mem_used*100/$mem_total}")

        printf "  Memory   : %s/%s (%s%%)\n" \
            "$(human_size "$mem_used")" \
            "$(human_size "$mem_total")" \
            "$mem_percent"

    else
        printf "  Memory   : N/A\n"
    fi
}

# -------------------------------------------------------------------
# Disk Usage
# -------------------------------------------------------------------

disk_usage() {

    section "Disk Usage"

    df -h -x tmpfs -x devtmpfs -x overlay -x squashfs |
    awk 'NR>1 && $1 ~ "^/dev/" {
        mount=$6
        used=$3
        size=$2
        percent=$5
        printf "%s %s %s %s\n",mount,used,size,percent
    }' |
    while read -r mount used size percent; do

        pct=${percent%\%}

        if (( pct >= 90 )); then
            color=$RED
        elif (( pct >= 75 )); then
            color=$YELLOW
        else
            color=$GREEN
        fi

        printf "  %b%-20s%b : %s used (%s/%s)\n" \
            "$color" "$mount" "$NC" "$percent" "$used" "$size"

    done
}

# -------------------------------------------------------------------
# Backup Status
# -------------------------------------------------------------------

backup_status() {

    section "Backup"

    [[ -f "$BACKUP_LOG" ]] || {
        echo "  No backup log."
        return
    }

    last_complete=$(grep "Backup finished" "$BACKUP_LOG" | tail -1 || true)

    if [[ -n "$last_complete" ]]; then

        timestamp=$(sed -n 's/.*at \(.*\) =.*/\1/p' <<< "$last_complete")

        printf "  Last backup : %b%s%b\n" "$GREEN" "$timestamp" "$NC"
        printf "  Status      : %b✓ OK%b\n" "$GREEN" "$NC"

    else

        last_line=$(strip_ansi "$(tail -1 "$BACKUP_LOG")")

        if grep -qi error <<< "$last_line"; then
            status="${RED}✗ ERROR${NC}"
        elif grep -qi "dry run" <<< "$last_line"; then
            status="${YELLOW}DRY RUN${NC}"
        else
            status="${YELLOW}? UNKNOWN${NC}"
        fi

        printf "  Last run : %b\n" "$status"
        printf "  Log line : %s\n" "$last_line"

    fi
}

# -------------------------------------------------------------------
# Organizer
# -------------------------------------------------------------------

organizer_status() {

    section "Download Organizer"

    [[ -f "$ORGANIZER_LOG" ]] || {
        echo "  No organizer log."
        return
    }

    moved=$(grep -c "Moved:" "$ORGANIZER_LOG" || echo 0)

    printf "  Files moved : %s\n" "$moved"

    last_move=$(grep "Moved:" "$ORGANIZER_LOG" | tail -1 | sed 's/.*Moved: //')

    [[ -n "$last_move" ]] && \
        printf "  Last move   : %s\n" "$last_move"

    if [[ -s "$UNDO_LOG" ]]; then
        undo_count=$(wc -l < "$UNDO_LOG")
        printf "  %bUndo log: %s pending%b\n" "$YELLOW" "$undo_count" "$NC"
    fi
}

# -------------------------------------------------------------------
# Disk Alerts
# -------------------------------------------------------------------

disk_alerts() {

    section "Disk Sentinel"

    [[ -f "$DISK_LOG" ]] || {
        echo "  No disk sentinel log."
        return
    }

    alerts=$(grep -E "WARNING|exceeded" "$DISK_LOG" | tail -3 || true)

    if [[ -n "$alerts" ]]; then

        echo "  Recent alerts:"
        echo "$alerts" | sed 's/^/    /'

    else
        echo "  No recent warnings."
    fi
}

# -------------------------------------------------------------------
# Pending Downloads
# -------------------------------------------------------------------

pending_downloads() {

    section "Pending Downloads"

    download_dir="$(get_config ".organize.download_dir" "$HOME/Downloads")"

    [[ -d "$download_dir" ]] || {
        echo "  Download directory missing."
        return
    }

    count=$(find "$download_dir" -maxdepth 1 -type f | wc -l)

    if (( count > 0 )); then

        printf "  %s file(s) waiting:\n" "$count"

        find "$download_dir" -maxdepth 1 -type f -printf "    %f\n" | head -5

        (( count > 5 )) && \
            printf "    ... and %s more\n" $((count-5))

    else
        echo "  No files waiting."
    fi
}

# -------------------------------------------------------------------
# Updates
# -------------------------------------------------------------------

updates_status() {

    section "Updates"

    dnf_updates=0
    flatpak_updates=0

    if command -v dnf >/dev/null; then
        if dnf check-update -q >/tmp/dnf-check.$$ 2>&1; then
            dnf_updates=0
        else
            dnf_updates=$(grep -c '^[[:alnum:]]' /tmp/dnf-check.$$ || true)
        fi
        rm -f /tmp/dnf-check.$$
    fi

    if command -v flatpak >/dev/null; then
        flatpak_updates=$(flatpak remote-ls --updates | wc -l)
    fi

    printf "  DNF updates     : %s\n" "$dnf_updates"
    printf "  Flatpak updates : %s\n" "$flatpak_updates"

    (( dnf_updates==0 && flatpak_updates==0 )) && \
        echo "  System up to date."
}

# -------------------------------------------------------------------
# Render Dashboard
# -------------------------------------------------------------------

render_dashboard() {

    [[ -t 1 ]] && clear

    printf "%b╔══════════════════════════════════════════════════════════╗%b\n" "$BLUE" "$NC"
    printf "%b║                NOBA DASHBOARD – %s           ║%b\n" "$BLUE" "$(date '+%Y-%m-%d %H:%M')" "$NC"
    printf "%b╚══════════════════════════════════════════════════════════╝%b\n" "$BLUE" "$NC"

    system_info
    echo
    disk_usage
    echo
    backup_status
    echo
    organizer_status
    echo
    disk_alerts
    echo
    pending_downloads
    echo
    updates_status

    printf "%b──────────────────────────────────────────────────────────%b\n" "$BLUE" "$NC"
}

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

if [[ "$REFRESH_INTERVAL" -eq 0 ]]; then
    render_dashboard
else
    while true; do
        render_dashboard
        sleep "$REFRESH_INTERVAL"
    done
fi

exit 0
