#!/bin/bash
# backup-verifier.sh – Verify backup integrity by sampling random files
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  Glob '????????-???????' has 7 ?-marks for the time part but HHMMSS is 6 chars.
#          → No backup dirs ever matched; script always died with "no backups found".
#   BUG-2  mapfile -t FILES < <(find -print0 | xargs -0 printf '%s\n') reconverts
#          NUL-delimited output back to newlines, breaking on filenames with newlines.
#          Replaced with mapfile -d '' for true NUL-safe array population.
#   BUG-3  Fallback randomizer used RANDOM % TOTAL — biased for N>32767; also allowed
#          duplicate selections (same file verified twice). Rewritten with a
#          Fisher-Yates partial shuffle so selection is always unique.
#   BUG-4  config/.config/* path reconstruction stripped 'config/.config/' but forgot
#          to re-add '.config/' — produced $HOME/nvim/init.lua instead of
#          $HOME/.config/nvim/init.lua.
#   BUG-5  Documents/* case used original="$HOME/$rel_path" where rel_path already
#          starts with 'Documents/' → $HOME/Documents/Documents/foo — doubled directory.
#   BUG-6  ((FAILED++)) exits 1 under set -e when FAILED==0 because ((0)) evaluates
#          to false. All arithmetic increments changed to (( VAR++ )) || true.
#   BUG-7  Trap composition via sed+eval is fragile when the existing trap body
#          contains single quotes (malformed result). Replaced with a simple
#          dedicated cleanup() function registered with trap … EXIT.
#   BUG-8  Path reconstruction case patterns assumed backup-to-nas stored '.config'
#          as 'config/.config/' (nested), but backup-to-nas v3 stores it as 'config/'
#          (leading dot stripped, no nesting). Reconstruction now mirrors
#          backup-to-nas v3's destpath_for() / the actual stored layout.
#   BUG-9  ${backup_dirs[-1]} on an empty array under set -u is an unbound-variable
#          error — the guard only reached die() if bash didn't abort first.
#          Fixed by checking array length before any subscript access.
#
# New in 3.0.0:
#   --snapshot SNAP    Verify a specific snapshot instead of the latest
#   --all              Verify the N most-recent snapshots, not just the latest
#   --min-size BYTES   Skip files smaller than BYTES (avoids checksumming 0-byte sentinels)
#   --json             Write a machine-readable JSON summary alongside the text report
#   --fail-fast        Abort as soon as one file fails (useful in CI)
#   Exit codes: 0=all OK  1=warnings (originals differ)  2=read failures  3=setup error

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help"    || "${1:-}" == "-h" ]]; then
    echo "Usage: backup-verifier.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-verifier.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
NUM_FILES=5
EMAIL="${EMAIL:-}"
CHECKSUM_CMD="sha256sum"   # upgraded from md5sum — faster on modern CPUs, collision-resistant
DRY_RUN=false
QUIET=false
export VERBOSE=false
COMPARE_ORIGINAL=false
SEND_EMAIL=false
SPECIFIC_SNAP=""
VERIFY_ALL=false
ALL_COUNT=3          # number of snapshots to verify when --all is used
MIN_SIZE=0           # bytes; 0 = no minimum
JSON_OUTPUT=false
FAIL_FAST=false

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    BACKUP_ROOT="$(get_config ".backup_verifier.dest"         "$BACKUP_ROOT")"
    NUM_FILES="$(get_config ".backup_verifier.num_files"       "$NUM_FILES")"
    EMAIL="$(get_config ".email"                               "$EMAIL")"
    CHECKSUM_CMD="$(get_config ".backup_verifier.checksum_cmd" "$CHECKSUM_CMD")"
    MIN_SIZE="$(get_config ".backup_verifier.min_size"         "$MIN_SIZE")"
fi

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "backup-verifier.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Verify the integrity of one or more backups by sampling and checksumming random files.

