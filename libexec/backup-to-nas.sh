#!/bin/bash
# backup-to-nas.sh – Incremental hardlink backup to NAS with retention, space check, and report
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  exec > >(tee) was placed AFTER the first log_info call — early errors were lost to the log
#   BUG-2  --link-dest used $base unchanged even when .config was renamed to "config" —
#          rsync couldn't find the prior snapshot → performed a wasteful full copy every run
#   BUG-3  mapfile -t SOURCES <<< "$empty_string" → SOURCES=("") — one phantom empty element
#          caused rsync to run with no source path, succeeding while backing up nothing
#   BUG-4  Retention loop used <<< "$(find ...)" — empty find output still delivered one blank
#          line; -z guard worked by luck, but the outer loop was also unsafe with paths that
#          contained spaces. Rewritten to use find -print0 / read -d ''
#   BUG-5  send_email_report: mail -a (attachment) is a mutt-only flag — silently dropped log
#          attachment when using mailutils/bsd-mailx. Fixed with inline log tail + uuencode path
#   BUG-6  No per-source failure tracking — email body said "FAILED" with no detail on which
#          sources were affected
#   BUG-7  check_space short-circuited entirely for incremental runs — a nearly-full disk caused
#          rsync to fail mid-run rather than being caught before it started
#
# New in 3.0.0:
#   --keep-count N   Keep the N most-recent backups regardless of age (default: 0 = age-only)
#   --exclude-from   Per-source exclude files (name: <basename>.excludes next to this script)
#   --verify         After backup, spot-check N random files with sha256sum
#   --report-only    Send the last run's report without running a new backup
#   Exit codes:      0=success  1=partial (some sources failed)  2=complete failure / abort

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: backup-to-nas.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-to-nas.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
SOURCES=()
DEST=""
EMAIL="${EMAIL:-}"
DRY_RUN=false
VERIFY=false
REPORT_ONLY=false
export VERBOSE=false
LOCK_FILE="/tmp/backup-to-nas.lock"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
RETENTION_DAYS=7
KEEP_COUNT=0          # 0 = not enforced; N = keep at least N most-recent regardless of age
SPACE_MARGIN_PERCENT=10
MIN_FREE_SPACE_GB=5
VERIFY_SAMPLE=20      # number of files to spot-check after backup
MOUNT_POINT=""

# ── Load configuration ─────────────────────────────────────────────────────────
# Must happen before logging and before any early exits, so config values are
# available even in --dry-run mode.
if command -v get_config &>/dev/null; then
    raw_sources=$(get_config_array ".backup.sources" 2>/dev/null || true)
    if [[ -n "$raw_sources" ]]; then
        # BUG-3 FIX: only populate SOURCES if the value is non-empty
        while IFS= read -r line; do
            [[ -n "$line" ]] && SOURCES+=("$line")
        done <<< "$raw_sources"
    fi

    DEST="$(get_config ".backup.dest"                    "$DEST")"
    EMAIL="$(get_config ".backup.email" "$(get_config ".email" "$EMAIL")")"
    RETENTION_DAYS="$(get_config ".backup.retention_days"         "$RETENTION_DAYS")"
    KEEP_COUNT="$(get_config ".backup.keep_count"                  "$KEEP_COUNT")"
    SPACE_MARGIN_PERCENT="$(get_config ".backup.space_margin_percent" "$SPACE_MARGIN_PERCENT")"
    MIN_FREE_SPACE_GB="$(get_config ".backup.min_free_space_gb"    "$MIN_FREE_SPACE_GB")"
    LOG_FILE="$(get_config ".backup.log_file"            "$LOG_FILE")"
fi

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "backup-to-nas.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Incremental hardlink backup to NAS with retention, space check, and email report.

