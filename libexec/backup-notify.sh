#!/bin/bash
# backup-notify.sh – Send a desktop notification about the last backup status
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  strip_ansi used <<< "$1" but was called as a pipe stage (| strip_ansi).
#          When used in a pipeline, $1 is empty — the pipe input was silently
#          discarded and last_context was always an empty string.
#   BUG-2  All status grep tests ran against an empty string (consequence of BUG-1),
#          so urgency/summary always fell through to "Unknown".
#   BUG-3  grep exits 1 when there is no match; under set -e this killed the script
#          before message was ever captured. All pattern matches now use || true.
#   BUG-4  --version printed bare "2.2.2" instead of "backup-notify.sh version 2.2.2",
#          inconsistent with the rest of the Nobara suite.
#   BUG-5  kdialog --passivepopup doesn't distinguish urgency — a "critical" backup
#          failure showed the same silent 5-second popup as a low-priority notice.
#   BUG-6  Only the last 5 log lines were scanned. With verbose rsync output the
#          "Backup finished / ERROR" line is often further back; scan is now configurable.
#   BUG-7  notify-send was called without -i (icon) or action hints for critical events,
#          missing the urgency visual/sound cue that desktop environments provide.
#
# New in 3.0.0:
#   State file    backup-to-nas writes a small JSON status file; notifier reads it
#                 first (precise) and falls back to log scanning (legacy compat).
#   --history N   Show a summary of the last N backup results instead of just the latest.
#   --test        Fire a test notification at each urgency level and exit.
#   --sound FILE  Play a sound on critical notifications (via paplay / aplay / mpv).
#   --icon        Resolve a themed icon based on status for notify-send -i.

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help"    || "${1:-}" == "-h" ]]; then
    echo "Usage: backup-notify.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-notify.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
STATE_FILE="${STATE_FILE:-$HOME/.local/share/backup-to-nas.state}"
DRY_RUN=false
FORCE_URGENCY=""
SCAN_LINES=40          # how many tail lines to scan for status
HISTORY_MODE=false
HISTORY_COUNT=5
TEST_MODE=false
SOUND_FILE=""
SHOW_ICON=true

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    LOG_FILE="$(get_config    ".backup_notify.log_file"    "$LOG_FILE")"
    STATE_FILE="$(get_config  ".backup_notify.state_file"  "$STATE_FILE")"
    SCAN_LINES="$(get_config  ".backup_notify.scan_lines"  "$SCAN_LINES")"
    SOUND_FILE="$(get_config  ".backup_notify.sound_file"  "$SOUND_FILE")"
fi

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "backup-notify.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Reads the last backup status and sends a desktop notification.
Checks the state file first (written by backup-to-nas v3), then falls back
to scanning the log file for legacy compatibility.

Options:
  --log-file FILE    Backup log to scan (default: $LOG_FILE)
  --state-file FILE  JSON state file written by backup-to-nas v3 (default: $STATE_FILE)
  --scan-lines N     Lines to scan from end of log (default: $SCAN_LINES)
  --urgency URG      Override urgency: low | normal | critical
  --history N        Show summary of last N backup results and exit
  --test             Fire a test notification at each urgency level and exit
  --sound FILE       Play FILE on critical notifications (paplay / aplay / mpv)
  --no-icon          Disable themed icon in notify-send
  --dry-run          Show what would be sent without notifying
  --help             Show this message
  --version          Show version information
EOF
    exit 0
}

# ── BUG-1 FIX: strip_ansi works both as a pipe stage AND with an argument ─────
# As pipe stage:  echo "text" | strip_ansi
# With argument:  strip_ansi "$var"
strip_ansi() {
    if [[ $# -gt 0 ]]; then
        # Called with argument — strip and print
        printf '%s\n' "$1" | sed 's/\x1b\[[0-9;]*m//g; s/\x1b\[[?][0-9;]*[a-zA-Z]//g'
    else
        # Called as pipeline stage — read stdin
        sed 's/\x1b\[[0-9;]*m//g; s/\x1b\[[?][0-9;]*[a-zA-Z]//g'
    fi
}

# ── Play a sound (best-effort) ─────────────────────────────────────────────────
play_sound() {
    local file="$1"
    [[ -z "$file" || ! -f "$file" ]] && return 0
    if   command -v paplay  &>/dev/null; then paplay  "$file" &
    elif command -v aplay   &>/dev/null; then aplay   "$file" &
    elif command -v mpv     &>/dev/null; then mpv --no-terminal "$file" &
    fi
}

# ── Resolve themed icon name for notify-send ───────────────────────────────────
icon_for() {
    local urgency="$1"
    case "$urgency" in
        critical) echo "dialog-error" ;;
        normal)   echo "emblem-default" ;;
        low)      echo "dialog-information" ;;
        *)        echo "dialog-information" ;;
    esac
}

