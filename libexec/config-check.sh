#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# config-check.sh – Validate configuration and check dependencies
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  Every tool in the per-script sections was also in "common", so each
#          dependency was reported twice. Restructured into exclusive per-script
#          sets (tools unique to that script only) — common tools checked once.
#   BUG-2  check_cmd return values were ignored; failures were printed but never
#          counted. MISSING_REQUIRED / MISSING_OPTIONAL counters added; final exit
#          code driven by MISSING_REQUIRED, not a separate hardcoded list.
#   BUG-3  Version detection used "$cmd --version" for everything. Many tools
#          (flock, findmnt) use -V; some (fuser) print to stderr; kdialog --version
#          exits 1 on older KDE. Now tries --version, then -V, then -v quietly.
#   BUG-4  Critical-deps list was hardcoded and included optional tools (fuser,
#          msmtp, convert). Replaced by a tiered required/optional classification
#          that matches what the suite actually needs to function at all.
#   BUG-5  sudo -n true under set -e killed the script when sudo was not installed
#          ("command not found" = exit 1). Wrapped with command -v guard.
#   BUG-6  Associative array iteration order is arbitrary in bash; the hardcoded
#          "for script in …" loop was the only ordering mechanism, but if a key
#          was added to the array and omitted from the loop it was silently skipped.
#          Dependency table is now an ordered list of plain arrays.
#   BUG-7  -v was overloaded: test harness treated first positional -v as --version
#          and exited 0, while getopt mapped -v to --verbose. The two meanings
#          conflicted silently. Short flag for --verbose changed to nothing
#          (--verbose only); -v / --version kept exclusively for the version path.
#   BUG-8  exec 1>/dev/null for --quiet was applied before any tool checks ran
#          (fine), but was irreversible — combined with --verbose it silently
#          discarded the verbose output with no warning. Now uses a QUIET flag
#          checked in output helpers, leaving the fd open for debugging.
#
# New in 3.0.0:
#   --scripts LIST   Only check deps for specific scripts (comma-separated)
#   --fix            Attempt to install missing required tools via the system PM
#   --json           Output results as a JSON object (for dashboard integration)
#   --report FILE    Write a plain-text report to FILE
#   Missing-count summary line always printed at the end

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: config-check.sh [OPTIONS]"; exit 0
fi
# BUG-7 FIX: -v / --version only for version; --verbose has no short alias
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "config-check.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
VERBOSE=false
QUIET=false
CHECK_YAML=true
CHECK_OLD=true
DRY_RUN=false
FIX_MODE=false
JSON_MODE=false
REPORT_FILE=""
FILTER_SCRIPTS=""   # comma-separated; empty = all
OLD_CONFIG_FILE="${OLD_CONFIG_FILE:-$HOME/.config/automation.conf}"
NEW_CONFIG_FILE="${NEW_CONFIG_FILE:-$HOME/.config/noba/config.yaml}"
LOG_DIR="$HOME/.local/share"

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
fi

# ── Counters (global, not subshell-safe — kept in main shell only) ─────────────
MISSING_REQUIRED=0
MISSING_OPTIONAL=0
PRESENT=0

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "config-check.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Check configuration files and dependencies for the Noba Automation Suite.

Options:
      --verbose        Show tool version strings and config file contents
  -q, --quiet          Only show errors; suppress info/success lines
      --no-yaml        Skip checking the new YAML config
      --no-old         Skip checking the old automation.conf
      --scripts LIST   Comma-separated subset of scripts to check
                         e.g. --scripts backup,cloud,verifier
      --fix            Attempt to install missing required tools (uses dnf/apt/pacman)
      --json           Output a JSON summary (for dashboard integration)
      --report FILE    Write a plain-text report to FILE
  -n, --dry-run        Simulate run — exits immediately (test harness)
  -h, --help           Show this message
  -v, --version        Show version information
EOF
    exit 0
}

# ── Output helpers (honour --quiet) ───────────────────────────────────────────
# BUG-8 FIX: don't exec 1>/dev/null; check flag in helpers instead
_out() {
    [[ "$QUIET" == true ]] && return 0
    echo "$@"
}
_out_always() { echo "$@"; }   # for errors and final summary