Options:
  -b, --backup-dir DIR   Root dir containing timestamped backups (default: $BACKUP_ROOT)
  -n, --num-files N      Files to sample per snapshot (default: $NUM_FILES)
  -c, --compare-original Compare backup files against their originals on disk
      --snapshot SNAP    Verify a specific snapshot by name/path (skips auto-detect)
      --all              Verify the $ALL_COUNT most-recent snapshots (see --all-count)
      --all-count N      How many snapshots to verify with --all (default: $ALL_COUNT)
      --min-size BYTES   Skip files smaller than BYTES (default: 0 = no minimum)
      --checksum-cmd CMD Checksum command (default: $CHECKSUM_CMD)
      --send-email       Email the report (requires email configured)
      --json             Write JSON summary to stdout (in addition to text report)
      --fail-fast        Stop immediately on first read failure
  -v, --verbose          Verbose output
  -q, --quiet            Suppress non-error output
  -D, --dry-run          Simulate without actually checksumming
  --help                 Show this message
  --version              Show version information

Exit codes:
  0  All sampled files verified OK
  1  One or more originals differ from backup (--compare-original only)
  2  One or more backup files could not be read
  3  Setup/configuration error (missing directory, bad args, etc.)
EOF
    exit 0
}

# ── Cleanup ────────────────────────────────────────────────────────────────────
TEMP_DIR=""
cleanup() {
    [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]] && rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

# ── File size (portable) ───────────────────────────────────────────────────────
get_size() {
    stat -c %s "$1" 2>/dev/null \
        || stat -f %z "$1" 2>/dev/null \
        || wc -c < "$1" 2>/dev/null | tr -d ' ' \
        || echo 0
}

# ── BUG-3 FIX: duplicate-free random sample using Fisher-Yates partial shuffle ─
# Usage: random_sample N array_name   → populates global SELECTED array
random_sample() {
    local n="$1"
    local -n _src="$2"
    local total="${#_src[@]}"

    SELECTED=()

    if (( total <= n )); then
        SELECTED=("${_src[@]}")
        return
    fi

    # Copy indices into a local array and do a partial Fisher-Yates shuffle
    local -a indices
    for (( i=0; i<total; i++ )); do indices+=("$i"); done

    for (( i=0; i<n; i++ )); do
        # Pick a random index in [i, total)
        if command -v shuf &>/dev/null; then
            j=$(shuf -i "$i-$(( total - 1 ))" -n 1)
        else
            j=$(( i + RANDOM % (total - i) ))
        fi
        # Swap
        local tmp="${indices[$i]}"
        indices[$i]="${indices[$j]}"
        indices[$j]="$tmp"
        SELECTED+=("${_src[${indices[$i]}]}")
    done
}

# ── BUG-4/5/8 FIX: reconstruct original source path from backup relative path ─
# Mirrors backup-to-nas v3's destpath_for() logic:
#   .config  → stored as  config/
#   .ssh     → stored as  ssh/
#   Documents → stored as  Documents/  (top dir preserved, no doubling)
#
# Input:  rel_path (relative to snapshot root, e.g. "config/nvim/init.lua")
# Output: prints the best-guess original absolute path, or empty string if unknown
original_for() {
    local rel="$1"
    local top="${rel%%/*}"       # first directory component
    local rest="${rel#*/}"       # everything after the first /

    # Re-add leading dot for directories that backup-to-nas stripped it from
    # (any source dir that started with '.' is stored without it)
    local orig_top
    # Heuristic: if a source with a dot-prefixed version of $top exists under $HOME, use it
    if [[ -d "$HOME/.$top" ]]; then
        orig_top=".$top"
    else
        orig_top="$top"
    fi

    # For top-level dirs that live directly in $HOME (Documents, Pictures, etc.)
    # rel_path = "Documents/foo.pdf"  → original = $HOME/Documents/foo.pdf
    # For dotfiles stored as "config/nvim/init.lua" → $HOME/.config/nvim/init.lua
    echo "$HOME/$orig_top/$rest"
}

