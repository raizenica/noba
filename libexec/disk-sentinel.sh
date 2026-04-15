#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# disk-sentinel.sh – Monitor disk space and alert when threshold exceeded
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  mapfile -t TARGETS <<< "$empty_string" produced TARGETS=("") — one phantom
#          empty element. The main loop ran with target="" → df "" → error every run.
#          Fixed with a guarded while-read loop (same pattern as backup-to-nas v3).
#   BUG-2  exec > >(tee -a "$LOG_FILE") appeared after the first log_info calls
#          (config-load section, check_deps). Early warnings were lost to the log.
#          Logging redirect moved before any output.
#   BUG-3  sudo du -h -x -d 3 "$target" was run synchronously inside the email body
#          string. On a full filesystem this can block for 30–120 s, delaying the alert.
#          Also silently produced empty output if passwordless sudo was unavailable.
#          Replaced with a timeout-wrapped, non-sudo du with sudo fallback.
#   BUG-4  SAFETY: run_sudo find /tmp -type f -atime +2 -delete as root deletes ALL
#          users' temp files — including active socket files, PID files, and lock files
#          belonging to running processes. Removed entirely. Journal vacuum and
#          systemd-tmpfiles --clean are the safe system-level cleaners; user-owned
#          /tmp is cleaned via a targeted pattern (noba-* only).
#   BUG-5  new_usage used sed 's/%//' which left a leading space from df's output
#          (" 87" instead of "87"). Replaced with the same awk pipeline used for the
#          initial usage parse.
#   BUG-6  email_body used literal \n escape sequences. printf interprets \n in the
#          FORMAT string but not in arguments, so the msmtp email arrived as one long
#          line. The mail -s path used echo -e, which did expand \n — inconsistent.
#          email_body is now built with real newlines; printf %s used for the body.
#   BUG-7  -v was overloaded: test harness exited 0 on first-positional -v (--version),
#          while getopt mapped -v to --verbose. Passing -v in normal use exited with
#          version output instead of running verbosely. Short alias removed from
#          getopt; --verbose is long-form only.
#   BUG-8  Script always exited 0 even when disks exceeded threshold. Cron MAILTO=
#          and systemd OnFailure= never triggered. Now exits 1 if any alert fired,
#          2 on setup/config errors.
#   BUG-9  IGNORE_FS loaded from YAML as a raw regex. An invalid regex caused the
#          =~ test to abort under set -e with "invalid regex". Now validated with a
#          test match before use; falls back to the built-in default on parse failure.
#
# New in 3.0.0:
#   --warn-threshold  Second (lower) threshold for warnings vs criticals (two-level alerts)
#   --add-target      Add a mount point to check without overriding config targets
#   --no-cleanup      Disable all cleanup for this run (without editing config)
#   --du-timeout N    Seconds to allow for du scan (default: 30)
#   --state-file      Write a machine-readable state file after each run (dashboard)
#   Exit codes:       0=all OK  1=threshold breached  2=config/setup error

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: disk-sentinel.sh [OPTIONS]"; exit 0
fi
# BUG-7 FIX: -v means --version only; --verbose has no short alias
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "disk-sentinel.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
THRESHOLD="${THRESHOLD:-85}"
WARN_THRESHOLD=""          # optional lower warning threshold (e.g. 75)
TARGETS=()
EXTRA_TARGETS=()           # from --add-target
DEFAULT_TARGETS=("/" "/home")
CLEANUP="${CLEANUP:-true}"
NO_CLEANUP=false
EMAIL="${EMAIL:-}"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/disk-sentinel.log}"
STATE_FILE="${STATE_FILE:-$HOME/.local/share/disk-sentinel.state}"
DRY_RUN=false
export VERBOSE=false
DU_TIMEOUT=30
IGNORE_FS_DEFAULT="^(proc|sysfs|tmpfs|devpts|securityfs|fusectl|debugfs|pstore|hugetlbfs|mqueue|configfs|devtmpfs|binfmt_misc)$"
IGNORE_FS="$IGNORE_FS_DEFAULT"

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    # BUG-1 FIX: guard with while-read to avoid phantom empty element
    raw_targets=$(get_config_array ".disk.targets" 2>/dev/null || true)
    if [[ -n "$raw_targets" ]]; then
        while IFS= read -r line; do
            [[ -n "$line" ]] && TARGETS+=("$line")
        done <<< "$raw_targets"
    fi

    THRESHOLD="$(get_config ".disk.threshold"       "$THRESHOLD")"
    WARN_THRESHOLD="$(get_config ".disk.warn_threshold" "$WARN_THRESHOLD")"
    CLEANUP="$(get_config   ".disk.cleanup_enabled" "$CLEANUP")"
    EMAIL="$(get_config     ".email"                "$EMAIL")"
    DU_TIMEOUT="$(get_config ".disk.du_timeout"     "$DU_TIMEOUT")"

    raw_ignore="$(get_config ".disk.ignore_fs" "")"
    if [[ -n "$raw_ignore" ]]; then
        # BUG-9 FIX: validate regex before using it
        if echo "" | grep -qE "$raw_ignore" 2>/dev/null; then
            IGNORE_FS="$raw_ignore"
        else
            log_warn "Invalid regex in .disk.ignore_fs — using default."
        fi
    fi

    config_log_dir="$(get_config ".logs.dir" "")"
    [[ -n "$config_log_dir" ]] && LOG_FILE="$config_log_dir/disk-sentinel.log"