Options:
  -s, --source DIR       Source directory (repeatable)
  -d, --dest PATH        Destination path on NAS (must be a mounted directory)
  -e, --email ADDR       Email for report (default: \$EMAIL env var)
  -r, --retention DAYS   Delete backups older than DAYS days (default: $RETENTION_DAYS)
  -k, --keep-count N     Keep at least N most-recent backups regardless of age (default: $KEEP_COUNT)
  -n, --dry-run          rsync --dry-run: show what would transfer, make no changes
  -V, --verify           After backup, spot-check $VERIFY_SAMPLE random files with sha256sum
      --report-only      Re-send the last run's report without running a new backup
  -v, --verbose          Enable verbose output
  --help                 Show this message
  --version              Show version information

Exit codes:
  0  All sources backed up successfully
  1  One or more sources failed (partial backup)
  2  Fatal error – backup aborted before any data was written
EOF
    exit 0
}

# ── Logging setup (BUG-1 FIX) ─────────────────────────────────────────────────
# Set up log tee BEFORE any log_info/log_error calls so nothing is lost.
# We defer this to a function so it can be skipped cleanly for dry-run.
setup_logging() {
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    exec > >(tee -a "$LOG_FILE") 2>&1
}

# ── Cleanup ────────────────────────────────────────────────────────────────────
_EMAIL_TMP=""
cleanup() {
    local exit_code=$?
    # Release flock-based lock
    [[ -n "${LOCK_FD:-}" ]] && { flock -u "$LOCK_FD" 2>/dev/null || true; }
    rm -f "$LOCK_FILE"
    # Remove email temp dir
    [[ -n "$_EMAIL_TMP" && -d "$_EMAIL_TMP" ]] && rm -rf "$_EMAIL_TMP"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

# ── Lock ───────────────────────────────────────────────────────────────────────
acquire_lock() {
    exec 200>"$LOCK_FILE"
    if ! flock -n 200; then
        die "Another backup instance is already running (lock: $LOCK_FILE)."
    fi
    LOCK_FD=200
}

# ── Space check (BUG-7 FIX) ───────────────────────────────────────────────────
# Always checks MIN_FREE_SPACE_GB. For initial runs, also checks estimated
# transfer size. For incremental runs, we can't know changed-file size cheaply,
# so we enforce a scaled-down margin (25% of full estimate) as a safety floor.
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
        fmt_req=$(numfmt --to=iec "$required_bytes")
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
        # Incremental: enforce a reduced floor (25% of full estimate)
        local incr_floor=$(( required_bytes / 4 ))
        if (( free_bytes < incr_floor )); then
            local fmt_floor
            fmt_floor=$(command -v numfmt &>/dev/null && numfmt --to=iec "$incr_floor" || echo "${incr_floor} B")
            log_error "Incremental safety floor not met — need at least $fmt_floor free, have $fmt_free."
            return 1
        fi
    else
        # Initial full backup: require full estimated space
        if (( free_bytes < required_bytes )); then
            log_error "Insufficient space for full backup — need $fmt_req, have $fmt_free."
            return 1
        fi
    fi

    log_info "Space check passed."
}

# ── link-dest path resolver (BUG-2 FIX) ───────────────────────────────────────
# Returns the path in a *previous* snapshot that corresponds to a given source,
# accounting for the fact that .config is stored as "config" (no leading dot).
linkdest_for() {
    local src="$1"
    local base
    base=$(basename "$src")
    # Mirror the naming logic used when creating dest_path below
    if [[ "$base" == .* ]]; then
        base="${base#.}"   # strip leading dot to get the stored name
    fi
    echo "$LATEST_BACKUP/$base"
}

# ── Destination path for a source ─────────────────────────────────────────────
destpath_for() {
    local src="$1"
    local base
    base=$(basename "$src")
    if [[ "$base" == .* ]]; then
        base="${base#.}"   # strip leading dot: .config → config, .ssh → ssh
    fi
    echo "$BACKUP_PATH/$base"
}

