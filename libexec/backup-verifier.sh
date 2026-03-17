#!/bin/bash
# backup-verifier.sh – Verify backup integrity by sampling random files
# Version: 1.0.1
#
# New in 1.0.0:
#   --snapshot SNAP    Verify a specific snapshot instead of the latest
#   --all              Verify the N most-recent snapshots, not just the latest
#   --min-size BYTES   Skip files smaller than BYTES (avoids checksumming 0-byte sentinels)
#   --json             Write a machine-readable JSON summary to stdout
#   --fail-fast        Abort as soon as one file fails (useful in CI)
#   Exit codes: 0=all OK  1=warnings (originals differ)  2=read failures  3=setup error
#
# Fixed in 1.0.1:
#   Version mismatch   Header said 1.0.0; show_version/shim said 3.0.0.
#                      Centralised into readonly VERSION="1.0.1".
#   set -e bomb ×3     (( expr )) && var=val aborts under set -e when expr is
#                      false (arithmetic returns exit 1).  All three occurrences
#                      rewritten as if (( expr )); then … fi.
#   original_for bug   When rel contained no '/' (file at snapshot root),
#                      rest="${rel#*/}" equalled the whole of rel, producing a
#                      doubled filename in the output path.  Now handled
#                      explicitly.
#   JSON_FILE dead var Assigned but never written to (JSON went to stdout via
#                      python3).  Removed.  JSON output now uses pure-bash
#                      printf — no python3 dependency.
#   ALL_COUNT config   ALL_COUNT was CLI-only; added to the config-load block
#                      alongside every other tunable.

set -euo pipefail

# ── Version ────────────────────────────────────────────────────────────────────
readonly VERSION="1.0.1"

# ── Test harness shims ────────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help"    || "${1:-}" == "-h" ]]; then
    echo "Usage: backup-verifier.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-verifier.sh version $VERSION"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
NUM_FILES=5
EMAIL="${EMAIL:-}"
CHECKSUM_CMD="sha256sum"
DRY_RUN=false
QUIET=false
export VERBOSE=false
COMPARE_ORIGINAL=false
SEND_EMAIL=false
SPECIFIC_SNAP=""
VERIFY_ALL=false
ALL_COUNT=3
MIN_SIZE=0
JSON_OUTPUT=false
FAIL_FAST=false

# ── Global sample buffer (written by random_sample, read by verify_snapshot) ──
SELECTED=()

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    BACKUP_ROOT="$(get_config ".backup_verifier.dest"          "$BACKUP_ROOT")"
    NUM_FILES="$(get_config ".backup_verifier.num_files"        "$NUM_FILES")"
    EMAIL="$(get_config ".email"                                "$EMAIL")"
    CHECKSUM_CMD="$(get_config ".backup_verifier.checksum_cmd"  "$CHECKSUM_CMD")"
    MIN_SIZE="$(get_config ".backup_verifier.min_size"          "$MIN_SIZE")"
    ALL_COUNT="$(get_config ".backup_verifier.all_count"        "$ALL_COUNT")"
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
show_version() { echo "backup-verifier.sh version $VERSION"; exit 0; }

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
      --help             Show this message
      --version          Show version information

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
    stat -c %s "$1" 2>/dev/null   \
        || stat -f %z "$1" 2>/dev/null \
        || wc -c < "$1" 2>/dev/null | tr -d ' ' \
        || echo 0
}

# ── Duplicate-free random sample (Fisher-Yates partial shuffle) ───────────────
# Writes into global SELECTED[].
# Usage: random_sample N array_name
random_sample() {
    local n="$1"
    local -n _src="$2"
    local total="${#_src[@]}"

    SELECTED=()

    if (( total <= n )); then
        SELECTED=("${_src[@]}")
        return
    fi

    local -a indices=()
    local i
    for (( i=0; i<total; i++ )); do indices+=("$i"); done

    for (( i=0; i<n; i++ )); do
        local j
        if command -v shuf &>/dev/null; then
            j=$(shuf -i "$i-$(( total - 1 ))" -n 1)
        else
            j=$(( i + RANDOM % (total - i) ))
        fi
        local tmp="${indices[$i]}"
        indices[$i]="${indices[$j]}"
        indices[$j]="$tmp"
        SELECTED+=("${_src[${indices[$i]}]}")
    done
}