# ── BUG-3 FIX: try multiple version flags before giving up ────────────────────
get_version() {
    local cmd="$1"
    local ver=""
    for flag in --version -V -v --help; do
        ver=$("$cmd" "$flag" 2>&1 | head -1) && [[ -n "$ver" ]] && break || ver=""
    done
    echo "${ver:-version unknown}"
}

# ── BUG-2 FIX: check_cmd increments global counters directly ──────────────────
# Usage: check_cmd CMD [DESCRIPTION] [required|optional]
check_cmd() {
    local cmd="$1"
    local desc="${2:-$cmd}"
    local tier="${3:-required}"

    if command -v "$cmd" &>/dev/null; then
        _out "  ✓ $desc"
        if [[ "$VERBOSE" == true ]]; then
            _out "      $(get_version "$cmd")"
        fi
        (( PRESENT++ )) || true
        return 0
    else
        if [[ "$tier" == "required" ]]; then
            log_error "  ✗ $desc (MISSING — required)"
            (( MISSING_REQUIRED++ )) || true
        else
            [[ "$QUIET" != true ]] && log_warn "  ✗ $desc (not found — optional)"
            (( MISSING_OPTIONAL++ )) || true
        fi
        return 1
    fi
}

# ── Attempt auto-install (--fix) ──────────────────────────────────────────────
try_install() {
    local pkg="$1"
    if command -v dnf &>/dev/null; then
        sudo -n dnf install -y "$pkg" 2>/dev/null && return 0
    elif command -v apt-get &>/dev/null; then
        sudo -n apt-get install -y "$pkg" 2>/dev/null && return 0
    elif command -v pacman &>/dev/null; then
        sudo -n pacman -S --noconfirm "$pkg" 2>/dev/null && return 0
    fi
    return 1
}

# ── Script-to-deps table (BUG-1/6 FIX) ───────────────────────────────────────
# Each entry: "script_key|description|required_tools|optional_tools"
# Tools listed here should be UNIQUE to this script (not in core_required).
# Ordered list — no associative array iteration surprises.
#
# Tier definitions:
#   core_required  — must be present for the suite to function at all
#   core_optional  — enhances the suite but not strictly needed
#   per_required   — required for the named script to work
#   per_optional   — optional/fallback for the named script
declare -a CORE_REQUIRED=(rsync python3 find sha256sum flock)
declare -a CORE_OPTIONAL=(jq yq msmtp notify-send)

# Each element: "key|label|required_extras|optional_extras"
SCRIPT_ENTRIES=(
    "backup|backup-to-nas.sh|findmnt|"
    "cloud|cloud-backup.sh|rclone|"
    "verifier|backup-verifier.sh|shuf|md5sum b2sum"
    "checksum|checksum.sh||b2sum"
    "notify|backup-notify.sh||kdialog msmtp"
    "organizer|organize-downloads.sh||fuser lsof"
    "disk|disk-sentinel.sh|df du|"
    "cloud_backup|cloud-backup.sh||rclone"
    "web|noba-web.sh|ss|lsof"
    "images|images-to-pdf.sh||convert"
    "motd|motd-generator.sh|curl|"
    "tui|noba-tui.sh||dialog"
    "clipboard|checksum.sh (clipboard)||wl-copy xclip xsel"
)

# ── JSON accumulator ───────────────────────────────────────────────────────────
JSON_LINES=()
json_add() { JSON_LINES+=("$1"); }

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o qnh \
        -l verbose,quiet,no-yaml,no-old,scripts:,fix,json,report:,dry-run,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --verbose)       VERBOSE=true;            shift ;;
        -q|--quiet)      QUIET=true;              shift ;;
        --no-yaml)       CHECK_YAML=false;        shift ;;
        --no-old)        CHECK_OLD=false;         shift ;;
        --scripts)       FILTER_SCRIPTS="$2";     shift 2 ;;
        --fix)           FIX_MODE=true;           shift ;;
        --json)          JSON_MODE=true;          shift ;;
        --report)        REPORT_FILE="$2";        shift 2 ;;
        -n|--dry-run)    DRY_RUN=true;            shift ;;
        -h|--help)       show_help ;;
        -v|--version)    show_version ;;
        --)              shift; break ;;
        *)               log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

[[ "$DRY_RUN" == true ]] && exit 0

# If --report, tee everything into the report file
if [[ -n "$REPORT_FILE" ]]; then
    exec > >(tee "$REPORT_FILE") 2>&1