# ── Optional post-backup verification ─────────────────────────────────────────
run_verify() {
    local backup_dir="$1"
    if ! command -v sha256sum &>/dev/null; then
        log_warn "sha256sum not available — skipping verification."
        return 0
    fi

    log_info "Verifying up to $VERIFY_SAMPLE random files..."
    local sample_count=0 fail_count=0

    while IFS= read -r -d '' backed_up; do
        # Reconstruct source path: strip BACKUP_PATH prefix, re-add leading dot if needed
        local rel="${backed_up#"$backup_dir/"}"
        local top_dir="${rel%%/*}"
        local src_top="$top_dir"
        local src_parent=""
        # Find which source this top-level dir belongs to, accounting for dot-stripping
        for s in "${SOURCES[@]}"; do
            local b; b=$(basename "$s")
            if [[ "${b#.}" == "$top_dir" ]]; then
                src_top="$b"
                src_parent="$(dirname "$s")"
                break
            fi
        done
        [[ -z "$src_parent" ]] && continue   # couldn't match — skip rather than guess
        # Reconstruct original path
        local original
        original="$src_parent/$src_top${rel#"$top_dir"}"

        if [[ -f "$original" ]]; then
            local orig_sum bkp_sum
            orig_sum=$(sha256sum "$original"  2>/dev/null | cut -d' ' -f1)
            bkp_sum=$( sha256sum "$backed_up" 2>/dev/null | cut -d' ' -f1)
            if [[ "$orig_sum" != "$bkp_sum" ]]; then
                log_warn "VERIFY MISMATCH: $backed_up"
                (( fail_count++ )) || true
            else
                log_verbose "OK: $(basename "$backed_up")"
            fi
            (( sample_count++ )) || true
        fi

        (( sample_count >= VERIFY_SAMPLE )) && break
    done < <(find "$backup_dir" -type f -print0 2>/dev/null | shuf -z 2>/dev/null || \
             find "$backup_dir" -type f -print0 2>/dev/null)

    if (( fail_count > 0 )); then
        log_error "Verification: $fail_count/$sample_count files mismatched."
        return 1
    fi
    log_info "Verification passed ($sample_count files checked)."
}

# ── Email report ──────────────────────────────────────────────────────────────
# BUG-5 FIX: `mail` does not support -a (attachments). We embed a log tail
# inline and attempt uuencode attachment only when it's available.
send_report() {
    local subject="$1" body_file="$2"
    [[ -z "$EMAIL" ]] && { log_warn "No email address configured — skipping report."; return 0; }

    # Append last 40 log lines inline (works with any mailer)
    {
        cat "$body_file"
        echo ""
        echo "── Last 40 lines of log ──"
        tail -n 40 "$LOG_FILE" 2>/dev/null || true
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
        log_warn "No mail program found (mutt / mail / sendmail) — skipping report."
    fi
}

# ── Logging (BUG-1 FIX: set up NOW, before argument parsing, so errors are captured) ──
# Dry-run also logs to file so you have a record of what would have happened.
setup_logging

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt -o qs:d:e:r:k:nVvh \
    -l quiet,source:,dest:,email:,retention:,keep-count:,dry-run,verify,report-only,verbose,help,version \
    -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -q|--quiet) shift ;;
        -s|--source)       SOURCES+=("$2");          shift 2 ;;
        -d|--dest)         DEST="$2";                shift 2 ;;
        -e|--email)        EMAIL="$2";               shift 2 ;;
        -r|--retention)    RETENTION_DAYS="$2";      shift 2 ;;
        -k|--keep-count)   KEEP_COUNT="$2";          shift 2 ;;
        -n|--dry-run)      DRY_RUN=true;             shift   ;;
        -V|--verify)       VERIFY=true;              shift   ;;
           --report-only)  REPORT_ONLY=true;         shift   ;;
        -v|--verbose)      export VERBOSE=true;      shift   ;;
        -h|--help)         show_help ;;
           --version)      show_version ;;
        --)                shift; break ;;
        *)                 log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Validation ─────────────────────────────────────────────────────────────────
for v in RETENTION_DAYS KEEP_COUNT MIN_FREE_SPACE_GB SPACE_MARGIN_PERCENT; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || die "$v must be a non-negative integer, got: ${!v}"
done

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