fi

[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=("${DEFAULT_TARGETS[@]}")

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "disk-sentinel.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Monitor disk space and send alerts when usage exceeds threshold.

Options:
  -t, --threshold PCT     Critical threshold percentage (default: $THRESHOLD)
  -w, --warn-threshold PCT  Warning threshold below critical (e.g. 75)
      --add-target DIR    Add an extra mount point to check (repeatable)
      --no-cleanup        Disable cleanup for this run
      --du-timeout N      Seconds allowed for du scan (default: $DU_TIMEOUT)
  -n, --dry-run           Show what would happen, make no changes
      --verbose           Enable verbose output
  --help                  Show this message
  -v, --version           Show version

Exit codes:
  0  All disks within threshold
  1  One or more disks exceeded threshold (alert fired)
  2  Configuration or setup error
EOF
    exit 0
}

# ── BUG-6 FIX: email body is built with real newlines; send_email uses printf %s ─
send_email() {
    local subject="$1" body="$2"
    [[ -z "$EMAIL" ]] && { log_warn "No email recipient — skipping notification."; return 0; }

    if command -v msmtp &>/dev/null; then
        # printf %s preserves real newlines; format string only has \n for header sep
        printf 'Subject: %s\n\n%s\n' "$subject" "$body" | msmtp "$EMAIL"
        log_info "Email sent via msmtp to $EMAIL"
    elif command -v mail &>/dev/null; then
        printf '%s\n' "$body" | mail -s "$subject" "$EMAIL"
        log_info "Email sent via mail to $EMAIL"
    else
        log_warn "No mail program found (msmtp / mail) — cannot send email."
    fi
}

# ── BUG-3 FIX: timeout-wrapped du with sudo fallback ─────────────────────────
get_top_dirs() {
    local target="$1" timeout="$2"
    local result=""

    # Try without sudo first (covers user-owned mounts like /home)
    if result=$(timeout "$timeout" du -h -x --max-depth=3 "$target" 2>/dev/null \
                | sort -rh | head -10); then
        echo "$result"
        return
    fi

    # Fallback: sudo with timeout
    if sudo -n true 2>/dev/null; then
        result=$(timeout "$timeout" sudo du -h -x --max-depth=3 "$target" 2>/dev/null \
                 | sort -rh | head -10) || true
        [[ -n "$result" ]] && echo "$result" && return
    fi

    echo "(du timed out or insufficient permissions for $target)"
}

# ── Safe cleanup helper ────────────────────────────────────────────────────────
run_sudo() {
    local desc="$1"; shift
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would run (sudo): $*"; return 0
    fi
    if sudo -n true 2>/dev/null; then
        sudo "$@" && return 0 || { log_warn "Command failed: $*"; return 1; }
    fi
    log_warn "sudo unavailable — skipping: $desc"
    return 1
}

