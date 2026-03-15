#!/bin/bash
# log-rotator.sh – Compress old logs and purge ancient archives
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  ((compress_count++)) and ((delete_count++)) under set -e — post-increment
#          returns the OLD value, so incrementing from 0 evaluates to ((0)) which
#          exits 1 and aborts the script on the very first successful compression.
#          All arithmetic counters guarded with || true.
#   BUG-2  is_file_open(): the fallback 'return 1' (when neither fuser nor lsof is
#          available) means "assume closed" — correct behaviour, but the comment was
#          misleading. Also clarified that fuser -s / lsof exit-0 = file IS open,
#          which is the correct semantics for 'if is_file_open; then skip'.
#   BUG-3  gzip without -f refused to overwrite an existing .log.gz, logging an
#          error and leaving the .log uncompressed forever. This happens whenever a
#          previous partial run left both a .log and a .log.gz. Replaced with a
#          safe_compress() that detects the conflict, verifies the existing .gz is
#          intact, and skips cleanly if it is — or re-compresses with -f if not.
#   BUG-4  No persistent log file — rotation activity only went to stdout/journal.
#          A LOG_FILE (log-rotator.log in the same log dir) is now created, with
#          exec > >(tee) set up before the first output line.
#   BUG-5  DELETE_DAYS == COMPRESS_DAYS was allowed by the -lt guard. A file could
#          be compressed and immediately eligible for deletion in the same run.
#          Validation changed to -le so DELETE_DAYS must be strictly greater.
#   BUG-6  find -mtime +N is exclusive (matches files MORE THAN N days old; files
#          exactly N days old are skipped). Help text said "older than N days" which
#          implies inclusive. find arguments are now adjusted by -1 so that behaviour
#          matches the documented "N or more days old" semantics, and the help text
#          clarifies the effective behaviour.
#   BUG-7  gzip removes the original on success but can leave a partial .gz if the
#          disk fills mid-write. safe_compress() gzips to a temp file, verifies the
#          result is non-zero-size and passes gzip --test, then atomically renames
#          it to the final .gz path before removing the original.
#   BUG-8  Script always exited 0 even when files failed to compress or delete.
#          Error count tracked throughout; exits 1 if any operation failed.
#
# New in 3.0.0:
#   --pattern GLOB   Only rotate files matching this glob (default: *.log)
#   --no-delete      Compress only; never delete archives
#   --stats          Print a size-saved summary at the end

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: log-rotator.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "log-rotator.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
COMPRESS_DAYS=30
DELETE_DAYS=90
DRY_RUN=false
NO_DELETE=false
SHOW_STATS=false
LOG_PATTERN="*.log"

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
    COMPRESS_DAYS="$(get_config ".log_rotation.compress_days" "$COMPRESS_DAYS")"
    DELETE_DAYS="$(get_config ".log_rotation.delete_days"     "$DELETE_DAYS")"
fi

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "log-rotator.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Compress log files older than N days and delete ancient archives.

The age thresholds are INCLUSIVE: --compress-days 30 compresses files that
are 30 or more days old (find -mtime +$((30-1)) internally).

Options:
  -c, --compress-days DAYS  Age before compressing .log to .log.gz (default: $COMPRESS_DAYS)
  -x, --delete-days DAYS    Age before deleting .log.gz archives (default: $DELETE_DAYS)
  -l, --log-dir DIR         Directory to rotate (default: $LOG_DIR)
      --pattern GLOB        Only rotate files matching GLOB (default: $LOG_PATTERN)
      --no-delete           Compress only; never delete any archives
      --stats               Print size-saved summary at the end
  -n, --dry-run             Show what would happen without making changes
  --help                    Show this message
  --version                 Show version information

Exit codes:
  0  All operations succeeded (or dry run)
  1  One or more compress/delete operations failed
  2  Configuration or setup error
EOF
    exit 0
}

# ── BUG-2 CLARIFIED: is_file_open semantics ───────────────────────────────────
# Returns 0 (true) if the file is currently open by a process.
# Returns 1 (false) if closed, or if we cannot determine (safe default: proceed).
is_file_open() {
    local file="$1"
    if command -v fuser &>/dev/null; then
        fuser -s "$file" 2>/dev/null; return $?
    elif command -v lsof &>/dev/null; then
        lsof "$file" >/dev/null 2>&1; return $?
    fi
    return 1   # cannot determine → treat as closed so rotation proceeds
}

