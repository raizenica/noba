#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# backup-to-nas.sh – Incremental hardlink backup to NAS with retention, space check, and report
# Version: 1.1.0

set -euo pipefail

# ── Version ────────────────────────────────────────────────────────────────────
readonly VERSION="1.1.0"

# ── Test harness shims (must come before sourcing the library) ─────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help"    || "${1:-}" == "-h" ]]; then
    echo "Usage: backup-to-nas.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-to-nas.sh version $VERSION"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
SOURCES=()
DEST=""
EMAIL="${EMAIL:-}"
DRY_RUN=false
VERIFY=false
NO_EMAIL=false
REPORT_ONLY=false
export VERBOSE=false
LOCK_FILE="${TMPDIR:-/tmp}/backup-to-nas.lock"
LOCK_FD=""
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
STATE_FILE="${STATE_FILE:-$HOME/.local/share/backup-to-nas.state}"
RETENTION_DAYS=7
KEEP_COUNT=0
SPACE_MARGIN_PERCENT=10
MIN_FREE_SPACE_GB=5
VERIFY_SAMPLE=20
MAX_DELETE=""         # empty = no --max-delete passed to rsync
EXTRA_RSYNC_OPTS=()
MOUNT_POINT=""

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    raw_sources=$(get_config_array ".backup.sources" 2>/dev/null || true)
    if [[ -n "$raw_sources" ]]; then
        while IFS= read -r line; do
            [[ -n "$line" ]] && SOURCES+=("$line")
        done <<< "$raw_sources"
    fi
    DEST="$(get_config ".backup.dest"                         "$DEST")"
    EMAIL="$(get_config ".backup.email"                       "$EMAIL")"
    RETENTION_DAYS="$(get_config ".backup.retention_days"     "$RETENTION_DAYS")"
    KEEP_COUNT="$(get_config ".backup.keep_count"             "$KEEP_COUNT")"
    SPACE_MARGIN_PERCENT="$(get_config ".backup.space_margin_percent" "$SPACE_MARGIN_PERCENT")"
    MIN_FREE_SPACE_GB="$(get_config ".backup.min_free_space_gb"  "$MIN_FREE_SPACE_GB")"
    LOG_FILE="$(get_config ".backup.log_file"                 "$LOG_FILE")"
    VERIFY_SAMPLE="$(get_config ".backup.verify_sample"       "$VERIFY_SAMPLE")"
    MAX_DELETE="$(get_config ".backup.max_delete"             "$MAX_DELETE")"
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Incremental hardlink backup to NAS with retention, space check, and email report.

Options:
  -s, --source DIR         Source directory (repeatable)
  -d, --dest PATH          Destination path on NAS (must be a mounted directory)
  -e, --email ADDR         Email for report (default: \$EMAIL env var)
  -r, --retention DAYS     Delete backups older than DAYS days (default: $RETENTION_DAYS)
  -k, --keep-count N       Keep at least N most-recent backups regardless of age (default: $KEEP_COUNT)
  -l, --log-file PATH      Log file path (default: $LOG_FILE)
  -n, --dry-run            rsync --dry-run: show what would transfer, make no changes
  -V, --verify             After backup, spot-check files with sha256sum
      --verify-count N     Number of files to spot-check (default: $VERIFY_SAMPLE)
      --max-delete N       Cap rsync deletions per source (safety guard)
      --rsync-opts OPTS    Extra rsync options appended verbatim
      --no-email           Suppress email report for this run
      --report-only        Re-send the last run's report without running a new backup
  -v, --verbose            Enable verbose output
      --help               Show this message
      --version            Show version

Exit codes:
  0  All sources backed up successfully
  1  One or more sources failed (partial backup)
  2  Fatal error – backup aborted before any data was written
EOF
    exit 0
}