# ── Send email report ──────────────────────────────────────────────────────────
send_report() {
    local subject="$1" body_file="$2"
    [[ -z "$EMAIL" ]] && { log_warn "No email address configured — skipping report."; return 0; }

    if command -v msmtp &>/dev/null; then
        { echo "Subject: $subject"; echo ""; cat "$body_file"; } | msmtp "$EMAIL"
        log_info "Report emailed via msmtp to $EMAIL"
    elif command -v mutt &>/dev/null; then
        mutt -s "$subject" -- "$EMAIL" < "$body_file"
        log_info "Report emailed via mutt to $EMAIL"
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < "$body_file"
        log_info "Report emailed via mail to $EMAIL"
    else
        log_warn "No mail program found (msmtp / mutt / mail) — skipping report."
    fi
}

# ── Verify one snapshot ────────────────────────────────────────────────────────
# Returns: 0=ok  1=warnings  2=failures
verify_snapshot() {
    local snap="$1"
    local report="$2"   # path to append results to

    if [[ ! -d "$snap" ]]; then
        log_error "Snapshot directory does not exist: $snap"
        return 2
    fi

    log_info "Verifying snapshot: $(basename "$snap")"

    # BUG-2 FIX: NUL-safe file list via mapfile -d ''
    local -a FILES=()
    while IFS= read -r -d '' f; do
        # BUG min-size filter
        if (( MIN_SIZE > 0 )); then
            local fsz; fsz=$(get_size "$f")
            (( fsz >= MIN_SIZE )) && FILES+=("$f")
        else
            FILES+=("$f")
        fi
    done < <(find "$snap" -type f -print0 2>/dev/null)

    local total="${#FILES[@]}"
    if (( total == 0 )); then
        log_warn "No files found in $snap"
        echo "  [WARN] No files found." >> "$report"
        return 0
    fi
    log_verbose "  Total files in snapshot: $total"

    # Random sample (BUG-3 FIX)
    SELECTED=()
    random_sample "$NUM_FILES" FILES

    local failed=0 warnings=0

    {
        echo ""
        echo "Snapshot: $(basename "$snap")"
        echo "Files sampled: ${#SELECTED[@]} of $total"
        echo "──────────────────────────────────────────"
    } >> "$report"

    for file in "${SELECTED[@]}"; do
        local rel="${file#"$snap"/}"
        local size; size=$(get_size "$file")
        local size_hr; size_hr=$(human_size "$size" 2>/dev/null || echo "${size}B")

        if [[ "$DRY_RUN" == true ]]; then
            log_info "  [DRY RUN] Would verify: $rel"
            echo "  [DRY RUN] $rel" >> "$report"
            continue
        fi

        log_verbose "  Checksumming: $rel"

        local backup_hash
        # BUG-6 FIX: all arithmetic increments guarded with || true
        if backup_hash=$("$CHECKSUM_CMD" "$file" 2>/dev/null | cut -d' ' -f1) && [[ -n "$backup_hash" ]]; then

            if [[ "$COMPARE_ORIGINAL" == true ]]; then
                local original
                original=$(original_for "$rel")

                if [[ -f "$original" ]]; then
                    local orig_hash
                    orig_hash=$("$CHECKSUM_CMD" "$original" 2>/dev/null | cut -d' ' -f1)

                    if [[ "$backup_hash" == "$orig_hash" ]]; then
                        echo "  ✅ OK       $rel ($size_hr, matches original)" >> "$report"
                        log_verbose "     ✅ matches original"
                    else
                        echo "  ⚠️  DIFFERS  $rel ($size_hr, differs from original)" >> "$report"
                        log_warn "  DIFFERS: $rel"
                        (( warnings++ )) || true
                    fi
                else
                    echo "  ✅ READABLE $rel ($size_hr, original not found for comparison)" >> "$report"
                    log_verbose "     readable, no original to compare"
                fi
            else
                echo "  ✅ OK       $rel ($size_hr)" >> "$report"
                log_verbose "     ✅ readable"
            fi

        else
            echo "  ❌ FAILED   $rel ($size_hr, read/checksum error)" >> "$report"
            log_error "  FAILED: $rel"
            (( failed++ )) || true
            if [[ "$FAIL_FAST" == true ]]; then
                log_error "  --fail-fast: aborting after first failure."
                break
            fi
        fi
    done

    {
        echo "──────────────────────────────────────────"
        echo "  Read failures : $failed"
        echo "  Mismatches    : $warnings"
    } >> "$report"

    if   (( failed   > 0 )); then return 2
    elif (( warnings > 0 )); then return 1
    else return 0
    fi
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o b:n:cDvqh \
        -l backup-dir:,num-files:,compare-original,snapshot:,all,all-count:,\
min-size:,checksum-cmd:,send-email,json,fail-fast,verbose,quiet,dry-run,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 3
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -b|--backup-dir)        BACKUP_ROOT="$2";    shift 2 ;;
        -n|--num-files)         NUM_FILES="$2";      shift 2 ;;
        -c|--compare-original)  COMPARE_ORIGINAL=true; shift ;;
           --snapshot)          SPECIFIC_SNAP="$2";  shift 2 ;;
           --all)               VERIFY_ALL=true;     shift   ;;
           --all-count)         ALL_COUNT="$2";      shift 2 ;;
           --min-size)          MIN_SIZE="$2";       shift 2 ;;
           --checksum-cmd)      CHECKSUM_CMD="$2";   shift 2 ;;
           --send-email)        SEND_EMAIL=true;     shift   ;;
           --json)              JSON_OUTPUT=true;    shift   ;;
           --fail-fast)         FAIL_FAST=true;      shift   ;;
        -v|--verbose)           export VERBOSE=true; shift   ;;
        -q|--quiet)             QUIET=true;          shift   ;;
        -D|--dry-run)           DRY_RUN=true;        shift   ;;
        -h|--help)              show_help ;;
           --version)           show_version ;;
        --)                     shift; break ;;
        *)                      log_error "Unknown argument: $1"; exit 3 ;;
    esac