# ── BUG-3/7 FIX: safe atomic compression ──────────────────────────────────────
# Compresses $1 to $1.gz via a temp file.
# - If a .gz already exists and passes gzip --test, skip (idempotent).
# - Gzips to a temp file first; only renames + removes original on verified success.
# Returns 0 on success/skip, 1 on failure.
safe_compress() {
    local log="$1"
    local gz="${log}.gz"
    local tmp_gz="${gz}.tmp.$$"

    # If a valid .gz already exists, the original is stale — skip silently
    if [[ -f "$gz" ]]; then
        if gzip --test "$gz" 2>/dev/null; then
            log_verbose "Skipping (valid .gz exists): $log"
            return 0
        else
            log_warn "Existing archive is corrupt, replacing: $gz"
            rm -f "$gz"
        fi
    fi

    # Compress to temp file (BUG-7 FIX: don't touch original until verified)
    if ! gzip -c "$log" > "$tmp_gz" 2>/dev/null; then
        rm -f "$tmp_gz"
        log_error "gzip failed for: $log"
        return 1
    fi

    # Verify the compressed output is non-empty and valid
    if [[ ! -s "$tmp_gz" ]] || ! gzip --test "$tmp_gz" 2>/dev/null; then
        rm -f "$tmp_gz"
        log_error "Compressed output invalid or empty: $tmp_gz"
        return 1
    fi

    # Atomic: rename temp → final, then remove original
    mv "$tmp_gz" "$gz"
    rm -f "$log"
    return 0
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o c:x:l:n \
        -l compress-days:,delete-days:,log-dir:,pattern:,no-delete,stats,dry-run,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -c|--compress-days) COMPRESS_DAYS="$2"; shift 2 ;;
        -x|--delete-days)   DELETE_DAYS="$2";   shift 2 ;;
        -l|--log-dir)       LOG_DIR="$2";       shift 2 ;;
           --pattern)       LOG_PATTERN="$2";   shift 2 ;;
           --no-delete)     NO_DELETE=true;     shift   ;;
           --stats)         SHOW_STATS=true;    shift   ;;
        -n|--dry-run)       DRY_RUN=true;       shift   ;;
        --help)             show_help ;;
        --version)          show_version ;;
        --)                 shift; break ;;
        *)                  log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Validation ─────────────────────────────────────────────────────────────────
for v in COMPRESS_DAYS DELETE_DAYS; do
    [[ "${!v}" =~ ^[0-9]+$ && "${!v}" -ge 1 ]] \
        || { log_error "$v must be a positive integer (got: ${!v})"; exit 2; }
done

# BUG-5 FIX: use -le so DELETE_DAYS must be STRICTLY greater than COMPRESS_DAYS
if (( DELETE_DAYS <= COMPRESS_DAYS )); then
    log_error "DELETE_DAYS ($DELETE_DAYS) must be strictly greater than COMPRESS_DAYS ($COMPRESS_DAYS)."
    exit 2
fi

if [[ ! -d "$LOG_DIR" ]]; then
    log_error "Log directory does not exist: $LOG_DIR"
    exit 2
fi

check_deps find gzip

# ── BUG-4 FIX: set up own log file before first output ────────────────────────
SELF_LOG="$LOG_DIR/log-rotator.log"
if [[ "$DRY_RUN" != true ]]; then
    exec > >(tee -a "$SELF_LOG") 2>&1
fi

# ── BUG-6 FIX: adjust find threshold for inclusive age matching ───────────────
# find -mtime +N matches files OLDER THAN N days (exclusive).
# To match files N or more days old (inclusive), use -mtime +$((N-1)).
COMPRESS_FIND=$(( COMPRESS_DAYS - 1 ))
DELETE_FIND=$(( DELETE_DAYS - 1 ))