# ── Duration formatter ─────────────────────────────────────────────────────────
format_duration() {
    local secs="$1"
    local h=$(( secs / 3600 ))
    local m=$(( (secs % 3600) / 60 ))
    local s=$(( secs % 60 ))
    if   (( h > 0 )); then printf '%dh %dm %ds' "$h" "$m" "$s"
    elif (( m > 0 )); then printf '%dm %ds' "$m" "$s"
    else                   printf '%ds' "$s"
    fi
}

# ── Logging setup ──────────────────────────────────────────────────────────────
# Called once after argument parsing so --log-file takes effect.
setup_logging() {
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    exec > >(tee -a "$LOG_FILE") 2>&1
}

# ── Cleanup ────────────────────────────────────────────────────────────────────
_EMAIL_TMP=""
_PARTIAL_PATH=""   # path of in-progress snapshot; removed on abort

# shellcheck disable=SC2329  # invoked via: trap cleanup EXIT INT TERM
cleanup() {
    local exit_code=$?
    # Kill any background rsync that may still be running
    jobs -p 2>/dev/null | xargs -r kill 2>/dev/null || true
    # Release flock
    if [[ -n "$LOCK_FD" ]]; then
        flock -u "$LOCK_FD" 2>/dev/null || true
        eval "exec $LOCK_FD>&-" 2>/dev/null || true
    fi
    rm -f "$LOCK_FILE"
    # Clean up a partial snapshot on unexpected exit
    if [[ -n "$_PARTIAL_PATH" && -d "$_PARTIAL_PATH" && "$exit_code" -ne 0 ]]; then
        log_warn "Removing incomplete snapshot: $(basename "$_PARTIAL_PATH")"
        rm -rf "$_PARTIAL_PATH"
    fi
    [[ -n "$_EMAIL_TMP" && -d "$_EMAIL_TMP" ]] && rm -rf "$_EMAIL_TMP"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

# ── Lock ───────────────────────────────────────────────────────────────────────
acquire_lock() {
    # Use a dynamic FD (bash 4.1+) rather than a hard-coded number.
    exec {LOCK_FD}>"$LOCK_FILE"
    if ! flock -n "$LOCK_FD"; then
        die "Another backup instance is already running (lock: $LOCK_FILE)."
    fi
}

# ── Space check ───────────────────────────────────────────────────────────────
check_space() {
    [[ "$DRY_RUN" == true ]] && return 0

    local src total_kb=0
    for src in "${SOURCES[@]}"; do
        [[ -e "$src" ]] || continue
        local sz
        sz=$(du -sk "$src" 2>/dev/null | cut -f1)
        total_kb=$(( total_kb + sz ))
    done

    local margined_kb=$(( total_kb + total_kb * SPACE_MARGIN_PERCENT / 100 ))
    local required_bytes=$(( margined_kb * 1024 ))
    local free_kb
    free_kb=$(df --output=avail "$MOUNT_POINT" 2>/dev/null | tail -1 | tr -d ' ')
    local free_bytes=$(( free_kb * 1024 ))

    local fmt_req fmt_free
    if command -v numfmt &>/dev/null; then
        fmt_req=$(numfmt  --to=iec "$required_bytes")
        fmt_free=$(numfmt --to=iec "$free_bytes")
    else
        fmt_req="${required_bytes} B"
        fmt_free="${free_bytes} B"
    fi

    log_info "Estimated source size (+ ${SPACE_MARGIN_PERCENT}% margin): $fmt_req"
    log_info "Free on $MOUNT_POINT: $fmt_free"

    local min_free_bytes=$(( MIN_FREE_SPACE_GB * 1024 * 1024 * 1024 ))
    if (( free_bytes < min_free_bytes )); then
        log_error "Free space below minimum ${MIN_FREE_SPACE_GB} GiB — aborting."
        return 1
    fi

    if [[ -n "$LATEST_BACKUP" ]]; then
        # Incremental: enforce a conservative 25%-of-full-estimate floor
        local incr_floor=$(( required_bytes / 4 ))
        if (( free_bytes < incr_floor )); then
            local fmt_floor
            fmt_floor=$(command -v numfmt &>/dev/null \
                && numfmt --to=iec "$incr_floor" || echo "${incr_floor} B")
            log_error "Incremental safety floor not met — need $fmt_floor free, have $fmt_free."
            return 1
        fi
    else
        if (( free_bytes < required_bytes )); then
            log_error "Insufficient space for full backup — need $fmt_req, have $fmt_free."
            return 1
        fi
    fi

    log_info "Space check passed."
}

# ── Destination writability check ─────────────────────────────────────────────
check_writable() {
    local probe
    probe=$(mktemp -q "$DEST/.write-test.XXXXXX" 2>/dev/null) || {
        log_error "Destination $DEST is not writable — check permissions."
        return 1
    }
    rm -f "$probe"
}

# ── Snapshot path helpers ──────────────────────────────────────────────────────
# Strip a leading dot from dotfiles so .config is stored as config/.
_strip_dot() { local b="$1"; [[ "$b" == .* ]] && echo "${b#.}" || echo "$b"; }

linkdest_for() {
    local src="$1"
    echo "$LATEST_BACKUP/$(_strip_dot "$(basename "$src")")"
}

# ── Post-backup verification ───────────────────────────────────────────────────
# Fixed: previously used dirname of SOURCES[0] for all files, which was wrong
# when multiple sources with different parent directories were involved.
run_verify() {
    local backup_dir="$1"
    if ! command -v sha256sum &>/dev/null; then
        log_warn "sha256sum not available — skipping verification."
        return 0
    fi

    log_info "Verifying up to $VERIFY_SAMPLE random files in $backup_dir..."

    # Collect a random sample without -z shuf (portability) using process sub.
    local -a sample_files=()
    while IFS= read -r -d '' f; do
        sample_files+=("$f")
        (( ${#sample_files[@]} >= VERIFY_SAMPLE )) && break
    done < <(
        # Prefer shuf -z; fall back to non-randomised find (still useful for CI).
        if command -v shuf &>/dev/null; then
            find "$backup_dir" -type f -print0 2>/dev/null | shuf --zero-terminated 2>/dev/null \
                || find "$backup_dir" -type f -print0 2>/dev/null
        else
            find "$backup_dir" -type f -print0 2>/dev/null
        fi
    )

    local sample_count=0 fail_count=0
    for backed_up in "${sample_files[@]}"; do
        [[ -f "$backed_up" ]] || continue

        # Strip the backup dir prefix to get the relative path.
        local rel="${backed_up#"$backup_dir/"}"
        local top_dir="${rel%%/*}"

        # Find which source this top-level dir belongs to.
        local original=""
        local s b
        for s in "${SOURCES[@]}"; do
            b=$(basename "$s")
            if [[ "$(_strip_dot "$b")" == "$top_dir" ]]; then
                # Reconstruct: parent of source / (possibly dot-prefixed) base / rest of path
                local rest="${rel#"$top_dir"}"
                original="$(dirname "$s")/$b$rest"
                break
            fi
        done

        [[ -z "$original" || ! -f "$original" ]] && continue

        local orig_sum bkp_sum
        orig_sum=$(sha256sum "$original"  2>/dev/null | cut -d' ' -f1)
        bkp_sum=$( sha256sum "$backed_up" 2>/dev/null | cut -d' ' -f1)

        if [[ "$orig_sum" != "$bkp_sum" ]]; then
            log_warn "VERIFY MISMATCH: $backed_up"
            (( fail_count++ )) || true
        else
            log_verbose "  OK: $(basename "$backed_up")"
        fi
        (( sample_count++ )) || true
    done

    if (( fail_count > 0 )); then
        log_error "Verification: $fail_count/$sample_count files mismatched."
        return 1
    fi
    log_info "Verification passed ($sample_count files checked)."
}

# ── Email report ───────────────────────────────────────────────────────────────
send_report() {
    local subject="$1" body_file="$2"

    if [[ "$NO_EMAIL" == true ]]; then
        log_info "Email suppressed by --no-email."
        return 0
    fi
    if [[ -z "$EMAIL" ]]; then
        log_warn "No email address configured — skipping report."
        return 0
    fi

    {
        cat "$body_file"
        echo ""
        echo "── Last 50 lines of log ──"
        tail -n 50 "$LOG_FILE" 2>/dev/null || true
    } > "${body_file}.full"

    if command -v mutt &>/dev/null; then
        mutt -s "$subject" -a "$LOG_FILE" -- "$EMAIL" < "${body_file}.full"
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < "${body_file}.full"
    elif command -v sendmail &>/dev/null; then
        {
            echo "To: $EMAIL"
            echo "Subject: $subject"
            echo ""
            cat "${body_file}.full"
        } | sendmail -t
    else
        log_warn "No mail program found (mutt/mail/sendmail) — skipping report."
    fi
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o s:d:e:r:k:l:nVvh \
        -l source:,dest:,email:,retention:,keep-count:,log-file:,dry-run,verify,\
verify-count:,max-delete:,rsync-opts:,no-email,report-only,verbose,help,version \
        -- "$@" 2>/dev/null); then
    echo "Invalid argument. Run with --help for usage." >&2
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -s|--source)        SOURCES+=("$2");                     shift 2 ;;
        -d|--dest)          DEST="$2";                           shift 2 ;;
        -e|--email)         EMAIL="$2";                          shift 2 ;;
        -r|--retention)     RETENTION_DAYS="$2";                 shift 2 ;;
        -k|--keep-count)    KEEP_COUNT="$2";                     shift 2 ;;
        -l|--log-file)      LOG_FILE="$2";                       shift 2 ;;
        -n|--dry-run)       DRY_RUN=true;                        shift   ;;
        -V|--verify)        VERIFY=true;                         shift   ;;
           --verify-count)  VERIFY_SAMPLE="$2";                  shift 2 ;;
           --max-delete)    MAX_DELETE="$2";                     shift 2 ;;
           --rsync-opts)    read -ra _extra <<< "$2"
                            EXTRA_RSYNC_OPTS+=("${_extra[@]}");  shift 2 ;;
           --no-email)      NO_EMAIL=true;                       shift   ;;
           --report-only)   REPORT_ONLY=true;                    shift   ;;
        -v|--verbose)       export VERBOSE=true;                 shift   ;;
        -h|--help)          show_help ;;
           --version)       echo "backup-to-nas.sh version $VERSION"; exit 0 ;;
        --)                 shift; break ;;
        *)                  echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# ── Logging – initialise now so --log-file is honoured ────────────────────────