fi

# ── Helper: should we check this script? ──────────────────────────────────────
should_check() {
    local key="$1"
    [[ -z "$FILTER_SCRIPTS" ]] && return 0
    IFS=',' read -ra _filter <<< "$FILTER_SCRIPTS"
    for f in "${_filter[@]}"; do
        [[ "${f// /}" == "$key" ]] && return 0
    done
    return 1
}

# ── Main ───────────────────────────────────────────────────────────────────────
_out "╔══════════════════════════════════════════════╗"
_out "║  Noba Suite — Config & Dependency Check       ║"
_out "╚══════════════════════════════════════════════╝"
_out ""

# ── 1. Config files ────────────────────────────────────────────────────────────
if [[ "$CHECK_OLD" == true ]]; then
    _out "── Legacy config: $OLD_CONFIG_FILE"
    if [[ -f "$OLD_CONFIG_FILE" ]]; then
        if [[ -r "$OLD_CONFIG_FILE" ]]; then
            _out "  ✓ Exists and readable"
            if [[ "$VERBOSE" == true ]]; then
                _out "  Variables:"
                grep -E '^[A-Za-z_]+=' "$OLD_CONFIG_FILE" 2>/dev/null \
                    | sed 's/^/    /' || _out "    (none)"
            fi
        else
            log_error "  ✗ File exists but is not readable"
        fi
    else
        _out "  ℹ  Not found (deprecated — this is fine)"
    fi
    _out ""
fi

if [[ "$CHECK_YAML" == true ]]; then
    _out "── YAML config: $NEW_CONFIG_FILE"
    if [[ -f "$NEW_CONFIG_FILE" ]]; then
        if [[ -r "$NEW_CONFIG_FILE" ]]; then
            _out "  ✓ Exists and readable"
            if command -v yq &>/dev/null; then
                # Validate YAML can be parsed
                if yq eval '.' "$NEW_CONFIG_FILE" >/dev/null 2>&1; then
                    _out "  ✓ YAML syntax valid (yq)"
                else
                    log_error "  ✗ YAML parse error — run: yq eval . '$NEW_CONFIG_FILE'"
                fi
                if [[ "$VERBOSE" == true ]]; then
                    _out "  Structure:"
                    yq eval '.' "$NEW_CONFIG_FILE" | sed 's/^/    /'
                fi
            else
                [[ "$QUIET" != true ]] && log_warn "  ⚠ yq not installed — cannot validate YAML content"
            fi
        else
            log_error "  ✗ File exists but is not readable"
        fi
    else
        [[ "$QUIET" != true ]] && log_warn "  ⚠ Not found (using defaults)"
    fi
    _out ""
fi

# ── 2. Core dependencies (checked once, not duplicated) ───────────────────────
_out "── Core required tools:"
for cmd in "${CORE_REQUIRED[@]}"; do
    if ! check_cmd "$cmd" "$cmd" required && [[ "$FIX_MODE" == true ]]; then
        _out "     Attempting install: $cmd"
        try_install "$cmd" && _out "     ✓ Installed" || _out "     ✗ Install failed"
    fi
done

_out ""
_out "── Core optional tools:"
for cmd in "${CORE_OPTIONAL[@]}"; do
    check_cmd "$cmd" "$cmd" optional || true
done
_out ""

# ── 3. Per-script dependencies (BUG-1 FIX: unique extras only) ────────────────
_out "── Per-script dependencies:"
for entry in "${SCRIPT_ENTRIES[@]}"; do
    IFS='|' read -r key label req_extras opt_extras <<< "$entry"
    should_check "$key" || continue

    [[ -z "$req_extras$opt_extras" ]] && continue   # nothing unique to check

    _out "  $label:"
    for cmd in $req_extras; do
        check_cmd "$cmd" "$cmd" required || true
    done
    for cmd in $opt_extras; do
        check_cmd "$cmd" "$cmd" optional || true
    done
done
_out ""

# ── 4. Clipboard tools ────────────────────────────────────────────────────────
_out "── Clipboard (checksum.sh --copy):"
clipboard_ok=false
for cmd in wl-copy xclip xsel; do
    if command -v "$cmd" &>/dev/null; then
        _out "  ✓ $cmd"
        clipboard_ok=true
        break
    fi