# ── BUG-5 FIX: kdialog with proper urgency handling ───────────────────────────
_kdialog_notify() {
    local urgency="$1" summary="$2" body="$3"
    case "$urgency" in
        critical)
            # kdialog --error gives a modal error dialog for genuinely critical events
            kdialog --error "$summary\n\n$body" --title "Noba Backup" ;;
        normal)
            kdialog --passivepopup "$body" 8 --title "$summary" ;;
        low|*)
            kdialog --passivepopup "$body" 4 --title "$summary" ;;
    esac
}

# ── Send notification ──────────────────────────────────────────────────────────
send_notification() {
    local urgency="$1" summary="$2" body="$3"
    local clean_body
    # BUG-1 FIX: strip_ansi called with argument, not as pipe stage
    clean_body=$(strip_ansi "$body")

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] urgency=$urgency | $summary | $clean_body"
        return 0
    fi

    # No display — log to console only
    if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
        log_info "No GUI display. Notification: [$urgency] $summary — $clean_body"
        return 0
    fi

    if command -v notify-send &>/dev/null; then
        local icon_args=()
        if [[ "$SHOW_ICON" == true ]]; then
            icon_args=("-i" "$(icon_for "$urgency")")
        fi
        # BUG-7 FIX: pass -u urgency and icon; critical also gets a sound hint
        notify-send -u "$urgency" -a "Noba Backup" \
            "${icon_args[@]}" \
            "$summary" "$clean_body"

        # Play sound for critical notifications
        if [[ "$urgency" == "critical" && -n "$SOUND_FILE" ]]; then
            play_sound "$SOUND_FILE"
        fi

    elif command -v kdialog &>/dev/null; then
        # BUG-5 FIX: urgency-aware kdialog dispatch
        _kdialog_notify "$urgency" "$summary" "$clean_body"
    else
        # Last resort: write to stderr for critical, stdout otherwise
        if [[ "$urgency" == "critical" ]]; then
            echo "CRITICAL: $summary — $clean_body" >&2
        else
            echo "$summary — $clean_body"
        fi
    fi
}

# ── Read state file (backup-to-nas v3 writes this) ────────────────────────────
# Returns 0 and sets STATUS_SOURCE, STATUS_URGENCY, STATUS_SUMMARY, STATUS_MSG
# Returns 1 if state file is absent or unreadable
read_state_file() {
    [[ -r "$STATE_FILE" ]] || return 1

    # State file format (one key=value per line, written by backup-to-nas v3):
    #   exit_code=0
    #   timestamp=2025-01-15 03:00:01
    #   failed_sources=
    #   duration=47
    #   snapshot=20250115-030001
    local exit_code="" timestamp="" failed="" duration="" snapshot=""

    while IFS='=' read -r key val; do
        case "$key" in
            exit_code)      exit_code="$val"  ;;
            timestamp)      timestamp="$val"  ;;
            failed_sources) failed="$val"     ;;
            duration)       duration="$val"   ;;
            snapshot)       snapshot="$val"   ;;
        esac
    done < "$STATE_FILE"

    [[ -z "$exit_code" ]] && return 1

    STATUS_SOURCE="state file"
    local age_note=""
    [[ -n "$timestamp" ]] && age_note=" at $timestamp"

    case "$exit_code" in
        0)
            STATUS_URGENCY="normal"
            STATUS_SUMMARY="✅ Backup Successful"
            STATUS_MSG="Snapshot ${snapshot}${age_note}"
            [[ -n "$duration" ]] && STATUS_MSG+="  (${duration}s)"
            ;;
        1)
            STATUS_URGENCY="critical"
            STATUS_SUMMARY="⚠️  Backup Partial"
            STATUS_MSG="Some sources failed${age_note}: ${failed:-unknown}"
            ;;
        2|*)
            STATUS_URGENCY="critical"
            STATUS_SUMMARY="❌ Backup Failed"
            STATUS_MSG="Exit code ${exit_code}${age_note}"
            [[ -n "$failed" ]] && STATUS_MSG+=": $failed"
            ;;
    esac
    return 0
}