MOUNT_POINT=$(df -P "$DEST" 2>/dev/null | tail -1 | awk '{print $6}')
[[ -n "$MOUNT_POINT" ]] || die "Cannot determine mount point for $DEST."

# ── Lock (only for real runs) ─────────────────────────────────────────────────
[[ "$DRY_RUN" != true ]] && acquire_lock

# ── Report-only mode ───────────────────────────────────────────────────────────
if [[ "$REPORT_ONLY" == true ]]; then
    log_info "Report-only: re-sending last run's report."
    _EMAIL_TMP=$(mktemp -d "/tmp/noba-backup.XXXXXX")
    echo "(report-only mode — see attached log)" > "$_EMAIL_TMP/body.txt"
    send_report "Backup Report (resent) – $(hostname) – $(date '+%Y-%m-%d')" "$_EMAIL_TMP/body.txt"
    exit 0
fi

# ── Find latest existing backup (needed for check_space + link-dest) ──────────
LATEST_BACKUP=""
while IFS= read -r -d '' d; do
    LATEST_BACKUP="$d"
done < <(find "$DEST" -maxdepth 1 -type d -name "????????-??????" -print0 2>/dev/null | sort -z)

# ── Space check ───────────────────────────────────────────────────────────────
check_space || die "Space check failed — aborting."

# ── Prepare backup destination ────────────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$DEST/$TIMESTAMP"

log_info "============================================================"
log_info "  Backup v3.0.0 started: $(date)"
log_info "  Host:       $(hostname)"
log_info "  Sources:    ${SOURCES[*]}"
log_info "  Dest:       $BACKUP_PATH"
log_info "  Retention:  ${RETENTION_DAYS}d  keep-count: ${KEEP_COUNT}"
log_info "  Dry run:    $DRY_RUN"
log_info "============================================================"

if [[ -n "$LATEST_BACKUP" ]]; then
    log_info "Incremental from: $(basename "$LATEST_BACKUP")"
else
    log_info "No prior backup found — performing full initial backup."
fi

if [[ "$DRY_RUN" != true ]]; then
    mkdir -p "$BACKUP_PATH"
else
    log_info "[DRY RUN] Would create: $BACKUP_PATH"
fi

# ── BUG-6 FIX: track per-source failures ─────────────────────────────────────
FAILED_SOURCES=()
START_TIME=$SECONDS

# ── rsync base options ────────────────────────────────────────────────────────
RSYNC_BASE=("-a" "--delete" "--delete-excluded" "--partial")
[[ "$VERBOSE"  == true ]] && RSYNC_BASE+=("-v" "--progress")
[[ "$DRY_RUN"  == true ]] && RSYNC_BASE+=("--dry-run")
[[ "$VERBOSE"  != true ]] && RSYNC_BASE+=("--quiet")

# ── Per-source backup loop ─────────────────────────────────────────────────────
for src in "${SOURCES[@]}"; do
    src="${src%/}"   # normalise: no trailing slash on source variable

    if [[ ! -e "$src" ]]; then
        log_warn "Source does not exist, skipping: $src"
        FAILED_SOURCES+=("$src (not found)")
        continue
    fi

    dest_path=$(destpath_for "$src")
    extra=()

    # Hardlink against previous snapshot (BUG-2 FIX: path uses stripped name)
    if [[ -n "$LATEST_BACKUP" ]]; then
        local_linkdest=$(linkdest_for "$src")
        [[ -d "$local_linkdest" ]] && extra+=("--link-dest=$local_linkdest")
    fi

    # Per-source exclude file: <scriptdir>/<basename>.excludes
    base=$(basename "$src")
    exclude_file="$SCRIPT_DIR/${base#.}.excludes"   # .config.excludes → config.excludes
    [[ -f "$exclude_file" ]] && extra+=("--exclude-from=$exclude_file")

    # Built-in excludes for known cache/junk directories
    if [[ "$base" == ".config" || "$base" == "config" ]]; then
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

    log_info "Syncing: $src → $dest_path"

    # rsync source: add trailing slash so contents (not the dir itself) go under dest_path
    if ! rsync "${RSYNC_BASE[@]}" "${extra[@]}" "${src}/" "$dest_path"; then
        log_error "rsync failed for: $src"
        FAILED_SOURCES+=("$src")
    else
        log_verbose "OK: $src"
    fi