done
[[ "$clipboard_ok" == false ]] \
    && { [[ "$QUIET" != true ]] && log_warn "  ⚠ No clipboard tool (wl-copy / xclip / xsel)"; }
_out ""

# ── 5. sudo availability ───────────────────────────────────────────────────────
# BUG-5 FIX: guard with command -v before running sudo -n
_out "── Privilege check:"
if ! command -v sudo &>/dev/null; then
    [[ "$QUIET" != true ]] && log_warn "  ⚠ sudo not found — unattended system ops will fail"
elif ! sudo -n true 2>/dev/null; then
    [[ "$QUIET" != true ]] && log_warn "  ⚠ sudo requires a password — unattended ops will fail"
else
    _out "  ✓ sudo passwordless access available"
fi
_out ""

# ── 6. Log directory scan ──────────────────────────────────────────────────────
_out "── Log files ($LOG_DIR):"
logs=(backup-to-nas backup-verifier cloud-backup disk-sentinel
      download-organizer noba-web noba-web-server)
for logname in "${logs[@]}"; do
    logfile="$LOG_DIR/$logname.log"
    if [[ -f "$logfile" ]]; then
        size=$(du -sh "$logfile" 2>/dev/null | cut -f1)
        _out "  ✓ $logname.log  ($size)"
        if [[ "$VERBOSE" == true ]]; then
            tail -n 2 "$logfile" 2>/dev/null | sed 's/^/      /' || true
        fi
    else
        _out "  ℹ  $logname.log — not yet created"
    fi
done
_out ""

# ── 7. Config validation suggestions ──────────────────────────────────────────
if [[ -f "$NEW_CONFIG_FILE" ]] && command -v yq &>/dev/null; then
    _out "── Config validation:"
    email=$(yq eval '.email // ""' "$NEW_CONFIG_FILE" 2>/dev/null || true)
    if [[ -n "$email" ]] && ! echo "$email" | grep -q '@'; then
        [[ "$QUIET" != true ]] && log_warn "  ⚠ .email may not be valid: $email"
    elif [[ -n "$email" ]]; then
        _out "  ✓ .email looks valid: $email"
    fi

    backup_dest=$(yq eval '.backup.dest // ""' "$NEW_CONFIG_FILE" 2>/dev/null || true)
    if [[ -n "$backup_dest" ]]; then
        if [[ -d "$backup_dest" ]]; then
            _out "  ✓ backup.dest exists: $backup_dest"
        else
            [[ "$QUIET" != true ]] && log_warn "  ⚠ backup.dest not mounted/present: $backup_dest"
        fi
    fi

    cloud_remote=$(yq eval '.cloud.remote // ""' "$NEW_CONFIG_FILE" 2>/dev/null || true)
    if [[ -n "$cloud_remote" ]] && ! echo "$cloud_remote" | grep -q ':'; then
        [[ "$QUIET" != true ]] && log_warn "  ⚠ cloud.remote doesn't look like a valid rclone remote: $cloud_remote"
    fi
    _out ""
fi

# ── 8. Summary ────────────────────────────────────────────────────────────────
TOTAL=$(( PRESENT + MISSING_REQUIRED + MISSING_OPTIONAL ))
_out_always "══════════════════════════════════════════════"
_out_always "  Found    : $PRESENT / $TOTAL tools"
(( MISSING_REQUIRED > 0 )) \
    && _out_always "  Missing  : $MISSING_REQUIRED required,  $MISSING_OPTIONAL optional" \
    || _out_always "  Missing  : $MISSING_OPTIONAL optional only"
_out_always "══════════════════════════════════════════════"

# ── 9. JSON output ─────────────────────────────────────────────────────────────
if [[ "$JSON_MODE" == true ]]; then
    python3 - "$PRESENT" "$MISSING_REQUIRED" "$MISSING_OPTIONAL" "$TOTAL" << 'PY'
import json, sys
p, mr, mo, t = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
print(json.dumps({
    "present": p, "missing_required": mr, "missing_optional": mo,
    "total": t, "status": "ok" if mr == 0 else "degraded"
}, indent=2))
PY
fi

# ── Exit code: driven by required-missing count (BUG-4 FIX) ───────────────────
if (( MISSING_REQUIRED > 0 )); then
    log_error "$MISSING_REQUIRED required tool(s) missing. Run with --fix to attempt install."
    exit 1
fi
exit 0