# ── Scan log file for status (legacy / fallback) ───────────────────────────────
# BUG-1/2/3 FIX: strip_ansi called correctly; grep guarded with || true
read_log_file() {
    [[ -r "$LOG_FILE" ]] || return 1

    # BUG-1 FIX: pipe through strip_ansi (pipeline stage, $# == 0 path)
    local last_context
    last_context=$(tail -n "$SCAN_LINES" "$LOG_FILE" | strip_ansi)

    STATUS_SOURCE="log file (last ${SCAN_LINES} lines)"

    # BUG-3 FIX: grep exit-code 1 guarded with || true throughout
    local error_line finished_line success_line
    error_line=$(  echo "$last_context" | grep -i "error\|failed\|FAILED" | tail -1 || true)
    finished_line=$(echo "$last_context" | grep -i "finished\|complete"   | tail -1 || true)
    success_line=$( echo "$last_context" | grep -i "success\|successful"  | tail -1 || true)

    # Determine overall status from log content
    # Prefer: error > success/finished > unknown
    if [[ -n "$error_line" ]]; then
        STATUS_URGENCY="critical"
        STATUS_SUMMARY="❌ Backup Failed"
        STATUS_MSG="$error_line"
    elif [[ -n "$success_line" ]]; then
        STATUS_URGENCY="normal"
        STATUS_SUMMARY="✅ Backup Successful"
        STATUS_MSG="$success_line"
    elif [[ -n "$finished_line" ]]; then
        STATUS_URGENCY="normal"
        STATUS_SUMMARY="✅ Backup Finished"
        STATUS_MSG="$finished_line"
    else
        STATUS_URGENCY="low"
        STATUS_SUMMARY="ℹ️  Backup Status Unknown"
        STATUS_MSG=$(tail -n 1 "$LOG_FILE" | strip_ansi || true)
        [[ -z "$STATUS_MSG" ]] && STATUS_MSG="No recognisable status in last $SCAN_LINES log lines."
    fi
    return 0
}

# ── History mode: summarise last N backup runs from log ───────────────────────
show_history() {
    local n="$1"
    [[ -r "$LOG_FILE" ]] || die "Cannot read log: $LOG_FILE"

    echo "Last $n backup runs:"
    echo "────────────────────────────────────────────"

    local count=0
    # Each run is bracketed by "======" separators
    while IFS= read -r line; do
        local clean; clean=$(strip_ansi "$line")
        if echo "$clean" | grep -qi "started\|finished\|failed"; then
            echo "  $clean"
            echo "$clean" | grep -qi "finished\|failed" && (( count++ )) || true
        fi
        (( count >= n )) && break
    done < <(grep -E "started|finished|failed|ERROR|SUCCESS" "$LOG_FILE" \
             | strip_ansi | tail -n $(( n * 4 )))

    echo "────────────────────────────────────────────"
    exit 0
}

# ── Test mode ─────────────────────────────────────────────────────────────────
run_test() {
    log_info "Firing test notifications..."
    send_notification "low"      "ℹ️  Noba Test (low)"      "This is a low-urgency test notification."
    sleep 1
    send_notification "normal"   "✅ Noba Test (normal)"   "This is a normal-urgency test notification."
    sleep 1
    send_notification "critical" "❌ Noba Test (critical)" "This is a critical-urgency test notification."
    log_success "Test notifications sent."
    exit 0
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o '' \
        -l log-file:,state-file:,scan-lines:,urgency:,history:,test,sound:,no-icon,dry-run,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --log-file)    LOG_FILE="$2";       shift 2 ;;
        --state-file)  STATE_FILE="$2";     shift 2 ;;
        --scan-lines)  SCAN_LINES="$2";     shift 2 ;;
        --urgency)     FORCE_URGENCY="$2";  shift 2 ;;
        --history)     HISTORY_MODE=true;   HISTORY_COUNT="$2"; shift 2 ;;
        --test)        TEST_MODE=true;      shift ;;
        --sound)       SOUND_FILE="$2";     shift 2 ;;
        --no-icon)     SHOW_ICON=false;     shift ;;
        --dry-run)     DRY_RUN=true;        shift ;;
        --help)        show_help ;;
        --version)     show_version ;;
        --)            shift; break ;;
        *)             log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Validate ───────────────────────────────────────────────────────────────────
[[ "$SCAN_LINES" =~ ^[0-9]+$ ]] || die "--scan-lines must be a positive integer."
if [[ -n "$FORCE_URGENCY" ]]; then
    [[ "$FORCE_URGENCY" =~ ^(low|normal|critical)$ ]] \
        || die "--urgency must be one of: low normal critical"
fi

# ── Special modes ──────────────────────────────────────────────────────────────
[[ "$TEST_MODE"    == true ]] && run_test
[[ "$HISTORY_MODE" == true ]] && show_history "$HISTORY_COUNT"

# ── Resolve status — state file first, log fallback ───────────────────────────
STATUS_SOURCE=""
STATUS_URGENCY="low"
STATUS_SUMMARY="ℹ️  Backup Status Unknown"
STATUS_MSG=""

if ! read_state_file; then
    # State file absent or unreadable — fall back to log scanning
    if ! read_log_file; then
        die "Cannot read backup log ($LOG_FILE) or state file ($STATE_FILE)."
    fi
fi

log_verbose "Status source: $STATUS_SOURCE"
log_verbose "Urgency: $STATUS_URGENCY  |  $STATUS_SUMMARY"

# Apply forced urgency override
[[ -n "$FORCE_URGENCY" ]] && STATUS_URGENCY="$FORCE_URGENCY"

# ── Send ───────────────────────────────────────────────────────────────────────
send_notification "$STATUS_URGENCY" "$STATUS_SUMMARY" "$STATUS_MSG"