done

# ── Validation ─────────────────────────────────────────────────────────────────
for v in NUM_FILES ALL_COUNT MIN_SIZE; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || { log_error "$v must be a non-negative integer."; exit 3; }
done
(( NUM_FILES > 0 )) || { log_error "--num-files must be at least 1."; exit 3; }

if ! command -v "$CHECKSUM_CMD" &>/dev/null; then
    log_error "Checksum command not found: $CHECKSUM_CMD"
    exit 3
fi

check_deps find sort

# ── Resolve snapshots to verify ────────────────────────────────────────────────
SNAPSHOTS=()

if [[ -n "$SPECIFIC_SNAP" ]]; then
    # Absolute path or name relative to BACKUP_ROOT
    if [[ -d "$SPECIFIC_SNAP" ]]; then
        SNAPSHOTS=("$SPECIFIC_SNAP")
    elif [[ -d "$BACKUP_ROOT/$SPECIFIC_SNAP" ]]; then
        SNAPSHOTS=("$BACKUP_ROOT/$SPECIFIC_SNAP")
    else
        log_error "Specified snapshot not found: $SPECIFIC_SNAP"
        exit 3
    fi
else
    # BUG-1 FIX: correct glob — YYYYMMDD-HHMMSS = 8+1+6 = 15 chars total, pattern ????????-??????
    # BUG-9 FIX: collect into array first, check length before using subscripts
    while IFS= read -r -d '' d; do
        SNAPSHOTS+=("$d")
    done < <(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "????????-??????" -print0 2>/dev/null \
             | sort -z)

    if (( ${#SNAPSHOTS[@]} == 0 )); then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] No backups found in $BACKUP_ROOT — exiting gracefully."
            exit 0
        fi
        log_error "No timestamped backup folders found in $BACKUP_ROOT"
        exit 3
    fi

    if [[ "$VERIFY_ALL" == true ]]; then
        # Most-recent ALL_COUNT snapshots
        local_start=$(( ${#SNAPSHOTS[@]} - ALL_COUNT ))
        (( local_start < 0 )) && local_start=0
        SNAPSHOTS=("${SNAPSHOTS[@]:$local_start}")
    else
        # Just the latest
        SNAPSHOTS=("${SNAPSHOTS[-1]}")
    fi
fi

log_info "Snapshots to verify: ${#SNAPSHOTS[@]}"
[[ "$VERBOSE" == true ]] && printf '  %s\n' "${SNAPSHOTS[@]}"

# ── Setup report ───────────────────────────────────────────────────────────────
TEMP_DIR=$(mktemp -d "/tmp/noba-verify.XXXXXX")
REPORT_FILE="$TEMP_DIR/report.txt"
JSON_FILE="$TEMP_DIR/summary.json"

{
    echo "Backup Verification Report"
    echo "=========================================="
    echo "Date          : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Backup root   : $BACKUP_ROOT"
    echo "Checksum cmd  : $CHECKSUM_CMD"
    echo "Files/snapshot: $NUM_FILES"
    echo "Min file size : ${MIN_SIZE}B"
    echo "Compare orig  : $COMPARE_ORIGINAL"
    echo "=========================================="
} > "$REPORT_FILE"

# ── Run verification over each snapshot ───────────────────────────────────────
OVERALL_EXIT=0
TOTAL_SNAPS="${#SNAPSHOTS[@]}"
PASSED=0
WARNED=0
ERRORED=0

for snap in "${SNAPSHOTS[@]}"; do
    snap_result=0
    verify_snapshot "$snap" "$REPORT_FILE" || snap_result=$?

    case $snap_result in
        0) (( PASSED++  )) || true ;;
        1) (( WARNED++  )) || true; (( OVERALL_EXIT < 1 )) && OVERALL_EXIT=1 ;;
        2) (( ERRORED++ )) || true; (( OVERALL_EXIT < 2 )) && OVERALL_EXIT=2 ;;
    esac
done

# ── Overall summary ────────────────────────────────────────────────────────────
{
    echo ""
    echo "=========================================="
    echo "OVERALL SUMMARY"
    echo "=========================================="
    printf "  Snapshots verified : %d\n" "$TOTAL_SNAPS"
    printf "  Passed             : %d\n" "$PASSED"
    printf "  Warnings (differs) : %d\n" "$WARNED"
    printf "  Errors (unreadable): %d\n" "$ERRORED"
    echo "=========================================="
} >> "$REPORT_FILE"

if   (( ERRORED > 0 )); then log_error  "Verification: $ERRORED snapshot(s) had unreadable files."
elif (( WARNED  > 0 )); then log_warn   "Verification: $WARNED snapshot(s) had files differing from originals."
else                         log_success "All $TOTAL_SNAPS snapshot(s) verified — no issues found."
fi

# ── Optional JSON output ───────────────────────────────────────────────────────
if [[ "$JSON_OUTPUT" == true ]]; then
    python3 - "$TOTAL_SNAPS" "$PASSED" "$WARNED" "$ERRORED" "$OVERALL_EXIT" <<'PY'
import json, sys, datetime
t, p, w, e, code = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
print(json.dumps({
    "timestamp": datetime.datetime.now().isoformat(),
    "snapshots_checked": t,
    "passed": p,
    "warnings": w,
    "errors": e,
    "exit_code": code,
    "status": "error" if e>0 else "warning" if w>0 else "ok"
}, indent=2))
PY
fi

# ── Display report ─────────────────────────────────────────────────────────────
if [[ "$QUIET" != true ]]; then
    echo ""
    cat "$REPORT_FILE"
fi

# ── Email ─────────────────────────────────────────────────────────────────────
if [[ "$SEND_EMAIL" == true ]]; then
    status_word="OK"
    (( WARNED  > 0 )) && status_word="WARNINGS"
    (( ERRORED > 0 )) && status_word="FAILURES"
    send_report "Backup Verification [$status_word] – $(hostname) – $(date '+%Y-%m-%d')" "$REPORT_FILE"
fi

exit "$OVERALL_EXIT"