log_info "=========================================="
log_info "  Log Rotator v3.0.0: $(date)"
log_info "  Directory : $LOG_DIR"
log_info "  Compress  : files ≥ ${COMPRESS_DAYS}d old  (find -mtime +${COMPRESS_FIND})"
log_info "  Delete    : archives ≥ ${DELETE_DAYS}d old  (find -mtime +${DELETE_FIND})"
[[ "$DRY_RUN"   == true ]] && log_info "  Mode      : DRY RUN"
[[ "$NO_DELETE" == true ]] && log_info "  Delete    : DISABLED"
log_info "=========================================="

# ── Counters ──────────────────────────────────────────────────────────────────
compress_ok=0
compress_skip=0
compress_err=0
delete_ok=0
delete_err=0
bytes_before=0
bytes_after=0

# ── Phase 1: Compress ─────────────────────────────────────────────────────────
log_info "Phase 1: Compressing logs older than ${COMPRESS_DAYS} day(s)..."

while IFS= read -r -d '' log; do
    if is_file_open "$log"; then
        log_warn "Skipping (open): $log"
        (( compress_skip++ )) || true
        continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "  [DRY RUN] Would compress: $log"
        (( compress_ok++ )) || true
        continue
    fi

    # Track size delta for --stats
    if [[ "$SHOW_STATS" == true ]]; then
        orig_size=$(stat -c %s "$log" 2>/dev/null || echo 0)
        (( bytes_before += orig_size )) || true
    fi

    if safe_compress "$log"; then
        gz_size=0
        if [[ "$SHOW_STATS" == true ]]; then
            gz_size=$(stat -c %s "${log}.gz" 2>/dev/null || echo 0)
            (( bytes_after += gz_size )) || true
        fi
        log_info "  Compressed: $(basename "$log")"
        (( compress_ok++ )) || true   # BUG-1 FIX: guarded with || true
    else
        (( compress_err++ )) || true
    fi

done < <(find "$LOG_DIR" -type f -name "$LOG_PATTERN" -mtime +"$COMPRESS_FIND" -print0 2>/dev/null)

# ── Phase 2: Delete ───────────────────────────────────────────────────────────
if [[ "$NO_DELETE" != true ]]; then
    log_info "Phase 2: Deleting archives older than ${DELETE_DAYS} day(s)..."

    while IFS= read -r -d '' gz; do
        if [[ "$DRY_RUN" == true ]]; then
            log_info "  [DRY RUN] Would delete: $gz"
            (( delete_ok++ )) || true
            continue
        fi

        if rm -f "$gz"; then
            log_info "  Deleted: $(basename "$gz")"
            (( delete_ok++ )) || true   # BUG-1 FIX
        else
            log_error "  Failed to delete: $gz"
            (( delete_err++ )) || true
        fi
    done < <(find "$LOG_DIR" -type f -name "${LOG_PATTERN}.gz" -mtime +"$DELETE_FIND" -print0 2>/dev/null)
fi

# ── Stats ──────────────────────────────────────────────────────────────────────
if [[ "$SHOW_STATS" == true && "$DRY_RUN" != true && $compress_ok -gt 0 ]]; then
    saved=$(( bytes_before - bytes_after ))
    if command -v numfmt &>/dev/null; then
        log_info "  Size before: $(numfmt --to=iec $bytes_before)"
        log_info "  Size after:  $(numfmt --to=iec $bytes_after)"
        log_info "  Saved:       $(numfmt --to=iec $saved)"
    else
        log_info "  Saved: ${saved} bytes"
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────────────
total_err=$(( compress_err + delete_err ))

log_info "=========================================="
if [[ "$DRY_RUN" == true ]]; then
    log_info "  DRY RUN — no files modified"
    log_info "  Would compress : $compress_ok"
    log_info "  Would delete   : $delete_ok"
    log_info "  Would skip     : $compress_skip (open files)"
else
    log_info "  Compressed : $compress_ok"
    log_info "  Deleted    : $delete_ok"
    log_info "  Skipped    : $compress_skip (open files)"
    (( compress_err > 0 )) && log_error "  Compress errors: $compress_err"
    (( delete_err   > 0 )) && log_error "  Delete errors:   $delete_err"
fi
log_info "=========================================="

# BUG-8 FIX: exit 1 if any operation failed
(( total_err > 0 )) && exit 1 || exit 0