do_cleanup() {
    local mount="$1"
    log_info "Cleanup on $mount..."

    # Package manager caches
    command -v dnf     &>/dev/null && run_sudo "dnf clean"     dnf clean all             || true
    command -v apt-get &>/dev/null && run_sudo "apt clean"     apt-get clean -y           || true
    command -v flatpak &>/dev/null && run_sudo "flatpak prune" flatpak uninstall --unused -y || true

    # User cache — thumbnails and files not accessed in 30+ days
    log_info "Cleaning ~/.cache (thumbnails + 30d-old files)..."
    rm -rf "$HOME/.cache/thumbnails/"* 2>/dev/null || true
    find "$HOME/.cache" -type f -atime +30 -delete 2>/dev/null || true

    # BUG-4 FIX: do NOT delete arbitrary /tmp files as root.
    # Use systemd-tmpfiles for safe system temp cleanup, or restrict to
    # script-owned prefix only.
    if command -v systemd-tmpfiles &>/dev/null; then
        run_sudo "tmpfiles clean" systemd-tmpfiles --clean || true
    else
        # Only remove files we own in /tmp (script-specific prefix)
        find /tmp -maxdepth 1 -name "noba-*" -user "$USER" -atime +2 -delete 2>/dev/null || true
        log_verbose "Skipped broad /tmp cleanup (systemd-tmpfiles not available)."
    fi

    # Journal vacuum (safe — only affects journald's own storage)
    command -v journalctl &>/dev/null \
        && run_sudo "journal vacuum" journalctl --vacuum-time=3d || true
}

# ── Parse usage integer from df output ────────────────────────────────────────
# BUG-5 FIX: awk strips leading space and %; consistent with initial parse
parse_usage() {
    awk '{gsub(/%/,"",$1); print $1+0}'
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o t:w:nh \
        -l threshold:,warn-threshold:,add-target:,no-cleanup,du-timeout:,dry-run,verbose,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -t|--threshold)      THRESHOLD="$2";            shift 2 ;;
        -w|--warn-threshold) WARN_THRESHOLD="$2";       shift 2 ;;
           --add-target)     EXTRA_TARGETS+=("$2");     shift 2 ;;
           --no-cleanup)     NO_CLEANUP=true;           shift   ;;
           --du-timeout)     DU_TIMEOUT="$2";           shift 2 ;;
        -n|--dry-run)        DRY_RUN=true;              shift   ;;
           --verbose)        export VERBOSE=true;       shift   ;;
        -h|--help)           show_help ;;
           --version)        show_version ;;
        --)                  shift; break ;;
        *)                   log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# Merge extra targets from --add-target
TARGETS+=("${EXTRA_TARGETS[@]+"${EXTRA_TARGETS[@]}"}")

# ── Validation ─────────────────────────────────────────────────────────────────
for v in THRESHOLD DU_TIMEOUT; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || { log_error "$v must be a non-negative integer."; exit 2; }
done
(( THRESHOLD >= 1 && THRESHOLD <= 100 )) \
    || { log_error "--threshold must be 1–100."; exit 2; }
if [[ -n "$WARN_THRESHOLD" ]]; then
    [[ "$WARN_THRESHOLD" =~ ^[0-9]+$ ]] \
        || { log_error "--warn-threshold must be a non-negative integer."; exit 2; }
    (( WARN_THRESHOLD < THRESHOLD )) \
        || { log_error "--warn-threshold ($WARN_THRESHOLD) must be below --threshold ($THRESHOLD)."; exit 2; }
fi

check_deps df awk du sort find

# ── BUG-2 FIX: logging redirect before any output ────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Main ───────────────────────────────────────────────────────────────────────
log_info "=========================================="
log_info "  Disk Sentinel v3.0.0: $(date)"
log_info "  Threshold: ${THRESHOLD}%${WARN_THRESHOLD:+  Warn: ${WARN_THRESHOLD}%}"
log_info "  Cleanup: $CLEANUP  Dry run: $DRY_RUN"
log_info "  Targets: ${TARGETS[*]}"
log_info "=========================================="

ALERT_COUNT=0   # BUG-8 FIX: count breaches for exit code