# ── Reconstruct original source path from a backup-relative path ──────────────
# Mirrors backup-to-nas destpath_for() logic:
#   .config → stored as config/   (.ssh → ssh/, etc.)
#   Documents → stored as Documents/  (no dot to re-add)
#
# Edge cases handled:
#   rel with no '/'  – file sitting directly at the snapshot root
#   dot-prefixed dir – $HOME/.$top reconstructed when the dir exists there
original_for() {
    local rel="$1"

    # File at snapshot root (no directory component)
    if [[ "$rel" != */* ]]; then
        echo "$HOME/$rel"
        return
    fi

    local top="${rel%%/*}"    # first directory component, e.g. "config"
    local rest="${rel#*/}"    # remainder,                  e.g. "nvim/init.lua"

    # Re-add leading dot when the original source had one
    local orig_top
    if [[ -d "$HOME/.$top" ]]; then
        orig_top=".$top"
    else
        orig_top="$top"
    fi

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
# Returns: 0=ok  1=warnings (mismatch)  2=failures (unreadable)
verify_snapshot() {
    local snap="$1"
    local report="$2"

    if [[ ! -d "$snap" ]]; then
        log_error "Snapshot directory does not exist: $snap"
        return 2
    fi

    log_info "Verifying snapshot: $(basename "$snap")"

    local -a FILES=()
    while IFS= read -r -d '' f; do
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

    random_sample "$NUM_FILES" FILES

    local failed=0 warnings=0

    {
        echo ""
        echo "Snapshot: $(basename "$snap")"
        echo "Files sampled: ${#SELECTED[@]} of $total"
        echo "──────────────────────────────────────────"
    } >> "$report"

    local file
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
        if backup_hash=$("$CHECKSUM_CMD" "$file" 2>/dev/null | cut -d' ' -f1) \
                && [[ -n "$backup_hash" ]]; then

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
        -b|--backup-dir)        BACKUP_ROOT="$2";      shift 2 ;;
        -n|--num-files)         NUM_FILES="$2";        shift 2 ;;
        -c|--compare-original)  COMPARE_ORIGINAL=true; shift   ;;
           --snapshot)          SPECIFIC_SNAP="$2";    shift 2 ;;
           --all)               VERIFY_ALL=true;       shift   ;;
           --all-count)         ALL_COUNT="$2";        shift 2 ;;
           --min-size)          MIN_SIZE="$2";         shift 2 ;;
           --checksum-cmd)      CHECKSUM_CMD="$2";     shift 2 ;;
           --send-email)        SEND_EMAIL=true;       shift   ;;
           --json)              JSON_OUTPUT=true;      shift   ;;
           --fail-fast)         FAIL_FAST=true;        shift   ;;
        -v|--verbose)           export VERBOSE=true;   shift   ;;
        -q|--quiet)             QUIET=true;            shift   ;;
        -D|--dry-run)           DRY_RUN=true;          shift   ;;
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
    if [[ -d "$SPECIFIC_SNAP" ]]; then
        SNAPSHOTS=("$SPECIFIC_SNAP")
    elif [[ -d "$BACKUP_ROOT/$SPECIFIC_SNAP" ]]; then
        SNAPSHOTS=("$BACKUP_ROOT/$SPECIFIC_SNAP")
    else
        log_error "Specified snapshot not found: $SPECIFIC_SNAP"
        exit 3
    fi
else
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
        local_start=$(( ${#SNAPSHOTS[@]} - ALL_COUNT ))
        # Fixed: was (( local_start < 0 )) && local_start=0
        # Under set -e, a false (( )) exits the script; use if instead.
        if (( local_start < 0 )); then local_start=0; fi
        SNAPSHOTS=("${SNAPSHOTS[@]:$local_start}")
    else
        SNAPSHOTS=("${SNAPSHOTS[-1]}")
    fi
fi

log_info "Snapshots to verify: ${#SNAPSHOTS[@]}"
[[ "$VERBOSE" == true ]] && printf '  %s\n' "${SNAPSHOTS[@]}"

# ── Setup report ───────────────────────────────────────────────────────────────
TEMP_DIR=$(mktemp -d "/tmp/noba-verify.XXXXXX")
REPORT_FILE="$TEMP_DIR/report.txt"

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

# ── Run verification ───────────────────────────────────────────────────────────
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
        # Fixed: was (( OVERALL_EXIT < 1 )) && OVERALL_EXIT=1  — set -e bomb
        1) (( WARNED++  )) || true
           if (( OVERALL_EXIT < 1 )); then OVERALL_EXIT=1; fi ;;
        # Fixed: was (( OVERALL_EXIT < 2 )) && OVERALL_EXIT=2  — set -e bomb
        2) (( ERRORED++ )) || true
           if (( OVERALL_EXIT < 2 )); then OVERALL_EXIT=2; fi ;;
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

if   (( ERRORED > 0 )); then log_error   "Verification: $ERRORED snapshot(s) had unreadable files."
elif (( WARNED  > 0 )); then log_warn    "Verification: $WARNED snapshot(s) had files differing from originals."
else                         log_success "All $TOTAL_SNAPS snapshot(s) verified — no issues found."
fi

# ── Optional JSON output (pure bash — no python3 dependency) ──────────────────
if [[ "$JSON_OUTPUT" == true ]]; then
    # Determine status string without (( )) && under set -e
    local_status="ok"
    if   (( ERRORED > 0 )); then local_status="error"
    elif (( WARNED  > 0 )); then local_status="warning"
    fi

    printf '{\n'
    printf '  "timestamp": "%s",\n'       "$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
    printf '  "snapshots_checked": %d,\n' "$TOTAL_SNAPS"
    printf '  "passed": %d,\n'            "$PASSED"
    printf '  "warnings": %d,\n'          "$WARNED"
    printf '  "errors": %d,\n'            "$ERRORED"
    printf '  "exit_code": %d,\n'         "$OVERALL_EXIT"
    printf '  "status": "%s"\n'           "$local_status"
    printf '}\n'
fi

# ── Display report ─────────────────────────────────────────────────────────────
if [[ "$QUIET" != true ]]; then
    echo ""
    cat "$REPORT_FILE"
fi

# ── Email ──────────────────────────────────────────────────────────────────────
if [[ "$SEND_EMAIL" == true ]]; then
    status_word="OK"
    (( WARNED  > 0 )) && status_word="WARNINGS" || true
    (( ERRORED > 0 )) && status_word="FAILURES" || true
    send_report "Backup Verification [$status_word] – $(hostname) – $(date '+%Y-%m-%d')" \
                "$REPORT_FILE"
fi

exit "$OVERALL_EXIT"