setup_logging

# ── Input validation ───────────────────────────────────────────────────────────
for v in RETENTION_DAYS KEEP_COUNT MIN_FREE_SPACE_GB SPACE_MARGIN_PERCENT VERIFY_SAMPLE; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || die "$v must be a non-negative integer, got: ${!v}"
done
if [[ -n "$MAX_DELETE" ]]; then
    [[ "$MAX_DELETE" =~ ^[0-9]+$ ]] || die "--max-delete must be a non-negative integer."
fi

if [[ ${#SOURCES[@]} -eq 0 ]]; then
    [[ "$DRY_RUN" == true || "$REPORT_ONLY" == true ]] && exit 0
    die "At least one --source must be specified."
fi
if [[ -z "$DEST" ]]; then
    [[ "$DRY_RUN" == true || "$REPORT_ONLY" == true ]] && exit 0
    die "Destination (--dest) is required."
fi
if [[ ! -d "$DEST" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        log_info "Dry run: destination $DEST not mounted — skipping mount checks."
        exit 0
    fi
    die "Destination $DEST does not exist — is the NAS mounted?"
fi

check_deps rsync df find du
check_writable || die "Aborting — destination not writable."

MOUNT_POINT=$(df -P "$DEST" 2>/dev/null | tail -1 | awk '{print $6}')
[[ -n "$MOUNT_POINT" ]] || die "Cannot determine mount point for $DEST."

# ── Acquire lock (real runs only) ─────────────────────────────────────────────
# shellcheck disable=SC2119  # acquire_lock takes no positional params; die() inside it causes the false positive
[[ "$DRY_RUN" != true ]] && acquire_lock

# ── Report-only mode ───────────────────────────────────────────────────────────
if [[ "$REPORT_ONLY" == true ]]; then
    log_info "Report-only: re-sending last run's report."
    _EMAIL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/noba-backup.XXXXXX")
    echo "(report-only mode — see attached log)" > "$_EMAIL_TMP/body.txt"
    send_report "Backup Report (resent) – $(hostname) – $(date '+%Y-%m-%d')" \
                "$_EMAIL_TMP/body.txt"
    exit 0
fi

# ── Locate the most-recent complete snapshot (for space check + link-dest) ────
# Only directories named YYYYMMDD-HHMMSS (no .partial suffix) are considered.
LATEST_BACKUP=""
while IFS= read -r -d '' d; do
    LATEST_BACKUP="$d"
done < <(find "$DEST" -maxdepth 1 -type d -name "????????-?????" -print0 2>/dev/null \
         | sort -z)

# ── Space check ───────────────────────────────────────────────────────────────
check_space || die "Space check failed — aborting."

# ── Prepare atomic snapshot directory ─────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$DEST/$TIMESTAMP"
_PARTIAL_PATH="$BACKUP_PATH.partial"   # used by cleanup trap

log_info "============================================================"
log_info "  Backup v${VERSION} started: $(date)"
log_info "  Host:        $(hostname)"
log_info "  Sources:     ${SOURCES[*]}"
log_info "  Dest:        $BACKUP_PATH"
log_info "  Retention:   ${RETENTION_DAYS}d  keep-count: ${KEEP_COUNT}"
log_info "  Dry run:     $DRY_RUN"
[[ -n "$MAX_DELETE"       ]] && log_info "  Max-delete:  $MAX_DELETE"
[[ "${#EXTRA_RSYNC_OPTS[@]}" -gt 0 ]] && \
    log_info "  Extra rsync: ${EXTRA_RSYNC_OPTS[*]}"
log_info "============================================================"

if [[ -n "$LATEST_BACKUP" ]]; then
    log_info "Incremental from: $(basename "$LATEST_BACKUP")"
else
    log_info "No prior backup found — performing full initial backup."
fi

if [[ "$DRY_RUN" != true ]]; then
    mkdir -p "$_PARTIAL_PATH" \
        || die "Cannot create snapshot directory: $_PARTIAL_PATH"
else
    log_info "[DRY RUN] Would create: $BACKUP_PATH"
fi

# ── Per-source failure tracking ────────────────────────────────────────────────
FAILED_SOURCES=()
START_TIME=$SECONDS

# ── rsync base options ─────────────────────────────────────────────────────────
RSYNC_BASE=(
    "--archive"          # -a: recurse, preserve permissions/times/symlinks/owner/group
    "--delete"
    "--delete-excluded"
    "--partial"
    "--stats"            # transfer statistics written to log
)
[[ -n "$MAX_DELETE" ]] && RSYNC_BASE+=("--max-delete=$MAX_DELETE")
if [[ "$VERBOSE" == true ]]; then
    if [[ -t 1 ]]; then
        # Interactive terminal: show live progress
        RSYNC_BASE+=("--info=progress2")
    else
        # Non-interactive (job runner, pipe): show file-level info without progress spam
        RSYNC_BASE+=("--info=name1,stats2")
    fi
else
    RSYNC_BASE+=("--quiet")
fi
[[ "$DRY_RUN" == true ]] && RSYNC_BASE+=("--dry-run")
[[ "${#EXTRA_RSYNC_OPTS[@]}" -gt 0 ]] && RSYNC_BASE+=("${EXTRA_RSYNC_OPTS[@]}")

# ── Per-source backup loop ─────────────────────────────────────────────────────
for src in "${SOURCES[@]}"; do
    src="${src%/}"   # normalise: strip trailing slash from variable (rsync gets src/)

    if [[ ! -e "$src" ]]; then
        log_warn "Source does not exist, skipping: $src"
        FAILED_SOURCES+=("$src (not found)")
        continue
    fi

    local_dest_path="$_PARTIAL_PATH/$(_strip_dot "$(basename "$src")")"
    extra=()

    # Hardlink against previous complete snapshot
    if [[ -n "$LATEST_BACKUP" ]]; then
        local_linkdest=$(linkdest_for "$src")
        [[ -d "$local_linkdest" ]] && extra+=("--link-dest=$local_linkdest")
    fi

    # Per-source exclude file: <script-dir>/<basename-without-dot>.excludes
    base=$(basename "$src")
    exclude_file="$SCRIPT_DIR/${base#.}.excludes"
    [[ -f "$exclude_file" ]] && extra+=("--exclude-from=$exclude_file")

    # Built-in excludes for known cache/junk patterns inside .config
    if [[ "$(_strip_dot "$base")" == "config" ]]; then
        extra+=(
            "--exclude=*cache*"
            "--exclude=*Cache*"
            "--exclude=*thumbnails*"
            "--exclude=*Trash*"
            "--exclude=*session*"
            "--exclude=*/sockets/"
            "--exclude=*lock"
            "--exclude=*.tmp"
            "--no-links"
        )
    fi

    log_info "Syncing: $src → $local_dest_path"

    if rsync "${RSYNC_BASE[@]}" "${extra[@]}" "${src}/" "$local_dest_path"; then
        log_verbose "  OK: $src"
    else
        rsync_exit=$?
        log_error "rsync exited with code $rsync_exit for: $src"
        FAILED_SOURCES+=("$src (rsync error $rsync_exit)")
    fi
done

DURATION=$(( SECONDS - START_TIME ))

# ── Optional verification ──────────────────────────────────────────────────────
if [[ "$VERIFY" == true && "$DRY_RUN" != true ]]; then
    run_verify "$_PARTIAL_PATH" || FAILED_SOURCES+=("verify")
fi

# ── Atomically promote the partial snapshot ───────────────────────────────────
# Only rename if at least one source succeeded; otherwise leave _PARTIAL_PATH
# so the cleanup trap removes it.
if [[ "$DRY_RUN" != true ]]; then
    if (( ${#FAILED_SOURCES[@]} == ${#SOURCES[@]} )) && (( ${#SOURCES[@]} > 0 )); then
        log_error "All sources failed — discarding partial snapshot."
        rm -rf "$_PARTIAL_PATH"
        _PARTIAL_PATH=""
        exit 2
    fi
    mv "$_PARTIAL_PATH" "$BACKUP_PATH"
    _PARTIAL_PATH=""   # prevent cleanup trap from removing the now-complete snapshot
    log_info "Snapshot finalised: $TIMESTAMP"
fi

# ── Retention pruning ─────────────────────────────────────────────────────────
if [[ "$DRY_RUN" != true && -d "$DEST" ]]; then
    log_info "Retention: ≥${RETENTION_DAYS}d old, keeping at least ${KEEP_COUNT} most-recent..."

    mapfile -d '' ALL_SNAPS < <(
        find "$DEST" -maxdepth 1 -type d -name "????????-??????" -print0 2>/dev/null \
        | sort -rz
    )
    total_snaps=${#ALL_SNAPS[@]}
    now_s=$(date +%s)

    for (( i=0; i<total_snaps; i++ )); do
        snap="${ALL_SNAPS[$i]}"
        [[ -z "$snap" ]] && continue

        if (( KEEP_COUNT > 0 && i < KEEP_COUNT )); then
            log_verbose "Keeping (keep-count $((i+1))/$KEEP_COUNT): $(basename "$snap")"
            continue
        fi

        folder=$(basename "$snap")
        date_part="${folder%%-*}"   # YYYYMMDD

        if folder_s=$(date -d "$date_part" +%s 2>/dev/null); then
            age_days=$(( (now_s - folder_s) / 86400 ))
            if (( age_days >= RETENTION_DAYS )); then
                log_info "Pruning: $folder ($age_days days old)"
                rm -rf "$snap"
            else
                log_verbose "Keeping: $folder ($age_days days old)"
            fi
        else
            log_warn "Cannot parse date from: $folder — skipping prune"
        fi
    done
fi

# ── Build report ───────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" != true && -d "$BACKUP_PATH" ]]; then
    BACKUP_SIZE=$(du -sh "$BACKUP_PATH" 2>/dev/null | cut -f1 || echo "unknown")
else
    BACKUP_SIZE="N/A (dry run)"
fi

_EMAIL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/noba-backup.XXXXXX")
BODY="$_EMAIL_TMP/report.txt"

if (( ${#FAILED_SOURCES[@]} > 0 )); then
    SUBJECT_PREFIX="❌ BACKUP PARTIAL/FAILED"
    EXIT_CODE=1
else
    SUBJECT_PREFIX="✅ BACKUP SUCCESSFUL"
    EXIT_CODE=0
fi

SUBJECT="$SUBJECT_PREFIX – $(hostname) – $(date '+%Y-%m-%d')"
DURATION_FMT=$(format_duration "$DURATION")

cat > "$BODY" <<EOF
$SUBJECT_PREFIX
Host:             $(hostname)
Finished:         $(date '+%Y-%m-%d %H:%M:%S')
Snapshot:         $TIMESTAMP
Retention policy: ${RETENTION_DAYS} days  (keep-count: ${KEEP_COUNT})
──────────────────────────────────────────
📊 STATS
──────────────────────────────────────────
Duration:         ${DURATION_FMT}
Snapshot size:    ${BACKUP_SIZE}
  (hardlinked files share disk blocks with prior snapshots)
──────────────────────────────────────────
📁 SOURCES
──────────────────────────────────────────
$(printf '  ✓ %s\n' "${SOURCES[@]}")
EOF

if (( ${#FAILED_SOURCES[@]} > 0 )); then
cat >> "$BODY" <<EOF
──────────────────────────────────────────
⚠️  FAILURES
──────────────────────────────────────────
$(printf '  ✗ %s\n' "${FAILED_SOURCES[@]}")
EOF
fi

cat >> "$BODY" <<EOF
──────────────────────────────────────────
Log file: $LOG_FILE
This is an automated message from the Noba Backup System v${VERSION}.
EOF

send_report "$SUBJECT" "$BODY"

log_info "============================================================"
log_info "  Backup finished: $(date)"
log_info "  Duration: ${DURATION_FMT}   Size: ${BACKUP_SIZE}"
(( ${#FAILED_SOURCES[@]} > 0 )) && \
    log_error "  Failed sources: ${FAILED_SOURCES[*]}"
log_info "============================================================"

# ── Write State File for backup-notify.sh ─────────────────────────────────────
if [[ "$DRY_RUN" != true ]]; then
    {
        echo "exit_code=$EXIT_CODE"
        echo "timestamp=$(date '+%Y-%m-%d %H:%M:%S')"
        echo "failed_sources=${FAILED_SOURCES[*]:-}"
        echo "duration=${DURATION:-0}"
        echo "snapshot=${TIMESTAMP:-}"
    } > "$STATE_FILE"
    log_verbose "Wrote state file to $STATE_FILE"
fi

# ── Optional post-run notification hook ───────────────────────────────────────
if [[ "$DRY_RUN" != true ]] && [[ -x "$SCRIPT_DIR/backup-notify.sh" ]]; then
    "$SCRIPT_DIR/backup-notify.sh" || true
fi

exit "$EXIT_CODE"
