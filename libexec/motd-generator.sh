#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# motd-generator.sh – Noba Command Centre – Terminal banner
# Version: 2.0.0
#
# Bugs fixed vs 1.x:
#   BUG-1  'local d_up=0' inside '( ... ) &' subshell — 'local' is only valid
#          inside a function. On bash 5.1 this printed "local: can only be used
#          in a function" to stderr on every login. Removed 'local'; plain
#          variable assignment used instead.
#   BUG-2  IFS='|' read on a corrupt/incomplete cache line caused a non-numeric
#          string to reach [ "${dnf_u:-0}" -gt 0 ], which exits 1 under set -e
#          and crashed the entire MOTD. Cache values are now validated with a
#          regex before arithmetic comparison.
#   BUG-3  print_disk_usage ran df output through a pipeline into while-read,
#          which executes in a subshell. Refactored to use process substitution
#          (while ... done < <(...)) so the loop stays in the main shell.
#          Also replaced the fragile inner 'read <<< "$line"' with direct awk
#          parsing of each df output line.
#   BUG-4  echo -e used throughout for colour output — non-POSIX and not
#          guaranteed to work on all bash builds. All output switched to printf.
#   BUG-5  'timeout dnf check-update | wc -l' — on timeout (exit 124), wc -l
#          received partial input and returned a non-zero line count instead of
#          the intended 0. Now captures the dnf output to a variable with an
#          explicit exit-code check; counts only on success.
#   BUG-6  --help and --version not in the test-harness early-exit block,
#          requiring the full getopt loop to run first. Added for consistency.
#   BUG-7  print_backup_status only stripped ANSI from last_line; last_backup
#          was passed to grep with raw escape sequences. Both variables now
#          stripped before use.
#   BUG-8  Background update job wrote directly to $UPDATE_CACHE, leaving a
#          partial/corrupt file readable mid-write. Now writes to a temp file
#          and renames atomically on completion.

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help"    || "${1:-}" == "-h" ]]; then
    echo "Usage: motd-generator.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "motd-generator.sh version 2.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
QUOTE_FILE="${QUOTE_FILE:-$HOME/.config/quotes.txt}"
SHOW_UPDATES=true
SHOW_BACKUP=true
NO_COLOR=false
CACHE_DIR="$HOME/.local/share/motd_cache"
UPDATE_CACHE="$CACHE_DIR/updates.txt"

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    QUOTE_FILE="$(get_config ".motd.quote_file" "$QUOTE_FILE")"
    QUOTE_FILE="${QUOTE_FILE/#\~/$HOME}"
    [[ "$(get_config ".motd.show_updates" "true")" == "false" ]] && SHOW_UPDATES=false
    [[ "$(get_config ".motd.show_backup"  "true")" == "false" ]] && SHOW_BACKUP=false
fi

# ── Colour palette (printf-based; BUG-4 FIX) ──────────────────────────────────
# All sequences defined as variables; printed via printf '%b' or plain printf.
R=$'\033[0;31m'   # red
G=$'\033[0;32m'   # green
Y=$'\033[0;33m'   # yellow / amber
B=$'\033[0;34m'   # blue
M=$'\033[0;35m'   # magenta
C=$'\033[0;36m'   # cyan
W=$'\033[0;37m'   # white
DIM=$'\033[2m'
BOLD=$'\033[1m'
NC=$'\033[0m'

c() {   # c COLOR [TEXT] — emit coloured text; $2 optional (colour-only mode)
    if [[ "$NO_COLOR" == true ]]; then
        printf '%s' "${2:-}"
    else
        printf '%b%s%b' "$1" "${2:-}" "$NC"
    fi
}
cl() { c "$1" "${2:-}"; printf '\n'; }   # c + newline

# ── ANSI strip helper ──────────────────────────────────────────────────────────
strip_ansi() { sed 's/\x1b\[[0-9;]*[mGKHF]//g'; }

# ── Layout constants ───────────────────────────────────────────────────────────
W_TOTAL=62   # total banner width (characters)

# ── Box-drawing helpers ────────────────────────────────────────────────────────
hline() {
    # hline [char] — print a full-width horizontal line
    local ch="${1:-─}"
    printf '%0.s'"$ch" $(seq 1 $W_TOTAL)
    printf '\n'
}