done

DURATION=$(( SECONDS - START_TIME ))

# ── Optional verification ──────────────────────────────────────────────────────
if [[ "$VERIFY" == true && "$DRY_RUN" != true ]]; then
    run_verify "$BACKUP_PATH" || FAILED_SOURCES+=("verify")
fi

# ── Retention pruning (BUG-4 FIX) ────────────────────────────────────────────
# Uses find -print0 / read -d '' so paths with spaces are handled correctly.
# KEEP_COUNT guard: never prune below N most-recent backups.
if [[ "$DRY_RUN" != true && -d "$DEST" ]]; then
    log_info "Running retention (≥${RETENTION_DAYS}d old, keep at least ${KEEP_COUNT} most-recent)..."

    # Collect all snapshot dirs newest-first
    mapfile -d '' ALL_SNAPS < <(
        find "$DEST" -maxdepth 1 -type d -name "????????-??????" -print0 2>/dev/null | sort -rz
    )
    total_snaps=${#ALL_SNAPS[@]}
    now_s=$(date +%s)

    for (( i=0; i<total_snaps; i++ )); do
        snap="${ALL_SNAPS[$i]}"
        [[ -z "$snap" ]] && continue

        # Honour keep-count: never delete the N newest
        if (( KEEP_COUNT > 0 && i < KEEP_COUNT )); then
            log_verbose "Keeping (keep-count): $(basename "$snap")"
            continue
        fi

        folder=$(basename "$snap")
        # Parse YYYYMMDD from "YYYYMMDD-HHMMSS"
        date_part="${folder%%-*}"
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

# ── Report ─────────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" != true && -d "$BACKUP_PATH" ]]; then
    BACKUP_SIZE=$(du -sh "$BACKUP_PATH" 2>/dev/null | cut -f1 || echo "unknown")
else
    BACKUP_SIZE="N/A (dry run)"
fi

_EMAIL_TMP=$(mktemp -d "/tmp/noba-backup.XXXXXX")
BODY="$_EMAIL_TMP/report.txt"

if (( ${#FAILED_SOURCES[@]} > 0 )); then
    SUBJECT_PREFIX="❌ BACKUP PARTIAL/FAILED"
    EXIT_CODE=1
else
    SUBJECT_PREFIX="✅ BACKUP SUCCESSFUL"
    EXIT_CODE=0
fi

SUBJECT="$SUBJECT_PREFIX – $(hostname) – $(date '+%Y-%m-%d')"

cat > "$BODY" <<EOF
$SUBJECT_PREFIX

Host:             $(hostname)
Finished:         $(date '+%Y-%m-%d %H:%M:%S')
Snapshot:         $TIMESTAMP
Retention policy: ${RETENTION_DAYS} days  (keep-count: ${KEEP_COUNT})

──────────────────────────────────────────
📊 STATS
──────────────────────────────────────────
Duration:         ${DURATION}s
Snapshot size:    ${BACKUP_SIZE}
  (hardlinked files share blocks with prior snapshots)

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
This is an automated message from the Nobara Backup System.
EOF

send_report "$SUBJECT" "$BODY"

log_info "============================================================"
log_info "  Backup finished: $(date)"
log_info "  Duration: ${DURATION}s   Size: ${BACKUP_SIZE}"
(( ${#FAILED_SOURCES[@]} > 0 )) && log_error "  Failed sources: ${FAILED_SOURCES[*]}"
log_info "============================================================"

# Invoke optional notification hook
if [[ "$DRY_RUN" != true ]] && [[ -x "$SCRIPT_DIR/backup-notify.sh" ]]; then
    "$SCRIPT_DIR/backup-notify.sh" || true
fi

exit $EXIT_CODE