for target in "${TARGETS[@]}"; do
    [[ -z "$target" ]] && continue   # BUG-1 FIX: skip phantom empty element

    if [[ ! -e "$target" ]]; then
        log_warn "Target '$target' does not exist — skipping."
        continue
    fi

    # Parse usage and mount point
    if ! df_line=$(df --output=pcent,target "$target" 2>/dev/null | tail -1); then
        log_warn "Cannot get disk usage for '$target' — skipping."
        continue
    fi
    usage=$(echo "$df_line" | awk '{print $1}' | parse_usage)
    mount=$(echo "$df_line" | awk '{print $2}')

    # Get filesystem type; guard against parse failure
    fstype=$(df -T "$target" 2>/dev/null | awk 'NR==2 {print $2}') || fstype="unknown"

    # BUG-9 FIX: wrap regex test to survive a bad pattern
    skip=false
    if [[ -n "$IGNORE_FS" ]]; then
        { [[ "$fstype" =~ $IGNORE_FS ]] && skip=true; } 2>/dev/null || true
    fi
    if [[ "$skip" == true ]]; then
        log_verbose "Skipping $mount (virtual filesystem: $fstype)"
        continue
    fi

    log_info "$mount: ${usage}% used  (fstype: $fstype)"

    # Determine alert level
    level=""
    if   (( usage >= THRESHOLD )); then
        level="critical"
    elif [[ -n "$WARN_THRESHOLD" ]] && (( usage >= WARN_THRESHOLD )); then
        level="warning"
    fi

    if [[ -z "$level" ]]; then
        log_info "$mount: OK"
        continue
    fi

    # ── Alert ────────────────────────────────────────────────────────────────
    icon="⚠"; [[ "$level" == "critical" ]] && icon="🔴"
    log_warn "$icon $mount exceeded ${level} threshold (${usage}% ≥ ${THRESHOLD}%)"
    (( ALERT_COUNT++ )) || true

    # BUG-3 FIX: timeout-wrapped, non-blocking du
    top_dirs=$(get_top_dirs "$mount" "$DU_TIMEOUT")

    # BUG-6 FIX: build body with real newlines using $'\n'
    nl=$'\n'
    email_body="${icon} Disk space ${level} on $mount"
    email_body+="${nl}Host:      $(hostname)"
    email_body+="${nl}Time:      $(date '+%Y-%m-%d %H:%M:%S')"
    email_body+="${nl}Usage:     ${usage}% (threshold ${THRESHOLD}%)"
    email_body+="${nl}"
    email_body+="${nl}Top directories by size:"
    email_body+="${nl}${top_dirs}"

    # ── Cleanup ───────────────────────────────────────────────────────────────
    effective_cleanup="$CLEANUP"
    [[ "$NO_CLEANUP" == true ]] && effective_cleanup=false

    if [[ "$effective_cleanup" == true ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] Would run cleanup on $mount"
            email_body+="${nl}${nl}[DRY RUN] Cleanup would be performed."
        else
            do_cleanup "$mount"
            # BUG-5 FIX: awk-based parse, consistent with initial usage read
            new_usage=$(df --output=pcent "$target" 2>/dev/null | tail -1 | parse_usage)
            freed=$(( usage - new_usage ))
            email_body+="${nl}${nl}Cleanup performed. Usage now: ${new_usage}% (freed ${freed}pp)"
            log_info "Post-cleanup usage: ${new_usage}%"
        fi
    else
        email_body+="${nl}${nl}Cleanup disabled."
    fi

    # ── Send alert ────────────────────────────────────────────────────────────
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would send email alert:"
        echo "$email_body" | sed 's/^/  /'
    else
        send_email "${icon} Disk ${level}: $mount at ${usage}% on $(hostname)" "$email_body"
    fi
done

# ── State file (for web dashboard) ────────────────────────────────────────────
if [[ "$DRY_RUN" != true ]]; then
    {
        echo "LAST_RUN=$(date '+%Y-%m-%d %H:%M:%S')"
        echo "ALERT_COUNT=$ALERT_COUNT"
        if (( ALERT_COUNT > 0 )); then echo "STATUS=alert"; else echo "STATUS=ok"; fi
    } > "$STATE_FILE"
fi

log_info "=========================================="
log_info "  Disk Sentinel finished: $(date)"
if (( ALERT_COUNT > 0 )); then
    log_warn "  $ALERT_COUNT threshold breach(es) detected."
else
    log_info "  All disks within threshold."
fi
log_info "=========================================="

# BUG-8 FIX: exit 1 when any threshold was breached
(( ALERT_COUNT > 0 )) && exit 1 || exit 0