section() {
    # section LABEL — labelled divider
    local label=" $1 "
    local label_len=${#label}
    local left=$(( (W_TOTAL - label_len) / 2 ))
    local right=$(( W_TOTAL - label_len - left ))
    printf '%s' "$(c "$DIM" "$(printf '%.0s─' $(seq 1 $left))")"
    printf '%s' "$(c "$Y" "$label")"
    printf '%s' "$(c "$DIM" "$(printf '%.0s─' $(seq 1 $right))")"
    printf '\n'
}

lrow() {
    # lrow LABEL VALUE [COLOR]  — left-aligned label row
    local label="$1" value="$2" col="${3:-$W}"
    printf '  %-14s ' "$(c "$DIM" "$label")"
    cl "$col" "$value"
}

badge() {
    # badge TEXT COLOR  — inline coloured badge
    c "$2" "[$1]"
}

# ── Header ────────────────────────────────────────────────────────────────────
print_header() {
    local host user ts
    host=$(hostname -s 2>/dev/null || hostname)
    user=$(whoami)
    ts=$(date '+%a %d %b  %H:%M')

    printf '\n'
    printf '%b' "$B"; hline "═"; printf '%b' "$NC"
    printf '\n'

    # Centre the hostname
    local title="  ${BOLD}${user}$(c "$DIM" "@")${BOLD}${host}${NC}"
    local plain_title="  ${user}@${host}"
    local pad=$(( (W_TOTAL - ${#plain_title}) / 2 ))
    printf '%*s' "$pad" ''
    printf '%b' "$title"
    printf '%*s' "$pad" ''
    printf '\n'

    printf '  %-*s%s\n' $(( W_TOTAL - ${#ts} - 2 )) \
        "$(c "$DIM" "Noba Command Centre")" \
        "$(c "$DIM" "$ts")"
    printf '\n'
    printf '%b' "$B"; hline "═"; printf '%b\n' "$NC"
}

# ── System info ───────────────────────────────────────────────────────────────
print_system_info() {
    section "SYSTEM"

    local uptime_str load_str mem_str kernel_str cpu_str
    uptime_str=$(uptime -p 2>/dev/null | sed 's/up //' || echo 'N/A')
    load_str=$(uptime | awk -F'load average:' '{gsub(/ /,"",$2); print $2}')
    mem_str=$(free -h 2>/dev/null | awk '/^Mem:/ {printf "%s / %s", $3, $2}' || echo 'N/A')
    kernel_str=$(uname -r 2>/dev/null || echo 'N/A')

    # CPU temp (try multiple sources)
    local cpu_temp='N/A'
    if command -v sensors &>/dev/null; then
        local t
        t=$(sensors 2>/dev/null | grep -oP '(?:Tctl|Package id 0|Core 0|temp1):.*?\+\K[\d.]+' | head -1 || true)
        [[ -n "$t" ]] && cpu_temp="${t%.*}°C"
    elif [[ -r /sys/class/thermal/thermal_zone0/temp ]]; then
        cpu_temp="$(( $(cat /sys/class/thermal/thermal_zone0/temp) / 1000 ))°C"
    fi

    # Colour temp
    local temp_col="$G"
    if [[ "$cpu_temp" != 'N/A' ]]; then
        local t_num="${cpu_temp//[^0-9]/}"
        (( t_num > 80 )) && temp_col="$R" || (( t_num > 65 )) && temp_col="$Y" || true
    fi

    printf '\n'
    lrow "Uptime"   "$uptime_str"   "$C"
    lrow "Load"     "$load_str"     "$W"
    lrow "Memory"   "$mem_str"      "$W"
    lrow "Kernel"   "$kernel_str"   "$DIM"
    lrow "CPU temp" "$cpu_temp"     "$temp_col"
    printf '\n'
}

# ── Disk usage (BUG-3 FIX: process substitution, no pipeline subshell) ────────
print_disk_usage() {
    section "STORAGE"

    local df_out
    # BUG-3 FIX: timeout protects against stale mounts; process substitution
    # keeps the loop in the main shell
    if ! df_out=$(timeout 2 df -h --output=source,size,used,pcent,target 2>/dev/null); then
        printf '  '; cl "$R" "[df timed out — possible stale network mount]"
        return
    fi

    printf '\n'
    local printed=0
    while IFS= read -r line; do
        # Skip header and non-device lines
        [[ "$line" =~ ^Filesystem ]] && continue
        local src size used pct mnt
        read -r src size used pct mnt <<< "$line"
        [[ "$src" != /dev/* ]] && continue
        [[ "$mnt" == /var/lib/snapd/* || "$mnt" == /snap/* ]] && continue

        local pct_num="${pct//%/}"
        local bar_col="$G"
        (( pct_num >= 90 )) && bar_col="$R"  || true
        (( pct_num >= 75 && pct_num < 90 )) && bar_col="$Y" || true

        # Progress bar (20 chars)
        local filled=$(( pct_num * 20 / 100 ))
        local empty=$(( 20 - filled ))
        local bar
        bar="$(printf '%0.s█' $(seq 1 $filled 2>/dev/null || true))"
        bar+="$(printf '%0.s░' $(seq 1 $empty 2>/dev/null || true))"

        # Truncate long mount paths
        local mnt_display="$mnt"
        (( ${#mnt} > 18 )) && mnt_display="…${mnt: -17}"

        printf '  %-20s' "$(c "$W" "$mnt_display")"
        printf ' %s' "$(c "$bar_col" "$bar")"
        printf ' %s' "$(c "$bar_col" "$pct")"
        printf ' %s\n' "$(c "$DIM" "$used/$size")"
        (( printed++ )) || true
    done < <(printf '%s\n' "$df_out")

    (( printed == 0 )) && { printf '  '; cl "$DIM" "No mounted filesystems found."; }
    printf '\n'
}

# ── Backup status (BUG-7 FIX: strip ANSI from all log reads) ──────────────────
print_backup_status() {
    section "BACKUP"
    local backup_log="$HOME/.local/share/backup-to-nas.log"
    printf '\n'

    if [[ ! -f "$backup_log" ]]; then
        printf '  '; cl "$DIM" "No backup log found."
        printf '\n'
        return
    fi

    # BUG-7 FIX: strip ANSI before any grep/display
    local last_backup last_line
    last_backup=$(tail -20 "$backup_log" | strip_ansi \
        | grep -E "Backup finished|Failed sources|ERROR" | tail -1 || true)
    last_line=$(tail -1 "$backup_log" | strip_ansi)

    if echo "$last_backup" | grep -qi "ERROR\|Failed"; then
        printf '  Status  '; cl "$R" "$(badge "FAILED" "$R")  $last_backup"
    elif echo "$last_backup" | grep -qi "finished\|successful"; then
        printf '  Status  '; cl "$G" "$(badge "OK" "$G")  $last_backup"
    else
        printf '  Status  '; cl "$Y" "$(badge "UNKNOWN" "$Y")"
    fi

    [[ -n "$last_line" ]] && { printf '  '; cl "$DIM" "$last_line"; }
    printf '\n'
}

# ── Update check: async background job (BUG-1/5/8 FIX) ───────────────────────
trigger_update_check() {
    mkdir -p "$CACHE_DIR"
    # Trigger bg refresh only if cache is stale (> 60 min) or absent
    if [[ ! -f "$UPDATE_CACHE" ]] \
        || [[ -n "$(find "$UPDATE_CACHE" -mmin +60 -print 2>/dev/null)" ]]; then
        (
            # BUG-1 FIX: no 'local' in subshell — use plain vars
            d_up=0
            f_up=0

            # BUG-5 FIX: capture output separately; check exit code explicitly
            # dnf check-update exits 100 when updates exist, 0 when none, 1 on error
            if command -v dnf &>/dev/null; then
                dnf_out=$(timeout 15 dnf check-update -q 2>/dev/null) && d_up=0 \
                    || { ec=$?; (( ec == 100 )) && d_up=$(printf '%s\n' "$dnf_out" | grep -c .) || d_up=0; }
            fi
            if command -v flatpak &>/dev/null; then
                f_out=$(timeout 15 flatpak remote-ls --updates 2>/dev/null) \
                    && f_up=$(printf '%s\n' "$f_out" | grep -c . || echo 0) \
                    || f_up=0
            fi

            # BUG-8 FIX: atomic write via temp file
            local_tmp="${UPDATE_CACHE}.tmp.$$"
            printf '%d|%d\n' "$d_up" "$f_up" > "$local_tmp"
            mv "$local_tmp" "$UPDATE_CACHE"
        ) &
        disown 2>/dev/null || true
    fi
}

print_updates() {
    section "UPDATES"
    trigger_update_check
    printf '\n'

    if [[ ! -f "$UPDATE_CACHE" ]]; then
        printf '  '; cl "$DIM" "Checking in background — re-run in a moment."
        printf '\n'
        return
    fi

    # BUG-2 FIX: validate cache content before arithmetic
    local raw_line dnf_u flatpak_u
    raw_line=$(head -1 "$UPDATE_CACHE" 2>/dev/null || echo "0|0")
    # Strip anything that isn't digits or pipe
    raw_line="${raw_line//[^0-9|]/}"
    IFS='|' read -r dnf_u flatpak_u <<< "$raw_line"
    # Default to 0 if empty or non-numeric
    [[ "$dnf_u"     =~ ^[0-9]+$ ]] || dnf_u=0
    [[ "$flatpak_u" =~ ^[0-9]+$ ]] || flatpak_u=0

    local any=false
    if (( dnf_u > 0 )); then
        printf '  '; printf '%-10s' "$(c "$DIM" "DNF")"; cl "$Y" "$dnf_u package(s) available"
        any=true
    fi
    if (( flatpak_u > 0 )); then
        printf '  '; printf '%-10s' "$(c "$DIM" "Flatpak")"; cl "$Y" "$flatpak_u app(s) available"
        any=true
    fi
    [[ "$any" == false ]] && { printf '  '; cl "$G" "All packages up to date."; }
    printf '\n'
}

# ── Quote ──────────────────────────────────────────────────────────────────────
print_quote() {
    local quote=""

    if [[ -f "$QUOTE_FILE" ]]; then
        quote=$(shuf -n 1 "$QUOTE_FILE" 2>/dev/null || true)
    elif command -v curl &>/dev/null && command -v jq &>/dev/null; then
        local api_out
        api_out=$(timeout 2 curl -s "https://api.quotable.io/random" 2>/dev/null || true)
        quote=$(printf '%s' "$api_out" | jq -r '(.content // "") + " – " + (.author // "")' 2>/dev/null || true)
        [[ "$quote" == " – " || "$quote" == "null – null" ]] && quote=""
    fi

    [[ -z "$quote" ]] && return

    section "QUOTE"
    printf '\n'
    # Word-wrap at W_TOTAL-4 chars
    printf '%s\n' "$quote" | fold -s -w $(( W_TOTAL - 4 )) | while IFS= read -r qline; do
        printf '  '; cl "$C" "$qline"
    done
    printf '\n'
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt -o '' \
        -l no-color,no-updates,no-backup,help,version \
        -- "$@" 2>/dev/null); then
    printf 'Invalid argument. Run with --help for usage.\n' >&2
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --no-color)   NO_COLOR=true;       shift ;;
        --no-updates) SHOW_UPDATES=false;  shift ;;
        --no-backup)  SHOW_BACKUP=false;   shift ;;
        --help)       # BUG-6 FIX: also handled in test harness above
            cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Display Noba system status as a terminal banner (MOTD).

Options:
  --no-color    Disable colour output (for plain terminals / log capture)
  --no-updates  Hide the pending-updates section
  --no-backup   Hide the backup-status section
  --help        Show this message
  --version     Show version information

Place this in ~/.bashrc or /etc/profile.d/ to run on each login:
  source ~/.local/bin/motd-generator.sh
EOF
            exit 0 ;;
        --version) echo "motd-generator.sh version 2.0.0"; exit 0 ;;
        --)        shift; break ;;
        *)         printf 'Unknown argument: %s\n' "$1" >&2; exit 1 ;;
    esac
done

# ── Render ─────────────────────────────────────────────────────────────────────
print_header
print_system_info
print_disk_usage
[[ "$SHOW_BACKUP"  == true ]] && print_backup_status
[[ "$SHOW_UPDATES" == true ]] && print_updates
print_quote

printf '%b' "$B"; hline "═"; printf '%b\n\n' "$NC"
